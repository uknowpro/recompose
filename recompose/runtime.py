"""Conservative Compose/image execution reconciliation; never evaluate shell code."""
import posixpath
import re
import shlex
from pathlib import Path

import yaml

PATH_PATTERN = re.compile(r'^/[A-Za-z0-9_./+ -]*$')
SYSTEM_ENV = {'PATH', 'HOME', 'LANG', 'LANGUAGE', 'LC_ALL', 'JAVA_HOME', 'JAVA_VERSION'}
OPTION_ENV = {'JAVA_TOOL_OPTIONS', 'JDK_JAVA_OPTIONS', '_JAVA_OPTIONS'}
CONFIG_KEYS = {'spring.config.location', 'spring.config.additional-location', 'logging.config'}
SAFE_PROPERTIES = {'file.encoding', 'user.timezone', 'spring.profiles.active', 'java.awt.headless'}
SAFE_APP_KEYS = {'server.port', 'spring.profiles.active'}


def safe_path(path, workdir='/'):
    if not isinstance(path, str) or '..' in path.split('/') or not PATH_PATTERN.fullmatch(posixpath.join(workdir, path)):
        raise ValueError('Unsupported container path; use a literal POSIX path without traversal or expressions')
    return posixpath.normpath(posixpath.join(workdir, path))


def vm_path(service, source):
    return f'/opt/{service}/rootfs' + safe_path(source)


def compose_service(path, service):
    if not path:
        return {}
    data = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    services = data.get('services') if isinstance(data, dict) else None
    if not isinstance(services, dict) or service not in services or not isinstance(services[service], dict):
        raise ValueError('Select an existing Compose service with --service')
    selected = dict(services[service])
    if data.get('include'):
        selected['include'] = True
    return selected


def argv(value):
    if value is None:
        return []
    if isinstance(value, str):
        try:
            return shlex.split(value, posix=True)
        except ValueError:
            raise ValueError('Invalid command quoting') from None
    if isinstance(value, list) and all(isinstance(x, str) for x in value):
        return value[:]
    raise ValueError('Commands must be strings or string lists')


