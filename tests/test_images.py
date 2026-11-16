import gzip
import io
import json
import tarfile
import tempfile
import unittest
import urllib.request
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

import yaml
from recompose.cli import generate, main
from recompose.images import ImageError, SafeRedirect, digest, image_operation, parse_reference


def jar_bytes(main='example.Main'):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as jar:
        jar.writestr('META-INF/MANIFEST.MF', f'Main-Class: {main}\n')
    return buffer.getvalue()


def layer_bytes(entries):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as tar:
        for name, value in entries:
            member = tarfile.TarInfo(name)
            if isinstance(value, tuple):
                member.type = tarfile.SYMTYPE
                member.linkname = value[0]
                tar.addfile(member)
            else:
                member.size = len(value)
                tar.addfile(member, io.BytesIO(value))
    return gzip.compress(buffer.getvalue())


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.layout = self.root / 'oci'
        (self.layout / 'blobs/sha256').mkdir(parents=True)
        (self.layout / 'oci-layout').write_text('{"imageLayoutVersion":"1.0.0"}')

    def blob(self, data, media):
        checksum = digest(data)
        (self.layout / 'blobs/sha256' / checksum.split(':')[1]).write_bytes(data)
        return {'mediaType': media, 'digest': checksum, 'size': len(data)}

    def fixture(self, layers=None, command=None, architecture='amd64'):
        self.jar = jar_bytes()
        if layers is None:
            layers = [[('app/app.jar', self.jar)]]
        config = {'os': 'linux', 'architecture': architecture, 'config': {
            'Entrypoint': command or ['java', '-jar', '/app/app.jar'], 'WorkingDir': '/app',
            'Env': ['JAVA_VERSION=21.0.5', 'PASSWORD=never-report-this']}}
        manifest = {'schemaVersion': 2,
                    'config': self.blob(json.dumps(config).encode(), 'application/vnd.oci.image.config.v1+json'),
                    'layers': [self.blob(layer_bytes(layer), 'application/vnd.oci.image.layer.v1.tar+gzip') for layer in layers]}
        self.manifest = manifest
        desc = self.blob(json.dumps(manifest).encode(), 'application/vnd.oci.image.manifest.v1+json')
        desc['platform'] = {'os': 'linux', 'architecture': architecture}
        (self.layout / 'index.json').write_text(json.dumps({'schemaVersion': 2, 'manifests': [desc]}))
        return desc

    def extract(self, **kwargs):
        return image_operation(layout=self.layout, output=self.root / 'out', **kwargs)

    def test_inspect_redacts_and_has_digest(self):
        self.fixture()
        r = image_operation(layout=self.layout)
        self.assertNotIn('never-report-this', json.dumps(r))
        self.assertEqual(r['runtime']['command_jar'], '/app/app.jar')
        self.assertEqual(r['runtime']['java_major_hint'], 21)
        self.assertTrue(r['source']['manifest_digest'].startswith('sha256:'))
        self.assertFalse((self.root / 'out').exists())

    def test_extract_to_generate(self):
        self.fixture()
        report = self.extract(service='demo')
        self.assertEqual((self.root / 'out/app.jar').read_bytes(), self.jar)
        plan_path = self.root / 'out/migration-plan.yaml'
        plan = yaml.safe_load(plan_path.read_text())
        self.assertFalse(plan['reviewed'])
        plan['reviewed'] = True
        plan_path.write_text(yaml.safe_dump(plan))
        generate(plan_path, self.root / 'deployment')
        self.assertEqual((self.root / 'deployment/artifacts/app.jar').read_bytes(), self.jar)
        self.assertEqual(report['artifact']['sha256'], digest(self.jar).split(':')[1])

    def test_overwrite_refused(self):
        self.fixture()
        self.extract()
        with self.assertRaises(ImageError):
            self.extract()

    def test_layer_replacement(self):
        replacement = jar_bytes('NewMain')
        self.fixture([[('app/app.jar', jar_bytes())], [('app/app.jar', replacement)]])
        self.extract()
        self.assertEqual((self.root / 'out/app.jar').read_bytes(), replacement)

    def test_whiteout(self):
        self.fixture([[('app/app.jar', jar_bytes())], [('app/.wh.app.jar', b'')]])
        with self.assertRaises(ImageError):
            self.extract()
        self.assertFalse((self.root / 'out').exists())

    def test_opaque_preserves_current_layer(self):
        new = jar_bytes('New')
        self.fixture([[('app/old.jar', jar_bytes())], [('app/app.jar', new), ('app/.wh..wh..opq', b'')]])
        r = self.extract()
        self.assertEqual(r['artifact']['executable_jar_candidates'], ['/app/app.jar'])

    def test_whiteout_does_not_remove_same_layer_replacement(self):
        new = jar_bytes('New')
        self.fixture([[('app/app.jar', jar_bytes())], [('app/app.jar', new), ('app/.wh.app.jar', b'')]])
        self.extract()
        self.assertEqual((self.root / 'out/app.jar').read_bytes(), new)

    def test_traversal_rejected(self):
        self.fixture([[('../escape.jar', jar_bytes())]])
        with self.assertRaises(ImageError):
            self.extract()
        self.assertFalse((self.root / 'escape.jar').exists())

    def test_symlink_not_followed(self):
        self.fixture([[('app/app.jar', ('/etc/passwd',))]])
        with self.assertRaises(ImageError):
            self.extract()

    def test_symlink_parent_not_followed(self):
        self.fixture([[('app', ('/tmp',)), ('app/app.jar', jar_bytes())]])
        with self.assertRaises(ImageError):
            self.extract()

    def test_nested_symlink_parent_not_followed(self):
        self.fixture([[('app/nested', ('/tmp',)), ('app/nested/app.jar', jar_bytes())]],
                     command=['java', '-jar', '/app/nested/app.jar'])
        with self.assertRaises(ImageError):
            self.extract()

    def test_ambiguous_jar_requires_selection(self):
        self.fixture([[('a.jar', jar_bytes()), ('b.jar', jar_bytes())]], command=['/entrypoint.sh'])
        with self.assertRaises(ImageError):
            self.extract()
        r = self.extract(jar='/b.jar')
        self.assertEqual(r['artifact']['source_path'], '/b.jar')

    def test_platform_mismatch(self):
        self.fixture(architecture='arm64')
        with self.assertRaises(ImageError):
            self.extract()

    def test_corrupt_blob(self):
        self.fixture()
        layer = self.manifest['layers'][0]
        (self.layout / 'blobs/sha256' / layer['digest'].split(':')[1]).write_bytes(b'broken')
        with self.assertRaises(ImageError):
            self.extract()

    def test_entry_size_limit(self):
        self.fixture()
        with patch('recompose.images.FILE_LIMIT', 10), self.assertRaises(ImageError):
            self.extract()

    def test_expanded_limit(self):
        self.fixture()
        with patch('recompose.images.EXPANDED_LIMIT', 100), self.assertRaises(ImageError):
            self.extract()

    def test_cli_local_image(self):
        self.fixture()
        path = self.root / 'report.json'
        self.assertEqual(main(['inspect', '--oci-layout', str(self.layout), '--format', 'json', '--output', str(path)]), 0)
        self.assertIn('runtime', json.loads(path.read_text()))

    def test_reference_normalization(self):
        self.assertEqual(parse_reference('eclipse-temurin:21-jre'), ('registry-1.docker.io', 'library/eclipse-temurin', '21-jre'))
        self.assertEqual(parse_reference('docker.io/library/openjdk:17')[1], 'library/openjdk')
        with self.assertRaises(ImageError):
            parse_reference('https://user:password@registry/app')

    def test_cross_host_redirect_removes_token(self):
        request = urllib.request.Request('https://registry.test/blob', headers={'Authorization': 'Bearer secret'})
        redirected = SafeRedirect().redirect_request(request, None, 302, '', {}, 'https://cdn.test/blob')
        self.assertFalse(redirected.has_header('Authorization'))
        with self.assertRaises(ImageError):
            SafeRedirect().redirect_request(request, None, 302, '', {}, 'http://cdn.test/blob')


