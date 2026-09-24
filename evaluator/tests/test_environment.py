import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from environment import (EnvironmentError, build_environment, build_overrides,
                         cargo_configs, runtime_info, validate_cargo_settings)


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        rustup = self.bin / 'rustup'
        rustup.write_text('fake rustup')
        rustup.chmod(0o700)
        for name in ('rustc', 'cargo'):
            os.link(rustup, self.bin / name)
        for name in ('node', 'npm', 'chrome'):
            path = self.bin / name
            path.write_text('fake executable')
            path.chmod(0o700)
        self.base = {'PATH': str(self.bin), 'HOME': str(self.root),
                     'PUPPETEER_EXECUTABLE_PATH': str(self.bin / 'chrome')}
        (self.root / 'rust-toolchain.toml').write_text('[toolchain]\nchannel="1.95.0"\n')
        self.node_version = 'v26.9.0'
        self.installed = '1.95.0-aarch64-apple-darwin (default)'
        self.proxy_rustc = 'rustc 1.95.0 (example)\nhost: aarch64-apple-darwin'

    def command(self, argv, env):
        args = list(map(str, argv))
        name = Path(args[0]).name
        if name == 'rustup':
            if args[1:] == ['toolchain', 'list']:
                return self.installed
            if args[1:] == ['--version']:
                return 'rustup 1.29.0'
            name = args[3]
            if name == 'rustc':
                return 'rustc 1.95.0 (example)\nhost: aarch64-apple-darwin'
        return {'rustc': self.proxy_rustc, 'cargo': 'cargo 1.95.0 (example)',
                'node': self.node_version, 'npm': '11.19.1',
                'chrome': 'Google Chrome 153.0.8010.53'}[name]

    def runtime(self):
        env = build_environment(self.base)
        with patch('environment.output', side_effect=self.command), patch('environment.REPO', self.root):
            return runtime_info(env, cwd=self.root)

    def test_sanitizes_book_overrides_and_forces_pinned_rust(self):
        base = {**self.base, 'MDBOOK_BOOK__TITLE': 'secret title', 'CARGO_TARGET_DIR': '/other',
                'JIT_LIB_INDEX_TRACE': '/trace', 'CARGO_NET_OFFLINE': 'true',
                'RUSTUP_TOOLCHAIN': 'nightly', 'RUSTFLAGS': '-C target-cpu=native'}
        removed = {}
        env = build_environment(base, self.root / 'cargo-home', removed_overrides=removed)
        self.assertEqual(env['RUSTUP_TOOLCHAIN'], '1.95.0')
        self.assertEqual(env['CARGO_INCREMENTAL'], '0')
        self.assertEqual(env['TZ'], 'UTC')
        self.assertNotIn('MDBOOK_BOOK__TITLE', env)
        self.assertNotIn('CARGO_NET_OFFLINE', env)
        self.assertEqual(removed['MDBOOK_BOOK__TITLE'], 'removed')
        self.assertEqual(removed['RUSTUP_TOOLCHAIN'], 'nightly')
        self.assertEqual(base['RUSTUP_TOOLCHAIN'], 'nightly')
        self.assertEqual(env['RUSTFLAGS'], base['RUSTFLAGS'])

    def test_rejects_unmanaged_compiler_even_beside_rustup(self):
        (self.bin / 'rustc').unlink()
        (self.bin / 'rustc').write_text('different compiler')
        with self.assertRaisesRegex(EnvironmentError, 'rustup-managed rustc'):
            build_environment(self.base)

    def test_runtime_records_versions_without_requiring_codex(self):
        info = self.runtime()
        self.assertEqual(info['rust_toolchain'], '1.95.0')
        self.assertEqual(info['node'], 'v26.9.0')
        self.assertNotIn('codex', info)
        self.assertEqual(info['rust_toolchain_file_sha256'], hashlib.sha256((self.root / 'rust-toolchain.toml').read_bytes()).hexdigest())

    def test_missing_named_toolchain_gives_install_instruction(self):
        self.installed = 'stable-aarch64-apple-darwin (default)'
        with self.assertRaisesRegex(EnvironmentError, 'rustup toolchain install 1.95.0'):
            self.runtime()

    def test_rejects_old_node_and_wrong_compiler_resolution(self):
        self.node_version = 'v22.0.0'
        with self.assertRaisesRegex(EnvironmentError, 'Node.js 24.0.0'):
            self.runtime()
        self.node_version = 'v26.9.0'
        self.proxy_rustc = 'rustc 1.94.0'
        with self.assertRaisesRegex(EnvironmentError, 'does not resolve'):
            self.runtime()

    def test_records_build_overrides_without_credentials(self):
        env = {'RUSTFLAGS': '-C opt-level=3', 'CARGO_PROFILE_RELEASE_LTO': 'true',
               'CARGO_TARGET_AARCH64_APPLE_DARWIN_LINKER': '/tool/linker',
               'CARGO_REGISTRIES_PRIVATE_TOKEN': 'secret', 'OPENAI_API_KEY': 'secret',
               'CARGO_TARGET_CUSTOM_TOKEN': 'secret'}
        recorded = build_overrides(env)
        self.assertEqual(len(recorded), 3)
        self.assertNotIn('secret', str(recorded))

    def test_config_files_are_hashed_without_disclosing_contents(self):
        config = self.root / '.cargo/config.toml'
        config.parent.mkdir()
        config.write_text('token = "private-secret"\n')
        recorded = cargo_configs(self.base, self.root)
        self.assertEqual(recorded[str(config)], hashlib.sha256(config.read_bytes()).hexdigest())
        self.assertNotIn('private-secret', str(recorded))

    def test_explicit_browser_must_exist_and_be_executable(self):
        with self.assertRaisesRegex(EnvironmentError, 'Chrome/Chromium is required'):
            build_environment(self.base, browser=self.root / 'missing')

    def test_rejects_compiler_and_output_environment_overrides(self):
        for key in ('RUSTC', 'CARGO_BUILD_RUSTC', 'CARGO_BUILD_TARGET', 'CARGO_BUILD_TARGET_DIR'):
            with self.subTest(key=key):
                env = {**self.base, key: 'private-value'}
                for validate in (lambda: build_environment(env),
                                 lambda: validate_cargo_settings(env, self.root)):
                    with self.assertRaisesRegex(EnvironmentError, key) as caught:
                        validate()
                    self.assertNotIn('private-value', str(caught.exception))

    def test_rejects_compiler_and_output_cargo_config(self):
        config = self.root / '.cargo/config.toml'
        config.parent.mkdir()
        child = self.root / 'package'
        child.mkdir()
        for key in ('rustc', 'target', 'target-dir'):
            with self.subTest(key=key):
                config.write_text(f'[build]\n{key} = "private-value"\n')
                with self.assertRaisesRegex(EnvironmentError, f'build.{key}') as caught:
                    validate_cargo_settings(self.base, child)
                self.assertNotIn('private-value', str(caught.exception))
                with self.assertRaisesRegex(EnvironmentError, f'build.{key}'):
                    self.runtime()

    def test_cargo_home_config_checked_and_aliases_preserved(self):
        home = self.root / 'cargo-home'
        home.mkdir()
        config = home / 'config.toml'
        env = {**self.base, 'CARGO_HOME': str(home), 'RUSTC_WRAPPER': '/wrapper'}
        config.write_text('[alias]\nb = "build"\n[build]\nrustflags = ["-C", "opt-level=2"]\n')
        validate_cargo_settings(env, self.root)
        config.write_text('[build]\ntarget-dir = "private-value"\n')
        with self.assertRaisesRegex(EnvironmentError, 'build.target-dir'):
            validate_cargo_settings(env, self.root)

    def test_extensionless_config_takes_precedence(self):
        directory = self.root / '.cargo'
        directory.mkdir()
        (directory / 'config').write_text('[alias]\nb = "build"\n')
        (directory / 'config.toml').write_text('[build]\nrustc = "ignored"\n')
        validate_cargo_settings(self.base, self.root)

    def test_invalid_config_error_does_not_expose_contents(self):
        config = self.root / '.cargo/config.toml'
        config.parent.mkdir()
        config.write_text('private-secret = invalid')
        with self.assertRaisesRegex(EnvironmentError, 'Cannot parse Cargo config') as caught:
            validate_cargo_settings(self.base, self.root)
        self.assertNotIn('private-secret', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
