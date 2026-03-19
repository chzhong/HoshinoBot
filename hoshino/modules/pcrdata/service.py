"""
PCR数据 HoshinoBot Service：定时更新 + 查询指令。
"""

import asyncio

from hoshino.safeservice import SafeService

from .api import get_unit_name
from .dbmgr import instance as db
from .pcr_data import CHARA_NAME
from .updater import check_and_update, fetch_manifest_ver, get_cached_status

sv = SafeService("PCR数据", help_="PCR角色数据自动更新", bundle="pcr")


# ── 定时任务 ──────────────────────────────────────────────────────────────────


@sv.scheduled_job("cron", hour=16, minute=5, jitter=60)
async def scheduled_update():
    sv.logger.info("[PCR数据] 定时检查数据库更新...")
    updated = await check_and_update()
    if updated:
        sv.logger.info(f"[PCR数据] 数据库已更新至 ver={db.ver}")


async def _startup_check():
    await asyncio.sleep(10)
    sv.logger.info("[PCR数据] 启动时检查数据库更新...")
    await check_and_update()


# ── 指令 ──────────────────────────────────────────────────────────────────────


@sv.on_fullmatch(("数据状态", "查看数据状态"))
async def cmd_data_status(bot, ev):
    """读缓存，不请求网络。"""
    status = get_cached_status()
    if not status and db.ver is None:
        await bot.send(ev, "暂无数据，请发送「检查数据状态」获取最新信息。")
        return
    lines = [f"本地数据库版本：{db.ver or '未初始化'}"]
    if db.db_size:
        lines.append(f"数据库大小：{db.db_size // 1024} KB")
    if status.get("required_manifest_ver"):
        lines.append(f"服务器版本：{status['required_manifest_ver']}")
    await bot.send(ev, "\n".join(lines))


@sv.on_fullmatch("检查数据状态")
async def cmd_check_status(bot, ev):
    """请求网络，返回最新状态。"""
    await bot.send(ev, "正在查询服务器版本...")
    try:
        ver = await fetch_manifest_ver()
    except Exception as e:
        await bot.send(ev, f"查询失败：{e}")
        return
    need_update = db.ver != ver
    lines = [
        f"服务器版本：{ver}",
        f"本地版本：{db.ver or '未初始化'}",
        "需要更新" if need_update else "已是最新",
    ]
    await bot.send(ev, "\n".join(lines))


@sv.on_prefix(("更新数据", "强制更新数据"))
async def cmd_force_update(bot, ev):
    await bot.send(ev, "开始强制更新数据库，请稍候...")
    updated = await check_and_update(force=True)
    if updated:
        await bot.send(
            ev,
            f"更新完成，当前版本：{db.ver}，大小：{db.db_size and db.db_size // 1024} KB",
        )
    else:
        await bot.send(ev, "更新失败，请查看日志。")


@sv.on_prefix("查角色名称")
async def cmd_query_name(bot, ev):
    arg = str(ev.message).strip()
    if not arg.isdigit():
        await bot.send(ev, "用法：查角色名称 <unit_id>")
        return
    names = get_unit_name(int(arg))
    await bot.send(ev, f"unit_id={arg} 的名称：{' / '.join(names)}")


@sv.on_prefix("查角色ID")
async def cmd_query_id(bot, ev):
    keyword = str(ev.message).strip().lower()
    if not keyword:
        await bot.send(ev, "用法：查角色ID <名称关键词>")
        return
    results = []
    for chara_id, names in CHARA_NAME.items():
        if any(keyword in n.lower() for n in names):
            results.append(f"{chara_id}：{'、'.join(names[:3])}")
    if results:
        await bot.send(ev, "\n".join(results[:10]))
    else:
        await bot.send(ev, f"未找到包含「{keyword}」的角色。")


try:
    asyncio.get_event_loop().create_task(_startup_check())
except Exception as e:
    sv.logger.warning(f"[PCR数据] startup check task create failed: {e}")
