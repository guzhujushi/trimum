"""Command metadata contract for the `trm` CLI.

The command surface is *derived from the argparse tree* -- one source of truth
that cannot drift -- and enriched by optional ``__command_meta__`` declarations
in the command modules::

    __command_meta__ = {
        "security allow-once": {
            "summary": "Issue a one-shot JIT authorization token",
            "args": "<agent_id> [--tool shell] [--cmd 'ls -la'] [--ttl 300]",
            "examples": ["trm security allow-once agent-1 --cmd 'ls -la'"],
            "requires_sudo": False,
            "risk": "medium",
            "tags": ["security"],
        },
    }

``trm commands --json`` publishes this surface so an agent can enumerate every
capability at runtime (the Omarchy ``omarchy commands`` contract, adapted);
``trm commands --check`` validates the contract, and the test suite runs the
same check so the metadata cannot rot.
"""

from __future__ import annotations

import argparse
import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Any

METADATA_KEYS = frozenset(
    {
        "summary",
        "args",
        "examples",
        "aliases",
        "hidden",
        "requires_sudo",
        "risk",
        "tags",
        "since",
    }
)
RISK_VALUES = frozenset({"low", "medium", "high", "critical"})

#: Global flags injected into every parser; they are never part of a route.
_GLOBAL_DESTS = frozenset({"help", "json", "config", "quiet", "verbose"})


def _as_tuple(value: Any) -> tuple[str, ...]:
    """Normalise a metadata value into a tuple of strings."""
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


@dataclass(frozen=True)
class CommandInfo:
    """One node of the `trm` command surface."""

    path: tuple[str, ...]
    kind: str = "command"
    summary: str = ""
    args: str = ""
    examples: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    hidden: bool = False
    requires_sudo: bool = False
    risk: str = ""
    tags: tuple[str, ...] = ()
    module: str = ""
    has_handler: bool = False

    @property
    def key(self) -> str:
        return " ".join(self.path)

    @property
    def route(self) -> str:
        return "trm " + self.key

    @property
    def group(self) -> str:
        return self.path[0] if len(self.path) > 1 else ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "group": self.group,
            "name": self.path[-1],
            "kind": self.kind,
            "summary": self.summary,
            "args": self.args,
            "examples": list(self.examples),
            "aliases": list(self.aliases),
            "hidden": self.hidden,
            "requires_sudo": self.requires_sudo,
            "risk": self.risk,
            "tags": list(self.tags),
            "module": self.module,
            "has_handler": self.has_handler,
        }


@dataclass(frozen=True)
class CommandMetadata:
    """Aggregated ``__command_meta__`` declarations of all command modules."""

    by_path: dict[str, dict[str, Any]] = field(default_factory=dict)
    module_by_path: dict[str, str] = field(default_factory=dict)
    duplicates: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def get(self, key: str) -> dict[str, Any]:
        return self.by_path.get(key, {})


def command_module_names() -> list[str]:
    """Return the importable command module names, in stable order."""
    package = importlib.import_module("trimum_core.cli.commands")
    return sorted(
        info.name
        for info in pkgutil.iter_modules(package.__path__)
        if not info.name.startswith("_")
    )


def load_command_metadata() -> CommandMetadata:
    """Import every command module and gather its ``__command_meta__``."""
    by_path: dict[str, dict[str, Any]] = {}
    module_by_path: dict[str, str] = {}
    owners: dict[str, list[str]] = {}

    for name in command_module_names():
        module = importlib.import_module(f"trimum_core.cli.commands.{name}")
        declared = getattr(module, "__command_meta__", None)
        if not isinstance(declared, dict):
            continue
        for key, meta in declared.items():
            if not isinstance(meta, dict):
                continue
            owners.setdefault(str(key), []).append(name)
            by_path.setdefault(str(key), dict(meta))
            module_by_path.setdefault(str(key), name)

    duplicates = {
        key: tuple(names) for key, names in owners.items() if len(names) > 1
    }
    return CommandMetadata(
        by_path=by_path, module_by_path=module_by_path, duplicates=duplicates
    )


def subparsers_action(
    parser: argparse.ArgumentParser,
) -> argparse._SubParsersAction | None:
    """Return the parser's subparsers action, if it declares one."""
    for action in parser._actions:  # noqa: SLF001 - argparse has no public API
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def _choice_help(action: argparse._SubParsersAction) -> dict[str, str]:
    """Map choice name to the help string shown in the parent listing."""
    helps: dict[str, str] = {}
    for choice in getattr(action, "_choices_actions", []):
        helps[str(choice.dest)] = str(choice.help or "")
    return helps


