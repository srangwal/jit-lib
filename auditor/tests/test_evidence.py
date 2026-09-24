import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from auditor.evidence import EvidenceError, prepare_evidence


def digest(data):
    return hashlib.sha256(data).hexdigest()


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.evaluation = self.root / 'run'
        self.destination = self.root / 'evidence'
        self.repo = self.root / 'repo'
        self.write(self.repo / 'evaluator/run.py', b'# current evaluator\n')
        for name in ('GOAL.md', 'EVALUATOR.md', 'AUDITOR.md'):
            self.write(self.repo / 'documentation' / name, b'# Current documentation\n')
        self.patcher = patch('auditor.evidence.REPO', self.repo)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        report = {'status': 'incomplete', 'variants': {}}
        for name in ('original', 'candidate'):
            variant = self.evaluation / 'variants' / name
            contents = {'Cargo.toml': b'[package]\nname="example"\n', 'src/lib.rs': name.encode()}
            manifest = {}
            for relative, data in contents.items():
                self.write(variant / 'library' / relative, data)
                manifest[relative] = {'bytes': len(data), 'sha256': digest(data)}
            self.write(variant / 'library-inputs.json', json.dumps(manifest).encode())
            self.write(variant / 'library/Cargo.lock', b'library test lock')
            self.write(variant / 'application/target/release/mdbook', name.encode())
            report['variants'][name] = {'binary_sha256': digest(name.encode()),
                                       'library_test_lock_sha256': digest(b'library test lock'),
                                       'application_lock_sha256': digest(b'application lock'),
                                       'library_source': '/never/follow/this/external/path'}
        app = self.evaluation / 'variants/original/application'
        self.write(app / 'Cargo.toml', b'application manifest')
        self.write(app / 'Cargo.lock', b'application lock')
        self.write(app / 'src/main.rs', b'fn main() {}')
        self.write(app / 'crates/search/src/lib.rs', b'// original indexing')
        self.write(self.evaluation / 'report.json', json.dumps(report).encode())
        self.write(self.evaluation / 'commands/0001.json', b'{"stdout":"/never/follow/external"}')

    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def prepare(self):
        return prepare_evidence(self.evaluation, self.destination)

    def test_legacy_incomplete_run_freezes_available_sources_and_binaries(self):
        result = self.prepare()
        self.assertIsNone(result['identity']['source_evaluator_version'])
        self.assertIsNone(result['binaryPaths']['capture'])
        self.assertTrue(any('predates' in item for item in result['limitations']))
        self.assertTrue(any('incomplete' in item for item in result['limitations']))
        source = self.evaluation / 'variants/candidate/library/src/lib.rs'
        source.write_text('changed after freezing')
        self.assertEqual((self.destination / 'variants/candidate/library/src/lib.rs').read_text(), 'candidate')
        self.assertEqual(result['binaryPaths']['original'].read_bytes(), b'original')
        self.assertIn('-original', (self.destination / 'library.diff').read_text())
        self.assertFalse((self.destination / 'variants/candidate/library/target').exists())

    def test_rejects_source_tamper_and_size_mismatch(self):
        path = self.evaluation / 'variants/candidate/library/src/lib.rs'
        path.write_text('changed')
        with self.assertRaisesRegex(EvidenceError, 'hash/size mismatch'):
            self.prepare()

    def test_rejects_stale_binary(self):
        path = self.evaluation / 'variants/candidate/application/target/release/mdbook'
        path.write_text('changed binary')
        with self.assertRaisesRegex(EvidenceError, 'hash/size mismatch'):
            self.prepare()

    def test_reports_evaluator_version_difference(self):
        path = self.evaluation / 'report.json'
        report = json.loads(path.read_text())
        recorded = {'sha256': 'historical', 'files': {'run.py': 'historical'}}
        report['evaluator_version'] = recorded
        path.write_text(json.dumps(report))
        result = self.prepare()
        self.assertEqual(result['identity']['source_evaluator_version'], recorded)
        self.assertTrue(any('differs' in item for item in result['limitations']))

    def test_omits_upstream_license_links_without_following_them(self):
        app = self.evaluation / 'variants/original/application'
        (app / 'LICENSE').write_text('Root license')
        (app / 'crates/search/LICENSE').symlink_to('../../LICENSE')
        self.prepare()
        self.assertEqual((self.destination / 'application/LICENSE').read_text(), 'Root license')
        self.assertFalse((self.destination / 'application/crates/search/LICENSE').exists())

    def test_rejects_missing_required_binary(self):
        (self.evaluation / 'variants/candidate/application/target/release/mdbook').unlink()
        with self.assertRaisesRegex(EvidenceError, 'required recorded binary'):
            self.prepare()

    def test_rejects_manifest_path_traversal(self):
        path = self.evaluation / 'variants/candidate/library-inputs.json'
        manifest = json.loads(path.read_text())
        manifest['../escape.rs'] = {'bytes': 0, 'sha256': digest(b'')}
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(EvidenceError, 'Unsafe evidence path'):
            self.prepare()

    def test_rejects_symlink_in_manifest_source(self):
        path = self.evaluation / 'variants/candidate/library/src/lib.rs'
        path.unlink()
        external = self.root / 'external'
        external.write_bytes(b'candidate')
        path.symlink_to(external)
        with self.assertRaisesRegex(EvidenceError, 'Symlink evidence entry'):
            self.prepare()

    def test_detects_source_change_during_copy(self):
        import shutil
        original_copy = shutil.copy2
        def mutate(source, target):
            result = original_copy(source, target)
            if Path(source).name == 'report.json':
                Path(source).write_text('{}')
            return result
        with patch('auditor.evidence.shutil.copy2', side_effect=mutate):
            with self.assertRaisesRegex(EvidenceError, 'changed while copying'):
                self.prepare()


if __name__ == '__main__':
    unittest.main()
