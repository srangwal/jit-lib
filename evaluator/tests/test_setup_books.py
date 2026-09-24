import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from setup_books import SetupError, setup_books, verify_checkout


class SetupBooksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.remote = self.root / 'remote'
        self.remote.mkdir()
        self.git(self.remote, 'init', '--quiet')
        (self.remote / 'book.toml').write_text('[book]\ntitle = "Pinned book"\n')
        self.git(self.remote, 'add', 'book.toml')
        self.git(self.remote, 'commit', '--quiet', '-m', 'Temporary test fixture')
        self.revision = self.git(self.remote, 'rev-parse', 'HEAD').strip()
        self.entry = {'id': 'sample', 'checkout': 'sample', 'revision': self.revision,
                      'upstream': self.remote.as_uri()}
        self.destination = self.root / 'books'

    def git(self, root, *args):
        env = dict(os.environ)
        env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        return subprocess.check_output(['git', '-C', str(root), '-c', 'user.name=Fixture',
                                        '-c', 'user.email=fixture@example.invalid',
                                        '-c', 'commit.gpgsign=false', *args], env=env, text=True)

    def setup(self, entries=None, destination=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return setup_books(entries or [self.entry], destination or self.destination)

    def test_fetches_exact_pin_and_rechecks_without_touching_existing_index(self):
        (self.remote / 'book.toml').write_text('[book]\ntitle = "Newer upstream"\n')
        self.git(self.remote, 'commit', '--quiet', '-am', 'Later upstream fixture')
        self.assertEqual(self.setup()[0]['status'], 'created')
        checkout = self.destination / 'sample'
        self.assertEqual(self.git(checkout, 'rev-parse', 'HEAD').strip(), self.revision)
        self.assertIn('Pinned book', (checkout / 'book.toml').read_text())
        index_time = (checkout / '.git/index').stat().st_mtime_ns
        self.assertEqual(self.setup()[0]['status'], 'verified')
        self.assertEqual((checkout / '.git/index').stat().st_mtime_ns, index_time)

    def test_rejects_dirty_checkout_without_overwriting_work(self):
        self.setup()
        file = self.destination / 'sample/book.toml'
        file.write_text('local edits')
        with self.assertRaisesRegex(SetupError, 'local changes'):
            self.setup()
        self.assertEqual(file.read_text(), 'local edits')

    def test_rejects_wrong_revision_and_origin_without_updating_checkout(self):
        self.setup()
        checkout = self.destination / 'sample'
        wrong_pin = {**self.entry, 'revision': '0' * 40}
        with self.assertRaisesRegex(SetupError, 'Wrong revision'):
            self.setup([wrong_pin])
        self.assertEqual(self.git(checkout, 'rev-parse', 'HEAD').strip(), self.revision)
        self.git(checkout, 'remote', 'set-url', 'origin', 'file:///different/upstream')
        with self.assertRaisesRegex(SetupError, 'Wrong origin'):
            self.setup()
        self.assertEqual(self.git(checkout, 'remote', 'get-url', 'origin').strip(), 'file:///different/upstream')

    def test_rejects_non_repository_and_parent_repository_discovery(self):
        checkout = self.destination / 'sample'
        checkout.mkdir(parents=True)
        marker = checkout / 'keep.txt'
        marker.write_text('existing contents')
        with self.assertRaises(SetupError):
            self.setup()
        self.assertEqual(marker.read_text(), 'existing contents')
        nested = self.remote / 'nested'
        nested.mkdir()
        with self.assertRaisesRegex(SetupError, 'own Git checkout'):
            verify_checkout(nested, self.entry)

    def test_rejects_symlink_checkout_and_parent_paths(self):
        self.destination.mkdir()
        target = self.destination / 'sample'
        target.symlink_to(self.remote, target_is_directory=True)
        with self.assertRaisesRegex(SetupError, 'Symlink'):
            self.setup()
        self.assertTrue(target.is_symlink())
        parent_link = self.root / 'linked-books'
        parent_link.symlink_to(self.destination, target_is_directory=True)
        with self.assertRaisesRegex(SetupError, 'Symlink'):
            self.setup(destination=parent_link / 'nested')

    def test_failed_fetch_cleans_staging_and_preserves_existing_checkout(self):
        self.setup()
        failed = {**self.entry, 'id': 'missing', 'checkout': 'missing', 'revision': '0' * 40}
        with self.assertRaisesRegex(SetupError, 'fetch'):
            self.setup([self.entry, failed])
        self.assertEqual(sorted(p.name for p in self.destination.iterdir()), ['sample'])
        self.assertEqual(self.git(self.destination / 'sample', 'rev-parse', 'HEAD').strip(), self.revision)
        self.assertEqual(self.git(self.destination / 'sample', 'status', '--porcelain'), '')

    def test_rejects_untracked_changes_before_acquiring_other_books(self):
        self.setup()
        extra = self.destination / 'sample/notes.txt'
        extra.write_text('not committed')
        other = {**self.entry, 'id': 'other', 'checkout': 'other'}
        with self.assertRaisesRegex(SetupError, 'local changes'):
            self.setup([other, self.entry])
        self.assertFalse((self.destination / 'other').exists())
        self.assertEqual(extra.read_text(), 'not committed')


if __name__ == '__main__':
    unittest.main()