def _derive_args(parser: argparse.ArgumentParser) -> str:
    """Derive a compact usage string from the parser's own arguments."""
    parts: list[str] = []
    for action in parser._actions:  # noqa: SLF001 - argparse has no public API
        if action.dest in _GLOBAL_DESTS:
            continue
        if action.option_strings:
            flag = action.option_strings[-1]
            parts.append(f"[{flag}]")
        elif action.nargs == "?":
            parts.append(f"[{action.dest}]")
        elif action.nargs in (None, 1):
            parts.append(f"<{action.dest}>")
        else:
            parts.append(f"<{action.dest} ...>")
    return " ".join(parts)


def collect_commands(
    parser: argparse.ArgumentParser | None = None,
    metadata: CommandMetadata | None = None,
) -> list[CommandInfo]:
    """Walk the parser tree and return every command, groups included."""
    if parser is None:
        from .parser import build_parser

        parser = build_parser()
    if metadata is None:
        metadata = load_command_metadata()

    collected: list[CommandInfo] = []
    _collect(parser, (), metadata, collected)
    return collected


def _canonical_names(action: argparse._SubParsersAction) -> dict[str, str]:
    """Map every choice name to its canonical name.

    ``add_parser(name, aliases=[...])`` registers one parser object under several
    names while only the canonical name shows up in ``_choices_actions``; the
    remaining names are aliases and must not be reported as separate commands.
    """
    helps = _choice_help(action)
    canonical_by_parser: dict[int, str] = {}
    for name, child in action.choices.items():
        if name in helps:
            canonical_by_parser[id(child)] = name

    canonical: dict[str, str] = {}
    for name, child in action.choices.items():
        if name in helps:
            canonical[name] = name
        else:
            canonical[name] = canonical_by_parser.get(id(child), name)
    return canonical


def _collect(
    parser: argparse.ArgumentParser,
    path: tuple[str, ...],
    metadata: CommandMetadata,
    out: list[CommandInfo],
) -> None:
    action = subparsers_action(parser)
    if action is None:
        return

    helps = _choice_help(action)
    canonical = _canonical_names(action)
    aliases_by_name: dict[str, list[str]] = {}
    for name, owner in canonical.items():
        if owner != name:
            aliases_by_name.setdefault(owner, []).append(name)

    for name, child in action.choices.items():
        if canonical.get(name) != name:
            continue
        child_path = path + (name,)
        key = " ".join(child_path)
        meta = metadata.get(key)
        has_children = subparsers_action(child) is not None
        aliases = set(_as_tuple(meta.get("aliases")))
        aliases.update(aliases_by_name.get(name, ()))
        out.append(
            CommandInfo(
                path=child_path,
                kind="group" if has_children else "command",
                summary=str(meta.get("summary") or helps.get(name, "") or ""),
                args=str(meta.get("args") or _derive_args(child)),
                examples=_as_tuple(meta.get("examples")),
                aliases=tuple(sorted(aliases)),
                hidden=bool(meta.get("hidden", False)),
                requires_sudo=bool(meta.get("requires_sudo", False)),
                risk=str(meta.get("risk") or ""),
                tags=_as_tuple(meta.get("tags")),
                module=metadata.module_by_path.get(key, ""),
                has_handler=callable(child.get_default("handler")),
            )
        )
        _collect(child, child_path, metadata, out)


def check_commands(
    parser: argparse.ArgumentParser | None = None,
    commands: list[CommandInfo] | None = None,
    metadata: CommandMetadata | None = None,
) -> list[str]:
    """Validate the command contract; return human-readable problems."""
    if metadata is None:
        metadata = load_command_metadata()
    if commands is None:
        commands = collect_commands(parser, metadata)

    problems: list[str] = []
    known = {info.key for info in commands}

    for key, names in sorted(metadata.duplicates.items()):
        problems.append(f"{key}: metadata declared twice by {', '.join(names)}")

    for key, meta in sorted(metadata.by_path.items()):
        if key not in known:
            problems.append(f"{key}: metadata declared for an unknown command")
            continue
        unknown = sorted(set(meta) - METADATA_KEYS)
        if unknown:
            problems.append(f"{key}: unsupported metadata key(s): {', '.join(unknown)}")
        risk = meta.get("risk")
        if risk and str(risk) not in RISK_VALUES:
            problems.append(f"{key}: invalid risk {risk!r}")

    for info in commands:
        if not info.summary:
            problems.append(f"{info.key}: missing summary (add help= or metadata)")
        if not info.has_handler:
            problems.append(f"{info.key}: no handler bound (set_defaults(handler=...))")
        for alias in info.aliases:
            sibling = " ".join(info.path[:-1] + (alias,))
            if alias in known or sibling in known:
                problems.append(
                    f"{info.key}: alias {alias!r} shadows an existing command"
                )
            elif not info.aliases:
                problems.append(f"{info.key}: alias {alias!r} does not resolve")
    return problems


__all__ = [
    "CommandInfo",
    "CommandMetadata",
    "METADATA_KEYS",
    "RISK_VALUES",
    "check_commands",
    "collect_commands",
    "command_module_names",
    "load_command_metadata",
    "subparsers_action",
]