class RegistryTests(unittest.TestCase):
    setUp = ImageTests.setUp
    blob = ImageTests.blob
    fixture = ImageTests.fixture
    extract = ImageTests.extract
    def test_anonymous_registry_extract(self):
        self.fixture()
        index = (self.layout / 'index.json').read_bytes()
        requests = []
        challenged = False
        def open_request(request, timeout):
            nonlocal challenged
            url = request.full_url
            requests.append(url)
            if url.startswith('https://auth.test/token?'):
                return io.BytesIO(b'{"token":"anonymous-token"}')
            if not challenged:
                challenged = True
                raise urllib.error.HTTPError(url, 401, 'auth', {'WWW-Authenticate': 'Bearer realm="https://auth.test/token",service="registry.test"'}, io.BytesIO())
            self.assertEqual(request.get_header('Authorization'), 'Bearer anonymous-token')
            key = url.rsplit('/', 1)[-1]
            if key == 'latest':
                return io.BytesIO(index)
            return io.BytesIO((self.layout / 'blobs/sha256' / key.split(':')[1]).read_bytes())
        with patch('urllib.request.OpenerDirector.open', side_effect=open_request):
            r = image_operation(image='registry.test/demo:latest', output=self.root / 'remote')
        self.assertEqual((self.root / 'remote/app.jar').read_bytes(), self.jar)
        self.assertEqual(r['source']['registry'], 'registry.test')
        self.assertNotIn('anonymous-token', json.dumps(r))
        self.assertTrue(any('scope=repository%3Ademo%3Apull' in url for url in requests))

    def test_unsupported_compression(self):
        self.fixture()
        self.manifest['layers'][0]['mediaType'] = 'application/vnd.oci.image.layer.v1.tar+zstd'
        desc = self.blob(json.dumps(self.manifest).encode(), 'application/vnd.oci.image.manifest.v1+json')
        (self.layout / 'index.json').write_text(json.dumps({'schemaVersion':2, 'manifests':[desc]}))
        with self.assertRaises(ImageError):
            self.extract()

    def test_manifest_tampering(self):
        desc = self.fixture()
        path = self.layout / 'blobs/sha256' / desc['digest'].split(':')[1]
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaises(ImageError):
            self.extract()

    def test_unknown_runtime_not_upgraded(self):
        self.fixture()
        config_desc = self.manifest['config']
        config = json.loads((self.layout / 'blobs/sha256' / config_desc['digest'].split(':')[1]).read_bytes())
        config['config']['Env'] = ['PASSWORD=hidden']
        self.manifest['config'] = self.blob(json.dumps(config).encode(), 'application/vnd.oci.image.config.v1+json')
        desc = self.blob(json.dumps(self.manifest).encode(), 'application/vnd.oci.image.manifest.v1+json')
        (self.layout / 'index.json').write_text(json.dumps({'schemaVersion':2, 'manifests':[desc]}))
        self.extract()
        p = yaml.safe_load((self.root / 'out/migration-plan.yaml').read_text())
        self.assertIsNone(p['java_version'])
