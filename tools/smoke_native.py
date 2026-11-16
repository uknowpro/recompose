"""Exercise a frozen CLI with no external tools available on PATH."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / 'tests'))
from test_images import ImageTests, jar_bytes


def smoke(binary):
    binary = Path(binary).resolve()
    fixture = ImageTests()
    fixture.setUp()
    env = dict(os.environ)
    env['PATH'] = ''
    env.pop('PYTHONHOME', None)
    env.pop('PYTHONPATH', None)
    def run(*args):
        result = subprocess.run([str(binary), *map(str, args)], env=env, capture_output=True,
                                text=True, encoding='utf-8', timeout=120)
        if result.returncode:
            raise RuntimeError(result.stderr)
        return result.stdout
    try:
        fixture.fixture(layers=[[('app/app.jar', jar_bytes()), ('app/config/application.yml', b'server.port: 8081')]])
        print(run('--version').strip())
        report = json.loads(run('inspect', '--oci-layout', fixture.layout, '--format', 'json'))
        assert report['runtime']['java_major_hint'] == 21
        # Exercise spaces and non-ASCII host paths, independent of container POSIX paths.
        destination = fixture.root / 'extracted app 한글'
        compose = fixture.root / 'compose.yml'
        compose.write_text('services:\n  app:\n    entrypoint: [java, -Xmx256m, -jar, app.jar, --spring.config.location=file:config/application.yml]\n', encoding='utf-8')
        run('extract', '--oci-layout', fixture.layout, '--compose', compose, '--output', destination)
        assert (destination / 'app.jar').read_bytes() == fixture.jar
        plan_path = destination / 'migration-plan.yaml'
        p = yaml.safe_load(plan_path.read_text(encoding='utf-8'))
        p['reviewed'] = True
        assert len(p['files']) == 1
        p['files'][0]['reviewed'] = True
        plan_path.write_text(yaml.safe_dump(p), encoding='utf-8')
        deployment = fixture.root / 'deployment'
        run('generate', '--plan', plan_path, '--output', deployment)
        assert (deployment / 'artifacts/app.jar').read_bytes() == fixture.jar
        assert (deployment / 'artifacts/support/0000.bin').read_bytes() == b'server.port: 8081'
        assert '-Xmx256m' in (deployment / 'service.service').read_text()
        print('Native inspect -> extract -> generate passed with PATH empty.')
        print('Artifact SHA-256:', hashlib.sha256(fixture.jar).hexdigest())
    finally:
        fixture.doCleanups()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--binary', required=True)
    smoke(p.parse_args().binary)
