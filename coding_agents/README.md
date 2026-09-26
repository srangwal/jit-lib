# Coding agents

The optimizer and auditor can each use **Codex CLI**, **Claude Code**, or
**OpenCode with a locally hosted model**. The controller and evaluator remain
ordinary programs. Changing agents does not change correctness checks,
performance rules, or the auditor's requirement to reproduce a violation.

## Choose an agent

Install the chosen CLI and make it available on `PATH`. Codex needs `codex login`;
Claude needs `claude auth login`. OpenCode needs no cloud login: start your local
OpenAI-compatible model server before running an attempt.

| `--agent` | CLI | Default model |
| --- | --- | --- |
| `codex` | `codex` | `gpt-6-sol` |
| `claude` | `claude` | `sonnet` |
| `opencode` | `opencode` | `qwen3.8:27b-mlx` |

Both components default to Codex. Their `config.json` files define the agent,
model defaults, and local endpoint. Select explicitly for a standalone run:

```sh
python3 optimizer/run.py --baseline .evaluator/runs/<self-check-run-id> \
  --agent claude --model sonnet
python3 auditor/run.py --evaluation .evaluator/runs/<run-id> \
  --agent opencode --model qwen3.8:27b-mlx \
  --local-base-url http://127.0.0.1:11434/v1
```

The URL is a setup default, not an automatically discovered server address.
Change its port/path to match your server. Only HTTP loopback addresses are
accepted (`127.0.0.1`, `localhost`, or `::1`, with an explicit port). The adapter
neither downloads a model nor starts the server. There is no cloud fallback.

Use `--agent-executable /path/to/cli` if the executable is not on `PATH`.
`--model` overrides the selected agent's default. Codex and Claude use medium
reasoning by default; OpenCode has no reasoning-effort setting and records null.
Claude's `sonnet` alias can change with the installed CLI. Use a full model ID to
pin it; `settings.json` also records the model names reported by Claude.

The controller selects the two agents independently:

```sh
python3 controller/run.py --baseline .evaluator/runs/<self-check-run-id> \
  --optimizer-agent opencode --optimizer-model qwen3.8:27b-mlx \
  --auditor-agent claude --auditor-model sonnet \
  --local-base-url http://127.0.0.1:11434/v1
```

A controller `--model` sets both models; component-specific model flags take
precedence. The existing environment checker and cold-setup reproduction command
still check and use Codex. They do not validate alternative agents or local servers.

## Boundaries and records

All runtimes require the project's macOS setup. Codex keeps its native tool
sandbox. Claude and OpenCode receive one MCP shell tool: commands run through
`sandbox-exec`, without network access. Optimizer commands may write only inside
the private workspace; auditor commands may write only private scratch. Reference
sources and evaluation evidence remain protected.

Claude's native tools and user hooks are disabled. OpenCode uses isolated
configuration and state, with its native tools disabled. Its entire CLI is also
restricted to the configured loopback endpoint and writes to private state and
workspace directories. These are operating-system boundaries, not a VM.

Each run records its selected agent, CLI version, model, endpoint when applicable,
and limits. Agent directories retain prompts, effective settings, commands,
event streams, responses, and stderr. `coding-agents-source/` preserves the shared
adapter implementation with recorded hashes. Existing component reports keep
their formats; callers still validate structured responses before using them.

## Code and checks

- `config.py`: validates selections and captures adapter source.
- `runtime.py`: invokes Claude/OpenCode and validates their final event output.
- `tools.py`: provides the sandboxed shell tool and a local boundary probe.

```sh
python3 -m unittest discover -s coding_agents/tests -v
JIT_LIB_NATIVE_SANDBOX_TESTS=1 python3 -m unittest discover -s coding_agents/tests -p test_tools.py -v
JIT_LIB_CLI_TESTS=1 python3 -m unittest discover -s coding_agents/tests -p test_cli_integration.py -v
```

The second command needs native macOS sandbox execution. Ordinary tests use
controlled responses and do not call a model. Passing adapter tests does not
establish model quality, a complete optimization run, or a library speedup.

The third command exercises installed Claude/OpenCode CLIs against scripted local
API responses. It checks tool use, protected writes, and structured results without
using a real model or paid account. Both passed with Claude Code 2.1.282 and
OpenCode 1.18.32 on macOS. It skips a CLI if it is not installed.

CLI options and configuration follow the official [Claude CLI reference](https://code.claude.com/docs/en/cli-reference),
[OpenCode configuration](https://opencode.ai/docs/config/),
[MCP setup](https://opencode.ai/docs/mcp-servers/), and
[local provider configuration](https://opencode.ai/docs/providers/).
