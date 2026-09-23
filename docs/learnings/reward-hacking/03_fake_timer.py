"""A child's reported duration can lie while a parent's clock keeps running.

Run: python3 03_fake_timer.py
The child processes are ordinary processes, not security sandboxes.
The parent measurement includes interpreter startup, not just the toy work.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time


DELAY = 0.25


def run_child(mode):
    if mode == "tampered":
        # This changes the clock function in this child process only.
        time.perf_counter = lambda: 0.0
    start = time.perf_counter()
    time.sleep(DELAY)  # Stand-in for work that takes time.
    answer = 2 + 2
    print(json.dumps({"answer": answer,
                      "reported_seconds": time.perf_counter() - start}))


def run_parent():
    print(f"Both children sleep for {DELAY} seconds and return the answer 4.")
    print("Mode       Child reports   Parent measures (includes startup)")
    results = {}
    for mode in ("honest", "tampered"):
        start = time.perf_counter()
        child = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()), "--child", mode],
            capture_output=True, text=True, check=True, timeout=5,
        )
        elapsed = time.perf_counter() - start
        result = json.loads(child.stdout)
        results[mode] = result
        assert result["answer"] == 4
        assert elapsed >= DELAY, "The parent must observe the sleep."
        print(f"{mode:10} {result['reported_seconds']:8.3f}s"
              f"       {elapsed:.3f}s")
    assert results["honest"]["reported_seconds"] >= DELAY
    assert results["tampered"]["reported_seconds"] == 0
    print("\nExpected: the tampered child reports zero; the parent still sees time pass.")
    print("A candidate's own timing report should not decide its performance score.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", choices=("honest", "tampered"),
                        help="internal mode used by the parent")
    args = parser.parse_args()
    if args.child:
        run_child(args.child)
    else:
        run_parent()
