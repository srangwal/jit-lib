"""Run a candidate-editing Codex session; official evaluation stays in the controller."""

import json
import math
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tomllib
import uuid

from auditor.agent import validate_response

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def sandbox_configuration(workspace, reasoning_effort="medium"):
    return {
        "approval_policy": "never", "web_search": "disabled",
        "model_reasoning_effort": reasoning_effort,
        "default_permissions": "optimizer",
        "permissions.optimizer.filesystem": {"/": "read", str(workspace): "write"},
        "permissions.optimizer.network.enabled": False,
        "project_doc_max_bytes": 0, "project_root_markers": [],
        "allow_login_shell": False, "features.shell_snapshot": False,
        "features.apps": False, "features.hooks": False,
        "features.multi_agent": False, "features.remote_plugin": False,
    }


def workspace_environment(workspace):
    scratch = {name: workspace / name for name in ("cargo-home", "target", "tmp")}
    for path in scratch.values():
        if path.is_symlink() or not path.resolve().is_relative_to(workspace):
            raise ValueError(f"Scratch directory escapes the private workspace: {path}")
        path.mkdir(exist_ok=True)
    pin = tomllib.loads((REPO / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    removed_names = {"JIT_LIB_INDEX_TRACE", "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "CC", "CXX", "AR",
                     "RANLIB", "CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS"}
    removed_prefixes = ("MDBOOK_", "RUSTC", "RUSTDOC", "CARGO_BUILD_", "CARGO_TARGET_", "CARGO_HOST_",
                        "CARGO_PROFILE_", "CC_", "CXX_", "CFLAGS_", "CXXFLAGS_")
    env = {key: value for key, value in os.environ.items()
           if key not in removed_names and not key.startswith(removed_prefixes)}
    rustup = shutil.which("rustup", path=env.get("PATH", ""))
    if not rustup:
        raise ValueError("rustup is required for private optimizer builds")
    proxies = Path(rustup).absolute().parent
    if any(not (proxies / name).is_file() or not os.path.samefile(proxies / name, rustup)
           for name in ("cargo", "rustc")):
        raise ValueError("Expected rustup cargo/rustc proxies beside rustup")
    local = {"PATH": str(proxies) + os.pathsep + env.get("PATH", ""),
             "CARGO_HOME": str(scratch["cargo-home"]), "CARGO_TARGET_DIR": str(scratch["target"]),
             "TMPDIR": str(scratch["tmp"]), "TMP": str(scratch["tmp"]), "TEMP": str(scratch["tmp"]),
             "RUSTUP_TOOLCHAIN": pin, "CARGO_NET_OFFLINE": "true"}
    env.update(local)
    return env, local


def config_arguments(configuration):
    def value_toml(value):
        if isinstance(value, dict):
            return "{" + ", ".join(json.dumps(k) + " = " + json.dumps(v) for k, v in value.items()) + "}"
        return json.dumps(value)
    return [argument for key, value in configuration.items() for argument in ("-c", key + "=" + value_toml(value))]


def probe_workspace(workspace, context, destination, *, executable="codex", timeout=30):
    """Execute a real local sandbox probe; never contacts a model or needs login."""
    workspace, context, destination = (Path(p).resolve() for p in (workspace, context, destination))
    if any(p.is_relative_to(workspace) or workspace.is_relative_to(p) for p in (context, destination)):
        raise ValueError("Context and recording directories must not overlap the writable workspace")
    destination.mkdir(parents=True, exist_ok=False)
    env, local = workspace_environment(workspace)
    # `sandbox` lacks exec's --ignore-user-config; a fresh home excludes user config.
    env["CODEX_HOME"] = str(destination / "codex-home")
    Path(env["CODEX_HOME"]).mkdir()
    name = ".optimizer-boundary-" + uuid.uuid4().hex
    paths = {"workspace": workspace / "tmp" / name, "context": context / name,
             "parent": workspace.parent / name, "records": destination / name,
             "slash_tmp": Path("/tmp") / name}
    script = """import json,sys
from pathlib import Path
results={}
for label,name in json.loads(sys.argv[1]).items():
    try:
        Path(name).write_text('optimizer boundary probe')
        results[label]=True
    except OSError:
        results[label]=False
print(json.dumps(results))
sys.exit(0 if results['workspace'] and not any(v for k,v in results.items() if k!='workspace') else 1)
"""
    config = sandbox_configuration(workspace)
    config.update({"shell_environment_policy.set." + key: value for key, value in local.items()})
    argv = [str(executable), "sandbox", "--permission-profile", "optimizer", *config_arguments(config), "-C", str(workspace), "--",
            sys.executable, "-c", script, json.dumps({key: str(path) for key, path in paths.items()})]
    (destination / "command.json").write_text(json.dumps(argv, indent=2) + "\n")
    try:
        with (destination / "stdout.log").open("wb") as stdout, (destination / "stderr.log").open("wb") as stderr:
            result = subprocess.run(argv, cwd=workspace, env=env, stdout=stdout, stderr=stderr, timeout=timeout)
        if result.returncode:
            detail = ((destination / "stderr.log").read_text(errors="replace") +
                      (destination / "stdout.log").read_text(errors="replace"))[-3000:]
            raise RuntimeError(f"Optimizer sandbox boundary probe failed; see {destination}\n{detail}")
        outcomes = json.loads((destination / "stdout.log").read_text())
        if outcomes != {key: key == "workspace" for key in paths}:
            raise RuntimeError(f"Unexpected optimizer sandbox permissions: {outcomes}")
        (destination / "result.json").write_text(json.dumps(outcomes, indent=2) + "\n")
        return outcomes
    finally:
        for path in paths.values():
            path.unlink(missing_ok=True)


def optimize(workspace: Path, context: Path, destination: Path, *, executable="codex",
             model="gpt-6-sol", reasoning_effort="medium", timeout=600) -> dict:
    """Allow tool writes only in the private workspace, with offline local build caches.

    The Codex controller writes its response/logs outside that writable root.
    Sandbox flags are not a claim of protection against deliberately escaping code.
    """
    if not model.strip() or not reasoning_effort.strip():
        raise ValueError("Model and reasoning effort must be explicit nonempty strings")
    if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Agent timeout must be positive and finite")
    workspace, context, destination = (Path(path).resolve() for path in (workspace, context, destination))
    if not workspace.is_dir() or not context.is_dir():
        raise ValueError("Workspace and read-only context must already exist")
    for outside in (context, destination):
        if outside.is_relative_to(workspace) or workspace.is_relative_to(outside):
            raise ValueError("Context and recording directories must not overlap the writable workspace")
    env, local_environment = workspace_environment(workspace)
    destination.mkdir(parents=True, exist_ok=False)
    prompt = (HERE / "prompt.md").read_text() + (
        "\n\nController paths:\nWritable workspace: " + json.dumps(str(workspace))
        + "\nRead-only context: " + json.dumps(str(context)) + "\n"
        + f"Agent time budget: {timeout:g} seconds. Finish and submit within this limit.\n"
    )
    schema = json.loads((HERE / "response.schema.json").read_text())
    (destination / "prompt.md").write_text(prompt)
    schema_path = destination / "response.schema.json"
    schema_path.write_text(json.dumps(schema, indent=2) + "\n")
    response = destination / "response.json"
    configuration = sandbox_configuration(workspace, reasoning_effort)
    argv = [str(executable), "exec", "--model", model, "--ignore-user-config", "--ignore-rules",
            "--skip-git-repo-check", "--ephemeral"]
    argv += config_arguments(configuration)
    # Also set the shell policy explicitly so generated commands inherit these values.
    for key, value in local_environment.items():
        argv += ["-c", "shell_environment_policy.set." + key + "=" + json.dumps(value)]
    argv += ["--json", "--output-schema", str(schema_path), "--output-last-message", str(response),
             "-C", str(workspace), "-"]
    (destination / "command.json").write_text(json.dumps(argv, indent=2) + "\n")
    (destination / "settings.json").write_text(json.dumps({
        "model": model, "reasoning_effort": reasoning_effort, "timeout_seconds": timeout,
        "cwd": str(workspace), "context": str(context), "environment": local_environment,
        "sandbox_configuration": configuration,
    }, indent=2) + "\n")
    with (destination / "events.jsonl").open("wb") as stdout, (destination / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen(argv, cwd=workspace, env=env, stdin=subprocess.PIPE,
                                   stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            process.communicate(prompt.encode(), timeout=timeout)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
    if process.returncode:
        raise RuntimeError(f"Optimizer Codex exited {process.returncode}; see {destination / 'stderr.log'}")
    if not response.is_file():
        raise RuntimeError("Optimizer Codex did not produce a structured response")
    return validate_response(json.loads(response.read_text()), schema)
