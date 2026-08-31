"""trm — trimum AI Shell CLI 入口。

用法：
    trm "查看磁盘空间"
    cat log.txt | trm "解释这个报错"
    trm "删除 /tmp 缓存" --dry-run
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
import yaml

from .executor import Executor
from .llm import LLMClient, LLMError
from .output import error, info, warning
from .planner import Planner
from .policy import PolicyEngine

PACKAGE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PACKAGE_DIR / "config.yaml"
DEFAULT_POLICY = PACKAGE_DIR / "policy.yaml"

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="trimum AI Shell：自然语言 -> 安全命令执行。",
)


def load_config(config_path: str | None = None) -> dict:
    """加载配置：--config 指定路径 > 包内默认 config.yaml > 内置空配置。"""
    candidates: list[Path] = []
    if config_path:
        candidates.append(Path(config_path))
    candidates.append(DEFAULT_CONFIG)
    for path in candidates:
        try:
            if path.is_file():
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                if isinstance(data, dict):
                    return data
        except (OSError, yaml.YAMLError):
            warning(f"配置文件读取失败，使用默认配置：{path}")
    return {}


def resolve_policy_file(config: dict, config_path: str | None) -> Path:
    """解析策略文件路径：配置指定（相对 CWD）> 包内默认 policy.yaml。"""
    name = (config.get("policy") or {}).get("file")
    if name:
        candidate = Path(name)
        if not candidate.is_absolute():
            base = Path(config_path).resolve().parent if config_path else Path.cwd()
            candidate = base / candidate
        if candidate.is_file():
            return candidate
    return DEFAULT_POLICY


def build_llm_client(config: dict) -> LLMClient:
    """根据配置构造 LLM 客户端（L-3：None 配置值有默认兜底）。"""
    llm_cfg = config.get("llm") or {}
    temperature = llm_cfg.get("temperature")
    timeout = llm_cfg.get("timeout_seconds")
    max_tokens = llm_cfg.get("max_tokens")
    max_retries = llm_cfg.get("max_retries")
    return LLMClient(
        base_url=llm_cfg.get("base_url"),
        model=llm_cfg.get("model", "deepseek-chat"),
        temperature=float(temperature) if temperature is not None else 0.2,
        max_tokens=int(max_tokens) if max_tokens is not None else 1024,
        timeout=float(timeout) if timeout is not None else 60.0,
        max_retries=int(max_retries) if max_retries is not None else 3,
    )


def read_pipe_input() -> str:
    """stdin 不是 TTY 时读取管道内容（支持 cat log | trm '...'）。"""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return ""
        return sys.stdin.read().strip()
    except (OSError, UnicodeDecodeError):
        return ""


def run(
    prompt: str,
    config_path: str | None = None,
    dry_run: bool = False,
    stdin_text: str | None = None,
) -> int:
    """核心流程：配置 -> LLM -> 规划 -> 策略 -> 执行。返回退出码。"""
    config = load_config(config_path)

    try:
        # L-1：LLMClient 生命周期由 with 管理，close() 保证连接池释放
        with build_llm_client(config) as llm:
            pipe_input = stdin_text if stdin_text is not None else read_pipe_input()
            plan = Planner(llm).plan(prompt, pipe_input=pipe_input)
    except LLMError as exc:
        error(str(exc))
        return 1

    try:
        executor_cfg = config.get("executor") or {}
        timeout_cfg = executor_cfg.get("timeout_seconds")
        executor = Executor(
            policy=PolicyEngine(resolve_policy_file(config, config_path)),
            timeout=float(timeout_cfg) if timeout_cfg is not None else 60.0,
            audit_log_path=(config.get("audit") or {}).get(
                "log_file", "~/.trimum/audit.log"
            ),
            dry_run=dry_run,
        )
    except Exception as exc:  # 策略/配置初始化失败
        error(f"策略引擎初始化失败（Policy init failed）：{exc}")
        return 1

    try:
        executor.execute(plan)
    except KeyboardInterrupt:
        warning("已中断（Interrupted）")
        return 130

    if dry_run and plan.commands:
        info("dry-run 模式：以上命令未实际执行（Not executed）")
    return 0


@app.command()
def trm(
    prompt: str = typer.Argument(..., help="自然语言描述，例如：查看磁盘空间"),
    config: str = typer.Option(
        None, "--config", "-c", help="配置文件路径（默认 package 内 config.yaml）"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="只展示计划与风险，不实际执行"
    ),
) -> None:
    """trm 'check disk space'：把自然语言转换为安全命令并执行。"""
    code = run(prompt, config_path=config, dry_run=dry_run)
    raise typer.Exit(code=code)


if __name__ == "__main__":
    app()