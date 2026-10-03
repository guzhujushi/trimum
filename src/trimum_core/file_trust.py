"""File trust tracking with time-decay confidence.

记录文件首次出现时间，按时间衰减管理信任等级：
    - 首次出现 <1h     → ISOLATED（隔离级，sandbox 模式强制 LLM 审查）
    - 1h ~ 24h         → HIGH（高管控）
    - 24h ~ 7d         → MEDIUM（中管控）
    - 7d ~ 30d         → LOW（低管控）
    - >30d             → TRUSTED（完全信任，不调 LLM）

持久化：SQLite（~/.trimum/data/file_trust.db）
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

from .models import FileTrustLevel


class FileTrustTracker:
    """时间衰减文件信任度追踪器。"""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            home = Path.home()
            data_dir = home / ".trimum" / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = data_dir / "file_trust.db"
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self._init_db()

    def _init_db(self):
        """初始化表结构。"""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS file_trust (
                path      TEXT PRIMARY KEY,
                first_seen REAL NOT NULL,
                last_seen  REAL NOT NULL
            )
        """)
        self.conn.commit()

    def record_access(self, path: str, ts: Optional[float] = None) -> FileTrustLevel:
        """记录文件访问/创建。

        首次出现 → 写入 first_seen
        已存在 → 更新 last_seen
        """
        path = str(path)
        ts = ts if ts is not None else time.time()
        row = self.conn.execute(
            "SELECT first_seen FROM file_trust WHERE path = ?", (path,)
        ).fetchone()

        if row is None:
            self.conn.execute(
                "INSERT INTO file_trust (path, first_seen, last_seen) VALUES (?, ?, ?)",
                (path, ts, ts),
            )
        else:
            self.conn.execute(
                "UPDATE file_trust SET last_seen = ? WHERE path = ?",
                (ts, path),
            )
        self.conn.commit()
        return self.get_trust_level(path, ts)

    def get_trust_level(self, path: str, ts: Optional[float] = None) -> FileTrustLevel:
        """查询文件信任等级。文件未记录时返回 ISOLATED。"""
        path = str(path)
        ts = ts if ts is not None else time.time()
        row = self.conn.execute(
            "SELECT first_seen FROM file_trust WHERE path = ?", (path,)
        ).fetchone()

        if row is None:
            return FileTrustLevel.ISOLATED

        age_seconds = ts - row[0]
        if age_seconds < 3600:          # <1h
            return FileTrustLevel.ISOLATED
        elif age_seconds < 86400:       # 1h~24h
            return FileTrustLevel.HIGH
        elif age_seconds < 604800:      # 24h~7d
            return FileTrustLevel.MEDIUM
        elif age_seconds < 2592000:     # 7d~30d
            return FileTrustLevel.LOW
        else:                           # >30d
            return FileTrustLevel.TRUSTED

    def get_first_seen(self, path: str) -> Optional[float]:
        """返回文件首次出现时间戳，未记录返回 None。"""
        row = self.conn.execute(
            "SELECT first_seen FROM file_trust WHERE path = ?", (str(path),)
        ).fetchone()
        return row[0] if row else None

    def cleanup(self, max_age_days: int = 90, ts: Optional[float] = None) -> int:
        """删除超过 max_age_days 未访问的记录。返回删除条数。"""
        ts = ts if ts is not None else time.time()
        cutoff = ts - max_age_days * 86400
        cur = self.conn.execute(
            "DELETE FROM file_trust WHERE last_seen < ?", (cutoff,)
        )
        self.conn.commit()
        return cur.rowcount

    def stats(self) -> dict:
        """返回简要统计。"""
        row = self.conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT first_seen) FROM file_trust"
        ).fetchone()
        return {"total": row[0], "distinct_first_seen": row[1]}

    def close(self):
        self.conn.close()

    def __del__(self):
        try:
            self.conn.close()
        except Exception:
            pass
