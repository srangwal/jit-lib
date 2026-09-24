import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare_books import prepare_book


class PrepareBooksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'sources' / 'sample'
        self.source.mkdir(parents=True)
        (self.source / 'book.toml').write_text('[book]\ntitle = "Sample"\n')
        (self.source / '.gitignore').write_text('generated/\n')
        self.git('init', '-q')
        self.git('add', '.')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'Fixture')
        self.entry = {'id': 'sample', 'checkout': 'sample', 'book_root': '.',
                      'revision': self.git('rev-parse', 'HEAD').strip(), 'prepare': []}

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.source), *args], text=True)

    def prepare(self, runner=lambda *args, **kwargs: None):
        return prepare_book(self.entry, self.root / 'sources', self.root / 'prepared',
                            os.environ, runner)

    def test_copies_only_committed_inputs_without_changing_source(self):
        (self.source / 'generated').mkdir()
        (self.source / 'generated' / 'stale.html').write_text('stale output')
        book, env = self.prepare()
        self.assertEqual((book / 'book.toml').read_bytes(), (self.source / 'book.toml').read_bytes())
        self.assertFalse((book / '.git').exists())
        self.assertFalse((book / 'generated').exists())
        self.assertEqual(env['CARGO_NET_OFFLINE'], 'true')
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_rejects_wrong_revision_and_dirty_source(self):
        self.entry['revision'] = '0' * 40
        with self.assertRaisesRegex(ValueError, 'expected'):
            self.prepare()
        self.entry['revision'] = self.git('rev-parse', 'HEAD').strip()
        (self.source / 'book.toml').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'not clean'):
            self.prepare()
        self.assertFalse((self.root / 'prepared').exists())

    def test_prebuilds_from_book_root_before_enabling_offline_mode(self):
        self.entry['prepare'] = [['cargo', 'build', '--locked']]
        calls = []
        def runner(argv, *, cwd, env):
            calls.append((argv, cwd, dict(env)))
        book, env = self.prepare(runner)
        self.assertEqual(calls[0][0], self.entry['prepare'][0])
        self.assertEqual(calls[0][1], book)
        self.assertEqual(calls[0][2]['CARGO_TARGET_DIR'], str(book / '.cargo-target'))
        self.assertEqual(env['CARGO_NET_OFFLINE'], 'true')

    def test_records_legacy_author_migration_only_in_prepared_copy(self):
        original = '[book]\ntitle = "Sample"\nauthor = "Author"\n'
        (self.source / 'book.toml').write_text(original)
        self.git('add', 'book.toml')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                 'commit', '-qm', 'Legacy configuration fixture')
        self.entry['revision'] = self.git('rev-parse', 'HEAD').strip()
        self.entry['compatibility'] = 'legacy-author'
        book, _ = self.prepare()
        self.assertIn('authors = ["Author"]', (book / 'book.toml').read_text())
        self.assertEqual((self.source / 'book.toml').read_text(), original)
        provenance = json.loads((book / 'preparation.json').read_text())
        self.assertNotEqual(provenance['config_sha256_before'], provenance['config_sha256_after'])
        self.assertEqual(provenance['transformations'][0]['after'], 'authors = ["Author"]')


if __name__ == '__main__':
    unittest.main()
