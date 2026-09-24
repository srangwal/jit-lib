#!/usr/bin/env python3
"""Acquire pinned books without changing any existing checkout."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


class SetupError(ValueError):
    pass


def reject_symlinks(path):
    path = Path(path).absolute()
    for ancestor in (*reversed(path.parents), path):
        if ancestor.is_symlink():
            raise SetupError(f'Symlink paths are not supported: {ancestor}')
    return path


def git(root, *arguments):
    env = dict(os.environ)
    for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_COMMON_DIR'):
        env.pop(key, None)
    env.update(GIT_OPTIONAL_LOCKS='0', GIT_TERMINAL_PROMPT='0')
    result = subprocess.run(['git', '-C', str(root), *arguments], env=env,
                            capture_output=True, text=True, timeout=300)
    if result.returncode:
        raise SetupError(f"Git {' '.join(arguments)} failed in {root}:\n{result.stderr.strip()}")
    return result.stdout.strip()


def canonical_origin(value):
    if value.startswith(('https://', 'http://')):
        return value.rstrip('/').removesuffix('.git')
    return value


def verify_checkout(path, entry):
    path = reject_symlinks(path)
    if not path.is_dir():
        raise SetupError(f'Existing path is not a directory: {path}')
    actual_root = Path(git(path, 'rev-parse', '--show-toplevel')).resolve()
    if actual_root != path:
        raise SetupError(f'Existing directory is not its own Git checkout: {path}')
    reject_symlinks(path / '.git')
    revision = git(path, 'rev-parse', 'HEAD')
    if revision != entry['revision']:
        raise SetupError(f"Wrong revision in {path}: expected {entry['revision']}, found {revision}")
    origin = git(path, 'remote', 'get-url', 'origin')
    if canonical_origin(origin) != canonical_origin(entry['upstream']):
        raise SetupError(f"Wrong origin in {path}: expected {entry['upstream']}, found {origin}")
    if git(path, 'status', '--porcelain', '--untracked-files=all'):
        raise SetupError(f'Checkout has local changes; leaving it untouched: {path}')


def setup_books(entries, destination):
    destination = reject_symlinks(destination)
    names = set()
    for entry in entries:
        name = entry['checkout']
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', name) or name in names:
            raise SetupError(f'Unsafe or duplicate checkout name: {name}')
        if not re.fullmatch(r'[0-9a-f]{40}', entry['revision']):
            raise SetupError(f'Expected a full pinned Git revision for {name}')
        names.add(name)
    destination.mkdir(parents=True, exist_ok=True)
    # Check every existing checkout before acquiring anything new.
    for entry in entries:
        target = destination / entry['checkout']
        reject_symlinks(target)
        if target.exists():
            verify_checkout(target, entry)
    results = []
    for entry in entries:
        target = destination / entry['checkout']
        if target.exists():
            verify_checkout(target, entry)
            status = 'verified'
        else:
            with tempfile.TemporaryDirectory(prefix=f".setup-{entry['checkout']}-", dir=destination) as temporary:
                staging = Path(temporary) / 'checkout'
                staging.mkdir()
                git(staging, 'init', '--quiet')
                git(staging, 'remote', 'add', 'origin', entry['upstream'])
                git(staging, 'fetch', '--depth', '1', '--no-tags', 'origin', entry['revision'])
                git(staging, 'checkout', '--detach', 'FETCH_HEAD')
                verify_checkout(staging, entry)
                reject_symlinks(target)
                if target.exists():
                    raise SetupError(f'Destination appeared during fetch; leaving it untouched: {target}')
                staging.rename(target)
            status = 'created'
        print(f"{status}: {entry['id']} ({entry['revision']})", flush=True)
        results.append({'id': entry['id'], 'path': str(target), 'status': status})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, default=HERE.parent / 'workloads/books')
    args = parser.parse_args()
    try:
        setup_books(json.loads((HERE / 'books.json').read_text()), args.destination)
    except (SetupError, OSError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f'Book setup failed: {error}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
