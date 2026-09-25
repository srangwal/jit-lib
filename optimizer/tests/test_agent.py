import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from optimizer import agent


class OptimizerAgentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.workspace, self.context = self.root / "workspace", self.root / "context"
        self.workspace.mkdir()
        self.context.mkdir()
        self.contract = self.root / "contract"
        self.contract.mkdir()
        (self.contract / "prompt.md").write_text("Improve only the private candidate; do not run official evaluation.")
        (self.contract / "response.schema.json").write_text(json.dumps({
            "type": "object", "properties": {
                "status": {"type": "string", "enum": ["candidate", "unchanged"]},
                "summary": {"type": "string"},
            }, "required": ["status", "summary"], "additionalProperties": False,
        }))
        self.patch = patch.object(agent, "HERE", self.contract)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.binary = self.root / "codex-double"
        self.destination = self.root / "record"

    def executable(self, code):
        self.binary.write_text(f"#!{sys.executable}\n" + code)
        self.binary.chmod(0o700)
        return str(self.binary)

    def optimize(self, code, **kwargs):
        return agent.optimize(self.workspace, self.context, self.destination,
                              executable=self.executable(code), **kwargs)

    def test_private_workspace_offline_environment_and_recorded_contract(self):
        result = self.optimize('''import json,os,sys
from pathlib import Path
workspace=Path.cwd()
assert Path(sys.argv[sys.argv.index("-C")+1]) == workspace
for variable,relative in [("CARGO_HOME","cargo-home"),("CARGO_TARGET_DIR","target"),("TMPDIR","tmp")]:
    assert os.environ[variable] == str(workspace/relative)
assert os.environ["CARGO_NET_OFFLINE"] == "true"
assert os.environ["RUSTUP_TOOLCHAIN"] == "1.95.0"
assert "Read-only context:" in sys.stdin.read()
Path("candidate.rs").write_text("private edit")
Path(sys.argv[sys.argv.index("--output-last-message")+1]).write_text(json.dumps({"status":"candidate","summary":"Changed"}))
print('{"type":"turn.completed"}')
''')
        self.assertEqual(result["status"], "candidate")
        self.assertEqual((self.workspace / "candidate.rs").read_text(), "private edit")
        argv = json.loads((self.destination / "command.json").read_text())
        self.assertEqual(argv[argv.index("--model") + 1], "gpt-6-sol")
        self.assertNotIn("--sandbox", argv)
        self.assertIn('permissions.optimizer.filesystem={"/" = "read", ' + json.dumps(str(self.workspace)) + ' = "write"}', argv)
        for flag in ("--ignore-user-config", "--ignore-rules", "--ephemeral"):
            self.assertIn(flag, argv)
        for setting in ('approval_policy="never"', 'web_search="disabled"', 'model_reasoning_effort="medium"',
                        'default_permissions="optimizer"',
                        "permissions.optimizer.network.enabled=false",
                        "project_doc_max_bytes=0", "project_root_markers=[]", "allow_login_shell=false",
                        "features.apps=false", "features.hooks=false", "features.multi_agent=false"):
            self.assertIn(setting, argv)
        self.assertNotIn("--add-dir", argv)
        self.assertIn(str(self.context), (self.destination / "prompt.md").read_text())
        self.assertIn("turn.completed", (self.destination / "events.jsonl").read_text())
        settings = json.loads((self.destination / "settings.json").read_text())
        self.assertEqual(settings["timeout_seconds"], 600)
        self.assertEqual(settings["environment"]["TMPDIR"], str(self.workspace / "tmp"))

    def test_explicit_model_effort_and_timeout_are_retained(self):
        self.optimize('''import json,sys
from pathlib import Path
Path(sys.argv[sys.argv.index("--output-last-message")+1]).write_text(json.dumps({"status":"unchanged","summary":"None"}))
''', model="test-model", reasoning_effort="high", timeout=5)
        settings = json.loads((self.destination / "settings.json").read_text())
        self.assertEqual((settings["model"], settings["reasoning_effort"], settings["timeout_seconds"]),
                         ("test-model", "high", 5))

    def test_overlapping_context_or_logs_and_escape_scratch_are_rejected(self):
        for context, destination in ((self.workspace, self.destination),
                                     (self.context, self.workspace / "logs"),
                                     (self.root, self.destination)):
            with self.subTest(context=context, destination=destination), self.assertRaisesRegex(ValueError, "overlap"):
                agent.optimize(self.workspace, context, destination, executable="must-not-run")
        (self.workspace / "cargo-home").symlink_to(self.context)
        with self.assertRaisesRegex(ValueError, "escapes"):
            agent.optimize(self.workspace, self.context, self.destination, executable="must-not-run")

    def test_nonzero_missing_and_schema_invalid_responses_fail_with_logs(self):
        programs = (
            ("import sys; print('failed',file=sys.stderr); sys.exit(7)", RuntimeError),
            ("pass", RuntimeError),
            ('''import sys
from pathlib import Path
Path(sys.argv[sys.argv.index("--output-last-message")+1]).write_text('{"status":"forged-success","summary":"x"}')
''', ValueError),
        )
        for number, (code, error) in enumerate(programs):
            self.destination = self.root / f"record-{number}"
            with self.subTest(number=number), self.assertRaises(error):
                self.optimize(code)
            self.assertTrue((self.destination / "command.json").is_file())
            self.assertTrue((self.destination / "stderr.log").is_file())

    def test_timeout_kills_the_process_group_including_its_child(self):
        code = '''import os,subprocess,sys,time
from pathlib import Path
child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"])
Path("child.pid").write_text(str(child.pid))
Path("parent.pid").write_text(str(os.getpid()))
time.sleep(60)
'''
        with self.assertRaises(subprocess.TimeoutExpired):
            self.optimize(code, timeout=0.3)
        for name in ("parent.pid", "child.pid"):
            pid = int((self.workspace / name).read_text())
            # Orphaned children can briefly remain zombies until init reaps them.
            for _ in range(50):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.02)
            else:
                os.kill(pid, signal.SIGKILL)
                self.fail(f"Timed-out process survived: {pid}")

    def test_local_build_environment_removes_wrappers_and_pins_proxy_path(self):
        with patch.dict(os.environ, {"RUSTC_WRAPPER": "/outside/wrapper", "RUSTFLAGS": "unsafe flags",
                                     "CC": "/outside/compiler", "CARGO_BUILD_TARGET": "other-platform",
                                     "RUSTUP_HOME": "/existing/read-only-toolchains"}):
            env, local = agent.workspace_environment(self.workspace)
        for name in ("RUSTC_WRAPPER", "RUSTFLAGS", "CC", "CARGO_BUILD_TARGET"):
            self.assertNotIn(name, env)
        self.assertEqual(env["RUSTUP_HOME"], "/existing/read-only-toolchains")
        proxies = Path(local["PATH"].split(os.pathsep)[0])
        self.assertTrue(os.path.samefile(proxies / "cargo", proxies / "rustup"))

    def test_normal_completion_also_kills_background_child(self):
        self.optimize('''import json,subprocess,sys,time
from pathlib import Path
child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"])
Path("child.pid").write_text(str(child.pid))
Path(sys.argv[sys.argv.index("--output-last-message")+1]).write_text(json.dumps({"status":"unchanged","summary":"None"}))
''')
        pid = int((self.workspace / "child.pid").read_text())
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.02)
        else:
            os.kill(pid, signal.SIGKILL)
            self.fail("Background child survived normal optimizer completion")

    @unittest.skipUnless(os.environ.get("OPTIMIZER_SANDBOX_TEST") == "1", "requires native Codex sandbox execution")
    def test_real_sandbox_writes_only_to_workspace(self):
        result = agent.probe_workspace(self.workspace, self.context, self.destination)
        self.assertEqual(result, {"workspace": True, "context": False, "parent": False,
                                  "records": False, "slash_tmp": False})


if __name__ == "__main__":
    unittest.main()
