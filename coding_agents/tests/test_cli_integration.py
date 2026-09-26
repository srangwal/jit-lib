"""Opt-in installed CLI checks using deterministic localhost APIs, never a real model."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from coding_agents.runtime import local_network_policy, run


class LocalAPI(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        claude = self.server.agent == 'claude'
        names = [tool['name'] if claude else tool['function']['name'] for tool in body.get('tools', [])]
        self.server.calls.append({'path': self.path, 'model': body.get('model'), 'tools': names})
        if 'count_tokens' in self.path:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"input_tokens":10}')
            return
        history = json.dumps(body.get('messages', []))
        tool_name = 'mcp__jit__shell' if claude else 'jit_shell'
        tool = tool_name in names and 'call_shell' not in history
        structured = claude and not tool and 'StructuredOutput' in names and 'call_output' not in history
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream' if body.get('stream') else 'application/json')
        self.end_headers()
        if claude:
            content = ({'type': 'tool_use', 'id': 'call_shell', 'name': tool_name,
                        'input': {'command': self.server.command, 'timeout': 5}} if tool else
                       {'type': 'tool_use', 'id': 'call_output', 'name': 'StructuredOutput',
                        'input': {'status': 'ok'}} if structured else
                       {'type': 'text', 'text': '{"status":"ok"}'})
            reason = 'tool_use' if tool or structured else 'end_turn'
            message = {'id': 'msg_test', 'type': 'message', 'role': 'assistant', 'model': body['model'],
                       'content': [content], 'stop_reason': reason, 'stop_sequence': None,
                       'usage': {'input_tokens': 10, 'output_tokens': 10}}
            if not body.get('stream'):
                self.wfile.write(json.dumps(message).encode())
                return
            start = {**message, 'content': [], 'stop_reason': None}
            block = {**content, 'input': {}} if tool or structured else {'type': 'text', 'text': ''}
            delta = ({'type': 'input_json_delta', 'partial_json': json.dumps(content['input'])}
                     if tool or structured else {'type': 'text_delta', 'text': content['text']})
            events = [
                {'type': 'message_start', 'message': start},
                {'type': 'content_block_start', 'index': 0, 'content_block': block},
                {'type': 'content_block_delta', 'index': 0, 'delta': delta},
                {'type': 'content_block_stop', 'index': 0},
                {'type': 'message_delta', 'delta': {'stop_reason': reason, 'stop_sequence': None},
                 'usage': {'output_tokens': 10}}, {'type': 'message_stop'}]
            for event in events:
                self.wfile.write(('event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n').encode())
        else:
            delta = ({'tool_calls': [{'index': 0, 'id': 'call_shell', 'type': 'function',
                        'function': {'name': tool_name, 'arguments': json.dumps({'command': self.server.command, 'timeout': 5})}}]}
                     if tool else {'content': '{"status":"ok"}'})
            for item in ({'delta': delta, 'finish_reason': None},
                         {'delta': {}, 'finish_reason': 'tool_calls' if tool else 'stop'}):
                event = {'id': 'chat_test', 'object': 'chat.completion.chunk', 'model': body['model'],
                         'choices': [{'index': 0, **item}]}
                self.wfile.write(('data: ' + json.dumps(event) + '\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
        self.wfile.flush()


@unittest.skipUnless(os.environ.get('JIT_LIB_CLI_TESTS') == '1' and sys.platform == 'darwin',
                     'Opt-in installed CLI checks on macOS; no real model calls')
class InstalledCLITests(unittest.TestCase):
    def test_opencode_network_policy_allows_only_selected_port(self):
        with tempfile.TemporaryDirectory() as temporary, socket.socket() as allowed, socket.socket() as forbidden:
            allowed.bind(('127.0.0.1', 0))
            forbidden.bind(('127.0.0.1', 0))
            allowed.listen(1)
            forbidden.listen(1)
            port, other_port = allowed.getsockname()[1], forbidden.getsockname()[1]
            policy = local_network_policy(Path(temporary), None, f'http://127.0.0.1:{port}/v1')
            code = '''import errno,socket,sys
socket.create_connection(('127.0.0.1',int(sys.argv[1])),timeout=2).close()
try:
    socket.create_connection(('127.0.0.1',int(sys.argv[2])),timeout=2).close()
except PermissionError:
    sys.exit(0)
sys.exit(1)
'''
            result = subprocess.run(['/usr/bin/sandbox-exec', '-p', policy, sys.executable, '-c', code,
                                     str(port), str(other_port)], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)

    def exercise(self, agent):
        executable = shutil.which(agent)
        if not executable:
            self.skipTest(f'{agent} is not installed')
        for writable in (True, False):
            with self.subTest(writable=writable), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                workspace, context, output = root / 'workspace', root / 'context', root / 'output'
                for path in (workspace, context, output, workspace / 'tmp'):
                    path.mkdir()
                protected = context / 'keep'
                protected.write_text('protected')
                server = ThreadingHTTPServer(('127.0.0.1', 0), LocalAPI)
                server.agent, server.calls = agent, []
                server.command = ('printf checked > marker; ' if writable else '') + (
                    f'if printf tampered > {shlex.quote(str(protected))}; then exit 9; fi; cat {shlex.quote(str(protected))}')
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                url = f'http://127.0.0.1:{server.server_port}'
                overrides = {'ANTHROPIC_API_KEY': 'local-test-no-account', 'ANTHROPIC_BASE_URL': url,
                             'ANTHROPIC_AUTH_TOKEN': '', 'CLAUDE_CODE_USE_BEDROCK': '0',
                             'CLAUDE_CODE_USE_VERTEX': '0', 'CLAUDE_CODE_USE_FOUNDRY': '0', 'NO_PROXY': '*'}
                try:
                    with patch.dict(os.environ, overrides):
                        result = run(agent, executable, 'claude-opus-5' if agent == 'claude' else 'fake-local',
                            'medium', 'Use the shell tool, then return the requested JSON.',
                            {'type': 'object', 'properties': {'status': {'type': 'string'}},
                             'required': ['status'], 'additionalProperties': False},
                            workspace if writable else context, output,
                            workspace=workspace if writable else None, timeout=30,
                            base_url=url + '/v1' if agent == 'opencode' else None)
                    self.assertEqual(result, {'status': 'ok'})
                    self.assertEqual(protected.read_text(), 'protected')
                    if writable:
                        self.assertEqual((workspace / 'marker').read_text(), 'checked')
                    self.assertGreaterEqual(len(server.calls), 2)
                    allowed = {'StructuredOutput', 'mcp__jit__shell'} if agent == 'claude' else {'jit_shell'}
                    self.assertTrue(all(set(call['tools']) <= allowed for call in server.calls))
                    events = (output / 'events.jsonl').read_text()
                    self.assertIn('Operation not permitted', events)
                    settings = json.loads((output / 'settings.json').read_text())
                    if agent == 'claude':
                        self.assertTrue(settings['reported_models'])
                except Exception:
                    print((output / 'stderr.log').read_text() if (output / 'stderr.log').exists() else 'CLI never started')
                    raise
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)

    def test_installed_opencode(self):
        self.exercise('opencode')

    def test_installed_claude(self):
        self.exercise('claude')
