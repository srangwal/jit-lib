"""One local MCP shell tool; every command runs inside a macOS write boundary."""

import argparse
import json
import math
import os
from pathlib import Path
import selectors
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid


MAX_OUTPUT = 64_000
MAX_TIMEOUT = 60
SHELL_TOOL = {
    "name": "shell",
    "description": "Run a shell command with network disabled. Only the configured private workspace/scratch is writable. Output is bounded; commands time out after at most 60 seconds.",
    "inputSchema": {"type": "object", "properties": {
        "command": {"type": "string", "minLength": 1},
        "timeout": {"type": "number", "exclusiveMinimum": 0, "maximum": MAX_TIMEOUT},
    }, "required": ["command"], "additionalProperties": False},
}


def _directory(path):
    path = Path(path).resolve(strict=True)
    if not path.is_dir():
        raise ValueError(f"Expected a directory: {path}")
    return path


def sandbox_profile(workspace=None, scratch=None):
    """Allow reads and subprocesses, but restrict writes and deny all networking."""
    roots = [_directory(path) for path in (workspace, scratch) if path is not None]
    if any(Path(__file__).resolve().is_relative_to(root) for root in roots):
        raise ValueError("Writable directories must not contain the MCP server source")
    allowed = ' '.join(f'(subpath {json.dumps(str(root))})' for root in roots)
    return ('(version 1)(allow default)(deny network*)'
            '(deny file-write* (require-not (require-any '
            f'(literal "/dev/null") {allowed})))')


def _descendants(parent):
    result = subprocess.run(["/bin/ps", "-axo", "pid=,ppid="], capture_output=True,
                            text=True, timeout=2)
    if result.returncode:
        return set()
    rows = [tuple(map(int, line.split())) for line in result.stdout.splitlines()]
    found = {parent}
    while True:
        expanded = found | {pid for pid, ppid in rows if ppid in found}
        if expanded == found:
            return found - {parent}
        found = expanded


def _stop(process, children):
    for pid in children:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        # macOS can return EPERM for the vanished group of an exited process.
        # Do not suppress a genuine failure to terminate a live process.
        if process.poll() is None:
            raise
    process.wait()


class ShellTools:
    def __init__(self, cwd, workspace=None, scratch=None, environment=None):
        self.cwd = _directory(cwd)
        self.workspace = _directory(workspace) if workspace is not None else None
        self.scratch = _directory(scratch) if scratch is not None else None
        self.profile = sandbox_profile(self.workspace, self.scratch)
        self.environment = {key: value for key, value in os.environ.items()
                            if key in {"PATH", "HOME", "RUSTUP_HOME", "SYSTEMROOT", "LANG", "LC_ALL"}}
        if environment is not None:
            if not isinstance(environment, dict):
                raise ValueError("Environment must map strings to strings")
            self.environment.update(environment)
        if any(not isinstance(k, str) or not isinstance(v, str) for k, v in self.environment.items()):
            raise ValueError("Environment must map strings to strings")
        temp = self.workspace / "tmp" if self.workspace else self.scratch
        if temp is not None:
            temp = _directory(temp)
            if self.workspace and not temp.is_relative_to(self.workspace):
                raise ValueError("Workspace tmp directory escapes the write boundary")
            self.environment.update({key: str(temp) for key in ("TMPDIR", "TMP", "TEMP")})

    def execute(self, command, timeout=MAX_TIMEOUT):
        if not isinstance(command, str) or not command.strip() or "\0" in command:
            raise ValueError("command must be a nonempty string without NUL bytes")
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or
                not math.isfinite(timeout) or not 0 < timeout <= MAX_TIMEOUT):
            raise ValueError("timeout must be greater than zero and at most 60 seconds")
        argv = ["/usr/bin/sandbox-exec", "-p", self.profile, "/bin/sh", "-c", command]
        process = subprocess.Popen(argv, cwd=self.cwd, env=self.environment, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        streams = {"stdout": bytearray(), "stderr": bytearray()}
        total = 0
        truncated = False
        timed_out = False
        children = set()
        stopped = False
        deadline = time.monotonic() + timeout
        next_scan = 0
        selector = selectors.DefaultSelector()
        try:
            for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map() or process.poll() is None:
                now = time.monotonic()
                if now >= deadline:
                    timed_out = True
                    break
                if now >= next_scan and process.poll() is None:
                    try:
                        children.update(_descendants(process.pid))
                    except (OSError, ValueError, subprocess.SubprocessError):
                        pass
                    next_scan = time.monotonic() + 0.1
                if process.poll() is not None and not stopped:
                    # Background children must not keep inherited output pipes alive.
                    _stop(process, children)
                    stopped = True
                    children.clear()
                for key, _ in selector.select(min(0.1, max(0, deadline - time.monotonic()))):
                    data = os.read(key.fd, 8192)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    remaining = max(0, MAX_OUTPUT - total)
                    streams[key.data].extend(data[:remaining])
                    total += min(len(data), remaining)
                    truncated |= len(data) > remaining
        finally:
            if not stopped:
                _stop(process, children)
            selector.close()
            process.stdout.close()
            process.stderr.close()
        return {"exit_code": process.returncode, "timed_out": timed_out,
                "output_truncated": truncated,
                **{name: data.decode(errors="replace") for name, data in streams.items()}}


def dispatch(request, shell):
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
    if "id" not in request:
        return None
    response = {"jsonrpc": "2.0", "id": request["id"]}
    method = request.get("method")
    params = request.get("params", {})
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "jit-lib-shell", "version": "1.0.0"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [SHELL_TOOL]}
    elif method == "tools/call":
        try:
            if not isinstance(params, dict) or params.get("name") != "shell":
                raise ValueError("Only the shell tool is supported")
            arguments = params.get("arguments", {})
            if not isinstance(arguments, dict) or set(arguments) - {"command", "timeout"}:
                raise ValueError("Only command and timeout arguments are supported")
            outcome = shell.execute(**arguments)
            result = {"content": [{"type": "text", "text": json.dumps(outcome)}],
                      "isError": outcome["exit_code"] != 0 or outcome["timed_out"]}
        except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
            result = {"content": [{"type": "text", "text": str(error)}], "isError": True}
    else:
        response["error"] = {"code": -32601, "message": "Method not found"}
        return response
    response["result"] = result
    return response


