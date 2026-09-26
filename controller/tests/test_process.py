import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from controller.process import run_process


class ProcessTests(unittest.TestCase):
    def test_real_command_records_output_and_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = run_process([sys.executable, "-c", "import sys; print('details'); sys.exit(7)"], root, 10, root)
            self.assertEqual(result["execution_status"], "completed")
            self.assertEqual(result["exit_code"], 7)
            self.assertEqual((root / "stdout.log").read_text().strip(), "details")

    def test_timeout_terminates_child_in_separate_process_group(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = ("import subprocess,sys,time,pathlib; "
                      "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],start_new_session=True); "
                      "pathlib.Path('child.pid').write_text(str(p.pid)); time.sleep(60)")
            result = run_process([sys.executable, "-c", script], root, 1, root)
            self.assertEqual(result["execution_status"], "timed_out")
            pid = int((root / "child.pid").read_text())
            probe = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True)
            self.assertTrue(probe.returncode != 0 or probe.stdout.strip().startswith("Z"), probe.stdout)
