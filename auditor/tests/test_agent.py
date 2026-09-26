import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from auditor.agent import check_login, configuration, investigate
from unittest.mock import patch


class AgentAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.binary = self.root / "codex-double"

    def executable(self, code):
        self.binary.write_text(f"#!{sys.executable}\n" + code)
        self.binary.chmod(0o700)
        return str(self.binary)

    def test_structured_output_and_restricted_invocation(self):
        executable = self.executable('''import json,sys
from pathlib import Path
if sys.argv[1:]==["login","status"]: sys.exit(0)
assert sys.argv[sys.argv.index("--sandbox")+1] == "read-only"
assert "--ignore-user-config" in sys.argv and "--ignore-rules" in sys.argv
assert 'approval_policy="never"' in sys.argv
assert "Controller history:" in sys.stdin.read()
Path(sys.argv[sys.argv.index("--output-last-message")+1]).write_text(json.dumps({
 "action":"finish","summary":"Inspected","findings":[],"probes":[]}))
print('{"type":"turn.completed"}')
''')
        check_login(executable)
        result = investigate(self.root, [], self.root / "round", executable=executable)
        self.assertEqual(result["action"], "finish")
        self.assertIn("turn.completed", (self.root / "round/events.jsonl").read_text())
        argv = json.loads((self.root / "round/command.json").read_text())
        self.assertEqual(argv[argv.index("--model") + 1], configuration()["models"]["codex"])
        self.assertIn('model_reasoning_effort="medium"', argv)

    def test_model_override_is_explicit(self):
        executable = self.executable('''import json,sys
from pathlib import Path
assert sys.argv[sys.argv.index("--model")+1] == "test-model"
Path(sys.argv[sys.argv.index("--output-last-message")+1]).write_text(json.dumps({
 "action":"finish","summary":"Inspected","findings":[],"probes":[]}))
''')
        investigate(self.root, [], self.root / "round", executable=executable, model="test-model")

    def test_external_agents_receive_read_only_context_and_same_contract(self):
        response = {"action": "finish", "summary": "Inspected", "findings": [], "probes": []}
        for name in ("claude", "opencode"):
            with patch("auditor.agent.run_external", return_value=response) as run:
                result = investigate(self.root, [], self.root / name, executable=name,
                                     agent=name, model="explicit-model", base_url="http://127.0.0.1:11434/v1" if name == "opencode" else None)
            self.assertEqual(result, response)
            self.assertEqual(run.call_args.args[:3], (name, name, "explicit-model"))
            self.assertNotIn("workspace", run.call_args.kwargs)

    def test_external_agent_cannot_bypass_response_validation(self):
        with patch("auditor.agent.run_external", return_value={"action": "accept"}), self.assertRaises(ValueError):
            investigate(self.root, [], self.root / "round", agent="claude")

    def test_login_failure_is_explicit(self):
        executable = self.executable("import sys\nsys.exit(1)\n")
        with self.assertRaisesRegex(RuntimeError, "authentication is required"):
            check_login(executable)

    def test_nonzero_exit_and_missing_structured_response_fail(self):
        for code in ("import sys\nsys.exit(2)\n", "pass\n"):
            executable = self.executable(code)
            with tempfile.TemporaryDirectory(dir=self.root) as temp:
                with self.assertRaises(RuntimeError):
                    investigate(self.root, [], Path(temp) / "round", executable=executable)

    def test_timeout_is_not_a_clean_response(self):
        executable = self.executable("import time\ntime.sleep(30)\n")
        with self.assertRaises(subprocess.TimeoutExpired):
            investigate(self.root, [], self.root / "round", executable=executable, timeout=0.1)


if __name__ == "__main__":
    unittest.main()
