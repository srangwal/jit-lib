"""Run a component without parsing its console output for decisions."""

import os
from pathlib import Path
import signal
import subprocess
import time


def descendants(pid):
    """Include children that created independent process groups (Cargo/Codex)."""
    result = subprocess.run(["ps", "-axo", "pid=,ppid="], capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise RuntimeError("Cannot inspect component process tree")
    rows = [tuple(map(int, line.split())) for line in result.stdout.splitlines()]
    found = {pid}
    while True:
        expanded = found | {child for child, parent in rows if parent in found}
        if expanded == found:
            return found
        found = expanded


def stop(process):
    try:
        children = descendants(process.pid)
    except (OSError, ValueError, subprocess.SubprocessError, RuntimeError):
        children = {process.pid}
    for pid in sorted(children, reverse=True):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def run_process(argv, directory, timeout, cwd):
    directory = Path(directory)
    started = time.monotonic()
    process = None
    status = "completed"
    try:
        with (directory / "stdout.log").open("xb") as stdout, (directory / "stderr.log").open("xb") as stderr:
            process = subprocess.Popen(list(map(str, argv)), cwd=cwd, stdout=stdout,
                                       stderr=stderr, start_new_session=True)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                status = "timed_out"
                stop(process)
            except BaseException:
                stop(process)
                raise
    finally:
        if process is not None and process.poll() is None:
            stop(process)
    return {"execution_status": status, "exit_code": process.returncode,
            "elapsed_seconds": time.monotonic() - started}
