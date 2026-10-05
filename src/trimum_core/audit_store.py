"""AuditStore — 结构化审计日志（JSONL）。

Phase 3 收尾 P1：审计此前只有 structlog 文本行 + 进程内环缓冲，无法按字段查询。
现在每条 ``AuditEvent`` 落一行 JSON，``trm log audit`` 直接读文件过滤，
进程内同时通过 EventBus 广播 ``task.audit.<event_type>``。

设计取舍：
- 写入失败绝不抛出（审计是旁路，不能拖垮执行路径）
- 单行 JSONL，便于 grep / jq / 流式 tail
- 超过 ``max_bytes`` 时轮转为 ``<name>.1``（只保留一份备份）
- 哈希链（§4.2.2 片 A1）：每行带 ``prev_hash`` / ``hmac``；链起点锚 ``<name>.chained``；
  日志目录下 **多写者共存**（daemon / CLI / api）⇒ 写路径用 ``<name>.lock`` + ``flock`` 串行化，
  且链尾每次现读磁盘，不依赖实例缓存。
- 审计链 key 见 ``resolve_hmac_key()``（0600 落盘，不再有仓库内硬编码兜底）
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

try:                      # 真机一律有 fcntl；Windows 开发机没有 ⇒ 退化为进程内锁
    import fcntl
except ImportError:       # pragma: no cover - 仅非 POSIX
    fcntl = None

from .models import AuditEvent
from .paths import trimum_path
from .sec_monitor import AuditChainVerifier
from .audit_witness import record_witness

log = logging.getLogger("trimum_core.audit_store")

DEFAULT_AUDIT_FILENAME = "audit.jsonl"


def default_audit_path() -> Path:
    """审计文件默认位置：与主日志同目录的 ``audit.jsonl``。"""
    from .config import Config

    return Path(Config().log_path).parent / DEFAULT_AUDIT_FILENAME


AUDIT_KEY_FILENAME = "audit.key"


class AuditKeyUnreadable(RuntimeError):
    """key 文件读不了（PermissionError / EIO 等）⇒ fail-closed。

    「读不了」不等于「空」：不许按空文件走 ``_repair_empty_key_file()`` 换 key，
    否则旧行（用旧 key 签的）整条链作废。
    """


def audit_key_path() -> Path:
    """审计链 HMAC key 的落盘位置：``<TRIMUM_HOME>/audit.key``（默认 ``~/.trimum/audit.key``）。"""
    return trimum_path(AUDIT_KEY_FILENAME)


def resolve_hmac_key(explicit: Optional[str] = None) -> str:
    """解析审计链 HMAC key：显式参数 → ``TRIMUM_AUDIT_HMAC_KEY`` → ``audit_key_path()`` → 生成并落盘。

    为什么要有它：硬编码兜底 key 写在仓库里 ⇒ 拿到源码的人能重签一条假链，链的取证价值归零。
    落盘 0600 之后威胁模型变成「能读你 home 的人」（≈同一用户）。

    轮换：删掉该文件（或改环境变量）后跑一次 ``bash scripts/audit_rechain.sh --apply``
    —— 旧行是用旧 key 签的，不重建会一直红。

    并发首建是原子的（临时文件 + ``os.link``）：目标一旦出现就是完整内容，没有
    「建好还没写」的窗口；读到空/坏 key 文件时有界重试后就地修复。

    已知退化：key 文件写不下来时（非 ``FileExistsError`` 的 ``OSError``）只告警并返回
    本次生成的 key ⇒ 每个进程的 key 不同 ⇒ 链会断，属已知退化。
    """
    if explicit and explicit.strip():
        return explicit.strip()
    env_key = os.environ.get("TRIMUM_AUDIT_HMAC_KEY")
    if env_key and env_key.strip():
        return env_key.strip()
    path = audit_key_path()
    if path.exists():
        text = _read_key_file(path)
        if text:
            mode = path.stat().st_mode
            if mode & 0o077:
                log.warning(
                    "audit_store.key_permissions_loose",
                    extra={"path": str(path), "mode": oct(mode & 0o777)},
                )
            return text
        return _repair_empty_key_file(path)
    new_key = secrets.token_hex(32)
    if _write_key_atomically(path, new_key):
        return new_key
    # 别的进程先建好了（或写不下来）⇒ 去读它的；绝不能用本次的 key 冒充（会断链）。
    text = _read_key_file(path)
    if text:
        return text
    return _repair_empty_key_file(path)


def _read_key_file(path: Path) -> str:
    """读已有 key 文件；空内容最多重试 5 次（每次 50ms），仍空则返回 ``""``。

    ``FileNotFoundError``（``exists()`` 与读取之间的竞态）当作读不到 ⇒ 返回 ``""``；
    其它 ``OSError``（EACCES / EIO 等）**读不了 ≠ 空** ⇒ 抛 ``AuditKeyUnreadable``
    fail-closed，绝不允许调用方据此换 key。
    """
    for _ in range(5):
        try:
            text = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return ""
        except OSError as exc:
            raise AuditKeyUnreadable(
                f"audit key file unreadable: {path} (errno={getattr(exc, 'errno', None)})"
            ) from exc
        if text:
            return text
        time.sleep(0.05)
    return ""


def _repair_empty_key_file(path: Path) -> str:
    """坏/空 key 文件就地修复：生成新 key 并原子替换文件。"""
    log.warning("audit_store.audit_key_empty", extra={"path": str(path)})
    new_key = secrets.token_hex(32)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(new_key + "\n")
        path.unlink(missing_ok=True)
        os.link(tmp, path)
        log.info("audit_store.audit_key_created", extra={"path": str(path)})
    except OSError as exc:
        log.warning(
            "audit_store.audit_key_persist_failed",
            extra={"path": str(path), "error": str(exc)},
        )
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
    return new_key


def _write_key_atomically(path: Path, key: str) -> bool:
    """同目录临时文件（0600）→ ``os.link`` 到目标：目标已存在则 ``FileExistsError``（别的进程先建好），
    一旦出现目标就是完整内容（硬链接指不到半个文件）⇒ 没有「建好还没写」的窗口。
    返回 ``True`` 表示本进程建好了目标；``False`` 表示别的进程已先建好（或写不下来）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(key + "\n")
        try:
            os.link(tmp, path)
            log.info("audit_store.audit_key_created", extra={"path": str(path)})
            return True
        except FileExistsError:
            return False  # 别的进程先建好了
    except OSError as exc:
        log.warning(
            "audit_store.audit_key_persist_failed",
            extra={"path": str(path), "error": str(exc)},
        )
        return False
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass



