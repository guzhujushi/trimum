"""Configuration loader for trimum Core."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml

from .models import RiskLevel, Action


# Default paths for Linux
XDG_CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
XDG_DATA_HOME = os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")

DEFAULT_CONFIG_DIR = Path(XDG_CONFIG_HOME) / "trimum"
DEFAULT_DATA_DIR = Path(XDG_DATA_HOME) / "trimum"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.yaml"
DEFAULT_POLICY_PATH = DEFAULT_CONFIG_DIR / "policy.yaml"
DEFAULT_CONTEXT_DB = DEFAULT_DATA_DIR / "context.db"
DEFAULT_LOG_PATH = DEFAULT_DATA_DIR / "trimum.log"
DEFAULT_SOCKET_PATH = Path("/run/user/1000/trimum.sock")

# Windows fallback for development
WINDOWS_CONFIG_DIR = Path.home() / ".trimum"


DEFAULT_CONFIG = {
    "core": {
        "host": "127.0.0.1",
        "port": 8321,
        "socket_path": str(DEFAULT_SOCKET_PATH),
        "workers": 1,
    },
    "logging": {
        "level": "INFO",
        "file": str(DEFAULT_LOG_PATH),
        "format": "json",
    },
    "context": {
        "db_path": str(DEFAULT_CONTEXT_DB),
    },
    "policy": {
        "path": str(DEFAULT_POLICY_PATH),
    },
    "agent_manager": {
        "max_agents": 10,
        "health_check_interval": 30,  # seconds
    },
}


class Config:
    """trimum Core configuration."""

    def __init__(self, config_path: Optional[Path] = None):
        self._raw: dict[str, Any] = dict(DEFAULT_CONFIG)  # shallow copy
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self._load_file()

    def _load_file(self) -> None:
        """Load config from YAML file, merging with defaults."""
        path = self.config_path
        if not path.exists():
            # Try Windows fallback
            win_path = WINDOWS_CONFIG_DIR / "config.yaml"
            if win_path.exists():
                path = win_path
            else:
                return  # No config file, use defaults

        try:
            with open(path, encoding="utf-8") as f:
                user_config = yaml.safe_load(f)
            if user_config and isinstance(user_config, dict):
                self._deep_merge(self._raw, user_config)
        except Exception as e:
            print(f"Warning: Failed to load config from {path}: {e}")

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> None:
        """Deep merge override into base."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                Config._deep_merge(base[key], value)
            else:
                base[key] = value

    @property
    def host(self) -> str:
        return self._raw["core"]["host"]

    @property
    def port(self) -> int:
        return int(self._raw["core"]["port"])

    @property
    def socket_path(self) -> str:
        return self._raw["core"]["socket_path"]

    @property
    def log_level(self) -> str:
        return self._raw["logging"]["level"]

    @property
    def log_path(self) -> str:
        return self._raw["logging"]["file"]

    @property
    def log_format(self) -> str:
        return self._raw["logging"].get("format", "json")

    @property
    def context_db_path(self) -> str:
        return self._raw["context"]["db_path"]

    @property
    def policy_path(self) -> str:
        return self._raw["policy"]["path"]

    @property
    def max_agents(self) -> int:
        return int(self._raw["agent_manager"]["max_agents"])

    @property
    def health_check_interval(self) -> int:
        return int(self._raw["agent_manager"]["health_check_interval"])

    @property
    def tools_config(self) -> dict:
        return self._raw.get("tools", {})

    def get(self, key_path: str, default: Any = None) -> Any:
        """Get nested config value by dot-separated key path."""
        keys = key_path.split(".")
        value = self._raw
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
                if value is None:
                    return default
            else:
                return default
        return value


class PolicyLoader:
    """Load and cache policy rules from YAML."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or DEFAULT_POLICY_PATH
        self._rules: list[dict] = []

    def load(self) -> list[dict]:
        """Load policy rules from YAML. Returns default rules on error."""
        path = self.path
        if not path.exists():
            # Try Windows fallback
            win_path = WINDOWS_CONFIG_DIR / "policy.yaml"
            if win_path.exists():
                path = win_path
            else:
                return self._get_default_rules()

        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            self._rules = data.get("rules", []) if data else []
            return self._rules
        except Exception as e:
            print(f"Warning: Failed to load policy from {path}: {e}")
            return self._get_default_rules()

    @staticmethod
    def _get_default_rules() -> list[dict]:
        return [
            {"pattern": "ls|cat|head|tail|find|grep|df|du|ps|pwd|whoami|echo|which|uname|free|uptime|date|id|who",
             "risk": "low", "action": "auto"},
            {"pattern": "rm|chmod|chown|mv|cp|mkdir|touch|kill|pkill|systemctl|pacman|apt|dnf|pip|npm install",
             "risk": "medium", "action": "confirm"},
            {"pattern": "rm -rf /|chmod -R 777 /|dd if=/dev|> /dev/sda|:(){ :|:& };:|mkfs|format",
             "risk": "critical", "action": "deny"},
        ]


def ensure_dirs(config: Config) -> None:
    """Ensure all required directories exist."""
    dirs = [
        Path(config.log_path).parent,
        Path(config.context_db_path).parent,
        Path(config.policy_path).parent,
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


__all__ = ["Config", "PolicyLoader", "ensure_dirs", "DEFAULT_CONFIG_DIR", "DEFAULT_DATA_DIR"]
