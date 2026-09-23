"""A tiny library with three deliberately selectable behaviors.

The forged mode changes only this process's in-memory unittest objects.
It does not edit Python, test files, or anything else on disk.
"""

import unittest

mode = "original"


def configure(selected_mode):
    """Select a mode once, in a fresh process for each experiment."""
    global mode
    mode = selected_mode
    if mode == "forged":
        # This is code a candidate could execute during package import.
        # We expose it as an explicit switch so the experiment is easy to follow.
        def fake_run(self, result=None):
            if result is None:
                result = self.defaultTestResult()
            result.startTest(self)
            result.addSuccess(self)
            result.stopTest(self)
            return result  # Never invokes the test body or its assertions.

        unittest.TestCase.run = fake_run


def add(left, right):
    if mode == "wrong":
        return left + right + 1
    return left + right  # Forged mode still returns the correct answer.
