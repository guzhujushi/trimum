"""trimum CLI — `trm` command entry point.

子命令结构:

    trm                          # 帮助（默认显示可用子命令）
    trm version                  # 显示版本
    trm health                   # 快速健康检查（不需要 daemon）
    trm status                   # 当前 Agent 运行状态 / 资源占用
    trm doctor                   # 检查环境依赖 / 配置完整性

    trm ask "<指令>"              # 单次提问（LLM 规划并执行）
    trm ask -i                   # 交互式多轮对话（流式输出）

    trm memory list              # 列出所有记忆分类
    trm memory get <key>         # 取一条记忆
    trm memory set <key> <val>   # 写入并自动分类
    trm memory search "<词>"     # 语义搜索
    trm memory stats             # 记忆数量统计

    trm security status          # 安全策略状态
    trm security allow-once <agent_id> [--tool shell] [--cmd "..."] [--ttl 300]
    trm security tokens          # 列出当前有效 token

    trm daemon start|stop|restart|status
    trm log tail                 # 实时日志（--audit / --since 1h）
    trm tool list                # 列出所有已注册工具
    trm tool info <name>         # 查看工具详情
    trm agent list               # 列出所有 agent
    trm agent info <id>          # 查看 agent 详情
    trm agent spawn <id>         # 启动新 agent
    trm agent kill <id>          # 停止 agent
    trm workflow list            # 列出所有 workflow
    trm workflow run <name>      # 运行 workflow
    trm workflow status <run_id> # 查看 workflow 运行状态
    trm config show              # 显示当前配置
    trm config set <key> <val>   # 设置配置项
    trm install                  # 交互式首次安装向导（--setup 走新版结构化向导）
    trm setup                    # 首启引导：宿主探测 / 身份证书 / 选装工具链 / 技能分发

    trm commands                 # 枚举全部命令（--json 机器可读 / --check 校验契约）
    trm skill list               # 列出技能及其分发状态
    trm skill sync               # 把 Agent Skills 链接进各宿主技能目录
"""

from __future__ import annotations

import argparse
import sys

from ._utils import fail, is_quiet, print_json, wants_json
from .parser import build_parser


def _normalize_global_flags(args: argparse.Namespace) -> None:
    """Fill global flag values that argparse may leave as ``SUPPRESS``."""
    args.json = bool(getattr(args, "json", False))
    args.quiet = bool(getattr(args, "quiet", False))
    args.verbose = bool(getattr(args, "verbose", False))
    if not hasattr(args, "config"):
        args.config = None


def _print_default_status(args: argparse.Namespace) -> None:
    """Print daemon status after help for the no-command invocation."""
    try:
        from .commands.status import get_status_data

        status = get_status_data()
        if wants_json(args):
            print_json(status)
        elif not is_quiet(args):
            state = "running" if status.get("running") else "offline"
            print(f"\nDaemon status: {state}")
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    """`trm` 命令主入口。"""
    if argv is None:
        argv = sys.argv[1:]

    parser = build_parser()
    args = parser.parse_args(argv)
    _normalize_global_flags(args)

    if not hasattr(args, "handler"):
        parser.print_help()
        _print_default_status(args)
        return 0

    try:
        return int(args.handler(args) or 0)
    except Exception as exc:
        return fail(f"command failed: {exc}")


__all__ = ["main", "build_parser"]