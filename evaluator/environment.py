#!/usr/bin/env python3
"""Check runtime prerequisites and record nonsecret build configuration."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tomllib

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


class EnvironmentError(RuntimeError):
    pass


def settings():
    return json.loads((HERE / 'environment.json').read_text())


def version_tuple(value):
    match = re.search(r'(\d+)\.(\d+)(?:\.(\d+))?', value)
    if not match:
        raise EnvironmentError(f'Cannot read version: {value}')
    return tuple(int(item or 0) for item in match.groups())


def executable(name, env):
    found = shutil.which(name, path=env.get('PATH', ''))
    if not found:
        raise EnvironmentError(f'Required executable is missing from PATH: {name}')
    return Path(found).absolute()


def output(argv, env):
    try:
        result = subprocess.run(list(map(str, argv)), env=env, capture_output=True,
                                text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise EnvironmentError(f'Cannot run {argv[0]}: {error}') from error
    if result.returncode:
        raise EnvironmentError(f"Command failed: {' '.join(map(str, argv))}\n{result.stderr.strip()}")
    return result.stdout.strip()


def build_environment(base, cargo_home=None, browser=None, *, removed_overrides=None):
    env = dict(base)
    validate_cargo_overrides(env)
    removed = {}
    for key in list(env):
        if key.startswith('MDBOOK_') or key in ('CARGO_TARGET_DIR', 'JIT_LIB_INDEX_TRACE', 'CARGO_NET_OFFLINE'):
            removed[key] = 'removed'
            env.pop(key)
    toolchain = settings()['rust_toolchain']
    if env.get('RUSTUP_TOOLCHAIN') not in (None, toolchain):
        removed['RUSTUP_TOOLCHAIN'] = env['RUSTUP_TOOLCHAIN']
    env.update(TZ='UTC', CARGO_INCREMENTAL='0', RUSTUP_TOOLCHAIN=toolchain)
    if cargo_home:
        env['CARGO_HOME'] = str(Path(cargo_home).expanduser().resolve())
    rustup = executable('rustup', env)
    for name in ('rustc', 'cargo'):
        proxy = rustup.parent / name
        if not proxy.is_file() or not os.path.samefile(proxy, rustup):
            raise EnvironmentError(f'Expected rustup-managed {name} proxy beside {rustup}; install rustup proxies first')
    env['PATH'] = str(rustup.parent) + os.pathsep + env.get('PATH', '')
    selected = browser or env.get('PUPPETEER_EXECUTABLE_PATH')
    if not selected:
        choices = [Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),
                   Path('/Applications/Chromium.app/Contents/MacOS/Chromium')]
        selected = next((path for path in choices if path.is_file()), None)
        selected = selected or next((shutil.which(name, path=env['PATH'])
                                     for name in ('google-chrome', 'chromium', 'chromium-browser')
                                     if shutil.which(name, path=env['PATH'])), None)
    selected = Path(selected).expanduser() if selected else None
    if not selected or not selected.is_file() or not os.access(selected, os.X_OK):
        raise EnvironmentError('Chrome/Chromium is required; provide --browser /path/to/executable')
    env['PUPPETEER_EXECUTABLE_PATH'] = str(Path(selected).expanduser().resolve())
    if removed_overrides is not None:
        removed_overrides.update(removed)
    return env


def build_overrides(env):
    fixed = {'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'RUSTC', 'RUSTC_WRAPPER',
             'RUSTC_WORKSPACE_WRAPPER', 'RUSTDOC', 'RUSTDOCFLAGS', 'CC', 'CXX',
             'CFLAGS', 'CXXFLAGS', 'CPPFLAGS', 'LDFLAGS', 'AR', 'RANLIB',
             'CARGO_INCREMENTAL', 'RUSTUP_TOOLCHAIN', 'CARGO_HOME', 'RUSTUP_HOME',
             'CARGO_BUILD_TARGET', 'CARGO_BUILD_RUSTFLAGS', 'CARGO_BUILD_RUSTC',
             'CARGO_BUILD_RUSTC_WRAPPER', 'CARGO_BUILD_RUSTC_WORKSPACE_WRAPPER'}
    prefixes = ('CARGO_PROFILE_', 'CARGO_TARGET_', 'CC_', 'CXX_', 'CFLAGS_', 'CXXFLAGS_')
    sensitive = ('TOKEN', 'PASSWORD', 'SECRET', 'CREDENTIAL', 'REGISTRY', 'API_KEY')
    return {key: value for key, value in sorted(env.items())
            if (key in fixed or key.startswith(prefixes)) and not any(part in key for part in sensitive)}


def cargo_configs(env, cwd):
    home = Path(env.get('CARGO_HOME', Path(env.get('HOME', str(Path.home()))) / '.cargo'))
    roots = [directory / '.cargo' for directory in (cwd, *cwd.parents)] + [home]
    configs = {}
    for directory in roots:
        for name in ('config', 'config.toml'):
            path = directory / name
            if path.is_file():
                configs[str(path.absolute())] = hashlib.sha256(path.read_bytes()).hexdigest()
    return configs


def validate_cargo_overrides(env):
    for key in ('RUSTC', 'CARGO_BUILD_RUSTC', 'CARGO_BUILD_TARGET', 'CARGO_BUILD_TARGET_DIR'):
        if key in env:
            raise EnvironmentError(f'Unsupported Cargo override {key}; unset it so the evaluator controls its compiler and build locations')


def validate_cargo_settings(env, cwd):
    validate_cargo_overrides(env)
    for filename in cargo_configs(env, Path(cwd).resolve()):
        path = Path(filename)
        # Cargo prefers the extensionless file when both names exist.
        if path.name == 'config.toml' and path.with_name('config').is_file():
            continue
        try:
            config = tomllib.loads(path.read_text())
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
            raise EnvironmentError(f'Cannot parse Cargo config {path}; fix its TOML before evaluation') from error
        build = config.get('build', {})
        if not isinstance(build, dict):
            raise EnvironmentError(f'Invalid Cargo build settings in {path}; expected a [build] table')
        for key in ('rustc', 'target', 'target-dir'):
            if key in build:
                raise EnvironmentError(f'Unsupported Cargo config build.{key} in {path}; remove it for evaluation so the evaluator controls its compiler and build locations')


def runtime_info(env, *, cwd=None):
    config = settings()
    if sys.version_info < version_tuple(config['minimum_python']):
        raise EnvironmentError(f"Python {config['minimum_python']} or newer is required")
    validate_cargo_settings(env, Path(cwd or Path.cwd()))
    rustup = executable('rustup', env)
    pin = config['rust_toolchain']
    installed = output([rustup, 'toolchain', 'list'], env)
    if not any(line.split()[0] == pin or line.split()[0].startswith(pin + '-')
               for line in installed.splitlines() if line.strip()):
        raise EnvironmentError(f'Missing pinned Rust toolchain. Run: rustup toolchain install {pin} --profile minimal')
    rustc = output([rustup, 'run', pin, 'rustc', '-vV'], env)
    cargo = output([rustup, 'run', pin, 'cargo', '--version'], env)
    # Verify ordinary commands used by the evaluator resolve to the selected proxies.
    for name, expected, args in (('rustc', rustc, ['-vV']), ('cargo', cargo, ['--version'])):
        if output([executable(name, env), *args], env) != expected or version_tuple(expected) != version_tuple(pin):
            raise EnvironmentError(f'{name} does not resolve to the required Rust {pin} toolchain')
    node = output([executable('node', env), '--version'], env)
    if version_tuple(node) < version_tuple(config['minimum_node']):
        raise EnvironmentError(f"Node.js {config['minimum_node']} or newer is required; found {node}")
    npm = output([executable('npm', env), '--version'], env)
    version_tuple(npm)
    browser = Path(env['PUPPETEER_EXECUTABLE_PATH'])
    chrome = output([browser, '--version'], env)
    if not re.search(r'(Chrome|Chromium)', chrome, re.IGNORECASE):
        raise EnvironmentError(f'Browser is not identified as Chrome/Chromium: {chrome}')
    root = Path(cwd or Path.cwd()).resolve()
    toolchain_file = REPO / 'rust-toolchain.toml'
    return {'python': platform.python_version(), 'rustc': rustc, 'cargo': cargo,
            'node': node, 'npm': npm, 'browser': chrome, 'browser_path': str(browser),
            'rustup': output([rustup, '--version'], env), 'rust_toolchain': pin,
            'environment_build_overrides': build_overrides(env),
            'cargo_config_sha256': cargo_configs(env, root),
            'rust_toolchain_file_sha256': hashlib.sha256(toolchain_file.read_bytes()).hexdigest(),
            'configuration_note': 'Cargo config files are hashed, not interpreted. Flags may also come from these files and package manifests.'}


def auditor_info(env):
    if platform.system() != 'Darwin' or not Path('/usr/bin/sandbox-exec').is_file():
        raise EnvironmentError('Auditor probes require macOS /usr/bin/sandbox-exec; no unsandboxed fallback is supported')
    codex = executable('codex', env)
    version = output([codex, '--version'], env)
    help_text = output([codex, 'exec', '--help'], env)
    for flag in ('--ignore-user-config', '--ignore-rules', '--sandbox', '--ephemeral',
                 '--output-schema', '--output-last-message'):
        if flag not in help_text:
            raise EnvironmentError(f'Installed Codex CLI lacks required {flag}; tested version is {settings()["tested"]["codex"]}')
    result = subprocess.run([str(codex), 'login', 'status'], env=env, capture_output=True, timeout=30)
    if result.returncode:
        raise EnvironmentError('Codex authentication is required. Run `codex login`, then retry.')
    return {'codex': version, 'codex_authenticated': True, 'sandbox_exec': '/usr/bin/sandbox-exec'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cargo-home', type=Path)
    parser.add_argument('--browser', type=Path)
    args = parser.parse_args()
    try:
        removed = {}
        env = build_environment(os.environ, args.cargo_home, args.browser, removed_overrides=removed)
        info = runtime_info(env)
        info.update(auditor_info(env))
        print(json.dumps({'ready': True, 'runtime': info, 'removed_overrides': removed}, indent=2))
        return 0
    except (EnvironmentError, OSError, subprocess.TimeoutExpired) as error:
        print(json.dumps({'ready': False, 'error': str(error)}, indent=2))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
