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

    def test_correction_prompt_keeps_source_fixed_and_omits_base_selection(self):
        rejection = {"error": "Expected application/path:line", "response": {"status": "candidate"}}
        self.optimize('''import json,sys
from pathlib import Path
prompt=sys.stdin.read()
assert "Expected application/path:line" in prompt
assert "Do not edit library source" in prompt
assert "There is initially no library/" not in prompt
assert "Remaining attempt time: 45 seconds" in prompt
Path(sys.argv[sys.argv.index("--output-last-message")+1]).write_text(json.dumps({"status":"candidate","summary":"Corrected"}))
''', correction=rejection, timeout=45)
        self.assertIn("reporting-only correction", (self.destination / "prompt.md").read_text())

    def test_external_agents_receive_correction_prompt(self):
        for name in ("claude", "opencode"):
            with patch("optimizer.agent.run_external", return_value={"status": "candidate", "summary": "Corrected"}) as run:
                agent.optimize(self.workspace, self.context, self.root / name, agent=name,
                               correction={"error": "Bad citation", "response": {}}, timeout=30)
            self.assertIn("Bad citation", run.call_args.args[4])
            self.assertIn("Do not edit library source", run.call_args.args[4])
            self.assertEqual(run.call_args.kwargs["timeout"], 30)

    def test_explicit_model_effort_and_timeout_are_retained(self):
        self.optimize('''import json,sys
from pathlib import Path
Path(sys.argv[sys.argv.index("--output-last-message")+1]).write_text(json.dumps({"status":"unchanged","summary":"None"}))
''', model="test-model", reasoning_effort="high", timeout=5)
        settings = json.loads((self.destination / "settings.json").read_text())
        self.assertEqual((settings["model"], settings["reasoning_effort"], settings["timeout_seconds"]),
                         ("test-model", "high", 5))

    def test_external_agent_receives_private_workspace_and_offline_build_environment(self):
        with patch("optimizer.agent.run_external", return_value={"status": "candidate", "summary": "Changed"}) as run:
            result = agent.optimize(self.workspace, self.context, self.destination,
                                    agent="claude", executable="claude", model="sonnet")
        self.assertEqual(result["status"], "candidate")
        self.assertEqual(run.call_args.args[:3], ("claude", "claude", "sonnet"))
        self.assertEqual(run.call_args.kwargs["workspace"], self.workspace)
        self.assertEqual(run.call_args.kwargs["environment"]["CARGO_NET_OFFLINE"], "true")
        self.assertIn(str(self.context), run.call_args.args[4])

    def test_single_session_services_base_requests_for_codex(self):
        requests = []
        def service():
            request = self.workspace / "base-request.json"
            if request.exists() and not requests:
                requests.append(json.loads(request.read_text()))
                (self.workspace / "base-response.json").write_text('{"status":"ready"}')
        result = self.optimize('''import json,sys,time
from pathlib import Path
Path("base-request.json").write_text('{"request_id":"one"}')
while not Path("base-response.json").exists():
    time.sleep(.02)
assert json.loads(Path("base-response.json").read_text())["status"] == "ready"
Path(sys.argv[sys.argv.index("--output-last-message")+1]).write_text(json.dumps({"status":"candidate","summary":"Changed"}))
''', checkpoint_handler=service)
        self.assertEqual(result["status"], "candidate")
        self.assertEqual(requests, [{"request_id": "one"}])

    def test_external_agent_has_same_checkpoint_monitor(self):
        observed = []
        def service():
            observed.append(True)
        def run(*args, **kwargs):
            deadline = time.monotonic() + 2
            while not observed and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(observed)
            return {"status": "candidate", "summary": "Changed"}
        with patch("optimizer.agent.run_external", side_effect=run):
            agent.optimize(self.workspace, self.context, self.destination, agent="claude", checkpoint_handler=service)

    def test_full_history_summary_and_effective_target_are_in_actual_prompt(self):
        (self.context / "history").mkdir()
        (self.context / "history/summary.md").write_text("candidate-001: indexing +12%, audit unresolved")
        (self.context / "objective.json").write_text('{"library_reduction_target_percent":35,"optimizer_stretch_target":{"time_reduction_percent":45}}')
        with patch("optimizer.agent.run_external", return_value={"status": "unchanged", "summary": "None"}) as run:
            agent.optimize(self.workspace, self.context, self.destination, agent="claude")
        rendered = run.call_args.args[4]
        self.assertIn("candidate-001: indexing +12%, audit unresolved", rendered)
        self.assertIn('"library_reduction_target_percent":35', rendered)
        self.assertIn('"optimizer_stretch_target":{"time_reduction_percent":45}', rendered)
        self.assertIn("base-request.json", rendered)

    def test_checkpoint_service_failure_rejects_agent_result(self):
        def broken():
            raise ValueError("Invalid checkpoint")
        with patch("optimizer.agent.run_external", return_value={"status": "candidate", "summary": "Changed"}):
            with self.assertRaisesRegex(ValueError, "Invalid checkpoint"):
                agent.optimize(self.workspace, self.context, self.destination, agent="claude", checkpoint_handler=broken)

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
