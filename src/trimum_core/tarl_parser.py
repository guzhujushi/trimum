"""TARL — Trimum AI Representation Language Parser & Serializer.

KV-pair line format::

    key:value key2:value2 key3:value3

- Fields separated by single space
- Values contain NO spaces (Scheme B)
- Keys are alphanumeric with dots (cmd, workflow.name, etc.)
- One line = one message
- Multiple lines = multiple messages
"""

from __future__ import annotations

import re
from typing import Any

__all__ = [
    "parse_line",
    "parse_multi",
    "serialize",
    "serialize_multi",
    "extract_prefix",
    "match_prefix",
]


def _split_kv(line: str) -> list[tuple[str, str]]:
    """Split a TARL line into (key, value) pairs.

    Handles edge cases: empty lines, leading/trailing whitespace.
    """
    line = line.strip()
    if not line:
        return []

    pairs: list[tuple[str, str]] = []
    for field in line.split(" "):
        field = field.strip()
        if not field:
            continue
        # Split on first colon only (value may contain colons? No per spec, but defensive)
        colon_idx = field.find(":")
        if colon_idx == -1:
            # Malformed field without colon — skip
            continue
        key = field[:colon_idx]
        value = field[colon_idx + 1:]
        pairs.append((key, value))
    return pairs


def parse_line(line: str) -> dict[str, str]:
    """Parse a single TARL line into a dict.

    For duplicate keys, the last value wins.

    Args:
        line: A single TARL line, e.g. ``cmd:restart_nginx user:guzhu``

    Returns:
        Dict of key→value pairs.

    Example::

        >>> parse_line("cmd:restart_nginx user:guzhu")
        {"cmd": "restart_nginx", "user": "guzhu"}
    """
    result: dict[str, str] = {}
    for key, value in _split_kv(line):
        result[key] = value
    return result


def parse_multi(text: str) -> list[dict[str, str]]:
    """Parse multi-line TARL text into a list of dicts.

    Each non-empty line is parsed as a separate message.

    Args:
        text: Multi-line TARL string.

    Returns:
        List of dicts, one per line.

    Example::

        >>> parse_multi("cmd:restart_nginx user:guzhu\\nstatus:completed")
        [{"cmd": "restart_nginx", "user": "guzhu"}, {"status": "completed"}]
    """
    messages: list[dict[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parsed = parse_line(line)
        if parsed:
            messages.append(parsed)
    return messages


def serialize(data: dict[str, str]) -> str:
    """Convert a dict back to a single TARL line.

    Keys are sorted for deterministic output.

    Args:
        data: Dict of key→value pairs.

    Returns:
        TARL line string.

    Example::

        >>> serialize({"cmd": "restart_nginx", "user": "guzhu"})
        "cmd:restart_nginx user:guzhu"
    """
    if not data:
        return ""
    parts = [f"{k}:{v}" for k, v in sorted(data.items()) if k and v is not None]
    return " ".join(parts)


def serialize_multi(messages: list[dict[str, str]]) -> str:
    """Convert a list of dicts back to multi-line TARL.

    Args:
        messages: List of dicts, one per line.

    Returns:
        Multi-line TARL string.

    Example::

        >>> serialize_multi([{"cmd": "restart_nginx"}, {"status": "completed"}])
        "cmd:restart_nginx\\nstatus:completed"
    """
    return "\n".join(serialize(m) for m in messages if m)


def extract_prefix(text: str, prefix: str) -> list[str]:
    """Extract all values for keys starting with a given prefix.

    Args:
        text: A single TARL line (or multi-line, searched per line).
        prefix: Key prefix to match (e.g. ``"cmd"``, ``"workflow"``).

    Returns:
        List of matching values, in order of appearance.

    Example::

        >>> extract_prefix("cmd:restart_nginx user:guzhu cmd:reload", "cmd")
        ["restart_nginx", "reload"]
    """
    results: list[str] = []
    for line in text.splitlines():
        for key, value in _split_kv(line):
            if key == prefix or key.startswith(prefix + "."):
                results.append(value)
    return results


def match_prefix(text: str, prefix: str) -> bool:
    """Check if a TARL line (or any line in multi-line) contains a key with the given prefix.

    Args:
        text: TARL string (single or multi-line).
        prefix: Key prefix to match.

    Returns:
        True if any key matches the prefix.

    Example::

        >>> match_prefix("cmd:restart_nginx", "cmd")
        True
        >>> match_prefix("status:completed", "cmd")
        False
    """
    return len(extract_prefix(text, prefix)) > 0


# ===================================================================
# Self-test
# ===================================================================

if __name__ == "__main__":
    import sys

    # Test parse_line
    r = parse_line("cmd:restart_nginx user:guzhu workflow:blog_deploy")
    assert r == {"cmd": "restart_nginx", "user": "guzhu", "workflow": "blog_deploy"}, f"FAIL: {r}"
    print("✅ parse_line basic")

    # Test parse_line duplicate keys
    r = parse_line("cmd:a cmd:b")
    assert r == {"cmd": "b"}, f"FAIL duplicate: {r}"
    print("✅ parse_line duplicate last-wins")

    # Test parse_line empty
    r = parse_line("")
    assert r == {}, f"FAIL empty: {r}"
    print("✅ parse_line empty")

    # Test parse_multi
    r = parse_multi("cmd:a\nstatus:completed")
    assert r == [{"cmd": "a"}, {"status": "completed"}], f"FAIL multi: {r}"
    print("✅ parse_multi basic")

    # Test parse_multi with blank lines
    r = parse_multi("cmd:a\n\nstatus:completed")
    assert r == [{"cmd": "a"}, {"status": "completed"}], f"FAIL multi blanks: {r}"
    print("✅ parse_multi blank lines")

    # Test serialize
    r = serialize({"cmd": "restart_nginx", "user": "guzhu"})
    assert r == "cmd:restart_nginx user:guzhu", f"FAIL serial: {r}"
    print("✅ serialize basic")

    # Test serialize empty
    r = serialize({})
    assert r == "", f"FAIL serial empty: {r}"
    print("✅ serialize empty")

    # Test serialize_multi
    r = serialize_multi([{"cmd": "a"}, {"status": "ok"}])
    assert r == "cmd:a\nstatus:ok", f"FAIL multi serial: {r}"
    print("✅ serialize_multi basic")

    # Test extract_prefix
    r = extract_prefix("cmd:restart_nginx user:guzhu cmd:reload", "cmd")
    assert r == ["restart_nginx", "reload"], f"FAIL extract: {r}"
    print("✅ extract_prefix basic")

    # Test extract_prefix multi-line
    r = extract_prefix("cmd:a\nstatus:ok\ncmd:b", "cmd")
    assert r == ["a", "b"], f"FAIL extract multi: {r}"
    print("✅ extract_prefix multi-line")

    # Test match_prefix
    assert match_prefix("cmd:restart_nginx", "cmd") is True
    assert match_prefix("status:completed", "cmd") is False
    print("✅ match_prefix basic")

    # Test roundtrip
    original = {"cmd": "deploy", "user": "guzhu", "workflow": "blog"}
    serialized = serialize(original)
    parsed = parse_line(serialized)
    assert original == parsed, f"FAIL roundtrip: {original} -> {serialized} -> {parsed}"
    print("✅ roundtrip")

    print("\n🎉 All tests passed!")
