"""`trm config` command group — show/set/path."""

from __future__ import annotations

import argparse

from .._utils import emit, fail


def add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("config", help="inspect and update configuration")
    nested = parser.add_subparsers(dest="config_command", title="config commands")

    show_parser = nested.add_parser("show", help="show the current configuration")
    show_parser.set_defaults(handler=handler)

    set_parser = nested.add_parser("set", help="set a configuration value")
    set_parser.add_argument("key", help="dot-separated key path, e.g. core.port")
    set_parser.add_argument("value", help="new value")
    set_parser.set_defaults(handler=handler)

    path_parser = nested.add_parser("path", help="show the configuration file path")
    path_parser.set_defaults(handler=handler)

    parser.set_defaults(handler=_show_help)


def _show_help(args: argparse.Namespace) -> int:
    del args
    print("usage: trm config {show,set,path} ...")
    return 0


def _parse_value(raw: str):
    """Convert a CLI string into a best-effort typed config value."""
    import yaml

    try:
        return yaml.safe_load(raw)
    except Exception:
        return raw


def _load_config():
    from trimum_core.config import Config

    return Config()


def handler(args: argparse.Namespace) -> int:
    """Execute the requested config subcommand."""
    command = getattr(args, "config_command", None)
    config = _load_config()

    if command == "show":
        data = {"path": str(config.config_path), "values": config._raw}
        emit(args, data)
        return 0

    if command == "set":
        value = _parse_value(args.value)
        try:
            config.set(args.key, value)
            config.save()
        except Exception as exc:
            return fail(f"failed to save config: {exc}")
        emit(args, {"key": args.key, "value": value, "path": str(config.config_path)})
        return 0

    if command == "path":
        emit(args, {"path": str(config.config_path)})
        return 0

    return _show_help(args)


__all__ = ["add_subparsers", "handler"]
