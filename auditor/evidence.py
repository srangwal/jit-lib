"""Freeze and verify evaluator evidence without executing candidate code."""

import difflib
import json
from pathlib import Path
import shutil

from evaluator.core import evaluator_fingerprint as fingerprint, sha256, write_json

REPO = Path(__file__).resolve().parents[1]


class EvidenceError(ValueError):
    pass


def safe_path(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts or '\\' in str(relative):
        raise EvidenceError(f'Unsafe evidence path: {relative}')
    path = root
    if path.is_symlink():
        raise EvidenceError(f'Symlink evidence root: {path}')
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise EvidenceError(f'Symlink evidence entry: {path}')
    return path


def evaluator_files(root):
    for path in sorted(Path(root).rglob('*')):
        relative = path.relative_to(root)
        if set(relative.parts) & {'__pycache__', 'target', 'node_modules', '.git'}:
            continue
        if path.is_symlink():
            raise EvidenceError(f'Symlink evaluator source: {path}')
        if path.is_file() and (path.suffix in {'.py', '.json', '.toml', '.rs', '.md', '.lock'}
                               or 'fixtures' in relative.parts or 'locks' in relative.parts):
            yield relative


def evaluator_fingerprint(root=None):
    root = Path(root) if root is not None else REPO / 'evaluator'
    return fingerprint(root)


def prepare_evidence(evaluation, destination):
    """Return frozen paths and identity; never follow paths stored inside reports."""
    evaluation, destination = Path(evaluation).absolute(), Path(destination).absolute()
    if evaluation.is_symlink() or not evaluation.is_dir():
        raise EvidenceError(f'Evaluation must be a real directory: {evaluation}')
    if destination.exists() or destination.is_symlink():
        raise EvidenceError(f'Evidence destination already exists: {destination}')
    if destination.is_relative_to(evaluation):
        raise EvidenceError('Evidence destination must be outside the evaluated run')
    destination.mkdir(parents=True)
    observed = {}

    def copy(root, relative, target, expected=None):
        source = safe_path(root, relative)
        if not source.is_file():
            raise EvidenceError(f'Missing evidence file: {source}')
        before = source.stat()
        digest = sha256(source)
        if expected and (digest != expected['sha256'] or
                         ('bytes' in expected and before.st_size != expected['bytes'])):
            raise EvidenceError(f'Evidence hash/size mismatch: {source}')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        after = source.stat()
        stamp = (before.st_ino, before.st_size, before.st_mtime_ns)
        if stamp != (after.st_ino, after.st_size, after.st_mtime_ns) or sha256(target) != digest:
            raise EvidenceError(f'Evidence changed while copying: {source}')
        observed[source] = (stamp, digest)
        return target

    def tree(root, relative, target, skip_license_links=False):
        source = safe_path(root, relative)
        if not source.is_dir():
            raise EvidenceError(f'Missing evidence directory: {source}')
        for file in sorted(source.rglob('*')):
            if skip_license_links and file.name == 'LICENSE' and file.is_symlink():
                continue
            if file.is_symlink():
                raise EvidenceError(f'Symlink evidence entry: {file}')
            if file.is_file():
                copy(root, file.relative_to(root), target / file.relative_to(source))

    report_path = copy(evaluation, 'report.json', destination / 'evaluation/report.json')
    report = json.loads(report_path.read_text())
    variants = report.get('variants', {})
    limitations = []
    if report.get('status') in {'incomplete', 'correctness-failed'}:
        limitations.append(f"Evaluation status is {report['status']}; this is not successful evaluation evidence.")
    for name in ('configuration.json', 'report.md', 'timings.json', 'correctness.json',
                 'books.json', 'book-inputs.json'):
        if (evaluation / name).exists():
            copy(evaluation, name, destination / 'evaluation' / name)
        else:
            limitations.append(f'Evaluation evidence does not include {name}.')
    for name in ('commands', 'correctness', 'checker-validation', 'timing-checks'):
        if (evaluation / name).exists():
            tree(evaluation, name, destination / 'evaluation' / name)

    library_manifests = {}
    for name in ('original', 'candidate'):
        prefix = Path('variants') / name
        manifest_path = copy(evaluation, prefix / 'library-inputs.json', destination / prefix / 'library-inputs.json')
        manifest = json.loads(manifest_path.read_text())
        if not isinstance(manifest, dict) or 'Cargo.toml' not in manifest:
            raise EvidenceError(f'Invalid library input manifest: {name}')
        for relative, expected in manifest.items():
            copy(evaluation, prefix / 'library' / relative, destination / prefix / 'library' / relative, expected)
        lock_hash = variants.get(name, {}).get('library_test_lock_sha256')
        if not lock_hash:
            raise EvidenceError(f'Missing recorded library test lock hash: {name}')
        copy(evaluation, prefix / 'library/Cargo.lock', destination / prefix / 'library/Cargo.lock',
             {'sha256': lock_hash})
        library_manifests[name] = manifest

    binary_paths, binary_hashes = {}, {}
    for key, name, relative, hash_key in (
        ('original', 'original', 'application/target/release/mdbook', 'binary_sha256'),
        ('candidate', 'candidate', 'application/target/release/mdbook', 'binary_sha256'),
        ('capture', 'capture', 'application/target/release/mdbook', 'binary_sha256'),
        ('original_replay', 'original', 'replay/target/release/index-replay', 'replay_binary_sha256'),
        ('candidate_replay', 'candidate', 'replay/target/release/index-replay', 'replay_binary_sha256'),
    ):
        expected = variants.get(name, {}).get(hash_key)
        source = safe_path(evaluation, Path('variants') / name / relative)
        if not expected or not source.is_file():
            if key in ('original', 'candidate'):
                raise EvidenceError(f'Missing required recorded binary/hash: {key}')
            limitations.append(f'No usable recorded {key} binary; related probes cannot run.')
            binary_paths[key] = None
            continue
        binary_paths[key] = copy(evaluation, source.relative_to(evaluation), destination / 'binaries' / key,
                                 {'sha256': expected})
        binary_hashes[key] = expected

    for name in ('Cargo.toml', 'Cargo.lock'):
        copy(evaluation, 'variants/original/application/' + name, destination / 'application' / name,
             {'sha256': variants['original']['application_lock_sha256']} if name == 'Cargo.lock' else None)
    for name in ('src', 'crates'):
        tree(evaluation, 'variants/original/application/' + name, destination / 'application' / name,
             skip_license_links=True)
    if (evaluation / 'variants/original/application/LICENSE').exists():
        copy(evaluation, 'variants/original/application/LICENSE', destination / 'application/LICENSE')
    limitations.append('Application crate LICENSE symlinks are omitted; the regular root license is retained when present.')
    limitations.append('Historical application source has no complete recorded source manifest; copied source is not independently authenticated.')
    diff = []
    for relative in sorted(library_manifests['original'].keys() | library_manifests['candidate'].keys()):
        contents = []
        for name in ('original', 'candidate'):
            file = destination / 'variants' / name / 'library' / relative
            contents.append(file.read_bytes() if file.is_file() else b'')
        if relative not in library_manifests['original']:
            diff.append(f'Added file: {relative}\n')
        if relative not in library_manifests['candidate']:
            diff.append(f'Removed file: {relative}\n')
        if contents[0] == contents[1]:
            continue
        try:
            a, b = [content.decode().splitlines(keepends=True) for content in contents]
            diff.extend(difflib.unified_diff(a, b, fromfile='original/' + relative, tofile='candidate/' + relative))
        except UnicodeDecodeError:
            diff.append(f'Binary files differ: {relative}\n')
    (destination / 'library.diff').write_text(''.join(diff))

    for relative in evaluator_files(REPO / 'evaluator'):
        copy(REPO / 'evaluator', relative, destination / 'evaluator-current' / relative)
    current = evaluator_fingerprint(destination / 'evaluator-current')
    for name in ('GOAL.md', 'EVALUATOR.md', 'AUDITOR.md'):
        copy(REPO / 'documentation', name, destination / 'documentation' / name)
    historical = report.get('evaluator_version')
    if historical is None:
        limitations.append('Run does not record an evaluator version; current evaluator code is review context, not an authenticated historical version.')
    elif historical != current:
        limitations.append('Current evaluator fingerprint differs from the recorded evaluator version; current code is review context only.')
    identity = {'evaluation': str(evaluation), 'evaluation_report_sha256': sha256(report_path),
                'evaluation_status': report.get('status'), 'binary_sha256': binary_hashes,
                'library_manifest_sha256': {n: sha256(destination / 'variants' / n / 'library-inputs.json')
                                           for n in ('original', 'candidate')},
                'source_evaluator_version': historical, 'current_evaluator_version': current}
    for source, (stamp, digest) in observed.items():
        now = source.stat()
        if stamp != (now.st_ino, now.st_size, now.st_mtime_ns) or sha256(source) != digest:
            raise EvidenceError(f'Evidence changed during preparation: {source}')
    write_json(destination / 'identity.json', identity)
    write_json(destination / 'limitations.json', limitations)
    return {'root': destination, 'binaryPaths': binary_paths, 'identity': identity, 'limitations': limitations}
