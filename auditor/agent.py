"""Codex supplies hypotheses; the controller establishes experimental results."""

import json
import os
from pathlib import Path
import signal
import subprocess

HERE = Path(__file__).resolve().parent


def validate_response(value, schema=None):
    """Validate the small JSON-schema subset used by our response contract."""
    schema = schema or json.loads((HERE / "response.schema.json").read_text())
    kind = schema["type"]
    expected = {"object": dict, "array": list, "string": str}[kind]
    if not isinstance(value, expected):
        raise ValueError(f"Expected {kind} in agent response")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"Unsupported agent response value: {value}")
    if kind == "object":
        if set(value) != set(schema["properties"]):
            raise ValueError("Missing or unexpected agent response fields")
        for key, item in value.items():
            validate_response(item, schema["properties"][key])
    elif kind == "array":
        for item in value:
            validate_response(item, schema["items"])
    return value


def check_login(executable):
    result = subprocess.run([executable, "login", "status"], capture_output=True,
                            text=True, timeout=30)
    if result.returncode:
        raise RuntimeError("Codex authentication is required. Run `codex login`, then retry. "
                           + result.stderr.strip())


def investigate(package, history, destination, *, executable="codex", model=None, timeout=600):
    destination.mkdir(parents=True, exist_ok=False)
    prompt = (HERE / "prompt.md").read_text() + "\n\nController history:\n" + json.dumps(history)
    (destination / "prompt.md").write_text(prompt)
    response = destination / "response.json"
    argv = [executable, "exec", "--ignore-user-config", "--ignore-rules",
            "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
            "-c", 'approval_policy="never"', "-c", 'web_search="disabled"',
            "--json", "--output-schema", str(HERE / "response.schema.json"),
            "--output-last-message", str(response), "-C", str(package), "-"]
    if model:
        argv[2:2] = ["--model", model]
    (destination / "command.json").write_text(json.dumps(argv, indent=2) + "\n")
    with (destination / "events.jsonl").open("wb") as stdout, (destination / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                                   start_new_session=True)
        try:
            process.communicate(prompt.encode(), timeout=timeout)
        except BaseException:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise
    if process.returncode:
        raise RuntimeError(f"Codex exited {process.returncode}; see {destination / 'stderr.log'}")
    if not response.is_file():
        raise RuntimeError("Codex did not produce a structured response")
    return validate_response(json.loads(response.read_text()))
