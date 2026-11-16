"""Built-in OCI/Docker schema-2 image access. Never runs source containers."""
import gzip
import hashlib
import http.client
import json
import posixpath
import re
import shutil
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib
from pathlib import Path, PurePosixPath

import yaml

from recompose.runtime import analyze_execution, compose_service, requested_file, masked_file, sensitive_file, vm_path

META_LIMIT = 8 * 1024 * 1024
BLOB_LIMIT = 1024 * 1024 * 1024
TOTAL_LIMIT = 2 * BLOB_LIMIT
EXPANDED_LIMIT = 4 * BLOB_LIMIT
FILE_LIMIT = 512 * 1024 * 1024
ENTRY_LIMIT = 200000
ACCEPT = ', '.join(['application/vnd.oci.image.index.v1+json', 'application/vnd.oci.image.manifest.v1+json',
                    'application/vnd.docker.distribution.manifest.list.v2+json', 'application/vnd.docker.distribution.manifest.v2+json'])
LAYER_TYPES = {'application/vnd.oci.image.layer.v1.tar', 'application/vnd.oci.image.layer.v1.tar+gzip',
               'application/vnd.docker.image.rootfs.diff.tar.gzip'}


class ImageError(ValueError):
    pass


def digest(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def parse_json(data):
    try:
        result = json.loads(data)
    except (ValueError, UnicodeError) as exc:
        raise ImageError('Invalid image JSON metadata') from exc
    if not isinstance(result, dict):
        raise ImageError('Image metadata must be an object')
    return result


def digest_hex(value):
    if not isinstance(value, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', value):
        raise ImageError('Only SHA-256 image descriptors are supported')
    return value.split(':')[1]


def descriptor(value):
    if not isinstance(value, dict):
        raise ImageError('Invalid image descriptor')
    digest_hex(value.get('digest'))
    size = value.get('size')
    if type(size) is not int or size < 0:
        raise ImageError('Invalid image descriptor size')
    return value


def platform_parts(platform):
    if not re.fullmatch(r'linux/(amd64|arm64)(/v[0-9]+)?', platform):
        raise ImageError('Supported platforms: linux/amd64 and linux/arm64[/variant]')
    return platform.split('/')


def parse_reference(reference):
    if not re.fullmatch(r'[a-zA-Z0-9._/:+-]+(?:@sha256:[0-9a-f]{64})?', reference):
        raise ImageError('Use a registry image reference without URL scheme or credentials')
    base, at, pinned = reference.partition('@')
    if at:
        digest_hex(pinned)
    last = base.rsplit('/', 1)[-1]
    if ':' in last:
        base, tag = base.rsplit(':', 1)
    else:
        tag = 'latest'
    parts = base.split('/')
    if len(parts) > 1 and ('.' in parts[0] or ':' in parts[0] or parts[0] == 'localhost'):
        host, repo = parts[0], '/'.join(parts[1:])
    else:
        host, repo = 'registry-1.docker.io', base
    if host in ('docker.io', 'index.docker.io'):
        host = 'registry-1.docker.io'
    if host == 'registry-1.docker.io' and '/' not in repo:
        repo = 'library/' + repo
    if not re.fullmatch(r'[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*', repo):
        raise ImageError('Unsupported repository name')
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}', tag):
        raise ImageError('Invalid image tag')
    return host, repo, pinned if at else tag


def secure_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ImageError('Image access requires HTTPS URLs without credentials')


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        secure_url(newurl)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and urllib.parse.urlsplit(req.full_url).netloc != urllib.parse.urlsplit(newurl).netloc:
            redirected.remove_header('Authorization')
        return redirected


class Source:
    def __init__(self, image=None, layout=None):
        self.layout = Path(layout).resolve() if layout else None
        self.total = 0
        self.token = None
        self.opener = urllib.request.build_opener(SafeRedirect())
        if image:
            self.host, self.repo, self.ref = parse_reference(image)
        if self.layout:
            marker = self.local('oci-layout', META_LIMIT)
            if parse_json(marker).get('imageLayoutVersion') != '1.0.0':
                raise ImageError('Unsupported OCI layout version')

    def local(self, relative, limit):
        path = (self.layout / relative).resolve()
        if not path.is_relative_to(self.layout) or not path.is_file():
            raise ImageError('Missing or unsafe OCI layout file')
        if path.stat().st_size > limit:
            raise ImageError('Image metadata size limit exceeded')
        return path.read_bytes()

    def open_url(self, url, authorize=True):
        secure_url(url)
        headers = {'Accept': ACCEPT, 'User-Agent': 'recompose/0.3.0'}
        if authorize and self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        try:
            return self.opener.open(urllib.request.Request(url, headers=headers), timeout=30)
        except urllib.error.HTTPError as exc:
            if exc.code != 401 or not authorize or self.token:
                raise ImageError(f'Registry HTTP {exc.code}; only public anonymous pulls are supported') from None
            challenge = exc.headers.get('WWW-Authenticate', '')
            exc.close()
            if not challenge.lower().startswith('bearer '):
                raise ImageError('Registry requires unsupported authentication')
            fields = dict(re.findall(r'(\w+)="([^"\r\n]*)"', challenge))
            realm = fields.get('realm', '')
            secure_url(realm)
            query = urllib.parse.urlencode({'service': fields.get('service', ''), 'scope': f'repository:{self.repo}:pull'})
            token_url = realm + ('&' if '?' in realm else '?') + query
            with self.open_url(token_url, authorize=False) as response:
                token_data = response.read(META_LIMIT + 1)
            if len(token_data) > META_LIMIT:
                raise ImageError('Authentication response too large')
            payload = parse_json(token_data)
            self.token = payload.get('token') or payload.get('access_token')
            if not isinstance(self.token, str) or not self.token or '\n' in self.token or '\r' in self.token:
                raise ImageError('Registry did not issue an anonymous pull token')
            return self.open_url(url)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ImageError('Registry connection failed; check network and TLS access') from None

    def metadata(self, reference=None):
        if self.layout:
            if reference is None:
                return self.local('index.json', META_LIMIT)
            return self.local('blobs/sha256/' + digest_hex(reference), META_LIMIT)
        reference = reference or self.ref
        with self.open_url(f'https://{self.host}/v2/{self.repo}/manifests/{reference}') as response:
            data = response.read(META_LIMIT + 1)
        if len(data) > META_LIMIT:
            raise ImageError('Image metadata size limit exceeded')
        return data

    def blob(self, desc, destination):
        descriptor(desc)
        if desc['size'] > BLOB_LIMIT or self.total + desc['size'] > TOTAL_LIMIT:
            raise ImageError('Image download size limit exceeded')
        if self.layout:
            path = (self.layout / 'blobs/sha256' / digest_hex(desc['digest'])).resolve()
            if not path.is_relative_to(self.layout):
                raise ImageError('Unsafe OCI blob path')
            stream = path.open('rb')
        else:
            stream = self.open_url(f'https://{self.host}/v2/{self.repo}/blobs/{desc["digest"]}')
        count, checksum, started = 0, hashlib.sha256(), time.monotonic()
        with stream, Path(destination).open('wb') as output:
            while chunk := stream.read(1024 * 1024):
                count += len(chunk)
                if count > desc['size'] or time.monotonic() - started > 300:
                    raise ImageError('Image blob size or transfer-time limit exceeded')
                checksum.update(chunk)
                output.write(chunk)
        if count != desc['size'] or 'sha256:' + checksum.hexdigest() != desc['digest']:
            raise ImageError('Image blob digest or size mismatch')
        self.total += count


def load_image(source, platform, workspace):
    requested = platform_parts(platform)
    raw = source.metadata()
    root_digest = digest(raw)
    if not source.layout and source.ref.startswith('sha256:') and root_digest != source.ref:
        raise ImageError('Requested manifest digest mismatch')
    manifest = parse_json(raw)
    for _ in range(4):
        if 'manifests' not in manifest:
            break
        candidates = []
        if not isinstance(manifest['manifests'], list):
            raise ImageError('Invalid image index')
        for item in manifest['manifests']:
            descriptor(item)
            p = item.get('platform', {})
            if p.get('os') == requested[0] and p.get('architecture') == requested[1] and (len(requested) < 3 or p.get('variant') == requested[2]):
                candidates.append(item)
        # Single unannotated OCI layout entry: validate its config below.
        if not candidates and source.layout and len(manifest['manifests']) == 1 and not manifest['manifests'][0].get('platform'):
            candidates = manifest['manifests']
        if len(candidates) != 1:
            raise ImageError('Platform is missing or ambiguous in image index')
        chosen = candidates[0]
        raw = source.metadata(chosen['digest'])
        if digest(raw) != chosen['digest'] or len(raw) != chosen['size']:
            raise ImageError('Manifest digest or size mismatch')
        manifest = parse_json(raw)
    if manifest.get('schemaVersion') != 2 or 'manifests' in manifest:
        raise ImageError('Only OCI/Docker schema-2 image manifests are supported')
    config_desc = descriptor(manifest.get('config'))
    if config_desc['size'] > META_LIMIT:
        raise ImageError('Image config too large')
    config_path = workspace / 'config.json'
    source.blob(config_desc, config_path)
    config = parse_json(config_path.read_bytes())
    if config.get('os') != requested[0] or config.get('architecture') != requested[1]:
        raise ImageError('Image config does not match selected platform')
    if len(requested) == 3 and config.get('variant') not in (None, requested[2]):
        raise ImageError('Image variant does not match selected platform')
    layers = manifest.get('layers')
    if not isinstance(layers, list) or len(layers) > 256:
        raise ImageError('Invalid or excessive image layers')
    for layer in layers:
        descriptor(layer)
        if layer.get('mediaType') not in LAYER_TYPES:
            raise ImageError('Unsupported layer format; only tar and gzip layers are supported')
    return manifest, config, {'index_digest': root_digest, 'manifest_digest': digest(raw),
                              'config_digest': config_desc['digest'], 'platform': platform}


def container_path(name):
    if not isinstance(name, str) or '\\' in name or any(ord(c) < 32 for c in name):
        raise ImageError('Unsafe image path')
    parts = name.split('/')
    if '..' in parts:
        raise ImageError('Parent traversal in image path')
    return '/'.join(p for p in parts if p not in ('', '.'))


class LimitedReader:
    def __init__(self, stream, budget):
        self.stream, self.budget = stream, budget

    def read(self, size=-1):
        data = self.stream.read(size)
        self.budget[0] += len(data)
        if self.budget[0] > EXPANDED_LIMIT:
            raise ImageError('Expanded image size limit exceeded')
        return data


def scan_layers(source, manifest, workspace, references=()):
    files, budget, entries, serial = {}, [0], 0, 0
    for number, layer in enumerate(manifest['layers']):
        archive = workspace / f'layer-{number}'
        source.blob(layer, archive)
        additions, removals, opaque = {}, [], []
        with archive.open('rb') as raw:
            stream = gzip.GzipFile(fileobj=raw) if layer['mediaType'].endswith('gzip') else raw
            with tarfile.open(fileobj=LimitedReader(stream, budget), mode='r|') as tar:
                for member in tar:
                    entries += 1
                    if entries > ENTRY_LIMIT:
                        raise ImageError('Image entry limit exceeded')
                    path = container_path(member.name)
                    if not path:
                        continue
                    basename = posixpath.basename(path)
                    parent = posixpath.dirname(path)
                    if basename == '.wh..wh..opq':
                        opaque.append(parent)
                        continue
                    if basename.startswith('.wh.'):
                        removals.append(posixpath.join(parent, basename[4:]))
                        continue
                    if member.size > FILE_LIMIT or member.size < 0:
                        raise ImageError('Image entry size limit exceeded')
                    entry = {'kind': 'other', 'payload': None}
                    if member.isdir():
                        entry['kind'] = 'directory'
                    elif member.isfile():
                        entry['kind'] = 'file'
                        if path.lower().endswith('.jar') or requested_file(path, references):
                            serial += 1
                            if serial > 256:
                                raise ImageError('Retained file candidate limit exceeded')
                            payload = workspace / f'jar-{serial}'
                            with tar.extractfile(member) as data, payload.open('wb') as output:
                                shutil.copyfileobj(data, output, 1024 * 1024)
                            entry['payload'] = payload
                    elif member.issym() or member.islnk():
                        entry['kind'] = 'link'  # Never materialized or followed.
                    additions[path] = entry
        # Whiteouts affect previous layers, regardless of archive member order.
        for old in list(files):
            if any(old == r or old.startswith(r + '/') for r in removals) or any(not d or old.startswith(d + '/') for d in opaque):
                del files[old]
        directory_paths = {str(parent) for name in (*files, *additions) for parent in PurePosixPath(name).parents if str(parent) != '.'}
        for path, entry in additions.items():
            if entry['kind'] != 'directory' and path in directory_paths:
                for old in list(files):
                    if old.startswith(path + '/'):
                        del files[old]
            files[path] = entry
        archive.unlink()
    # Never select a file whose parent path is a non-directory (including links).
    result = {}
    for path, entry in files.items():
        if entry['payload']:
            parents = list(PurePosixPath(path).parents)[:-1]
            if any(files.get(str(p), {}).get('kind', 'directory') != 'directory' for p in parents):
                continue
            result[path] = entry['payload']
    return result


def runtime_summary(config):
    settings = config.get('config') or {}
    if not isinstance(settings, dict):
        raise ImageError('Invalid runtime config')
    entrypoint, cmd = settings.get('Entrypoint') or [], settings.get('Cmd') or []
    if not all(isinstance(v, list) and all(isinstance(x, str) for x in v) for v in (entrypoint, cmd)):
        raise ImageError('Unsupported runtime command metadata')
    command = entrypoint + cmd
    workdir = settings.get('WorkingDir') or '/'
    if not isinstance(workdir, str):
        raise ImageError('Invalid image working directory')
    jar_path = None
    if command and posixpath.basename(command[0]) == 'java' and '-jar' in command:
        index = command.index('-jar')
        if index + 1 < len(command) and '$' not in command[index + 1]:
            jar_path = container_path(posixpath.join(workdir, command[index + 1]))
    environment = settings.get('Env') or []
    if not isinstance(environment, list) or not all(isinstance(v, str) for v in environment):
        raise ImageError('Invalid image environment')
    major = None
    for item in environment:
        key, _, value = item.partition('=')
        if key == 'JAVA_VERSION':
            match = re.match(r'^(?:jdk-)?(?:1\.)?(\d+)(?:[._+u-]|$)', value)
            if match:
                major = int(match[1])
    return {'working_directory': '/' + container_path(workdir), 'command_jar': '/' + jar_path if jar_path else None,
            'environment_keys': sorted({v.split('=', 1)[0] for v in environment}),
            'java_major_hint': major, 'java_version_evidence': 'image-env-hint' if major else 'unknown',
            'has_entrypoint': bool(entrypoint), 'has_command': bool(cmd)}


def executable_jar(path):
    try:
        with zipfile.ZipFile(path) as jar:
            item = jar.getinfo('META-INF/MANIFEST.MF')
            if item.file_size > 1024 * 1024:
                return False
            return bool(re.search(rb'^Main-Class:\s*\S+', jar.read(item), re.M))
    except (zipfile.BadZipFile, KeyError, RuntimeError):
        return False


def _image_operation(image=None, layout=None, platform='linux/amd64', output=None, jar=None, service='app', compose=None, include_files=None):
    spec = compose_service(compose, service)
    if not image and not layout:
        image = spec.get('image')
    if bool(image) == bool(layout):
        raise ImageError('Choose exactly one image reference or OCI layout')
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,30}', service):
        raise ImageError('Invalid service name')
    destination = Path(output).resolve() if output else None
    if destination and destination.exists():
        raise ImageError('Output directory already exists')
    with tempfile.TemporaryDirectory(prefix='recompose-image-') as temp:
        workspace = Path(temp)
        source = Source(image, layout)
        manifest, config, provenance = load_image(source, platform, workspace)
        provenance['type'] = 'oci-layout' if layout else 'registry'
        if image:
            provenance.update(registry=source.host, repository=source.repo, requested_reference=source.ref)
        runtime = runtime_summary(config)
        execution = analyze_execution(config, spec, service, include_files)
        runtime['execution'] = execution
        report = {'schema_version': 1, 'source': provenance, 'runtime': runtime,
                  'layer_count': len(manifest['layers']),
                  'limitations': ['Only recognized arguments are copied; environment values are never copied.',
                                  'Java version is an environment hint, not executable or bytecode verification.',
                                  'Host mounts, secrets, OS packages and shell scripts require manual migration; file secret screening is heuristic.']}
        if not destination:
            return report
        candidates = scan_layers(source, manifest, workspace, execution['references'])
        runnable = {name: path for name, path in candidates.items() if name.lower().endswith('.jar') and executable_jar(path) and not masked_file(name, execution)}
        selected = container_path(jar) if jar else container_path(execution['command_jar']) if execution['command_jar'] else None
        if selected is None and len(runnable) == 1:
            selected = next(iter(runnable))
        if selected not in runnable:
            raise ImageError('No unambiguous executable JAR; use --jar with a regular executable JAR path. Candidates: ' + ', '.join('/' + x for x in sorted(runnable)))
        if jar and execution['command_jar'] and '/' + selected != execution['command_jar']:
            execution['review_items'].append({'code': 'JAR_OVERRIDE', 'detail': 'Selected JAR differs from the effective command; review arguments and dependencies.', 'resolved': False})
        content = runnable[selected]
        with zipfile.ZipFile(content) as archive:
            manifest_text = archive.read('META-INF/MANIFEST.MF')
        if re.search(rb'^Class-Path:', manifest_text, re.M):
            execution['review_items'].append({'code': 'MANIFEST_CLASSPATH', 'detail': 'Review manifest Class-Path and explicitly include its dependencies; entries are not resolved automatically.', 'resolved': False})
        checksum = hashlib.sha256()
        with content.open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                checksum.update(chunk)
        report['artifact'] = {'source_path': '/' + selected, 'sha256': checksum.hexdigest(),
                              'executable_jar_candidates': ['/' + name for name in sorted(runnable)]}
        supporting = []
        for ref in execution['references']:
            matches = [(name, path) for name, path in candidates.items()
                       if requested_file(name, [ref]) and not masked_file(name, execution)]
            if not matches:
                execution['review_items'].append({'code': 'MISSING_FILE', 'detail': ref['path'], 'resolved': False})
            for name, path in sorted(matches):
                if name == selected or any(item['container_path'] == '/' + name for item, _ in supporting):
                    continue
                if sensitive_file(name, path):
                    execution['review_items'].append({'code': 'SENSITIVE_FILE', 'detail': '/' + name + ': inject separately; file omitted', 'resolved': False})
                    continue
                item = {'source': f'files/{len(supporting):04d}.bin', 'container_path': '/' + name,
                        'destination': vm_path(service, '/' + name), 'role': ref['role'], 'reviewed': False,
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                supporting.append((item, path))
        migration = {'schema_version': 1, 'service': service, 'target': 'ubuntu-24.04', 'reviewed': False,
                     'artifact': 'app.jar', 'java_version': runtime['java_major_hint'],
                     'java_version_evidence': runtime['java_version_evidence'], 'jvm_options': execution['jvm_options'], 'app_args': execution['app_args'],
                     'artifact_destination': vm_path(service, '/' + selected),
                     'working_directory': execution['target_working_directory'],
                     'files': [item for item, _ in supporting], 'review_items': execution['review_items'],
                     'os_packages': [], 'required_environment': execution['required_environment'], 'analysis': report}
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=destination.parent) as staging:
            bundle = Path(staging) / 'extracted'
            bundle.mkdir()
            shutil.copyfile(content, bundle / 'app.jar')
            for item, path in supporting:
                target = bundle / item['source']
                target.parent.mkdir(exist_ok=True)
                shutil.copyfile(path, target)
            (bundle / 'image-report.json').write_text(json.dumps(report, indent=2) + '\n')
            (bundle / 'migration-plan.yaml').write_text(yaml.safe_dump(migration, sort_keys=False))
            if destination.exists():
                raise ImageError('Output directory already exists')
            bundle.rename(destination)
        return {'output': str(destination), **report}


def image_operation(image=None, layout=None, platform='linux/amd64', output=None, jar=None, service='app', compose=None, include_files=None):
    try:
        return _image_operation(image, layout, platform, output, jar, service, compose, include_files)
    except ImageError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError, zlib.error, OverflowError, http.client.HTTPException):
        raise ImageError('Malformed or unsupported image data') from None
