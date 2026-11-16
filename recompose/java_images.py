"""Offline, evidence-based Java base-image review (no registry or EOL lookup)."""
import re
from pathlib import Path

POLICY_DATE = '2026-11-16'
OPENJDK_NOTICE = 'https://hub.docker.com/_/openjdk'
FROM_DOCS = 'https://docs.docker.com/reference/dockerfile/#from'
KNOWN = {'openjdk', 'eclipse-temurin', 'amazoncorretto', 'ibm-semeru-runtimes', 'sapmachine'}


def image_review(reference):
    result = {'distribution': None, 'java_major_hint': None, 'tag': None,
              'digest_pinned': False, 'replacement': 'unknown', 'findings': []}
    def finding(code, message, action, source=FROM_DOCS):
        result['findings'].append({'code': code, 'message': message, 'action': action,
                                   'source': source, 'reviewed_on': POLICY_DATE})
    if '$' in reference or not re.fullmatch(r'[a-zA-Z0-9._/:+-]+(?:@sha256:[0-9a-f]{64})?', reference):
        finding('JAVA_IMAGE_UNRESOLVED', 'Image reference is unresolved or unsupported.',
                'Supply a concrete Dockerfile FROM reference; ARG evaluation is not performed.')
        return result
    base, _, digest = reference.partition('@')
    result['digest_pinned'] = bool(digest)
    parts = base.split('/')
    if len(parts) == 1:
        repo_tag = parts[0]
    elif len(parts) == 2 and parts[0] == 'library':
        repo_tag = parts[1]
    elif parts[0] in ('docker.io', 'index.docker.io') and (len(parts) == 2 or (len(parts) == 3 and parts[1] == 'library')):
        repo_tag = parts[-1]
    else:
        repo_tag = ''  # Never treat a private lookalike as an official image.
    repo, sep, tag = repo_tag.partition(':')
    result['tag'] = tag if sep else None
    if repo in KNOWN:
        result['distribution'] = repo
        match = re.match(r'^(?:jdk-|jre-)?(\d+)(?:[u._-]|$)', tag)
        if match:
            result['java_major_hint'] = int(match[1])
    if repo == 'openjdk':
        result['replacement'] = 'recommended'
        finding('JAVA_OPENJDK_IMAGE_DEPRECATED', 'The Docker Official Image named openjdk is deprecated.',
                'For continued container use, review a maintained OpenJDK distribution at the same Java major first. '
                'For VM migration, choose a supported VM runtime separately; rebuilding the source image is not inherently required.', OPENJDK_NOTICE)
    elif repo in KNOWN:
        result['replacement'] = 'review-required'
        finding('JAVA_VENDOR_SUPPORT_UNVERIFIED', 'Recognized image distribution; lifecycle and patch support are not checked.',
                'Verify vendor support, image digest and target OS availability; no upgrade is implied.')
    else:
        finding('JAVA_IMAGE_UNKNOWN', 'Java distribution cannot be inferred from this reference.',
                'Inspect image runtime metadata or select the VM Java version explicitly.')
    if re.search(r'(^|[-_.])ea($|[-_.0-9])', tag):
        finding('JAVA_EARLY_ACCESS', 'Tag indicates an early-access build.',
                'Select and test an appropriate stable runtime before production deployment.', OPENJDK_NOTICE)
    if 'alpine' in tag:
        finding('JAVA_LIBC_REVIEW', 'Tag suggests an Alpine-based source image.',
                'Check native libraries, JNI, fonts and libc compatibility on the Ubuntu target.')
    if not digest:
        finding('IMAGE_DIGEST_UNPINNED', 'Source image is not pinned by digest.',
                'Record the actual image digest before extracting artifacts or comparing results.')
    if result['java_major_hint'] is None:
        finding('JAVA_VERSION_UNKNOWN', 'No reliable Java-major hint is present in the tag.',
                'Set java_version explicitly after checking the actual runtime and application requirements.')
    return result


def review_dockerfile(path, target=None):
    stages = []
    aliases = {}
    if path:
        physical = Path(path).read_text().splitlines()
        # Refuse unsupported syntax rather than mistaking heredoc content for FROM.
        if any(re.match(r'\s*#\s*escape\s*=', line, re.I) for line in physical) or any('<<' in line and not line.lstrip().startswith('#') for line in physical):
            raise ValueError('Dockerfile escape directives and heredocs are not supported for base-image review')
        buffer = ''
        start = 1
        for number, line in enumerate(physical, 1):
            if not buffer:
                start = number
            if line.lstrip().startswith('#'):
                continue
            buffer += line.rstrip().removesuffix('\\') + (' ' if line.rstrip().endswith('\\') else '')
            if line.rstrip().endswith('\\'):
                continue
            instruction, buffer = buffer.strip(), ''
            if not re.match(r'^FROM(?:\s|$)', instruction, re.I):
                continue
            match = re.fullmatch(r'FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+([a-zA-Z0-9_-]+))?', instruction, re.I)
            if not match:
                raise ValueError('Unsupported FROM instruction')
            ref, alias = match.groups()
            parent = aliases.get(ref.lower())
            origin = stages[parent]['base_reference'] if parent is not None else ref
            stage = {'index': len(stages), 'name': alias, 'base_reference': origin,
                     'inherits_stage': parent, 'evidence': f'{path}:{start}', **image_review(origin)}
            stages.append(stage)
            if alias:
                if alias.lower() in aliases:
                    raise ValueError('Duplicate Dockerfile stage name')
                aliases[alias.lower()] = stage['index']
        if buffer:
            raise ValueError('Unterminated Dockerfile continuation')
    selected = len(stages) - 1 if stages else None
    if target:
        selected = aliases.get(target.lower())
        if selected is None:
            raise ValueError('Requested build target was not found')
    runtime = stages[selected] if selected is not None else None
    # Do not expose unresolved ARG references or malformed image strings.
    for stage in stages:
        stage.pop('base_reference')
    return {'policy_reviewed_on': POLICY_DATE, 'stages': stages, 'selected_stage': selected,
            'java_major_hint': runtime['java_major_hint'] if runtime else None,
            'confidence': 'tag-hint-only' if runtime and runtime['java_major_hint'] else 'unknown',
            'limitations': ['No image pull, registry lookup, vulnerability scan or live support-lifecycle check.',
                            'FROM tags are hints; later Java installation, COPY and runtime overrides are not evaluated.',
                            'ARG substitutions are not resolved. Unselected stages remain separate from runtime selection.']}
