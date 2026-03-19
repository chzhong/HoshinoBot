"""
测试脚本：验证 pcrdata 完整流程（下载→unhash→查询）。

运行方式（在 HoshinoBot 根目录）：
    python -m hoshino.modules.pcrdata.tests.test_fetch_db
"""

import asyncio
import os
import sys

# 允许从根目录直接运行
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

VERSION_URL = "https://redive.estertion.win/last_version_cn.json"
FIXED_VERSION = "202603131142"  # 留空则从网络获取


def fetch_version() -> str:
    import json
    import urllib.request

    if FIXED_VERSION:
        print(f"[1] 使用固定版本号: {FIXED_VERSION}")
        return FIXED_VERSION
    print(f"[1] 获取版本号: {VERSION_URL}")
    _UA = {"User-Agent": "Mozilla/5.0"}
    req = urllib.request.Request(VERSION_URL, headers=_UA)
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    version = str(data["TruthVersion"])
    print(f"    版本: {version}")
    return version


async def run(version: str):
    from hoshino.modules.pcrdata.assetmgr import assetmgr
    from hoshino.modules.pcrdata.dbmgr import dbmgr
    from hoshino.modules.pcrdata.api import get_unit_name

    print(f"[2] 初始化 assetmgr (version={version})...")
    mgr = assetmgr()
    await mgr.init(version)
    print(f"    manifest 已加载，registries: {len(mgr.registries)} 条")

    print("[3] 下载并 unhash 数据库...")
    db = dbmgr()
    await db.update_db(mgr)
    print(f"    数据库路径: {db.db_path}")
    print(f"    数据库大小: {db.db_size / 1024:.1f} KB" if db.db_size else "    (大小未知)")

    print("[4] 验证 get_unit_names...")
    names = db.get_unit_names()
    print(f"    共 {len(names)} 条角色记录")

    print("\n[5] get_unit_name 接口测试（已知角色）：")
    for uid in [100101, 100201, 100301, 106001, 170101]:
        result = get_unit_name(uid)
        print(f"    unit_id={uid}: {result}")

    print("\n[6] get_unit_name 静态数据测试（chara_id）：")
    for cid in [1001, 1002, 1003]:
        result = get_unit_name(cid)
        print(f"    chara_id={cid}: {result}")

    print("\n[OK] 测试完成")


def main():
    version = fetch_version()
    asyncio.run(run(version))


if __name__ == "__main__":
    main()
