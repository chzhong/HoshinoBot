"""
PCR 数据库管理：下载、unhash、查询。
使用 sqlite3，无 sqlalchemy 依赖。
"""

import json
import os
import sqlite3
from typing import TYPE_CHECKING, Dict, Optional

from .constants import CACHE_DIR, MANIFEST_VERSION, PROJ_DIR

if TYPE_CHECKING:
    from .assetmgr import assetmgr

_RAINBOW_JSON = os.path.join(PROJ_DIR, "rainbow.json")
_DB_DIR = os.path.join(CACHE_DIR, "db")


class dbmgr:
    def __init__(self):
        self.ver: Optional[str] = None
        self._dbpath: Optional[str] = None
        self._load_cached_db()

    def _load_cached_db(self) -> None:
        os.makedirs(_DB_DIR, exist_ok=True)
        preferred_ver = MANIFEST_VERSION
        if preferred_ver:
            preferred_path = os.path.join(_DB_DIR, f"{preferred_ver}.db")
            if os.path.exists(preferred_path):
                self.ver = preferred_ver
                self._dbpath = preferred_path
                return

        versions = []
        for name in os.listdir(_DB_DIR):
            if name.endswith(".db"):
                ver = name[:-3]
                if ver.isdigit():
                    versions.append(ver)
        if versions:
            latest_ver = max(versions)
            self.ver = latest_ver
            self._dbpath = os.path.join(_DB_DIR, f"{latest_ver}.db")

    @property
    def db_path(self) -> Optional[str]:
        return self._dbpath

    @property
    def db_size(self) -> Optional[int]:
        if self._dbpath and os.path.exists(self._dbpath):
            return os.path.getsize(self._dbpath)
        return None

    async def update_db(self, mgr: "assetmgr") -> None:
        """从 assetmgr 下载数据库并 unhash，更新 self.ver / self._dbpath。"""
        ver = mgr.ver
        os.makedirs(_DB_DIR, exist_ok=True)
        dbpath = os.path.join(_DB_DIR, f"{ver}.db")

        if not os.path.exists(dbpath):
            data = await mgr.db()
            with open(dbpath, "wb") as f:
                f.write(data)

        self._dbpath = dbpath
        self.ver = ver
        self._unhash()

    def _unhash(self) -> int:
        """用彩虹表将哈希表名/列名还原为真实名称（原地修改）。返回成功还原的表数量。"""
        if not self._dbpath or not os.path.exists(_RAINBOW_JSON):
            return 0

        with open(_RAINBOW_JSON, encoding="utf-8") as f:
            rainbow = json.load(f)

        conn = sqlite3.connect(self._dbpath)
        try:
            cur = conn.cursor()
            db_tables = {
                t[0]
                for t in cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }

            ok = 0
            for hashed_table, cols_dict in rainbow.items():
                if hashed_table not in db_tables:
                    continue

                intact_table = cols_dict.get("--table_name", hashed_table)
                if intact_table in db_tables and intact_table != hashed_table:
                    continue

                row = cur.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                    (hashed_table,),
                ).fetchone()
                if not row:
                    continue
                create_sql = row[0]

                for hashed_col, intact_col in cols_dict.items():
                    if hashed_col == "--table_name":
                        create_sql = create_sql.replace(hashed_table, intact_table)
                    else:
                        create_sql = create_sql.replace(hashed_col, intact_col)

                col_rows = cur.execute(
                    f"PRAGMA table_info(`{hashed_table}`)"
                ).fetchall()
                hashed_cols = [r[1] for r in col_rows]
                intact_cols = [cols_dict.get(c, c) for c in hashed_cols]

                insert_sql = (
                    f"INSERT INTO `{intact_table}` "
                    f"(`{'`, `'.join(intact_cols)}`) "
                    f"SELECT `{'`, `'.join(hashed_cols)}` FROM `{hashed_table}`"
                )
                drop_sql = f"DROP TABLE `{hashed_table}`"

                try:
                    cur.execute(create_sql)
                    cur.execute(insert_sql)
                    cur.execute(drop_sql)
                    conn.commit()
                    ok += 1
                except Exception:
                    conn.rollback()

            return ok
        finally:
            conn.close()

    def get_unit_names(self) -> Dict[int, str]:
        """返回 {unit_id: unit_name}，数据库不可用时返回空 dict。"""
        if not self._dbpath or not os.path.exists(self._dbpath):
            return {}
        try:
            conn = sqlite3.connect(self._dbpath)
            try:
                cur = conn.execute("SELECT unit_id, unit_name FROM unit_data")
                return {row[0]: row[1] for row in cur.fetchall()}
            finally:
                conn.close()
        except Exception:
            return {}

    def get_unit_name(self, unit_id: int) -> Optional[str]:
        if not self._dbpath or not os.path.exists(self._dbpath):
            return None
        try:
            conn = sqlite3.connect(self._dbpath)
            try:
                cur = conn.execute(
                    "SELECT unit_name FROM unit_data WHERE unit_id = ?",
                    (unit_id,),
                )
                row = cur.fetchone()
                return row[0] if row else None
            finally:
                conn.close()
        except Exception:
            return None


instance = dbmgr()
