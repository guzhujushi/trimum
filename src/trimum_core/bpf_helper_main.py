"""`python -m trimum_core.bpf_helper_main`：helper 进程入口（socket 路径 / 允许 uid / loader 装好就 serve）。"""
from __future__ import annotations

import argparse
import logging
import os

from .bpf_helper import LoaderError, allowed_uids, serve, socket_path

log = logging.getLogger("trimum_core.bpf_helper_main")

#: 允许 uid 的环境变量口子（在 main 里自己读，不改 bpf_helper）。
#: 优先级链（对外表现）：`--allow-uid` > env `TRIMUM_BPF_ALLOWED_UIDS` > 配置 `security.bpf_helper_allowed_uids` > 默认（空集）。
ALLOWED_UIDS_ENV: str = "TRIMUM_BPF_ALLOWED_UIDS"


class UnavailableLoader:
    """兜底 loader（ebpf1e 的 `build_loader()` 只在真 loader 装不上时用它）：如实报「不可用」，
    **绝不假装在监控**。"""

    def load(self, program):
        raise LoaderError("bpf loader 未实现（ebpf1e）")

    def unload(self, program):
        raise LoaderError("bpf loader 未实现（ebpf1e）")

    def stats(self) -> dict:
        return {"available": False, "reason": "loader_not_implemented"}

    def tail(self, limit):
        raise LoaderError("bpf loader 未实现（ebpf1e）")


def build_loader(config: object | None = None) -> object:
    """真 eBPF loader（`bpf_loader.BpfLoader`，ebpf1e 起）。

    `config` 就是 `main` 那个配置对象（`Config()`，helper 里 `XDG_CONFIG_HOME=/etc`
    ⇒ 读 `/etc/trimum/config.yaml`）：loader 的路径/阈值全按「显式 > env > 配置 > 默认」解析，
    **不传就等于只认 env + 默认**（帮 helper 一个坑：别把配置对象漏掉）。

    `BpfLoader` 本身**惰性**加载 libbpf（构造不 dlopen），所以正常情况这里永远拿到真 loader；
    真拿不到（import 失败 / 构造炸了）⇒ 回退 `UnavailableLoader`，让 `bpf.stats` **如实报不可用**
    （fail-closed：不假装在监控，也不让 helper 起不来）。
    """
    try:
        from .bpf_loader import BpfLoader

        return BpfLoader(config=config)
    except Exception:
        log.warning("真 bpf loader 构造失败，回退 UnavailableLoader（如实报不可用）", exc_info=True)
        return UnavailableLoader()


def _explicit_uids(args) -> "list[str] | None":
    """`--allow-uid`（可重复）给到的 uid 串；一个都没给就返回 None（交给 env / 配置 / 默认）。"""
    if args.allow_uid:
        return list(args.allow_uid)
    return None


def _build_parser() -> "argparse.ArgumentParser":
    parser = argparse.ArgumentParser(
        prog="python -m trimum_core.bpf_helper_main",
        description="trimum eBPF 特权 helper：unix socket 收动词，SO_PEERCRED 门，分发给 loader。",
    )
    parser.add_argument("--once", action="store_true",
                        help="只处理一条连接就退出（= max_requests=1，自检用）。")
    parser.add_argument("--socket", default=None, metavar="PATH",
                        help="覆盖 unix socket 路径；缺省按「env TRIMUM_BPF_SOCKET > 配置 > 默认」走。")
    parser.add_argument("--allow-uid", action="append", default=[], metavar="UID",
                        help="允许的对端 uid，可重复；优先级最高，压过 env 与配置。")
    return parser


def main(argv: "list[str] | None" = None, *, serve_fn=serve, config=None) -> int:
    """入口。`argv` 用 `argparse`：可选 `--once`（= `max_requests=1`，自检用）、`--socket <path>`（覆盖路径）、
    `--allow-uid <uid>`（可重复，最高优先级）。

    **配置是惰性**：`config` 形参缺省为 None 时，`main` 内部才 `from .config import Config` 并构造一个
    （模块顶层**不** import Config，避免入口加载就拖入配置栈）。

    两条解析链（都带上配置对象，**不传 config 就走 env / 默认，绝不读配置键**）：

    - **socket 路径**：`--socket` 给了就用它，否则 `socket_path(config=cfg)`
      （该 helper 已实现「显式 > env `TRIMUM_BPF_SOCKET` > 配置 `security.bpf_socket` > 默认」）。
    - **允许 uid**：优先级 **`--allow-uid` > env `TRIMUM_BPF_ALLOWED_UIDS` > 配置
      `security.bpf_helper_allowed_uids` > 默认（空集）**：
      `explicit = args.allow_uid or os.environ.get("TRIMUM_BPF_ALLOWED_UIDS") or None`，
      再 `allowed_uids(explicit=explicit, config=cfg)`。

    **若允许 uid 结果为空集** ⇒ `log.warning` 一句「无允许 uid，所有对端都会被拒」，
    但**照样起服务**（fail-closed，不静默放行）。

    - 调 `serve(...)`（`loader=build_loader()`）；
    - `serve` 抛异常（bind 失败等）⇒ `log.error` + 返回 **1**（让 systemd `Restart=on-failure` 生效），**不许吞掉**；
    - 正常退出 ⇒ 返回 0。

    `serve_fn` 是可注入的 serve 实现（默认就是 `bpf_helper.serve`）：签名须与 `serve` 相同
    （`serve_fn(sock, *, loader=..., allowed_uids=..., max_requests=...)`），测试用假实现即可，不真起 socket。
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_parser().parse_args(argv)

    if config is None:
        from .config import Config
        config = Config()

    sock = args.socket if args.socket else socket_path(config=config)
    uids = allowed_uids(explicit=_explicit_uids(args) or os.environ.get(ALLOWED_UIDS_ENV) or None,
                        config=config)
    if not uids:
        log.warning("无允许 uid，所有对端都会被拒（fail-closed；配置 security.bpf_helper_allowed_uids 或重启前放行）")
    max_requests = 1 if args.once else None
    try:
        serve_fn(sock, loader=build_loader(config=config), allowed_uids=uids,
                 max_requests=max_requests)
    except Exception:
        log.error("serve 失败（bind 失败 / 权限不足等），退出码 1（systemd Restart=on-failure 会拉起）", exc_info=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