def reconcile(config, spec):
    settings = config.get('config') or {}
    if not isinstance(settings, dict):
        raise ValueError('Invalid image execution config')
    entrypoint = argv(settings.get('Entrypoint'))
    cmd = argv(settings.get('Cmd'))
    sources = {'entrypoint': 'image', 'command': 'image', 'working_dir': 'image'}
    if spec.get('entrypoint') is not None:
        entrypoint, cmd = argv(spec['entrypoint']), []
        sources.update(entrypoint='compose', command='cleared-by-entrypoint')
    if spec.get('command') is not None:
        cmd = argv(spec['command'])
        sources['command'] = 'compose'
    workdir = settings.get('WorkingDir') or '/'
    if spec.get('working_dir') is not None:
        workdir = spec['working_dir']
        sources['working_dir'] = 'compose'
    workdir = safe_path(workdir)
    environment = {}
    for item in settings.get('Env') or []:
        if not isinstance(item, str) or '=' not in item:
            raise ValueError('Invalid image environment')
        key, value = item.split('=', 1)
        environment[key] = value
    overrides = spec.get('environment') or {}
    if isinstance(overrides, list):
        if not all(isinstance(item, str) for item in overrides):
            raise ValueError('Invalid Compose environment')
        overrides = {item.split('=', 1)[0]: item.partition('=')[2] if '=' in item else None for item in overrides if isinstance(item, str)}
    if not isinstance(overrides, dict):
        raise ValueError('Invalid Compose environment')
    environment.update(overrides)
    required = sorted((set(environment) - SYSTEM_ENV) | set(overrides))
    if not all(isinstance(k, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', k) for k in required):
        raise ValueError('Invalid environment variable name')
    masked = []
    volumes = spec.get('volumes') or []
    if not isinstance(volumes, list):
        raise ValueError('Compose volumes must be a list')
    for volume in volumes:
        target = volume.get('target') if isinstance(volume, dict) else None
        if isinstance(volume, str):
            parts = volume.split(':')
            target = next((p for p in reversed(parts) if p.startswith('/')), None)
        if target:
            masked.append(safe_path(target))
    return entrypoint + cmd, workdir, required, environment, sources, masked


def analyze_execution(config, spec=None, service='app', include_files=None):
    spec = spec or {}
    command, workdir, required, environment, sources, masked = reconcile(config, spec)
    result = {'mode': 'review-required', 'command_jar': None, 'working_directory': workdir,
              'target_working_directory': vm_path(service, workdir), 'sources': sources,
              'required_environment': required, 'jvm_options': [], 'app_args': [], 'references': [],
              'review_items': [], 'masked_paths': masked}
    def issue(code, detail):
        if not any(x['code'] == code and x['detail'] == detail for x in result['review_items']):
            result['review_items'].append({'code': code, 'detail': detail, 'resolved': False})
    def reference(path, role, directory=False):
        path = safe_path(path, workdir)
        if directory and path == '/':
            raise ValueError('Root-directory dependency collection is not supported')
        item = {'path': path, 'role': role, 'directory': directory}
        if item not in result['references']:
            result['references'].append(item)
        return vm_path(service, path)
    def config_value(value):
        mapped = []
        for part in value.split(','):
            prefix = ''
            if part.startswith('optional:'):
                prefix, part = 'optional:', part[9:]
            if part.startswith('classpath:'):
                mapped.append(prefix + part)
                continue
            if part.startswith('file:'):
                part = part[5:]
            if ':' in part or not part:
                raise ValueError('Only local configuration file locations are supported')
            directory = part.endswith('/')
            mapped.append(prefix + 'file:' + reference(part, 'config', directory) + ('/' if directory else ''))
        return ','.join(mapped)
    for field in ('env_file', 'secrets', 'configs', 'volumes', 'ports', 'user', 'depends_on', 'network_mode', 'platform', 'extends', 'include', 'healthcheck', 'ulimits', 'cap_add', 'devices', 'privileged', 'read_only', 'tmpfs', 'deploy'):
        if spec.get(field):
            issue('COMPOSE_' + field.upper(), f'Review Compose {field}; external values/resources are not imported automatically.')
    for key in OPTION_ENV:
        if environment.get(key):
            issue('ENV_JVM_OPTIONS', f'Review and supply {key} separately; its value is not copied or expanded.')
    for name in include_files or []:
        reference(name, 'explicit', name.endswith('/'))
    if not command or posixpath.basename(command[0]) != 'java':
        issue('STARTUP_WRAPPER', 'Startup is not a direct java command; review its behavior and reconstruct arguments before deployment.')
        return result
    if any('$' in token or '`' in token or any(ord(c) < 32 for c in token) for token in command):
        issue('COMMAND_EXPRESSION', 'Command contains expressions or control characters; values and shell expressions are not evaluated.')
        return result
    if '-jar' not in command:
        issue('JAVA_LAUNCH_MODE', 'Only direct java -jar launch is currently mapped; classpath/module/source launch requires manual planning.')
        return result
    index = command.index('-jar')
    if index + 1 >= len(command):
        issue('JAVA_JAR_MISSING', 'The java -jar argument is missing.')
        return result
    result['command_jar'] = safe_path(command[index + 1], workdir)
    result['mode'] = 'java-jar'
    jvm = command[1:index]
    for position, token in enumerate(jvm):
        mapped = None
        try:
            if re.fullmatch(r'-Xm[sx][0-9]+[kKmMgG]?|-Xss[0-9]+[kKmMgG]?|-XX:[+-][A-Za-z0-9]+|-XX:[A-Za-z0-9]+=[0-9.]+', token):
                mapped = token
            elif token in ('-ea', '-da', '-server', '-client'):
                mapped = token
            elif token.startswith('-javaagent:') or token.startswith('-agentpath:'):
                prefix, value = token.split(':', 1)
                path, equals, _ = value.partition('=')
                mapped = prefix + ':' + reference(path, 'agent' if prefix == '-javaagent' else 'native')
                if equals:
                    issue('AGENT_OPTIONS', 'Agent options were omitted; review them and inject sensitive values separately.')
            elif token.startswith('-D') and '=' in token:
                key, value = token[2:].split('=', 1)
                if key in SAFE_PROPERTIES and re.fullmatch(r'[A-Za-z0-9_.,/+:-]+', value):
                    mapped = token
                elif key in CONFIG_KEYS:
                    mapped = '-D' + key + '=' + config_value(value)
                elif key in ('java.library.path', 'loader.path'):
                    separator = ':' if key == 'java.library.path' else ','
                    role = 'native' if key == 'java.library.path' else 'library'
                    paths = [reference(v.removeprefix('file:'), role, not v.endswith(('.jar', '.so'))) for v in value.split(separator)]
                    mapped = '-D' + key + '=' + separator.join(paths)
        except ValueError:
            mapped = None
        if mapped is None:
            issue('JVM_ARGUMENT_REVIEW', f'JVM argument {position} was omitted; review its value and paths in the original configuration.')
        else:
            result['jvm_options'].append(mapped)
    for position, token in enumerate(command[index + 2:]):
        mapped = None
        try:
            if token.startswith('--') and '=' in token:
                key, value = token[2:].split('=', 1)
                if key in SAFE_APP_KEYS and re.fullmatch(r'[A-Za-z0-9_.,-]+', value):
                    mapped = token
                elif key in CONFIG_KEYS:
                    mapped = '--' + key + '=' + config_value(value)
        except ValueError:
            mapped = None
        if mapped is None:
            issue('APP_ARGUMENT_REVIEW', f'Application argument {position} was omitted; review it without placing secrets in reports.')
        else:
            result['app_args'].append(mapped)
    return result


def requested_file(path, references):
    for item in references:
        if path == item['path'].lstrip('/'):
            return True
        if item['directory'] and path.startswith(item['path'].strip('/') + '/'):
            if item['role'] == 'native':
                return '.so' in posixpath.basename(path)
            if item['role'] == 'library':
                return path.endswith('.jar')
            return True
    return False


def masked_file(path, execution):
    path = '/' + path.lstrip('/')
    return any(path == p or path.startswith(p.rstrip('/') + '/') for p in execution['masked_paths'])


def sensitive_file(path, payload):
    name = posixpath.basename(path).lower()
    if any(x in name for x in ('secret', 'credential', '.env')) or name.endswith(('.pem', '.key', '.p12', '.pfx')):
        return True
    if name.endswith(('.yaml', '.yml', '.properties', '.conf', '.json', '.xml')) and payload.stat().st_size <= 2 * 1024 * 1024:
        text = payload.read_text(encoding='utf-8', errors='replace')
        # Conservative literal-secret screening. This is not a general secret scanner.
        for match in re.finditer(r'(?im)[\w.\-]*(?:password|passwd|secret|token|credential)[\w.\-]*["\']?\s*[:=]\s*([^\r\n]+)', text):
            value = match[1].strip().strip('"\'')
            if value and not value.startswith(('${', '{{')):
                return True
    return False
