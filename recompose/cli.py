"""Conservative, offline Java-to-VM migration scaffold."""
import argparse
import hashlib
import json
import re
import shlex
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import yaml


class MigrationError(ValueError):
    pass


def read_yaml(path):
    value = yaml.safe_load(Path(path).read_text())
    if not isinstance(value, dict):
        raise MigrationError('Expected a YAML mapping')
    return value


def packages(path):
    """Candidates only: never infer runtime necessity from installation alone."""
    if not path:
        return []
    lines = Path(path).read_text().replace('\\\n', ' ').splitlines()
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


def inspect(compose, dockerfile=None):
    data = read_yaml(compose)
    services = data.get('services')
    if not isinstance(services, dict) or not services:
        raise MigrationError('Compose must contain services')
    output = []
    for name, spec in services.items():
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
            'limitations': ['Static analysis only; no image inspection or extraction.',
                             'Compose interpolation, includes and overrides are not resolved.',
                             'Base-image packages and runtime necessity are not inferred.']}


def plan(compose, service, dockerfile=None):
    report = inspect(compose, dockerfile)
    selected = next((s for s in report['services'] if s['name'] == service), None)
    if selected is None:
        raise MigrationError('Unknown service')
    return {'schema_version': 1, 'service': service, 'target': 'ubuntu-24.04',
            'reviewed': False, 'artifact': None, 'java_version': 21,
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
    args += ['-jar', f'/opt/{name}/app.jar']
    args += [unit_arg(v) for v in p.get('app_args', [])]
    unit = f'''[Unit]
Description=Recompose Java service {name}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={name}
Group={name}
WorkingDirectory=/var/lib/{name}
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
        {'name': 'Create service account', 'ansible.builtin.user': {'name': name, 'system': True, 'create_home': False, 'shell': '/usr/sbin/nologin'}},
    ]
    for folder, owner in [(f'/opt/{name}', 'root'), (f'/etc/{name}', 'root'), (f'/var/lib/{name}', name)]:
        tasks.append({'name': f'Create {folder}', 'ansible.builtin.file': {'path': folder, 'state': 'directory', 'owner': owner, 'group': name, 'mode': '0750'}})
    for src, dest, mode in [('artifacts/app.jar', f'/opt/{name}/app.jar', '0644'), ('service.service', f'/etc/systemd/system/{name}.service', '0644')]:
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
        (root / 'service.service').write_text(unit)
        (root / 'install.yml').write_text(yaml.safe_dump(play, sort_keys=False))
        (root / 'app.env.j2').write_text('{% for key, value in recompose_environment.items() %}\n{{ key }}={{ value | string | to_json }}\n{% endfor %}\n')
        (root / 'environment.example.yml').write_text(yaml.safe_dump({'recompose_environment': {k: 'REPLACE_ME' for k in p.get('required_environment', [])}}))
        (root / 'manifest.json').write_text(json.dumps({'schema_version': 1, 'service': name, 'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest()}, indent=2))
        (root / 'RUNBOOK.md').write_text('Review generated files and supply environment values securely.\n\nRun: ansible-playbook -i HOST, install.yml -e @environment.yml\n\nVerify: systemctl status '+name+' and application-specific HTTP checks.\nNo automatic data migration, rollback or health guarantee is provided.\n')
        root.rename(dest)
    return {'output': str(dest), 'service': name}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='recompose')
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('inspect', 'plan'):
        cmd = sub.add_parser(command)
        cmd.add_argument('--compose', required=True)
        cmd.add_argument('--dockerfile')
        if command == 'plan':
            cmd.add_argument('--service', required=True)
        cmd.add_argument('--output')
    cmd = sub.add_parser('generate')
    cmd.add_argument('--plan', required=True)
    cmd.add_argument('--output', required=True)
    a = parser.parse_args(argv)
    try:
        if a.command == 'generate':
            result = generate(a.plan, a.output)
        else:
            result = inspect(a.compose, a.dockerfile) if a.command == 'inspect' else plan(a.compose, a.service, a.dockerfile)
        rendered = yaml.safe_dump(result, sort_keys=False)
        if a.command != 'generate' and a.output:
            with Path(a.output).open('x') as f:
                f.write(rendered)
        else:
            print(rendered, end='')
        return 0
    except (MigrationError, OSError, yaml.YAMLError, zipfile.BadZipFile) as exc:
        # Parser exceptions can contain source lines with secrets.
        message = str(exc) if isinstance(exc, MigrationError) else type(exc).__name__
        print(f'recompose: {message}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
