from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from evaluator.core import inventory, sha256, write_json
from optimizer.context import ContextError, prepare_context


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / 'repo'
        self.run = self.root / 'run'
        self.destination = self.root / 'context'
        self.pins = {'application': {'url': 'app', 'revision': 'abc'},
                     'library': {'url': 'lib', 'revision': 'def'}}
        write_json(self.repo / 'evaluator/config.json', self.pins)
        self.file(self.repo / 'documentation/GOAL.md', 'Project goal')
        self.library = self.run / 'variants/original/library'
        self.file(self.library / 'Cargo.toml', '[package]\nname="library"\n')
        self.file(self.library / 'src/lib.rs', 'pub fn baseline() {}')
        manifest = inventory(self.library)
        self.file(self.library / 'Cargo.lock', 'library lock')
        for name in ('original', 'candidate'):
            write_json(self.run / 'variants' / name / 'library-inputs.json', manifest)
        self.application = self.run / 'variants/original/application'
        self.file(self.application / 'Cargo.toml', 'application manifest')
        self.file(self.application / 'Cargo.lock', 'application lock')
        self.file(self.application / 'src/main.rs', 'fn main() {}')
        self.file(self.application / 'target/release/mdbook', 'excluded binary')
        self.file(self.application / 'LICENSE', 'license')
        self.file(self.application / 'crates/example/lib.rs', '// crate')
        (self.application / 'crates/example/LICENSE').symlink_to('../../LICENSE')
        book = self.run / 'books/selected/src/SUMMARY.md'
        self.file(book, '# Summary')
        write_json(self.run / 'book-inputs.json', {'selected': {'src/SUMMARY.md': sha256(book)}})
        write_json(self.run / 'books.json', [{'id': 'selected'}])
        write_json(self.run / 'timings.json', [])
        write_json(self.run / 'correctness.json', {'selected': {'passed': True}})
        self.report = {'mode': 'self-check', 'status': 'validated', 'configuration': self.pins,
                       'evaluator_version': {'sha256': 'recorded', 'files': {'run.py': 'hash'}},
                       'variants': {'original': {'library_test_lock_sha256': sha256(self.library / 'Cargo.lock')}}}
        self.save_report()
        self.patch = patch('optimizer.context.REPO', self.repo)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def file(self, path, contents):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)

    def save_report(self):
        write_json(self.run / 'report.json', self.report)

    def prepare(self, **kwargs):
        return prepare_context(self.run, self.destination, **kwargs)

    def test_freezes_verified_sources_books_and_records_limits(self):
        identity = self.prepare()
        self.assertEqual(identity['baseline_report_sha256'], sha256(self.run / 'report.json'))
        self.assertEqual(identity['files'], {key: value for key, value in inventory(self.destination).items()
                                             if key != 'identity.json'})
        self.assertEqual((self.destination / 'books/selected/src/SUMMARY.md').read_text(), '# Summary')
        self.assertEqual((self.destination / 'application/crates/example/LICENSE').read_text(), 'license')
        self.assertFalse((self.destination / 'application/crates/example/LICENSE').is_symlink())
        self.assertFalse((self.destination / 'application/target').exists())
        self.assertIn('No profile supplied.', identity['limitations'])
        self.assertTrue(any('not authenticated historical source' in text for text in identity['limitations']))
        self.assertFalse((self.destination / 'original/Cargo.toml').stat().st_mode & 0o222)
        self.file(self.library / 'src/lib.rs', 'changed afterwards')
        self.assertEqual((self.destination / 'original/src/lib.rs').read_text(), 'pub fn baseline() {}')

    def test_rejects_unvalidated_or_non_self_check_reports(self):
        for mode, status in [('run', 'validated'), ('self-check', 'incomplete'), ('self-check', 'calibration-warning')]:
            with self.subTest(mode=mode, status=status):
                self.report.update(mode=mode, status=status)
                self.save_report()
                with self.assertRaisesRegex(ContextError, 'validated evaluator self-check'):
                    self.prepare()

    def test_requires_matching_pins_and_evaluator_version(self):
        self.report['configuration'] = {**self.pins, 'library': {'revision': 'different'}}
        self.save_report()
        with self.assertRaisesRegex(ContextError, 'pins'):
            self.prepare()
        self.report['configuration'] = self.pins
        del self.report['evaluator_version']
        self.save_report()
        with self.assertRaisesRegex(ContextError, 'evaluator version'):
            self.prepare()

    def test_rejects_different_candidate_manifest(self):
        write_json(self.run / 'variants/candidate/library-inputs.json', {})
        with self.assertRaisesRegex(ContextError, 'must be identical'):
            self.prepare()

    def test_rejects_tampered_library_and_lock(self):
        self.file(self.library / 'src/lib.rs', 'tampered')
        with self.assertRaisesRegex(ContextError, 'hash/size mismatch'):
            self.prepare()
        self.destination = self.root / 'second-context'
        self.file(self.library / 'src/lib.rs', 'pub fn baseline() {}')
        self.file(self.library / 'Cargo.lock', 'tampered lock')
        with self.assertRaisesRegex(ContextError, 'hash/size mismatch'):
            self.prepare()

    def test_rejects_tampered_book(self):
        self.file(self.run / 'books/selected/src/SUMMARY.md', 'wrong')
        with self.assertRaisesRegex(ContextError, 'hash/size mismatch'):
            self.prepare()

    def test_materializes_internal_book_file_symlinks_with_recorded_hash(self):
        book = self.run / 'books/selected'
        self.file(book / 'LICENSE', 'book license')
        (book / 'src/LICENSE').symlink_to('../LICENSE')
        write_json(self.run / 'book-inputs.json', {'selected': {'src/LICENSE': sha256(book / 'LICENSE')}})
        self.prepare()
        copied = self.destination / 'books/selected/src/LICENSE'
        self.assertFalse(copied.is_symlink())
        self.assertEqual(copied.read_text(), 'book license')

    def test_rejects_escaping_book_symlinks(self):
        book = self.run / 'books/selected'
        outside = self.root / 'external-license'
        self.file(outside, 'outside')
        (book / 'src/LICENSE').symlink_to(outside)
        write_json(self.run / 'book-inputs.json', {'selected': {'src/LICENSE': sha256(outside)}})
        with self.assertRaisesRegex(ContextError, 'Escaping context symlink'):
            self.prepare()

    def test_rejects_book_directory_symlinks(self):
        book = self.run / 'books/selected'
        (book / 'linked').symlink_to('src', target_is_directory=True)
        write_json(self.run / 'book-inputs.json', {'selected': {'linked/SUMMARY.md': sha256(book / 'src/SUMMARY.md')}})
        with self.assertRaisesRegex(ContextError, 'Symlink context input'):
            self.prepare()

    def test_materialized_book_symlink_still_requires_original_hash(self):
        book = self.run / 'books/selected'
        self.file(book / 'LICENSE', 'changed')
        (book / 'src/LICENSE').symlink_to('../LICENSE')
        write_json(self.run / 'book-inputs.json', {'selected': {'src/LICENSE': 'original-hash'}})
        with self.assertRaisesRegex(ContextError, 'hash/size mismatch'):
            self.prepare()

    def test_rejects_book_path_traversal(self):
        write_json(self.run / 'book-inputs.json', {'selected': {'../../../outside': 'hash'}})
        with self.assertRaisesRegex(ContextError, 'Unsafe context path'):
            self.prepare()

    def test_rejects_library_path_traversal(self):
        manifest = inventory(self.library)
        manifest['../outside'] = {'bytes': 1, 'sha256': 'bad'}
        for name in ('original', 'candidate'):
            write_json(self.run / 'variants' / name / 'library-inputs.json', manifest)
        with self.assertRaisesRegex(ContextError, 'Unsafe context path'):
            self.prepare()

    def test_requires_all_recorded_context_files(self):
        (self.run / 'correctness.json').unlink()
        with self.assertRaisesRegex(ContextError, 'Missing context input'):
            self.prepare()

    def test_rejects_destination_symlink_ancestor(self):
        linked = self.root / 'linked'
        linked.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ContextError, 'Symlink context input'):
            prepare_context(self.run, linked / 'context')

    def test_copies_manifested_lock_only_when_both_hashes_agree(self):
        for name in ('original', 'candidate'):
            write_json(self.run / 'variants' / name / 'library-inputs.json', inventory(self.library))
        self.prepare()
        self.assertEqual(sha256(self.destination / 'original/Cargo.lock'), sha256(self.library / 'Cargo.lock'))
        self.destination = self.root / 'second-context'
        self.report['variants']['original']['library_test_lock_sha256'] = 'different'
        self.save_report()
        with self.assertRaisesRegex(ContextError, 'Manifested Cargo.lock differs'):
            self.prepare()

    def test_rejects_symlink_and_input_destination(self):
        path = self.library / 'src/lib.rs'
        path.unlink()
        path.symlink_to(self.library / 'Cargo.toml')
        with self.assertRaisesRegex(ContextError, 'Symlink context input'):
            self.prepare()
        with self.assertRaisesRegex(ContextError, 'outside the evaluation'):
            prepare_context(self.run, self.run / 'context')
        linked = self.root / 'linked'
        linked.symlink_to(self.run, target_is_directory=True)
        with self.assertRaisesRegex(ContextError, 'Symlink context input'):
            prepare_context(linked, self.root / 'unused')

    def test_profile_and_feedback_are_explicit_copies(self):
        profile = self.root / 'profile.json'
        feedback = self.root / 'feedback.json'
        self.file(profile, '{"measurement": 1}')
        self.file(feedback, '{"finding": "example"}')
        identity = self.prepare(profile=profile, feedback=feedback)
        self.assertEqual((self.destination / 'profile.txt').read_bytes(), profile.read_bytes())
        self.assertEqual((self.destination / 'feedback.txt').read_bytes(), feedback.read_bytes())
        self.assertNotIn('No profile supplied.', identity['limitations'])
        with self.assertRaisesRegex(ContextError, 'already exists'):
            self.prepare()

    def test_rejects_external_application_license_link(self):
        path = self.application / 'crates/example/LICENSE'
        path.unlink()
        external = self.root / 'outside'
        self.file(external, 'outside')
        path.symlink_to(external)
        with self.assertRaisesRegex(ContextError, 'Unsupported application symlink'):
            self.prepare()


if __name__ == '__main__':
    unittest.main()
