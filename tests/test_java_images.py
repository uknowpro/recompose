import json
import tempfile
import unittest
from pathlib import Path

from recompose.cli import MigrationError, main, plan
from recompose.java_images import image_review, review_dockerfile


class ImageReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dockerfile = self.root / 'Dockerfile'
        self.compose = self.root / 'compose.yml'
        self.compose.write_text('services:\n  app:\n    image: example/app\n')

    def review(self, text, target=None):
        self.dockerfile.write_text(text)
        return review_dockerfile(self.dockerfile, target)

    def test_official_openjdk_aliases(self):
        for ref in ['openjdk:17', 'library/openjdk:17', 'docker.io/openjdk:17', 'docker.io/library/openjdk:17']:
            r = image_review(ref)
            self.assertEqual(r['replacement'], 'recommended')
            self.assertEqual(r['java_major_hint'], 17)
            self.assertTrue(r['findings'][0]['source'])

    def test_private_lookalike_unknown(self):
        for ref in ['corp/openjdk:17', 'registry.test/openjdk:17', 'evil/docker.io/openjdk:17']:
            self.assertEqual(image_review(ref)['replacement'], 'unknown')

    def test_final_stage_not_builder(self):
        r = self.review('FROM openjdk:8 AS builder\nFROM eclipse-temurin:21-jre AS runtime\n')
        self.assertEqual(r['java_major_hint'], 21)
        self.assertEqual(r['stages'][0]['replacement'], 'recommended')
        self.assertNotEqual(r['stages'][1]['replacement'], 'recommended')

    def test_alias_inherits_hint(self):
        r = self.review('FROM eclipse-temurin:17-jre AS base\nFROM base AS app\n')
        self.assertEqual(r['java_major_hint'], 17)
        self.assertEqual(r['stages'][1]['inherits_stage'], 0)

    def test_target_selection(self):
        r = self.review('FROM eclipse-temurin:17 AS app\nFROM eclipse-temurin:21 AS test\n', 'app')
        self.assertEqual(r['java_major_hint'], 17)
        with self.assertRaises(ValueError):
            review_dockerfile(self.dockerfile, 'missing')

    def test_compose_target(self):
        self.compose.write_text('services:\n  app:\n    build:\n      target: app\n')
        self.dockerfile.write_text('FROM eclipse-temurin:17 AS app\nFROM eclipse-temurin:21 AS test\n')
        self.assertEqual(plan(self.compose, 'app', self.dockerfile)['java_version'], 17)

    def test_unknown_does_not_default_to_21(self):
        self.assertIsNone(plan(self.compose, 'app')['java_version'])
        r = self.review('ARG BASE=openjdk:17\nFROM ${BASE}\n')
        self.assertIsNone(r['java_major_hint'])

    def test_unsupported_major_preserved(self):
        self.dockerfile.write_text('FROM openjdk:8-jre\n')
        self.assertEqual(plan(self.compose, 'app', self.dockerfile)['java_version'], 8)

    def test_digest_only_unknown_version(self):
        r = image_review('eclipse-temurin@sha256:' + 'a' * 64)
        self.assertTrue(r['digest_pinned'])
        self.assertIsNone(r['java_major_hint'])

    def test_ea_and_alpine(self):
        r = image_review('openjdk:28-ea-alpine')
        codes = {f['code'] for f in r['findings']}
        self.assertIn('JAVA_EARLY_ACCESS', codes)
        self.assertIn('JAVA_LIBC_REVIEW', codes)

    def test_physical_line_evidence(self):
        r = self.review('# comment\nFROM --platform=linux/amd64 \\\n eclipse-temurin:21 AS app\n')
        self.assertTrue(r['stages'][0]['evidence'].endswith(':2'))

    def test_heredoc_rejected(self):
        with self.assertRaises(ValueError):
            self.review('FROM alpine\nRUN <<EOF\nFROM openjdk:17\nEOF\n')

    def test_json_cli(self):
        output = self.root / 'report.json'
        self.assertEqual(main(['inspect', '--compose', str(self.compose), '--format', 'json', '--output', str(output)]), 0)
        self.assertIn('java_image_review', json.loads(output.read_text()))

    def test_invalid_compose(self):
        self.compose.write_text('services: []\n')
        with self.assertRaises(MigrationError):
            plan(self.compose, 'app')
