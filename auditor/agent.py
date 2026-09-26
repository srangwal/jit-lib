"""The coding agent supplies hypotheses; the controller establishes experimental results."""

import json
import os
from pathlib import Path
import signal
import subprocess

from coding_agents.runtime import check_login, run as run_external

HERE = Path(__file__).resolve().parent


def configuration():
    return json.loads((HERE / "config.json").read_text())


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


def investigate(package, history, destination, *, executable="codex", model=None,
                reasoning_effort=None, timeout=600, agent="codex", base_url=None):
    destination.mkdir(parents=True, exist_ok=False)
    prompt = (HERE / "prompt.md").read_text() + "\n\nController history:\n" + json.dumps(history)
    (destination / "prompt.md").write_text(prompt)
    model = model or configuration()["models"][agent]
    reasoning_effort = reasoning_effort or configuration()["reasoning_effort"]
    if agent != "codex":
        schema = json.loads((HERE / "response.schema.json").read_text())
        return validate_response(run_external(agent, executable, model, reasoning_effort, prompt, schema,
                                              package, destination, timeout=timeout, base_url=base_url))
    response = destination / "response.json"
    argv = [executable, "exec", "--ignore-user-config", "--ignore-rules",
            "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
            "-c", 'approval_policy="never"', "-c", 'web_search="disabled"',
            "--json", "--output-schema", str(HERE / "response.schema.json"),
            "--output-last-message", str(response), "-C", str(package), "-"]
    argv[2:2] = ["--model", model]
    argv[2:2] = ["-c", "model_reasoning_effort=" + json.dumps(reasoning_effort or configuration()["reasoning_effort"])]
    (destination / "settings.json").write_text(json.dumps({
        "agent": agent, "executable": executable, "model": model, "reasoning_effort": reasoning_effort,
        "timeout_seconds": timeout, "tool_policy": "Codex read-only sandbox"}, indent=2) + "\n")
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
