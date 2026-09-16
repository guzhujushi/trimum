"""Security configuration loader for trimum.

读取 ~/.trimum/security.yaml，提供安全等级体系配置。
每个 Agent 可以通过 agent.json5 的 security.mode 选择自己的安全级别。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml

from .models import (
    SecurityMode,
    FileTrustLevel,
    AgentSecurityConfig,
)

DEFAULT_SECURITY_YAML = """
# trimum 安全等级体系
# 等级：regex（最省） < balanced（默认） < sandbox（最严）
defaults:
  mode: "balanced"

levels:
  regex:
    llm_threshold: "never"
    file_trust_enabled: false

  balanced:
    llm_threshold: "suspicious"
    file_trust:
      enabled: true
      strict_hours: 1
      medium_days: 1
      trusted_days: 30
    cache:
      ttl_seconds: 300
      max_entries: 1000
    resource_limits:
      enabled: false

  sandbox:
    llm_threshold: "always"
    file_trust:
      enabled: true
      strict_hours: 24
      medium_days: 7
      trusted_days: 90
    cache:
      ttl_seconds: 60
      max_entries: 200
    resource_limits:
      enabled: true
      max_memory_mb: 256
      max_cpu_percent: 50
      max_processes: 20

llm:
  provider: "deepseek"
  model: "deepseek-chat"
  api_key_env: "DEEPSEEK_API_KEY"
  base_url: "https://api.deepseek.com/v1"
  timeout_seconds: 15
  max_retries: 2

# Agent 级别的安全等级覆盖（可选）
agents:
  # download-manager:
  #   mode: "sandbox"
  # fs-helper:
  #   mode: "regex"
"""


class SecurityConfig:
    """安全等级体系配置加载器。

    用法：
        config = SecurityConfig()
        config.load()                    # 读取 ~/.trimum/security.yaml
        mode = config.get_mode("fs-helper")  # 查询 Agent 的安全等级
    """

    def __init__(self, path: Optional[Path] = None):
        self.path = path or self._default_path()
        self._raw: dict[str, Any] = {}
        self._loaded = False

    @staticmethod
    def _default_path() -> Path:
        """返回默认配置路径 ~/.trimum/security.yaml"""
        home = Path.home()
        return home / ".trimum" / "security.yaml"

    def load(self) -> "SecurityConfig":
        """从配置文件加载。文件不存在时用内置默认值。"""
        # 先加载内置默认
        self._raw = yaml.safe_load(DEFAULT_SECURITY_YAML) or {}

        # 尝试加载用户配置并合并
        if self.path.exists():
            try:
                with open(self.path, encoding="utf-8") as f:
                    user_cfg = yaml.safe_load(f) or {}
                self._merge(self._raw, user_cfg)
            except Exception as e:
                print(f"Warning: Failed to load security config from {self.path}: {e}")

        self._loaded = True
        return self

    @staticmethod
    def _merge(base: dict, override: dict):
        """深度合并 override 到 base。"""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                SecurityConfig._merge(base[key], value)
            else:
                base[key] = value

    def get_mode(self, agent_name: Optional[str] = None) -> SecurityMode:
        """获取 Agent 的安全等级模式。

        优先级：agent.json5 的 security.mode > security.yaml 的 agents.<name>.mode > defaults.mode
        """
        if not self._loaded:
            self.load()

        # 1. Agent 级覆盖
        if agent_name:
            agents_cfg = self._raw.get("agents", {}) or {}
            if agent_name in agents_cfg:
                mode_str = agents_cfg[agent_name].get("mode", "")
                if mode_str:
                    try:
                        return SecurityMode(mode_str)
                    except ValueError:
                        print(f"Warning: Invalid mode '{mode_str}' for agent '{agent_name}', falling back")

        # 2. 默认模式
        default_mode = self._raw.get("defaults", {}).get("mode", "balanced")
        try:
            return SecurityMode(default_mode)
        except ValueError:
            return SecurityMode.BALANCED

    def get_level_config(self, mode: SecurityMode) -> dict:
        """获取某个安全等级的具体配置。"""
        if not self._loaded:
            self.load()
        return self._raw.get("levels", {}).get(mode.value, {})

    def get_llm_config(self) -> dict:
        """获取 LLM provider 配置。"""
        if not self._loaded:
            self.load()
        return self._raw.get("llm", {})

    def get_agent_security(self, agent_name: str) -> AgentSecurityConfig:
        """获取 Agent 的完整安全配置。"""
        mode = self.get_mode(agent_name)
        level_cfg = self.get_level_config(mode)
        llm_cfg = self.get_llm_config()

        return AgentSecurityConfig(
            mode=mode,
            llm_threshold=level_cfg.get("llm_threshold", "suspicious"),
            file_trust_enabled=level_cfg.get("file_trust_enabled", True),
            cache_ttl_seconds=level_cfg.get("cache", {}).get("ttl_seconds", 300),
            cache_max_entries=level_cfg.get("cache", {}).get("max_entries", 1000),
            resource_limits=level_cfg.get("resource_limits", {}),
        )

    def ensure_default(self) -> Path:
        """如果配置文件不存在，写入默认配置并返回路径。"""
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(DEFAULT_SECURITY_YAML, encoding="utf-8")
        return self.path


__all__ = ["SecurityConfig"]
