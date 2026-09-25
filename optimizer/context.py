"""Freeze verified baseline inputs for an optimizer, without executing them."""

import hashlib
import json
import os
from pathlib import Path

from evaluator.core import inventory, sha256, write_json

REPO = Path(__file__).resolve().parents[1]


class ContextError(ValueError):
    pass


def safe_path(root, relative):
    relative = Path(relative)
    if not relative.parts or relative.is_absolute() or '..' in relative.parts or '\\' in str(relative):
        raise ContextError(f'Unsafe context path: {relative}')
    path = root / relative
    for entry in (path, *path.parents):
        if entry.is_symlink():
            raise ContextError(f'Symlink context input: {entry}')
    return path


def prepare_context(evaluation: Path, destination: Path, *, profile: Path | None = None,
                    feedback: Path | None = None) -> dict:
    evaluation = Path(os.path.abspath(evaluation))
    destination = Path(os.path.abspath(destination))
    safe_path(evaluation.parent, evaluation.name)
    safe_path(destination.parent, destination.name)
    if not evaluation.is_dir():
        raise ContextError(f'Missing evaluation directory: {evaluation}')
    if destination.exists():
        raise ContextError(f'Context destination already exists: {destination}')
    if destination.is_relative_to(evaluation):
        raise ContextError('Context destination must be outside the evaluation directory')
    observed = {}
    observed_links = {}

    def materialized_file(root, relative):
        relative = Path(relative)
        if not relative.parts or relative.is_absolute() or '..' in relative.parts or '\\' in str(relative):
            raise ContextError(f'Unsafe context path: {relative}')
        source = root / relative
        safe_path(source.parent.parent, source.parent.name)
        if not source.is_symlink():
            return safe_path(root, relative)
        link = source.readlink()
        target = Path(os.path.abspath(source.parent / link))
        if not target.is_relative_to(root):
            raise ContextError(f'Escaping context symlink: {source}')
        target = safe_path(root, target.relative_to(root))
        if not target.is_file():
            raise ContextError(f'Context symlink must refer to a regular file: {source}')
        stat = source.lstat()
        observed_links[source] = (stat.st_ino, stat.st_mtime_ns, link)
        return target

    def read(source):
        safe_path(source.parent, source.name)
        if not source.is_file():
            raise ContextError(f'Missing context input: {source}')
        before = source.stat()
        content = source.read_bytes()
        digest = sha256(source)
        stamp = (before.st_ino, before.st_size, before.st_mtime_ns)
        if stamp != signature(source) or digest != hashlib.sha256(content).hexdigest():
            raise ContextError(f'Context input changed while reading: {source}')
        previous = observed.setdefault(source, (stamp, digest))
        if previous != (stamp, digest):
            raise ContextError(f'Context input changed during preparation: {source}')
        return content

    def signature(source):
        stat = source.stat()
        return stat.st_ino, stat.st_size, stat.st_mtime_ns

    def load(source):
        try:
            return json.loads(read(source))
        except (ValueError, UnicodeError) as error:
            raise ContextError(f'Invalid JSON context input: {source}') from error

    def copy(source, relative, expected=None):
        content = read(source)
        digest = observed[source][1]
        if isinstance(expected, str):
            expected = {'sha256': expected}
        if expected is not None and (not isinstance(expected, dict) or
                expected.get('sha256') != digest or expected.get('bytes', len(content)) != len(content)):
            raise ContextError(f'Context input hash/size mismatch: {source}')
        target = safe_path(destination, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        if sha256(target) != digest:
            raise ContextError(f'Context copy hash mismatch: {target}')
        target.chmod(source.stat().st_mode & 0o555)

    report_path = evaluation / 'report.json'
    report = load(report_path)
    if not isinstance(report, dict) or report.get('mode') != 'self-check' or report.get('status') != 'validated':
        raise ContextError('Optimizer requires a completed, validated evaluator self-check')
    configuration = load(REPO / 'evaluator/config.json')
    pins = {key: configuration[key] for key in ('application', 'library')}
    if any(report.get('configuration', {}).get(key) != value for key, value in pins.items()):
        raise ContextError('Baseline application/library pins do not match evaluator/config.json')
    version = report.get('evaluator_version')
    if not isinstance(version, dict) or not version.get('sha256') or not isinstance(version.get('files'), dict):
        raise ContextError('Baseline report must record an evaluator version')
    manifests = {name: load(evaluation / 'variants' / name / 'library-inputs.json')
                 for name in ('original', 'candidate')}
    manifest = manifests['original']
    if not isinstance(manifest, dict) or 'Cargo.toml' not in manifest or manifest != manifests['candidate']:
        raise ContextError('Self-check original/candidate library manifests must be identical and include Cargo.toml')
    original = report.get('variants', {}).get('original', {})
    if not original.get('library_test_lock_sha256'):
        raise ContextError('Baseline lacks the original library test lock hash')
    books = load(evaluation / 'book-inputs.json')
    if not isinstance(books, dict) or not books:
        raise ContextError('Baseline lacks book input manifests')
    destination.mkdir(parents=True, exist_ok=False)
    for filename in ('report.json', 'books.json', 'book-inputs.json', 'timings.json', 'correctness.json'):
        copy(evaluation / filename, Path('evaluation') / filename)
    for name in manifests:
        copy(evaluation / 'variants' / name / 'library-inputs.json',
             Path('evaluation') / f'{name}-library-inputs.json')
    library = evaluation / 'variants/original/library'
    for relative, expected in manifest.items():
        if not isinstance(expected, dict) or 'sha256' not in expected or 'bytes' not in expected:
            raise ContextError(f'Invalid library manifest entry: {relative}')
        copy(safe_path(library, relative), Path('original') / relative, expected)
    if 'Cargo.lock' in manifest:
        if manifest['Cargo.lock']['sha256'] != original['library_test_lock_sha256']:
            raise ContextError('Manifested Cargo.lock differs from recorded library test lock')
    else:
        copy(library / 'Cargo.lock', 'original/Cargo.lock', original['library_test_lock_sha256'])
    for book, inputs in books.items():
        if Path(book).name != book or not isinstance(inputs, dict) or not inputs:
            raise ContextError(f'Invalid book input manifest: {book}')
        book_root = safe_path(evaluation / 'books', book)
        for relative, expected in inputs.items():
            if not isinstance(expected, str):
                raise ContextError(f'Invalid book input hash: {book}/{relative}')
            copy(materialized_file(book_root, relative), Path('books') / book / relative, expected)
    application = safe_path(evaluation, 'variants/original/application')
    if not (application / 'Cargo.toml').is_file():
        raise ContextError('Baseline application source is missing Cargo.toml')
    for root, directories, files in os.walk(application, followlinks=False):
        directories[:] = sorted(name for name in directories if name not in {'target', 'node_modules', '.git'})
        for name in directories:
            safe_path(application, (Path(root) / name).relative_to(application))
        for name in sorted(files):
            source = Path(root) / name
            relative = source.relative_to(application)
            if source.is_symlink():
                resolved = source.resolve()
                if name != 'LICENSE' or not resolved.is_relative_to(application):
                    raise ContextError(f'Unsupported application symlink: {source}')
                source = safe_path(application, resolved.relative_to(application))
            copy(source, Path('application') / relative)
    limitations = ['Historical application source has no complete recorded source manifest; copied application hashes identify current context, not authenticated historical source.']
    for name, supplied in (('profile', profile), ('feedback', feedback)):
        if supplied is None:
            limitations.append(f'No {name} supplied.')
        else:
            copy(Path(os.path.abspath(supplied)), f'{name}.txt')
    copy(REPO / 'documentation/GOAL.md', 'GOAL.md')
    for source, (stamp, digest) in observed.items():
        safe_path(source.parent, source.name)
        if signature(source) != stamp or sha256(source) != digest:
            raise ContextError(f'Context input changed during preparation: {source}')
    for source, recorded in observed_links.items():
        stat = source.lstat()
        if not source.is_symlink() or (stat.st_ino, stat.st_mtime_ns, source.readlink()) != recorded:
            raise ContextError(f'Context symlink changed during preparation: {source}')
    identity = {'source': str(evaluation), 'baseline_report_sha256': observed[report_path][1],
                'baseline_status': report['status'], 'pins': pins, 'evaluator_version': version,
                'limitations': limitations, 'files': inventory(destination)}
    write_json(destination / 'identity.json', identity)
    (destination / 'identity.json').chmod(0o444)
    return identity
