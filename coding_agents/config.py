"""Resolve explicit runtime settings before starting an attempt."""

from urllib.parse import urlsplit
from pathlib import Path
import shutil

AGENTS = ("codex", "claude", "opencode")
EXECUTABLES = {"codex": "codex", "claude": "claude", "opencode": "opencode"}


def local_url(value):
    parsed = urlsplit(value or "")
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or not parsed.port or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("OpenCode requires --local-base-url http://127.0.0.1:PORT/v1 (loopback only)")
    # Avoid DNS and IPv4/IPv6 ambiguity for the localhost spelling.
    host = "[::1]" if parsed.hostname == "::1" else "127.0.0.1"
    return f"http://{host}:{parsed.port}{parsed.path.rstrip('/')}"


def resolve(defaults, agent=None, model=None, base_url=None):
    agent = agent or defaults.get("agent", "codex")
    if agent not in AGENTS:
        raise ValueError(f"Unknown coding agent: {agent}")
    model = model if model is not None else defaults["models"].get(agent)
    if not isinstance(model, str) or not model.strip():
        raise ValueError(f"An explicit --model is required for {agent}")
    if model != model.strip() or any(character in model for character in "\r\n\x00{}"):
        raise ValueError("Invalid model identifier")
    endpoint = base_url if base_url is not None else defaults.get("local_base_url")
    if agent == "opencode":
        endpoint = local_url(endpoint)
    elif base_url is not None:
        raise ValueError("--local-base-url applies only to OpenCode")
    else:
        endpoint = None
    return {"agent": agent, "model": model, "local_base_url": endpoint}


def add_arguments(parser, defaults):
    parser.add_argument("--agent", choices=AGENTS, default=defaults.get("agent", "codex"))
    parser.add_argument("--agent-executable", help="Override the selected CLI executable")
    parser.add_argument("--model", help="Model identifier; defaults are in the component config.json")
    parser.add_argument("--local-base-url", help="OpenCode only: local OpenAI-compatible server URL")


def apply_arguments(parser, args, defaults):
    try:
        values = resolve(defaults, args.agent, args.model, args.local_base_url)
    except ValueError as error:
        parser.error(str(error))
    for key, value in values.items():
        setattr(args, key, value)


def snapshot(destination):
    """Retain the shared adapter source alongside each component's evidence."""
    from evaluator.core import evaluator_fingerprint
    source = Path(__file__).resolve().parent
    version = evaluator_fingerprint(source)
    for name in version["files"]:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target)
    if evaluator_fingerprint(destination) != version:
        raise ValueError("Coding-agent adapter changed during source capture")
    return version
