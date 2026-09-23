"""Keep assertions in a parent that never imports the toy library.

The worker is an ordinary subprocess, NOT an OS sandbox. This demonstrates
separate Python memory only. Original and forged must both exit 1 because
the deliberately false assertion now really executes in the parent.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import unittest


def worker(mode):
    import toy_library  # Only the child imports and configures candidate code.

    toy_library.configure(mode)
    left, right = json.load(sys.stdin)
    print(json.dumps({"value": toy_library.add(left, right)}))


def remote_add(mode, left, right):
    completed = subprocess.run(
        [sys.executable, "-B", str(Path(__file__).resolve()), mode, "--worker"],
        input=json.dumps([left, right]),
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    # A worker's exit 0 is not a test verdict. Read and validate its data.
    answer = json.loads(completed.stdout)
    if type(answer) is not dict or set(answer) != {"value"}:
        raise ValueError("Worker must return exactly one value field")
    if type(answer["value"]) is not int:
        raise ValueError("Worker value must be an integer")
    return answer["value"]


def run_tests(mode):
    executed_bodies = []
    original_runner = unittest.TestCase.run

    class ApplicationTests(unittest.TestCase):
        def test_addition(self):
            executed_bodies.append(self._testMethodName)
            self.assertEqual(remote_add(mode, 2, 3), 5)

        def test_deliberate_failure(self):
            executed_bodies.append(self._testMethodName)
            self.assertEqual(remote_add(mode, 2, 3), 999, "This must fail!")

    print(f"Worker library mode: {mode}")
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ApplicationTests)
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
    print(f"Bodies actually entered: {executed_bodies}")
    print(f"Parent runner unchanged: {unittest.TestCase.run is original_runner}")
    print(f"Parent imported toy_library: {'toy_library' in sys.modules}")
    return 0 if result.wasSuccessful() else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("original", "forged", "wrong"))
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args.mode)
        return 0
    return run_tests(args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
