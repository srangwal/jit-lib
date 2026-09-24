import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from builds import check_dependency_lock, local_env, run_suites, snapshot, use_library
from core import EvaluationError


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_dependency_lock_rejects_transitive_version_changes(self):
        def lock(path, version, library_source):
            path.write_text('version = 4\n[[package]]\nname = "regex"\nversion = "' + version +
                            '"\nsource = "registry+test"\nchecksum = "abc"\n[[package]]\n'
                            'name = "elasticlunr-rs"\nversion = "3.0.2"\n' + library_source)
        old, new = self.root / 'old.lock', self.root / 'new.lock'
        lock(old, '1.0.0', 'source = "registry+test"\nchecksum = "def"\n')
        lock(new, '1.0.0', '')
        check_dependency_lock(old, new)
        lock(new, '1.1.0', '')
        with self.assertRaises(EvaluationError):
            check_dependency_lock(old, new)

    def test_dependency_lock_rejects_added_git_dependency(self):
        old, new = self.root / 'old.lock', self.root / 'new.lock'
        baseline = ('version = 4\n[[package]]\nname = "regex"\nversion = "1.0.0"\n'
                    'source = "registry+test"\nchecksum = "abc"\n')
        old.write_text(baseline)
        new.write_text(baseline + '[[package]]\nname = "external-helper"\nversion = "1.0.0"\n'
                       'source = "git+https://example.invalid/helper#1234"\n')
        with self.assertRaisesRegex(EvaluationError, 'external-helper'):
            check_dependency_lock(old, new)

    def test_dependency_replacement_is_narrow_and_requires_expected_pin(self):
        app = self.root / 'application'
        app.mkdir()
        manifest = app / 'Cargo.toml'
        manifest.write_text('[workspace.dependencies]\nelasticlunr-rs = "3.0.2"\nregex = "1"\n')
        use_library(app, self.root / 'library')
        self.assertIn('elasticlunr-rs = { path = "../library" }', manifest.read_text())
        self.assertIn('regex = "1"', manifest.read_text())
        with self.assertRaises(EvaluationError):
            use_library(app, self.root / 'library')

    def test_candidate_snapshot_retains_edits_additions_and_deletions(self):
        source, dest = self.root / 'source', self.root / 'snapshot'
        source.mkdir()
        (source / 'Cargo.toml').write_text('[package]\nname = "candidate"\n')
        (source / 'new.rs').write_text('new input')
        (source / 'ignored.txt').write_text('not input')
        with patch('builds.subprocess.check_output', return_value=b'Cargo.toml\0new.rs\0deleted.rs\0') as git:
            snapshot(source, dest, candidate=True)
        self.assertTrue((dest / 'new.rs').exists())
        self.assertFalse((dest / 'deleted.rs').exists())
        self.assertFalse((dest / 'ignored.txt').exists())
        self.assertIn('--others', git.call_args.args[0])

    def test_all_required_suites_use_local_targets(self):
        app, library, gui = [self.root / n for n in ('app', 'lib', 'gui')]
        for p in (app, library, gui):
            p.mkdir()
        calls = []
        def run(argv, *, cwd, env):
            self.assertNotIn('CARGO_TARGET_DIR', env)
            calls.append((argv, cwd))
            return {'exit_code': 0}
        result = run_suites({'application': app, 'library': library, 'host': 'test-host'},
                            {'CARGO_TARGET_DIR': '/wrong'}, run, gui)
        self.assertEqual(len(result), 4)
        self.assertIn('--no-default-features', calls[1][0])
        self.assertEqual(calls[2][0][-2:], ['--test', 'gui'])
        self.assertEqual(calls[3][1], library)
        self.assertEqual((app / 'node_modules').readlink(), gui.resolve() / 'node_modules')


if __name__ == '__main__':
    unittest.main()
