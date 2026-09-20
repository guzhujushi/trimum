---
name: trm-cli
description: Drive the trimum (trm) runtime — discover capabilities, run tools and workflows, and read the audit trail instead of guessing.
---

# trm CLI

`trm` is the command-line front end of **trimum**, an AI process runtime for this
machine. Every capability it exposes is checked by the Tool Gateway (policy,
agent permissions, security rules, one-shot authorization) and recorded in the
audit log — so prefer `trm` over raw shell commands whenever a command exists.

## Discover before you guess

```bash
trm commands --json        # every command, machine-readable, with summaries
trm commands --check       # validate the command surface still matches the code
trm tool list --json       # registered tools (built-in + ~/.trimum/tools/*)
trm tool info <name>       # arguments, risk level, permissions of one tool
trm health --json          # is the daemon up, are API keys configured
trm doctor                 # environment dependencies and config completeness
```

Rules of thumb:

- Prefer `trm commands --json` over reading this file for the exact current surface.
- Prefer `--json` output when you need to parse results; omit it for humans.

## Run work

```bash
trm ask "summarise the failing tests in this repo"   # LLM plans and executes
trm ask -i                                           # interactive multi-turn
trm exec "git status --short"                        # human-sourced command path
trm workflow list                                    # defined workflows
trm workflow run <name>                              # execute one
trm agent list                                       # registered agents
trm agent spawn <agent_id>                           # start a sub-agent
```

## Security and authorization

High-risk actions may come back as `confirm` or `denied`:

```bash
trm security status                                  # current policy state
trm security allow-once <agent_id> --cmd "ls -la"    # one-shot JIT token
trm security tokens                                  # valid tokens
trm security learning                                # learned behaviour profile
```

If an action is denied: **do not try to bypass it with a different tool**. Report
the denial to the user, explain what was blocked, and ask whether to authorize it
with `trm security allow-once`.

## Audit trail

```bash
trm log audit --json                      # structured audit entries
trm log audit --event-type security_blocked
trm log audit --since 1h --risk high
trm log tail -f                           # live daemon log
```

Use the audit log to prove what ran: it records the tool, the decision
(allow/confirm/deny), the source type (human/AI) and the risk level.

## Memory

```bash
trm memory list --entries        # categories and indexed entries
trm memory search "deploy"       # full-text search
trm memory set <key> <value>     # classify and store a fact
trm memory stats
```

## Working with tools

Tools live at `~/.trimum/tools/<name>/{tool.json5,main.py}`. To inspect or add
one:

```bash
trm tool list
trm tool info shell
```

New tools must declare a `tool.json5` manifest; the loader ignores directories
without one (that is how deprecated tools are disabled).