def probe(workspace, context, destination):
    """Verify the actual write/network boundary without a model or agent CLI."""
    workspace, context = _directory(workspace), _directory(context)
    destination = Path(destination).resolve()
    if any(p.is_relative_to(workspace) or workspace.is_relative_to(p) for p in (context, destination)):
        raise ValueError("Context and evidence must not overlap the workspace")
    destination.mkdir(parents=True, exist_ok=False)
    name = ".shell-boundary-" + uuid.uuid4().hex
    paths = {"workspace": workspace / "tmp" / name, "context": context / name,
             "parent": workspace.parent / name, "records": destination / name,
             "slash_tmp": Path("/tmp") / name}
    shell = ShellTools(workspace, workspace)
    (destination / "sandbox.sb").write_text(shell.profile)
    listener = socket.socket()
    try:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        script = '''import json,sys,socket
from pathlib import Path
result={}
for label,path in json.loads(sys.argv[1]).items():
    try:
        Path(path).write_text("boundary probe")
        result[label]=True
    except OSError:
        result[label]=False
try:
    socket.create_connection(("127.0.0.1",int(sys.argv[2])),timeout=2).close()
    result["network"]=True
except OSError:
    result["network"]=False
print(json.dumps(result))
'''
        command = shlex.join([sys.executable, "-c", script,
                              json.dumps({key: str(path) for key, path in paths.items()}),
                              str(listener.getsockname()[1])])
        result = shell.execute(command, timeout=10)
        (destination / "execution.json").write_text(json.dumps(result, indent=2) + "\n")
        if result["exit_code"] or result["timed_out"]:
            raise RuntimeError(f"Shell sandbox boundary probe failed; see {destination}")
        outcomes = json.loads(result["stdout"])
        (destination / "result.json").write_text(json.dumps(outcomes, indent=2) + "\n")
        if outcomes != {**{key: key == "workspace" for key in paths}, "network": False}:
            raise RuntimeError(f"Unexpected shell sandbox permissions: {outcomes}")
        return outcomes
    finally:
        listener.close()
        for path in paths.values():
            path.unlink(missing_ok=True)


def serve(input_stream, output_stream, shell):
    for line in input_stream:
        try:
            response = dispatch(json.loads(line), shell)
        except (ValueError, TypeError):
            response = {"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32700, "message": "Parse error"}}
        if response is not None:
            output_stream.write(json.dumps(response) + "\n")
            output_stream.flush()


def proxy(path):
    """Relay stdio over one local socket without interpreting MCP messages."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(str(path))
        def upload():
            try:
                while data := os.read(sys.stdin.fileno(), 32768):
                    connection.sendall(data)
            except OSError:
                pass
            finally:
                try:
                    connection.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
        # stdin may stay open after the server exits; never wait for this reader.
        threading.Thread(target=upload, daemon=True).start()
        while data := connection.recv(32768):
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()


def listen(path, shell):
    """Accept exactly one MCP client; the trusted server stays outside CLI isolation."""
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise ValueError("Refusing to replace an existing socket path")
    bound = False
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        try:
            listener.bind(str(path))
            bound = True
            path.chmod(0o600)
            listener.listen(1)
            connection, _ = listener.accept()
            with connection, connection.makefile("r", encoding="utf-8") as source, \
                    connection.makefile("w", encoding="utf-8") as sink:
                serve(source, sink, shell)
        finally:
            if bound:
                path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd")
    parser.add_argument("--workspace")
    parser.add_argument("--scratch")
    parser.add_argument("--environment", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--listen", type=Path, help="Serve one MCP client on a local Unix socket")
    mode.add_argument("--connect", type=Path, help="Relay MCP stdio to an existing local Unix socket")
    args = parser.parse_args()
    def interrupted(signum, frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    if args.connect:
        if any((args.cwd, args.workspace, args.scratch, args.environment)):
            parser.error("--connect accepts no execution settings")
        proxy(args.connect)
        return
    if not args.cwd:
        parser.error("--cwd is required when serving tools")
    environment = json.loads(args.environment.read_text()) if args.environment else None
    shell = ShellTools(args.cwd, args.workspace, args.scratch, environment)
    if args.listen:
        listen(args.listen, shell)
    else:
        serve(sys.stdin, sys.stdout, shell)


if __name__ == "__main__":
    main()
