import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from coding_agents import tools


class ShellToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        (self.workspace / "tmp").mkdir()
        self.context = self.root / "context"
        self.context.mkdir()
        self.shell = tools.ShellTools(self.workspace, self.workspace)

    def execute_without_sandbox(self, command, **kwargs):
        """Exercise stream/deadline mechanics only; native policy has its own test."""
        popen = subprocess.Popen
        def launch(argv, **options):
            if argv[0] == "/usr/bin/sandbox-exec":
                self.assertEqual(argv[:2], ["/usr/bin/sandbox-exec", "-p"])
                argv = argv[3:]
            return popen(argv, **options)
        with patch.object(tools.subprocess, "Popen", side_effect=launch):
            return self.shell.execute(command, **kwargs)

    def test_profile_denies_network_and_writes_outside_explicit_roots(self):
        profile = tools.sandbox_profile(self.workspace)
        self.assertIn("(deny network*)", profile)
        self.assertIn('(literal "/dev/null")', profile)
        self.assertIn('(subpath ' + json.dumps(str(self.workspace)) + ')', profile)
        self.assertNotIn(str(self.context), profile)
        self.assertNotIn('(subpath "/tmp")', profile)

    def test_auditor_has_only_explicit_scratch_write_root(self):
        shell = tools.ShellTools(self.context, scratch=self.workspace / "tmp")
        self.assertEqual(shell.environment["TMPDIR"], str(self.workspace / "tmp"))
        self.assertIn(json.dumps(str(self.workspace / "tmp")), shell.profile)
        self.assertNotIn(json.dumps(str(self.context)), shell.profile)

    def test_rejects_write_root_containing_server(self):
        with self.assertRaisesRegex(ValueError, "server source"):
            tools.sandbox_profile(Path(tools.__file__).parent)

    def test_rejects_symlink_tmp_escape(self):
        (self.workspace / "tmp").rmdir()
        (self.workspace / "tmp").symlink_to(self.context, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "escapes"):
            tools.ShellTools(self.workspace, self.workspace)

    def test_environment_drops_inherited_tokens_and_accepts_trusted_build_values(self):
        with patch.dict(os.environ, {"API_KEY": "secret", "ANTHROPIC_API_KEY": "secret",
                                     "CARGO_NET_OFFLINE": "false", "PATH": "/bin"}):
            shell = tools.ShellTools(self.workspace, self.workspace,
                                     environment={"CARGO_NET_OFFLINE": "true"})
        self.assertNotIn("API_KEY", shell.environment)
        self.assertNotIn("ANTHROPIC_API_KEY", shell.environment)
        self.assertEqual(shell.environment["CARGO_NET_OFFLINE"], "true")
        self.assertEqual(shell.environment["PATH"], "/bin")
        self.assertEqual(shell.environment["TMPDIR"], str(self.workspace / "tmp"))

    def test_rejects_invalid_environment(self):
        for environment in ([], {"PATH": 5}):
            with self.assertRaises(ValueError):
                tools.ShellTools(self.context, environment=environment)

    def test_rejects_invalid_commands_and_deadlines_before_execution(self):
        for command in (None, "", "  ", "a\0b"):
            with self.assertRaises(ValueError):
                self.shell.execute(command)
        for timeout in (True, 0, -1, 61, float("nan"), float("inf"), "60"):
            with self.assertRaises(ValueError):
                self.shell.execute("true", timeout)

    def test_output_and_exit_code_preserved(self):
        result = self.execute_without_sandbox("printf hello; printf problem >&2; exit 7")
        self.assertEqual(result, {"stdout": "hello", "stderr": "problem", "exit_code": 7,
                                  "timed_out": False, "output_truncated": False})

    def test_output_is_bounded_and_fully_drained(self):
        command = shlex.join([sys.executable, "-c", "import sys;sys.stdout.write('x'*200000);sys.stderr.write('y'*200000)"])
        result = self.execute_without_sandbox(command)
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(result["output_truncated"])
        self.assertEqual(len(result["stdout"]) + len(result["stderr"]), tools.MAX_OUTPUT)

    def test_timeout_kills_shell_process_group(self):
        result = self.execute_without_sandbox("sleep 10", timeout=0.1)
        self.assertTrue(result["timed_out"])
        self.assertNotEqual(result["exit_code"], 0)

    def test_background_child_does_not_hold_output_open(self):
        result = self.execute_without_sandbox("sleep 10 & printf done", timeout=3)
        self.assertFalse(result["timed_out"])
        self.assertEqual(result["stdout"], "done")

    def test_mcp_lists_exactly_one_tool(self):
        result = tools.dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, self.shell)
        self.assertEqual([tool["name"] for tool in result["result"]["tools"]], ["shell"])

    def test_mcp_initialization_ping_and_notifications(self):
        for method in ("initialize", "ping"):
            response = tools.dispatch({"jsonrpc": "2.0", "id": 3, "method": method}, self.shell)
            self.assertEqual(response["id"], 3)
            self.assertIn("result", response)
        self.assertIsNone(tools.dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"}, self.shell))

    def test_mcp_call_failure_is_tool_error(self):
        shell = Mock()
        shell.execute.return_value = {"exit_code": 1, "timed_out": False, "stdout": "", "stderr": "denied"}
        request = {"jsonrpc": "2.0", "id": "call", "method": "tools/call",
                   "params": {"name": "shell", "arguments": {"command": "false"}}}
        response = tools.dispatch(request, shell)
        self.assertTrue(response["result"]["isError"])
        self.assertEqual(json.loads(response["result"]["content"][0]["text"])["stderr"], "denied")
        shell.execute.assert_called_once_with(command="false")

    def test_mcp_rejects_tool_and_argument_injection(self):
        for params in ({"name": "read"}, {"name": "shell", "arguments": {"command": "true", "cwd": "/"}},
                       {"name": "shell", "arguments": []}, {"name": "shell", "arguments": {}}, None):
            response = tools.dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}, self.shell)
            self.assertTrue(response["result"]["isError"])

    def test_stdio_emits_only_jsonrpc(self):
        requests = '\n'.join([json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
                              json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                              'malformed', json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})])
        result = subprocess.run([sys.executable, str(Path(tools.__file__)), "--cwd", str(self.context)],
                                input=requests, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(responses), 3)
        self.assertEqual(responses[1]["error"]["code"], -32700)
        self.assertEqual(responses[2]["id"], 2)

    def bridge_server(self):
        # macOS Unix socket paths are limited to roughly 104 bytes.
        directory = tempfile.TemporaryDirectory(prefix="jit-mcp-", dir="/tmp")
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "socket"
        process = subprocess.Popen([sys.executable, str(Path(tools.__file__)), "--listen", str(path),
                                    "--cwd", str(self.context)], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.PIPE)
        def cleanup():
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=3)
            process.stderr.close()
        self.addCleanup(cleanup)
        for _ in range(100):
            if path.exists():
                return process, path
            if process.poll() is not None:
                self.fail(process.stderr.read().decode())
            time.sleep(0.02)
        self.fail("MCP socket server did not become ready")

    def test_socket_proxy_preserves_messages_across_chunk_boundaries(self):
        server, path = self.bridge_server()
        request = {"jsonrpc": "2.0", "id": "x" * 100000, "method": "tools/list"}
        result = subprocess.run([sys.executable, str(Path(tools.__file__)), "--connect", str(path)],
                                input=json.dumps(request) + "\n", text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertEqual(response["id"], request["id"])
        self.assertEqual(response["result"]["tools"][0]["name"], "shell")
        self.assertEqual(server.wait(timeout=3), 0)
        self.assertFalse(path.exists())

    def test_socket_proxy_exits_when_server_closes_with_stdin_still_open(self):
        server, path = self.bridge_server()
        proxy = subprocess.Popen([sys.executable, str(Path(tools.__file__)), "--connect", str(path)],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            proxy.stdin.write(b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n')
            proxy.stdin.flush()
            self.assertEqual(json.loads(proxy.stdout.readline())["result"], {})
            server.terminate()
            server.wait(timeout=3)
            self.assertEqual(proxy.wait(timeout=3), 0)
        finally:
            if proxy.poll() is None:
                proxy.kill()
            proxy.wait(timeout=3)
            proxy.stdin.close()
            proxy.stdout.close()
            proxy.stderr.close()

    def test_socket_listener_refuses_existing_file(self):
        path = self.root / "existing"
        path.write_text("keep")
        with self.assertRaisesRegex(ValueError, "existing"):
            tools.listen(path, self.shell)
        self.assertEqual(path.read_text(), "keep")

    def test_proxy_rejects_execution_configuration(self):
        result = subprocess.run([sys.executable, str(Path(tools.__file__)), "--connect", str(self.root / "socket"),
                                 "--cwd", str(self.context)], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertIn("no execution settings", result.stderr)

    @unittest.skipUnless(os.environ.get("JIT_LIB_NATIVE_SANDBOX_TESTS") == "1", "Opt-in native macOS sandbox probe")
    def test_native_write_and_network_boundary(self):
        outcomes = tools.probe(self.workspace, self.context, self.root / "evidence")
        self.assertTrue(outcomes["workspace"])
        self.assertFalse(any(value for key, value in outcomes.items() if key != "workspace"))


if __name__ == "__main__":
    unittest.main()
