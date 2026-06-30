"""
PCR 数据更新调度器。
- fetch_manifest_ver(): 从游戏服务器获取当前 manifest 版本
- check_and_update(): 与本地版本比较，有新版本则更新
- CLI: python -m hoshino.modules.pcrdata.updater
"""

import asyncio
import logging
import os
import sys
from typing import Optional

from .constants import save_app_version, save_manifest_version
from .pcrclient import pcrclient


def _get_logger(logger: Optional[logging.Logger] = None) -> logging.Logger:
    return logger or logging.getLogger(__name__)


_pcrclient = pcrclient()
_last_status: dict = {}


def get_cached_status() -> dict:
    return dict(_last_status)


async def fetch_manifest_ver() -> str:
    """POST source_ini/get_maintenance_status，返回 required_manifest_ver 字符串。

    样例：
    {
        'json': 1,
        'encrypt': 0,
        'res_ver': '10002200',
        'res_http_type': 0,
        'node_type': 0,
        'silence_download_size': 5,
        'resource': ['l1-prod-patch-gzlj.bilibiligame.net/client_ob_771/', 'l3-prod-patch-gzlj.bilibiligame.net/client_ob_771/', 'l4-prod-patch-gzlj.bilibiligame.net/client_ob_771/'],
        'execl_ver': '1.0.0',
        'res_key': 'd145b29050641dac2f8b19df0afe0e59',
        'start_time': '2026-03-16 11:00:00',
        'manifest_ver': '202603131142',
        'required_manifest_ver': '202603131142',
        'movie_ver': '202603161053',
        'sound_ver': '202603161053',
        'patch_ver': '202603121042',
        'login_stop': 0,
        'APP-VER': '11.4.0' // appended
    }
    """
    manifest = await _pcrclient.get_maintenance_status()

    _last_status.clear()
    _last_status.update(manifest)
    if "APP-VER" in manifest:
        save_app_version(manifest["APP-VER"])
    if "required_manifest_ver" in manifest:
        manifest_ver = str(manifest["required_manifest_ver"])
        save_manifest_version(manifest_ver)
        return manifest_ver
    raise ValueError(f"manifest_ver not found in response: {manifest}")


async def check_and_update(
    force: bool = False,
    logger: Optional[logging.Logger] = None,
) -> bool:
    """
    检查并更新数据库。
    force=True 时跳过版本比较，强制重新下载。
    logger 未指定时使用本模块 logger（CLI 等独立运行场景）。
    返回是否执行了更新。
    """
    from .assetmgr import assetmgr
    from .dbmgr import instance as db

    log = _get_logger(logger)

    try:
        ver = await fetch_manifest_ver()
    except Exception as e:
        log.error(f"fetch_manifest_ver failed: {e}")
        return False

    if not force and db.ver == ver:
        log.info(f"db is up-to-date (ver={ver})")
        return False

    log.info(f"updating db: {db.ver} -> {ver}")
    try:
        mgr = assetmgr()
        await mgr.init(ver)
        await db.update_db(mgr)
        log.info(f"db updated to ver={ver}, size={db.db_size}")
        return True
    except Exception as e:
        log.error(f"db update failed: {e}")
        return False


# ── CLI 入口 ──────────────────────────────────────────────────────────────────


async def _cli_main():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

    print("[updater] 检查最新 manifest 版本...")
    updated = await check_and_update(force="--force" in sys.argv)
    from .dbmgr import instance as db

    if updated:
        print(
            f"[updater] 数据库已更新至 ver={db.ver}，大小={db.db_size and db.db_size // 1024}KB"
        )
    else:
        print(f"[updater] 无需更新，当前 ver={db.ver}")


if __name__ == "__main__":
    asyncio.run(_cli_main())
