"""Configuration loader for trimum Core."""

from __future__ import annotations

import copy
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


# IPC socket：跟随 XDG/uid，不再写死 uid=1000
def default_socket_path(
    runtime_dir: Optional[str] = None, uid: Optional[int] = None
) -> Path:
    """默认 IPC socket 路径。

    优先 `XDG_RUNTIME_DIR`（与客户端 `trimum_client.discover_socket()` 的查找
    口径一致），否则退回 systemd 用户实例约定的 `/run/user/<uid>`；连 uid 都
    拿不到（Windows）时退回数据目录。

    原先写死 `/run/user/1000/trimum.sock`（假设 uid=1000），换 uid 就会与
    客户端对不上。
    """
    if runtime_dir is None:
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        return Path(runtime_dir) / "trimum.sock"
    if uid is None and hasattr(os, "getuid"):
        uid = os.getuid()
    if uid is not None:
        return Path("/run") / "user" / str(uid) / "trimum.sock"
    return DEFAULT_DATA_DIR / "trimum.sock"


DEFAULT_SOCKET_PATH = default_socket_path()

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
        # 必须深拷贝：浅拷贝下 `_raw["core"]` 与 `DEFAULT_CONFIG["core"]` 是同一个
        # dict，任何 set()/yaml 合并都会污染全局默认值，导致进程内后续 Config()
        # 继承别人写的路径（socket_path 尤其致命）。
        self._raw: dict[str, Any] = copy.deepcopy(DEFAULT_CONFIG)
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

    def set(self, key_path: str, value: Any) -> None:
        """Set a nested config value by dot-separated key path.

        Intermediate dictionaries are created as needed.  The change is
        kept in memory until :meth:`save` is called.
        """
        keys = key_path.split(".")
        node = self._raw
        for key in keys[:-1]:
            child = node.get(key)
            if not isinstance(child, dict):
                child = {}
                node[key] = child
            node = child
        node[keys[-1]] = value

    def save(self, path: Optional[Path] = None) -> None:
        """Persist the current configuration to YAML.

        If *path* is omitted, the current ``config_path`` is used.
        """
        target = Path(path or self.config_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            yaml.safe_dump(self._raw, f, allow_unicode=True, sort_keys=False)
        self.config_path = target


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
