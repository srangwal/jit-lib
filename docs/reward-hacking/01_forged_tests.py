"""Compare honest test execution with success reported without running tests.

Run with original, forged, or wrong. Original intentionally exits 1 because
the second test is deliberately false. Forged misleadingly exits 0.
"""

import argparse
import sys
import unittest

import toy_library

executed_bodies = []


class ApplicationTests(unittest.TestCase):
    def test_addition(self):
        executed_bodies.append(self._testMethodName)
        self.assertEqual(toy_library.add(2, 3), 5)

    def test_deliberate_failure(self):
        executed_bodies.append(self._testMethodName)
        self.assertEqual(toy_library.add(2, 3), 999, "This must fail!")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("original", "forged", "wrong"))
    args = parser.parse_args()
    toy_library.configure(args.mode)

    print(f"Library mode: {args.mode}")
    print(f"Ordinary application answer: 2 + 3 = {toy_library.add(2, 3)}")
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ApplicationTests)
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
    print(f"Runner reports {result.testsRun} tests run")
    print(f"Bodies actually entered: {executed_bodies}")
    print("The body list is a teaching aid, not a protected security check.")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
