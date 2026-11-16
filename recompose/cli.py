"""Conservative, offline Java-to-VM migration scaffold."""
import argparse
import hashlib
import json
import re
import shlex
import shutil
import sys
import tempfile
import tarfile
import urllib.error
import zipfile
from pathlib import Path, PurePosixPath

import yaml

from recompose.java_images import review_dockerfile
from recompose.images import ImageError, image_operation


class MigrationError(ValueError):
    pass


def read_yaml(path):
    value = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise MigrationError('Expected a YAML mapping')
    return value


def packages(path):
    """Candidates only: never infer runtime necessity from installation alone."""
    if not path:
        return []
    lines = Path(path).read_text(encoding='utf-8').replace('\\\n', ' ').splitlines()
    stage = 'unknown'
    result = []
    for number, line in enumerate(lines, 1):
        if re.match(r'^\s*FROM\s', line, re.I):
            stage = line.strip()
        match = re.search(r'\b(apt-get|apt|apk|dnf|yum)\s+(?:--\S+\s+)*(install|add)\s+([^;&|]+)', line)
        if match:
            for name in shlex.split(match[3]):
                if not name.startswith('-'):
                    result.append({'name': name, 'manager': match[1], 'stage': stage,
                                   'evidence': f'{path}:logical-line-{number}',
                                   'status': 'review-required'})
    return result


def inspect(compose, dockerfile=None, build_target=None):
    data = read_yaml(compose)
    services = data.get('services')
    if not isinstance(services, dict) or not services:
        raise MigrationError('Compose must contain services')
    try:
        image_analysis = review_dockerfile(dockerfile, build_target)
    except ValueError as exc:
        raise MigrationError(str(exc)) from exc
    output = []
    for name, spec in services.items():
        if not isinstance(name, str):
            raise MigrationError('Service name must be a string')
        if not isinstance(spec, dict):
            raise MigrationError('Service must be a mapping')
        env = spec.get('environment', {}) or {}
        if isinstance(env, list):
            env = {str(item).split('=', 1)[0]: None for item in env}
        if not isinstance(env, dict):
            raise MigrationError('Invalid environment configuration')
        # Report names only. Commands and image URLs may also contain credentials.
        output.append({'name': name, 'environment_keys': sorted(str(k) for k in env),
                       'has_image': bool(spec.get('image')),
                       'has_command_override': 'command' in spec or 'entrypoint' in spec,
                       'review_fields': sorted(k for k in spec if k != 'environment'),
                       'status': 'review-required'})
    return {'schema_version': 1, 'services': output, 'os_package_candidates': packages(dockerfile),
            'java_image_review': image_analysis,
            'limitations': ['Static analysis only; no image inspection or extraction.',
                             'Compose interpolation, includes and overrides are not resolved.',
                             'Base-image packages and runtime necessity are not inferred.']}


def plan(compose, service, dockerfile=None, build_target=None):
    data = read_yaml(compose)
    services = data.get("services")
    if not isinstance(services, dict):
        raise MigrationError("Compose must contain services")
    spec = services.get(service, {})
    build = spec.get("build", {}) if isinstance(spec, dict) else {}
    if build_target is None and isinstance(build, dict):
        build_target = build.get("target")
    if build_target is not None and not isinstance(build_target, str):
        raise MigrationError('Build target must be a string')
    report = inspect(compose, dockerfile, build_target)
    selected = next((s for s in report['services'] if s['name'] == service), None)
    if selected is None:
        raise MigrationError('Unknown service')
    return {'schema_version': 1, 'service': service, 'target': 'ubuntu-24.04',
            'reviewed': False, 'artifact': None,
            'java_version': report['java_image_review']['java_major_hint'],
            'java_version_evidence': report['java_image_review']['confidence'],
            'jvm_options': [], 'app_args': [], 'os_packages': [],
            'required_environment': selected['environment_keys'], 'analysis': report}


def safe_string(value):
    return isinstance(value, str) and not any(ord(c) < 32 for c in value)


def unit_arg(value):
    if not safe_string(value):
        raise MigrationError('Arguments must be strings without control characters')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('$', '$$') + '"'


