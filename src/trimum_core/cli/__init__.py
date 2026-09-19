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
    trm install                  # 交互式首次安装向导
"""

from __future__ import annotations

import sys

from .parser import build_parser


def main(argv: list[str] | None = None) -> int:
    """`trm` 命令主入口。"""
    if argv is None:
        argv = sys.argv[1:]

    parser = build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "handler"):
        parser.print_help()
        try:
            from .commands.status import get_status_data

            status = get_status_data()
            state = "running" if status.get("running") else "offline"
            print(f"\nDaemon status: {state}")
        except Exception:
            pass
        return 0

    return args.handler(args)


__all__ = ["main", "build_parser"]
