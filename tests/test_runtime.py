import json
import unittest
import yaml
import test_images
from test_images import jar_bytes
from recompose.runtime import analyze_execution, reconcile
from recompose.cli import generate, MigrationError


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.config = {'config': {'Entrypoint': ['java'], 'Cmd': ['-jar', 'app.jar'], 'WorkingDir': '/app'}}

    def test_compose_precedence(self):
        for overrides, expected in [({}, ['java', '-jar', 'app.jar']),
                ({'entrypoint': None, 'command': None}, ['java', '-jar', 'app.jar']),
                ({'entrypoint': ['other']}, ['other']),
                ({'entrypoint': [], 'command': 'java -jar "another app.jar"'}, ['java', '-jar', 'another app.jar']),
                ({'command': []}, ['java']), ({'command': ''}, ['java'])]:
            with self.subTest(overrides=overrides):
                self.assertEqual(reconcile(self.config, overrides)[0], expected)

    def test_arguments_and_secret_redaction(self):
        result = analyze_execution(self.config, {'entrypoint': ['java', '-Xmx512m', '-Dpassword=do-not-report', '-jar', 'app.jar', '--server.port=8081', '--token=do-not-report']})
        self.assertEqual(result['jvm_options'], ['-Xmx512m'])
        self.assertEqual(result['app_args'], ['--server.port=8081'])
        self.assertNotIn('do-not-report', json.dumps(result))
        self.assertEqual(len(result['review_items']), 2)

    def test_wrapper_and_expression(self):
        for command in [['sh', '-c', 'java -jar app.jar'], ['java', '-jar', '${JAR}']]:
            result = analyze_execution(self.config, {'entrypoint': command})
            self.assertEqual(result['mode'], 'review-required')
            self.assertTrue(result['review_items'])

    def test_workdir_and_required_env(self):
        result = analyze_execution(self.config, {'working_dir': '/srv', 'environment': {'TOKEN': 'hidden'}})
        self.assertEqual(result['command_jar'], '/srv/app.jar')
        self.assertEqual(result['required_environment'], ['TOKEN'])
        self.assertNotIn('hidden', json.dumps(result))


class SupplementalTests(unittest.TestCase):
    setUp = test_images.ImageTests.setUp
    blob = test_images.ImageTests.blob
    fixture = test_images.ImageTests.fixture
    extract = test_images.ImageTests.extract

    def prepare(self):
        self.fixture(layers=[[('app/app.jar', jar_bytes()), ('app/config/application.yml', b'server:\n  port: 8081\n'),
                              ('app/agent.jar', jar_bytes()), ('app/lib/extra.jar', jar_bytes()), ('app/native/libdemo.so', b'native')]],
                     command=['java', '-Xmx512m', '-javaagent:agent.jar', '-Dloader.path=lib/', '-Djava.library.path=native/',
                              '-jar', 'app.jar', '--spring.config.location=file:config/application.yml'])
        self.extract(service='demo')
        self.planpath = self.root / 'out/migration-plan.yaml'
        self.plan = yaml.safe_load(self.planpath.read_text())
        self.plan['reviewed'] = True

    def writeplan(self):
        self.planpath.write_text(yaml.safe_dump(self.plan))

    def test_full_bundle_and_review_gate(self):
        self.prepare()
        self.assertEqual(len(self.plan['files']), 4)
        self.writeplan()
        with self.assertRaises(MigrationError):
            generate(self.planpath, self.root / 'deployment')
        for item in self.plan['files']:
            item['reviewed'] = True
        self.writeplan()
        generate(self.planpath, self.root / 'deployment')
        unit = (self.root / 'deployment/service.service').read_text()
        self.assertIn('-javaagent:/opt/demo/rootfs/app/agent.jar', unit)
        self.assertIn('file:/opt/demo/rootfs/app/config/application.yml', unit)
        self.assertIn('WorkingDirectory=/opt/demo/rootfs/app', unit)
        self.assertEqual(len(list((self.root / 'deployment/artifacts/support').iterdir())), 4)

    def test_changed_file_digest_rejected(self):
        self.prepare()
        for item in self.plan['files']:
            item['reviewed'] = True
        (self.planpath.parent / self.plan['files'][0]['source']).write_bytes(b'changed')
        self.writeplan()
        with self.assertRaisesRegex(MigrationError, 'digest'):
            generate(self.planpath, self.root / 'deployment')

    def test_unsafe_destination_rejected(self):
        self.prepare()
        for item in self.plan['files']:
            item['reviewed'] = True
        self.plan['files'][0]['destination'] = '/etc/cron.d/evil'
        self.writeplan()
        with self.assertRaises(MigrationError):
            generate(self.planpath, self.root / 'deployment')

    def test_whiteout_and_symlink_dependency_not_copied(self):
        self.fixture(layers=[[('app/app.jar', jar_bytes()), ('app/settings.yml', b'port: 80')],
                             [('app/.wh.settings.yml', b''), ('app/linked.yml', ('settings.yml',))]])
        self.extract(include_files=['/app/settings.yml', '/app/linked.yml'])
        plan = yaml.safe_load((self.root / 'out/migration-plan.yaml').read_text())
        self.assertEqual(plan['files'], [])
        self.assertEqual([i['code'] for i in plan['review_items']], ['MISSING_FILE', 'MISSING_FILE'])

    def test_secrets_not_exported(self):
        self.fixture(layers=[[('app/app.jar', jar_bytes()), ('app/settings.yml', b'password: VERYSECRET')]])
        result = self.extract(include_files=['/app/settings.yml'])
        self.assertNotIn('VERYSECRET', json.dumps(result))
        self.assertFalse((self.root / 'out/files').exists())
        self.assertEqual(result['runtime']['execution']['review_items'][0]['code'], 'SENSITIVE_FILE')

    def test_compose_mount_masks_file(self):
        self.fixture(layers=[[('app/app.jar', jar_bytes()), ('app/config/a.yml', b'port: 80')]])
        compose = self.root / 'compose.yml'
        compose.write_text('services:\n  app:\n    volumes: ["./config:/app/config:ro"]\n')
        self.extract(compose=compose, include_files=['/app/config/'])
        plan = yaml.safe_load((self.root / 'out/migration-plan.yaml').read_text())
        self.assertEqual(plan['files'], [])
        plan['reviewed'] = True
        path = self.root / 'out/migration-plan.yaml'
        path.write_text(yaml.safe_dump(plan))
        with self.assertRaisesRegex(MigrationError, 'review_items'):
            generate(path, self.root / 'deployment')