def generate(plan_path, destination):
    p = read_yaml(plan_path)
    if p.get('schema_version') != 1 or p.get('reviewed') is not True:
        raise MigrationError('Review the plan and set reviewed: true first')
    name = p.get('service', '')
    if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,30}', name):
        raise MigrationError('Service must match [a-z][a-z0-9-]{0,30}')
    if p.get('target') != 'ubuntu-24.04' or p.get('java_version') not in (17, 21):
        raise MigrationError('Supported target: ubuntu-24.04, Java 17 or 21')
    if not isinstance(p.get('artifact'), str) or not p['artifact']:
        raise MigrationError('Set artifact to a reviewed executable JAR path')
    artifact = (Path(plan_path).resolve().parent / p['artifact']).resolve()
    if not artifact.is_file() or not zipfile.is_zipfile(artifact):
        raise MigrationError('Artifact must be a JAR/ZIP file')
    with zipfile.ZipFile(artifact) as jar:
        try:
            manifest = jar.read('META-INF/MANIFEST.MF').decode('utf-8')
        except (KeyError, UnicodeError) as exc:
            raise MigrationError('JAR manifest is missing or invalid') from exc
        if not re.search(r'^Main-Class:\s*\S+', manifest, re.M):
            raise MigrationError('JAR must declare Main-Class')
    review_items = p.get('review_items', [])
    if not isinstance(review_items, list) or any(not isinstance(i, dict) or i.get('resolved') is not True for i in review_items):
        raise MigrationError('Resolve each review_items entry before generation')
    def managed_path(value):
        prefix = f'/opt/{name}/rootfs'
        if (not isinstance(value, str) or not re.fullmatch(r'/[A-Za-z0-9_./+ -]+', value)
                or '..' in value.split('/') or not (value == prefix or value.startswith(prefix + '/'))):
            raise MigrationError('File destinations must be safe paths under the service rootfs')
        return str(PurePosixPath(value))
    artifact_dest = managed_path(p['artifact_destination']) if 'artifact_destination' in p else f'/opt/{name}/app.jar'
    workdir = managed_path(p['working_directory']) if 'working_directory' in p else f'/var/lib/{name}'
    supporting = p.get('files', [])
    if not isinstance(supporting, list):
        raise MigrationError('files must be a list')
    base = Path(plan_path).resolve().parent
    targets = {artifact_dest}
    checked_files = []
    for item in supporting:
        if not isinstance(item, dict) or item.get('reviewed') is not True or not isinstance(item.get('source'), str):
            raise MigrationError('Review every supplemental file before generation')
        target = managed_path(item.get('destination'))
        source = (base / item['source']).resolve()
        if not source.is_relative_to(base) or not source.is_file():
            raise MigrationError('Supplemental source must be a regular file inside the plan directory')
        if target in targets or any(target.startswith(t + '/') or t.startswith(target + '/') for t in targets):
            raise MigrationError('Conflicting file destinations')
        targets.add(target)
        checksum = hashlib.sha256(source.read_bytes()).hexdigest()
        if checksum != item.get('sha256'):
            raise MigrationError('Supplemental file digest mismatch; review the changed file')
        checked_files.append((source, target, checksum))
    if any(workdir == t or workdir.startswith(t + '/') for t in targets):
        raise MigrationError('Working directory conflicts with a file destination')
    args = []
    for key in ('jvm_options', 'app_args', 'os_packages', 'required_environment'):
        values = p.get(key, [])
        if not isinstance(values, list) or not all(safe_string(v) for v in values):
            raise MigrationError(f'{key} must be a list of strings')
    for package in p.get('os_packages', []):
        if not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*', package):
            raise MigrationError('OS packages must be explicit Ubuntu package names')
    for key in p.get('required_environment', []):
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
            raise MigrationError('Invalid environment variable name')
    args = [unit_arg(v) for v in p.get('jvm_options', [])]
    args += ['-jar', unit_arg(artifact_dest)]
    args += [unit_arg(v) for v in p.get('app_args', [])]
    unit = f'''[Unit]
Description=Recompose Java service {name}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={name}
Group={name}
WorkingDirectory={unit_arg(workdir)}
EnvironmentFile=/etc/{name}/app.env
ExecStart=/usr/bin/java {' '.join(args)}
Restart=on-failure
RestartSec=5
TimeoutStopSec=60
NoNewPrivileges=true
PrivateTmp=true
UMask=0027

[Install]
WantedBy=multi-user.target
'''
    tasks = [
        {'name': 'Require supported OS', 'ansible.builtin.assert': {'that': ["ansible_distribution == 'Ubuntu'", "ansible_distribution_version == '24.04'"]}},
        {'name': 'Require deployment environment', 'ansible.builtin.assert': {'that': ["recompose_environment is defined", "recompose_environment is mapping"]}},
        {'name': 'Require application variables', 'ansible.builtin.assert': {'that': ["item in recompose_environment"]}, 'loop': p.get('required_environment', [])},
        {'name': 'Install runtime dependencies', 'ansible.builtin.apt': {'name': [f"openjdk-{p['java_version']}-jre-headless"] + p.get('os_packages', []), 'state': 'present', 'update_cache': True}},
        {'name': 'Check selected Java runtime', 'ansible.builtin.command': {'argv': ['/usr/bin/java', '-version']}, 'register': 'recompose_java', 'changed_when': False},
        {'name': 'Require planned Java major', 'ansible.builtin.assert': {'that': [f"recompose_java.stderr is search('version \"{p['java_version']}[.\"]')"], 'fail_msg': 'Select the planned Java major at /usr/bin/java before deployment.'}},
        {'name': 'Create service account', 'ansible.builtin.user': {'name': name, 'system': True, 'create_home': False, 'shell': '/usr/sbin/nologin'}},
    ]
    for folder, owner in [(f'/opt/{name}', 'root'), (f'/etc/{name}', 'root'), (f'/var/lib/{name}', name)]:
        tasks.append({'name': f'Create {folder}', 'ansible.builtin.file': {'path': folder, 'state': 'directory', 'owner': owner, 'group': name, 'mode': '0750'}})
    directories = {str(PurePosixPath(t).parent) for t in targets} | {workdir}
    for folder in sorted(directories, key=lambda x: (len(x.split('/')), x)):
        tasks.append({'name': 'Create application directory', 'ansible.builtin.file': {'path': folder, 'state': 'directory', 'owner': name if folder == workdir else 'root', 'group': name, 'mode': '0750'}})
    for index, (_, target, _) in enumerate(checked_files):
        tasks.append({'name': 'Install reviewed supplemental file', 'ansible.builtin.copy': {'src': f'artifacts/support/{index:04d}.bin', 'dest': target, 'owner': 'root', 'group': name, 'mode': '0640'}, 'diff': False, 'notify': 'Restart application'})
    for src, dest, mode in [('artifacts/app.jar', artifact_dest, '0644'), ('service.service', f'/etc/systemd/system/{name}.service', '0644')]:
        tasks.append({'name': f'Install {src}', 'ansible.builtin.copy': {'src': src, 'dest': dest, 'owner': 'root', 'group': 'root', 'mode': mode}, 'notify': 'Restart application'})
    tasks += [
        {'name': 'Install environment', 'ansible.builtin.template': {'src': 'app.env.j2', 'dest': f'/etc/{name}/app.env', 'owner': 'root', 'group': 'root', 'mode': '0600'}, 'no_log': True, 'notify': 'Restart application'},
        {'name': 'Apply configuration changes', 'ansible.builtin.meta': 'flush_handlers'},
        {'name': 'Enable application', 'ansible.builtin.systemd_service': {'name': name, 'enabled': True, 'state': 'started', 'daemon_reload': True}},
    ]
    play = [{'name': f'Install {name}', 'hosts': 'all', 'become': True, 'tasks': tasks,
             'handlers': [{'name': 'Restart application', 'ansible.builtin.systemd_service': {'name': name, 'state': 'restarted', 'daemon_reload': True}}]}]
    dest = Path(destination).resolve()
    if dest.exists():
        raise MigrationError('Output directory already exists; choose a new destination')
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as temp:
        root = Path(temp) / 'bundle'
        (root / 'artifacts').mkdir(parents=True)
        shutil.copyfile(artifact, root / 'artifacts/app.jar')
        for index, (source, _, _) in enumerate(checked_files):
            (root / 'artifacts/support').mkdir(exist_ok=True)
            shutil.copyfile(source, root / f'artifacts/support/{index:04d}.bin')
        (root / 'service.service').write_text(unit)
        (root / 'install.yml').write_text(yaml.safe_dump(play, sort_keys=False))
        (root / 'app.env.j2').write_text('{% for key, value in recompose_environment.items() %}\n{{ key }}={{ value | string | to_json }}\n{% endfor %}\n')
        (root / 'environment.example.yml').write_text(yaml.safe_dump({'recompose_environment': {k: 'REPLACE_ME' for k in p.get('required_environment', [])}}))
        (root / 'manifest.json').write_text(json.dumps({'schema_version': 1, 'service': name, 'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest(), 'files': [{'destination': t, 'sha256': h} for _, t, h in checked_files]}, indent=2))
        (root / 'RUNBOOK.md').write_text('Review generated files and supply environment values securely.\n\nRun: ansible-playbook -i HOST, install.yml -e @environment.yml\n\nVerify: systemctl status '+name+' and application-specific HTTP checks.\nNo automatic data migration, rollback or health guarantee is provided.\n')
        root.rename(dest)
    return {'output': str(dest), 'service': name}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='recompose')
    parser.add_argument('--version', action='version', version='recompose 0.4.0')
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('inspect', 'plan'):
        cmd = sub.add_parser(command)
        if command == 'inspect':
            inputs = cmd.add_mutually_exclusive_group(required=True)
            inputs.add_argument('--compose')
            inputs.add_argument('--image')
            inputs.add_argument('--oci-layout')
            cmd.add_argument('--platform', default='linux/amd64')
        else:
            cmd.add_argument('--compose', required=True)
        cmd.add_argument('--dockerfile')
        cmd.add_argument('--build-target')
        cmd.add_argument('--format', choices=('yaml', 'json'), default='yaml')
        if command == 'plan':
            cmd.add_argument('--service', required=True)
        cmd.add_argument('--output')
    cmd = sub.add_parser('extract')
    cmd.add_argument('--compose')
    cmd.add_argument('--include-file', action='append', default=[])
    inputs = cmd.add_mutually_exclusive_group()
    inputs.add_argument('--image')
    inputs.add_argument('--oci-layout')
    cmd.add_argument('--platform', default='linux/amd64')
    cmd.add_argument('--jar')
    cmd.add_argument('--service', default='app')
    cmd.add_argument('--output', required=True)
    cmd.add_argument('--format', choices=('yaml', 'json'), default='yaml')
    cmd = sub.add_parser('generate')
    cmd.add_argument('--plan', required=True)
    cmd.add_argument('--output', required=True)
    a = parser.parse_args(argv)
    try:
        if a.command == 'extract':
            result = image_operation(a.image, a.oci_layout, a.platform, a.output, a.jar, a.service, a.compose, a.include_file)
        elif a.command == 'inspect' and not a.compose:
            if a.dockerfile or a.build_target:
                raise MigrationError('--dockerfile and --build-target require --compose')
            result = image_operation(a.image, a.oci_layout, a.platform)
        elif a.command == 'generate':
            result = generate(a.plan, a.output)
        else:
            result = inspect(a.compose, a.dockerfile, a.build_target) if a.command == 'inspect' else plan(a.compose, a.service, a.dockerfile, a.build_target)
        rendered = json.dumps(result, indent=2) + '\n' if getattr(a, 'format', 'yaml') == 'json' else yaml.safe_dump(result, sort_keys=False)
        if a.command not in ('generate', 'extract') and a.output:
            with Path(a.output).open('x') as f:
                f.write(rendered)
        else:
            print(rendered, end='')
        return 0
    except (MigrationError, ImageError, OSError, yaml.YAMLError, zipfile.BadZipFile, tarfile.TarError, EOFError, urllib.error.URLError) as exc:
        # Parser exceptions can contain source lines with secrets.
        message = str(exc) if isinstance(exc, (MigrationError, ImageError)) else type(exc).__name__
        print(f'recompose: {message}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