class AuditStore:
    """JSONL 审计日志读写。"""

    def __init__(self, path: Optional[str | Path] = None, max_bytes: int = 5 * 1024 * 1024, hmac_key: Optional[str] = None) -> None:
        self.path = Path(path) if path is not None else default_audit_path()
        self.max_bytes = max_bytes
        self.hmac_key = resolve_hmac_key(hmac_key)
        self._verifier = AuditChainVerifier(self.hmac_key)
        # 仅供观察：本实例**最近一次成功写入**的 hmac（真正的链尾每次 append 现读磁盘，见 _current_prev_hash）
        self._last_hash: Optional[str] = None

    # ------------------------------------------------------------------
    # 写
    # ------------------------------------------------------------------

    _TAIL_WINDOW = 64 * 1024   # 读尾回溯窗口：末行往前的最大字节数

    def _tail_record(self, path: Path) -> Optional[dict[str, Any]]:
        """读 ``path`` 的最后一条 JSON 记录（空文件 / 不存在 / 坏行 ⇒ ``None``）。

        只回溯末行的 ``_TAIL_WINDOW`` 字节；窗口里没有完整行（超长行）时整读兜底。
        """
        try:
            size = path.stat().st_size
        except OSError:
            return None
        if size <= 0:
            return None
        start = max(0, size - self._TAIL_WINDOW)
        try:
            with path.open("rb") as fh:
                fh.seek(start)
                chunk = fh.read()
        except OSError:
            return None
        lines = [ln for ln in chunk.split(b"\n") if ln.strip()]
        if start > 0 and lines:
            lines = lines[1:]          # 窗口首行可能被截断，丢掉
        if not lines:
            try:
                lines = [ln for ln in path.read_bytes().split(b"\n") if ln.strip()]
            except OSError:
                return None
        if not lines:
            return None
        try:
            record = json.loads(lines[-1].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return record if isinstance(record, dict) else None

    def _last_chained_hmac(self, path: Path) -> str:
        """``path`` 里**最后一条带 hmac 的行**的 hmac（坏行跳过）；没有 ⇒ ``""``。"""
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return ""
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            hmac = record.get("hmac") if isinstance(record, dict) else None
            if hmac:
                return hmac
        return ""

    def _current_prev_hash(self) -> str:
        """**每次 append 前现读磁盘**取链尾 hmac（不缓存）。

        daemon / CLI / api 会**各自**建 ``AuditStore`` 写同一份日志（多写者），实例内缓存
        必然串链（F-A）：A 写完 B 写、A 再写时还在用 A 的旧哈希。兜底顺序：
        主文件末行 hmac → （主文件不存在/为空时）``.1`` 末行 hmac → 主文件里最后一条带 hmac 的行。
        主文件**存在**但末行是 legacy 行、或末行是坏 JSON 时，都不再借 ``.1`` 的旧 hmac
        （F-D：那不是轮转窗口，借了必串链）。
        """
        tail = self._tail_record(self.path)
        if tail is not None and "hmac" in tail:
            return tail["hmac"]
        if tail is None and not self._has_content(self.path):
            # 只有「主文件不存在 / 为空」才是轮转窗口，才看 .1；
            # 末行是坏 JSON（文件非空）时**不许**借 .1 的旧 hmac（那必串链）
            backup_tail = self._tail_record(self.path.with_suffix(self.path.suffix + ".1"))
            if backup_tail is not None and "hmac" in backup_tail:
                return backup_tail["hmac"]
        return self._last_chained_hmac(self.path)

    @staticmethod
    def _has_content(path: Path) -> bool:
        try:
            return path.stat().st_size > 0
        except OSError:
            return False

    @contextlib.contextmanager
    def _write_lock(self) -> Iterator[None]:
        """跨进程写锁（``<audit>.lock`` + ``flock``）；非 POSIX 退化为不锁（见模块头 fcntl 兜底）。"""
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        handle = None
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(lock_path, "a+")
        except OSError as e:
            log.debug("audit_store.lock_open_failed: %s", e)
        try:
            if handle is not None and fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            if handle is not None:
                try:
                    if fcntl is not None:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
                finally:
                    handle.close()

    def _marker_path(self) -> Path:
        """链起点锚文件（``audit.jsonl.chained``）：内容 = 首条链行的 hmac。

        为什么要它：「无 hmac 的行＝历史行」这条规则单独存在时，攻击者把**所有** hmac 字段删掉
        就能让整份文件退化通过。锚文件在链开始那一刻写下，校验时要求**必须能在文件里找到这条记录**。
        """
        return self.path.with_suffix(self.path.suffix + ".chained")

    def append(self, event: AuditEvent) -> bool:
        """追加一条审计事件，返回是否成功（失败不抛异常）。

        会话：整个「现读链尾 → 算 hmac → 落盘」在**跨进程写锁**里（daemon / CLI / api 是多写者），
        链尾**每次现读磁盘**而不是用实例缓存，否则第二个写者会拿着过期哈希串链（F-A）。
        审计是旁路：任一步失败都不拖垮执行路径，失败时**不推进** `_last_hash`、不落盘、不写锚。
        """
        try:
            with self._write_lock():
                event.prev_hash = self._current_prev_hash()
                event.hmac = self._verifier.compute_hash(event.model_dump(exclude={"hmac"}))
                line = json.dumps(event.model_dump(), ensure_ascii=False, default=str)
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._rotate_if_needed()
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
                self._last_hash = event.hmac
                marker = self._marker_path()
                if not marker.exists():
                    try:
                        marker.parent.mkdir(parents=True, exist_ok=True)
                        marker.write_text(event.hmac, encoding="utf-8")
                    except Exception as e:   # 锚文件写失败不能把「已落盘」的这次 append 判成失败
                        log.debug("audit_store.marker_write_failed: %s", e)
                # 带外见证（片 A2 后半）：把链尾 + 各段边界抄一份到 <TRIMUM_HOME>/（与数据目录分离）。
                # 失败只告警 —— 审计是旁路，不能因为见证写不下来就把这次 append 判成失败。
                record_witness(self.path)
            return True
        except Exception as e:  # 审计失败不能影响主流程
            log.debug("audit_store.append_failed: %s", e)
            return False

    def _rotate_if_needed(self) -> None:
        try:
            if self.path.exists() and self.path.stat().st_size >= self.max_bytes:
                backup = self.path.with_suffix(self.path.suffix + ".1")
                backup.unlink(missing_ok=True)
                self.path.rename(backup)
        except OSError as e:
            log.debug("audit_store.rotate_failed: %s", e)

    def verify_chain(self) -> tuple[bool, list[str]]:
        """校验审计链；把 ``audit.jsonl.1`` 与主文件当成同一条链（``.1`` 在前）。

        语义与已知边界（写进 docstring，别省）：
        - 「最老文件的首行」允许 prev_hash 非空：只保留一份 ``.1`` 时，更老的段已被轮转丢弃，
          锚点无从校验（``allow_missing_anchor=True``）；这不影响逐行 hmac 校验。
        - 链起点由 ``audit.jsonl.chained`` 锚定：锚在则必须能找到那条记录，
          否则报错；但只保留一份 ``.1`` 时，锚行可能已被轮转覆盖，
          此时容忍（``allow_stale_anchor=True``）——「一条链行都不剩」仍会报错。
        - **已知边界（同目录锚挡不住有目录写权限者；带外见证留给片 A2）**：
          ① 最老边界的前缀截断（整段删 ``.1`` / 只删 ``.1`` 首行）与合法轮转不可区分 ⇒ 通过；
          ② 尾部截断（清空/截短主文件）链自身测不出 ⇒ 通过；
          ③ 把**所有** hmac 删掉**并且**删掉 ``.chained`` ⇒ 退化成「纯 legacy 文件」而通过
             （锚文件与链都在同一目录，挡不住有写权限者）；
          ④ **链已开始之后又出现无 hmac 的行**（旧版本写者混写）⇒ **永久红**，且轮转改变不了顺序。
             要回到绿：部署新版（daemon + CLI 同版本）后对旧段做一次归档重建
             —— ``bash scripts/audit_rechain.sh``（先 dry-run，再由本人 ``--apply``），见 ``TODO.md`` 片 A2。
        """
        paths = [p for p in (self.path.with_suffix(self.path.suffix + ".1"), self.path) if p.exists()]
        marker = self._marker_path()
        chain_start = marker.read_text(encoding="utf-8").strip() if marker.exists() else None
        if chain_start is None:
            # marker 不在，但文件里已经有链行 ⇒ 锚被删了，不许退回「全 legacy」的宽松模式。
            # 注意要扫**两个**文件：轮转窗口内主文件可能不存在，链行全在 .1 里（H-A）。
            for path in paths:
                for record in self._iter_events(path):
                    if "hmac" in record:
                        return False, [f"Audit chain anchor missing ({marker.name}) while chained records exist"]
            if not paths:
                return True, []
        return self._verifier.verify_chain_files(
            paths,
            tolerate_legacy=True,
            chain_start_hmac=chain_start,
            allow_missing_anchor=True,
            allow_stale_anchor=True,
        )

    # ------------------------------------------------------------------
    # 读
    # ------------------------------------------------------------------

    def read(self) -> list[dict[str, Any]]:
        """读取全部审计事件（坏行跳过）。"""
        return list(self._iter_events())

    def query(
        self,
        *,
        since: Optional[float] = None,
        event_type: Optional[str] = None,
        agent_id: Optional[str] = None,
        risk: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """按字段过滤，返回最近 ``limit`` 条（时间正序）。"""
        matched = [
            event
            for event in self._iter_events()
            if self._matches(event, since=since, event_type=event_type, agent_id=agent_id, risk=risk)
        ]
        if limit and limit > 0:
            matched = matched[-limit:]
        return matched

    @staticmethod
    def _matches(
        event: dict[str, Any],
        *,
        since: Optional[float],
        event_type: Optional[str],
        agent_id: Optional[str],
        risk: Optional[str],
    ) -> bool:
        if since is not None:
            try:
                if float(event.get("timestamp", 0)) < since:
                    return False
            except (TypeError, ValueError):
                return False
        if event_type and event.get("event_type") != event_type:
            return False
        if agent_id and event.get("agent_id") != agent_id:
            return False
        if risk and event.get("risk") != risk:
            return False
        return True

    def _iter_events(self, path: Optional[Path] = None) -> Iterable[dict[str, Any]]:
        """读取给定文件（默认主文件）里的事件；坏行跳过。"""
        target = path if path is not None else self.path
        try:
            lines = target.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        events = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events


__all__ = ["AuditStore", "AuditKeyUnreadable", "DEFAULT_AUDIT_FILENAME", "default_audit_path", "resolve_hmac_key", "audit_key_path"]
