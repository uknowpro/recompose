import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import yaml
from recompose.cli import MigrationError, generate, inspect, main, packages, plan, unit_arg


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.compose = self.root / 'compose.yml'
        self.compose.write_text('services:\n  demo:\n    image: demo\n    environment:\n      PASSWORD: secret-value\n')
        self.jar = self.root / 'app.jar'
        with zipfile.ZipFile(self.jar, 'w') as jar:
            jar.writestr('META-INF/MANIFEST.MF', 'Main-Class: example.Main\n')
        self.p = plan(self.compose, 'demo')
        self.p.update(reviewed=True, artifact='app.jar', java_version=21)
        self.path = self.root / 'plan.yml'

    def generate(self):
        self.path.write_text(yaml.safe_dump(self.p))
        return generate(self.path, self.root / 'bundle')

    def test_inspect_redacts_values(self):
        report = inspect(self.compose)
        self.assertNotIn('secret-value', json.dumps(report))
        self.assertEqual(report['services'][0]['environment_keys'], ['PASSWORD'])

    def test_review_required(self):
        self.p['reviewed'] = False
        with self.assertRaises(MigrationError):
            self.generate()

    def test_bundle(self):
        self.generate()
        root = self.root / 'bundle'
        self.assertEqual((root / 'artifacts/app.jar').read_bytes(), self.jar.read_bytes())
        self.assertIn('User=demo', (root / 'service.service').read_text())
        plays = yaml.safe_load((root / 'install.yml').read_text())
        self.assertTrue(plays[0]['become'])
        self.assertNotIn('secret-value', (root / 'environment.example.yml').read_text())
        with self.assertRaises(MigrationError):
            generate(self.path, root)

    def test_unknown_java_blocks_generation(self):
        self.p['java_version'] = None
        with self.assertRaises(MigrationError):
            self.generate()

    def test_unsupported_java_blocks_generation(self):
        self.p['java_version'] = 8
        with self.assertRaises(MigrationError):
            self.generate()

    def test_unsafe_service(self):
        self.p['service'] = '../escape'
        with self.assertRaises(MigrationError):
            self.generate()

    def test_invalid_package(self):
        self.p['os_packages'] = ['foo\nbar']
        with self.assertRaises(MigrationError):
            self.generate()

    def test_missing_manifest(self):
        with zipfile.ZipFile(self.jar, 'w') as jar:
            jar.writestr('example.txt', 'not runnable')
        with self.assertRaises(MigrationError):
            self.generate()

    def test_unit_escaping(self):
        self.assertEqual(unit_arg('a% $b'), '"a%% $$b"')
        with self.assertRaises(MigrationError):
            unit_arg('a\nb')

    def test_package_stages(self):
        dockerfile = self.root / 'Dockerfile'
        dockerfile.write_text('FROM build AS builder\nRUN apt-get install -y gcc\nFROM runtime\nRUN apk add --no-cache fontconfig\n')
        candidates = packages(dockerfile)
        self.assertEqual([p['name'] for p in candidates], ['gcc', 'fontconfig'])
        self.assertTrue(all(p['status'] == 'review-required' for p in candidates))
        self.assertNotEqual(candidates[0]['stage'], candidates[1]['stage'])

    def test_unknown_service(self):
        with self.assertRaises(MigrationError):
            plan(self.compose, 'missing')

    def test_cli_plan(self):
        out = self.root / 'output.yml'
        self.assertEqual(main(['plan', '--compose', str(self.compose), '--service', 'demo', '--output', str(out)]), 0)
        self.assertFalse(yaml.safe_load(out.read_text())['reviewed'])
