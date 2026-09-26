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

from coding_agents import config, runtime


DEFAULTS = {"agent": "codex", "models": {"codex": "gpt-6-sol", "claude": "sonnet", "opencode": None},
            "local_base_url": "http://127.0.0.1:11434/v1"}


def events(*items):
    return "\n".join(json.dumps(item) for item in items)


class AgentConfigurationTests(unittest.TestCase):
    def test_backend_defaults_and_explicit_override(self):
        self.assertEqual(config.resolve(DEFAULTS), {"agent": "codex", "model": "gpt-6-sol", "local_base_url": None})
        self.assertEqual(config.resolve(DEFAULTS, "claude")["model"], "sonnet")
        self.assertEqual(config.resolve(DEFAULTS, "opencode", "local-code")["local_base_url"],
                         "http://127.0.0.1:11434/v1")
        self.assertEqual(config.resolve(DEFAULTS, "claude", "opus")["model"], "opus")

    def test_local_model_must_be_explicit(self):
        with self.assertRaisesRegex(ValueError, "explicit --model"):
            config.resolve(DEFAULTS, "opencode")

    def test_invalid_model_or_agent_is_rejected(self):
        for model in ("", " padded ", "x\ny", "{env:API_KEY}", "x\0y"):
            with self.assertRaises(ValueError):
                config.resolve(DEFAULTS, "claude", model)
        with self.assertRaises(ValueError):
            config.resolve(DEFAULTS, "other", "model")

    def test_local_endpoint_is_not_accepted_for_cloud_runtimes(self):
        for agent in ("codex", "claude"):
            with self.assertRaisesRegex(ValueError, "only to OpenCode"):
                config.resolve(DEFAULTS, agent, base_url="http://127.0.0.1:11434/v1")

    def test_loopback_url_is_canonicalized(self):
        self.assertEqual(config.local_url("http://localhost:11434/v1/"), "http://127.0.0.1:11434/v1")
        self.assertEqual(config.local_url("http://[::1]:8000/v1"), "http://[::1]:8000/v1")

    def test_rejects_remote_ambiguous_authenticated_and_malformed_urls(self):
        for url in (None, "https://127.0.0.1:8000/v1", "http://example.com:8000/v1", "http://0.0.0.0:8000/v1",
                    "http://127.0.0.2:8000/v1", "http://127.0.0.1/v1", "http://localhost:0/v1",
                    "http://localhost:99999/v1", "http://localhost:bad/v1", "http://user:pass@localhost:8000/v1",
                    "http://localhost:8000/v1?url=https://elsewhere", "http://localhost:8000/v1#ignored",
                    "file:///tmp/model", "http://localhost.evil:8000/v1"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                config.local_url(url)

    def test_opencode_disables_cloud_and_native_tools(self):
        command = [sys.executable, "tools.py"]
        actual = runtime.opencode_configuration("local-code", "http://localhost:11434/v1", command)
        self.assertEqual(actual["enabled_providers"], ["jit-local"])
        self.assertEqual(actual["model"], "jit-local/local-code")
        self.assertEqual(actual["small_model"], actual["model"])
        self.assertEqual(actual["provider"]["jit-local"]["options"]["baseURL"], "http://127.0.0.1:11434/v1")
        self.assertEqual(actual["tools"], {"*": False, "jit_shell": True})
        self.assertEqual(actual["permission"], {"*": "deny", "jit_shell": "allow"})
        self.assertEqual(actual["mcp"]["jit"]["command"], command)
        self.assertFalse(actual["autoupdate"])
        self.assertFalse(actual["lsp"])
        self.assertEqual(actual["plugin"], [])

    def test_policy_permits_only_selected_loopback_port_and_private_writes(self):
        profile = runtime.local_network_policy(Path("/tmp/runtime-state"), Path("/tmp/workspace"),
                                               "http://localhost:11434/v1")
        self.assertIn("(deny network*)", profile)
        self.assertIn('(remote ip "localhost:11434")', profile)
        self.assertIn("(deny file-write*)", profile)
        self.assertIn(str(Path("/tmp/workspace").resolve()), profile)
        self.assertNotIn('remote ip "*', profile)


class AgentResponseTests(unittest.TestCase):
    def test_claude_structured_response(self):
        stream = events({"type": "system"}, {"type": "result", "subtype": "success",
                                             "is_error": False, "structured_output": {"status": "candidate"}})
        self.assertEqual(runtime.parse_response("claude", stream), {"status": "candidate"})

    def test_claude_fails_closed_on_error_missing_or_duplicate_result(self):
        success = {"type": "result", "subtype": "success", "structured_output": {"ok": True}}
        for stream in ("", "not JSON", "[]", events({"type": "assistant"}), events(success, success),
                       events({**success, "is_error": True}), events({**success, "subtype": "error_max_turns"}),
                       events({**success, "structured_output": "{}"})):
            with self.subTest(stream=stream), self.assertRaises(ValueError):
                runtime.parse_response("claude", stream)

    def test_opencode_uses_last_completed_step(self):
        stream = events({"type": "step_start"}, {"type": "text", "part": {"text": "Working..."}},
                        {"type": "step_finish", "part": {"reason": "tool-calls"}},
                        {"type": "step_start"}, {"type": "text", "part": {"text": '{"status":'}},
                        {"type": "text", "part": {"text": '"candidate"}'}},
                        {"type": "step_finish", "part": {"reason": "stop"}})
        self.assertEqual(runtime.parse_response("opencode", stream), {"status": "candidate"})

    def test_opencode_errors_incomplete_turns_and_markdown_fail_closed(self):
        text = {"type": "text", "part": {"text": "{}"}}
        stop = {"type": "step_finish", "part": {"reason": "stop"}}
        for stream in (events(text), events(stop), events(text, {"type": "error"}, stop),
                       events(text, {"type": "step_finish", "part": {"reason": "length"}}),
                       events({"type": "text", "part": {"text": "```json\n{}\n```"}}, stop)):
            with self.subTest(stream=stream), self.assertRaises(ValueError):
                runtime.parse_response("opencode", stream)

    def test_opencode_final_answer_must_be_an_object(self):
        for value in ([], None, "answer", 5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                runtime.parse_response("opencode", events({"type": "text", "part": {"text": json.dumps(value)}},
                                                           {"type": "step_finish", "part": {"reason": "stop"}}))


class RuntimeInvocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        (self.workspace / "tmp").mkdir()
        self.destination = self.root / "evidence"
        self.destination.mkdir()
        self.executable = self.root / "fake-agent"

    def executable_code(self, source):
        self.executable.write_text(f"#!{sys.executable}\n" + source)
        self.executable.chmod(0o700)
        return str(self.executable)

    def run_claude(self, source, **kwargs):
        return runtime.run("claude", self.executable_code(source), "sonnet", "medium", "Task instruction",
                           {"type": "object"}, self.workspace, self.destination,
                           workspace=self.workspace, **kwargs)

    def test_claude_flags_prompt_metadata_and_only_sandbox_tool(self):
        response = self.run_claude('''import json,sys,os
assert "Task instruction" in sys.stdin.read()
assert sys.argv[sys.argv.index("--tools")+1] == ""
assert sys.argv[sys.argv.index("--allowedTools")+1] == "mcp__jit__shell"
assert sys.argv[sys.argv.index("--permission-mode")+1] == "dontAsk"
for flag in ("--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence", "--no-chrome"):
    assert flag in sys.argv
assert os.environ["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
print(json.dumps({"type":"result","subtype":"success","structured_output":{"status":"unchanged"}}))
''', environment={"CARGO_NET_OFFLINE": "true"})
        self.assertEqual(response, {"status": "unchanged"})
        metadata = json.loads((self.destination / "settings.json").read_text())
        self.assertEqual(metadata["agent"], "claude")
        self.assertEqual(metadata["model"], "sonnet")
        self.assertEqual(metadata["reasoning_effort"], "medium")
        self.assertFalse(metadata["native_tools"])
        mcp = json.loads((self.destination / "mcp.json").read_text())
        self.assertEqual(set(mcp["mcpServers"]), {"jit"})
        arguments = mcp["mcpServers"]["jit"]["args"]
        self.assertEqual(arguments[arguments.index("--workspace") + 1], str(self.workspace))
        self.assertEqual(json.loads((self.destination / "tool-environment.json").read_text()),
                         {"CARGO_NET_OFFLINE": "true"})
        self.assertEqual(json.loads((self.destination / "response.json").read_text()), response)

    def test_runtime_failure_preserves_logs_and_does_not_create_response(self):
        with self.assertRaisesRegex(RuntimeError, "exited 9"):
            self.run_claude("import sys; print('backend failed', file=sys.stderr); sys.exit(9)")
        self.assertIn("backend failed", (self.destination / "stderr.log").read_text())
        self.assertFalse((self.destination / "response.json").exists())

    def test_timeout_terminates_cli(self):
        pid_file = self.workspace / "pid"
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_claude(f"import os,time\nfrom pathlib import Path\nPath({str(pid_file)!r}).write_text(str(os.getpid()))\ntime.sleep(60)", timeout=1.5)
        pid = int(pid_file.read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.assertFalse((self.destination / "response.json").exists())

    def test_process_inspection_failure_still_cleans_up_cli(self):
        pid_file = self.workspace / "pid"
        def denied(pid):
            time.sleep(0.1)
            raise PermissionError("process inspection denied")
        try:
            with patch.object(runtime, "_descendants", side_effect=denied), \
                    self.assertRaises((OSError, subprocess.TimeoutExpired)):
                self.run_claude(f"import os,time\nfrom pathlib import Path\nPath({str(pid_file)!r}).write_text(str(os.getpid()))\ntime.sleep(60)", timeout=1.5)
            pid = int(pid_file.read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
        finally:
            if pid_file.exists():
                try:
                    os.kill(int(pid_file.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_timeout_terminates_child_in_separate_session(self):
        pid_file = self.workspace / "child-pid"
        child_code = "import time;time.sleep(60)"
        source = f'''import subprocess,sys,time
from pathlib import Path
child=subprocess.Popen([sys.executable,"-c",{child_code!r}],start_new_session=True)
Path({str(pid_file)!r}).write_text(str(child.pid))
time.sleep(60)
'''
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                self.run_claude(source, timeout=1.5)
            pid = int(pid_file.read_text())
            for _ in range(20):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.025)
            else:
                self.fail("Runtime timeout left a separate-session child alive")
        finally:
            if pid_file.exists():
                try:
                    os.kill(int(pid_file.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_opencode_invocation_isolated_provider_and_environment(self):
        executable = self.executable_code('''import json,os,sys
from pathlib import Path
assert "Task instruction" in sys.stdin.read()
assert sys.argv[1:3] == ["run","--pure"]
assert sys.argv[sys.argv.index("--model")+1] == "jit-local/test-model"
assert "OPENAI_API_KEY" not in os.environ
assert "ANTHROPIC_API_KEY" not in os.environ
assert os.environ["OPENCODE_DISABLE_PROJECT_CONFIG"] == "true"
assert os.environ["OPENCODE_DISABLE_MODELS_FETCH"] == "true"
assert Path.cwd().name == "runtime-state"
config=json.loads(os.environ["OPENCODE_CONFIG_CONTENT"])
assert config["enabled_providers"] == ["jit-local"]
print(json.dumps({"type":"step_start"}))
print(json.dumps({"type":"text","part":{"text":"{\\"status\\":\\"unchanged\\"}"}}))
print(json.dumps({"type":"step_finish","part":{"reason":"stop"}}))
''')
        popen = subprocess.Popen
        def sandbox_double(argv, **kwargs):
            if argv[0] == "/usr/bin/sandbox-exec":
                self.assertEqual(argv[:2], ["/usr/bin/sandbox-exec", "-f"])
                self.assertTrue(Path(argv[2]).is_file())
                argv = argv[3:]
            return popen(argv, **kwargs)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret", "ANTHROPIC_API_KEY": "secret"}), \
                patch.object(runtime.subprocess, "Popen", side_effect=sandbox_double):
            result = runtime.run("opencode", executable, "test-model", "medium", "Task instruction",
                                 {"type": "object"}, self.workspace, self.destination,
                                 workspace=self.workspace, base_url="http://127.0.0.1:11434/v1")
        self.assertEqual(result, {"status": "unchanged"})
        metadata = json.loads((self.destination / "settings.json").read_text())
        self.assertEqual(metadata["agent"], "opencode")
        self.assertIsNone(metadata["reasoning_effort"])
        self.assertEqual(metadata["local_base_url"], "http://127.0.0.1:11434/v1")

    def test_login_reports_required_action_and_local_does_not_call_cli(self):
        with patch.object(runtime.subprocess, "run") as run:
            runtime.check_login("missing-opencode", "opencode")
            run.assert_not_called()
            run.return_value = subprocess.CompletedProcess([], 0, '{"loggedIn":false}', "")
            with self.assertRaisesRegex(RuntimeError, "claude auth login"):
                runtime.check_login("claude", "claude")
            run.return_value = subprocess.CompletedProcess([], 1, "", "")
            with self.assertRaisesRegex(RuntimeError, "codex login"):
                runtime.check_login("codex", "codex")


if __name__ == "__main__":
    unittest.main()
