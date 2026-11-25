"""NoneBot 1.x discovers this module inside the pcr_roster directory."""

import asyncio
import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import nonebot

from hoshino import R, Service, priv, util
from hoshino.service import sucmd

from .core.catalog import json_bytes, load_files, write_bytes
from .core.icons import IconDownloader, UNKNOWN, icon_name, install_icon_compat
from .core.service import RosterService


sv = Service(
    "PCR花名册", bundle="PCR", use_priv=priv.SUPERUSER, enable_on_default=True,
    help_="花名册状态：查看版本与角色数量\n同步花名册：更新名称及档案\n下载所有角色头像：补齐本地头像",
)
DATA_DIR = Path(__file__).resolve().parent.parent / "priconne"
STATE_DIR = Path.home() / ".hoshino/pcr_roster"
STATUS_PATH = STATE_DIR / "status.json"
CHINA = timezone(timedelta(hours=8))
service = RosterService(DATA_DIR, STATE_DIR)
lock = asyncio.Lock()
icon_job = None
last_issue = ""


def chara_module():
    # Import only the compatibility helpers; this does not load priconne/gacha as a plugin.
    return importlib.import_module("hoshino.modules.priconne.chara")


def refresh_runtime(catalog):
    chara = chara_module()
    trie = type(chara.roster._roster)()
    for key, names in catalog.names.items():
        for name in names:
            normalized = util.normalize_str(name)
            if normalized and normalized not in trie:
                trie[normalized] = key
    # The report and Web modules import CHARA_NAME directly, so do not replace it.
    data = importlib.import_module("hoshino.modules.priconne._pcr_data")
    data.CHARA_NAME.clear()
    data.CHARA_NAME.update(catalog.names)
    data.CHARA_PROFILE.clear()
    data.CHARA_PROFILE.update(catalog.profiles)
    chara.roster._roster = trie
    chara.roster._all_name_list = trie.keys()
    install_icon_compat(chara, R)


def save_status(status):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    write_bytes(STATUS_PATH, json_bytes(status))


def read_status():
    try:
        status = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        return status if isinstance(status, dict) else {}
    except (OSError, ValueError):
        return {}


def describe(status):
    if not status:
        return "花名册：暂无成功同步记录。"
    note = f"\n提示：{status['note']}" if status.get("note") else ""
    return (f"花名册：{status.get('names', 0)} 名角色，{status.get('profiles', 0)} 份档案\n"
            f"来源：{status.get('source', '未知')}，资源版本：{status.get('version') or '未知'}\n"
            f"上次同步：{status.get('at', '未知')}（北京时间）{note}")


async def sync_once():
    global last_issue
    async with lock:
        try:
            selected, catalog, changed = await service.sync()
            refresh_runtime(catalog)
            status = {"at": datetime.now(CHINA).strftime("%Y-%m-%d %H:%M:%S"),
                      "source": selected.data.source, "version": selected.data.version,
                      "names": len(catalog.names), "profiles": len(catalog.profiles), "note": selected.note}
            try:
                await asyncio.to_thread(save_status, status)
            except OSError:
                status["note"] = "资料已应用，但无法保存同步状态"
            last_issue = ""
            message = ("已更新。\n" if changed else "数据无变化。\n") + describe(status)
            sv.logger.info(message)
            return message
        except Exception as error:
            detail = str(error) if type(error) is RuntimeError else type(error).__name__
            last_issue = f"本次同步失败：{detail}。请核对数据源和写入权限。"
            sv.logger.warning(last_issue)
            return last_issue


@nonebot.on_startup
async def startup():
    async def delayed_sync():
        await asyncio.sleep(10)
        await sync_once()
    asyncio.create_task(delayed_sync())


@sv.scheduled_job("cron", hour=16, minute=5)
async def scheduled_sync():
    await sync_once()


async def reject_arguments(session):
    if (session.current_arg or "").strip():
        await session.send("这条命令不需要参数，请只发送命令名。")
        return True
    return False


@sucmd("pcr-roster-status", force_private=False, aliases=("花名册状态",))
async def status_command(session):
    if await reject_arguments(session):
        return
    status = await asyncio.to_thread(read_status)
    extra = f"\n{last_issue}" if last_issue else ""
    await session.send(describe(status) + extra)


@sucmd("pcr-roster-sync", force_private=False, aliases=("同步花名册",))
async def sync_command(session):
    if await reject_arguments(session):
        return
    if lock.locked() or (icon_job and not icon_job.done()):
        await session.send("已有花名册或头像任务在运行。")
        return
    await session.send(await sync_once())


async def download_job(bot, ev):
    async with lock:
        try:
            try:
                selected = await service.select()
                ids = selected.data.playable or set(selected.data.names)
                release = selected.release
            except RuntimeError:
                catalog = await asyncio.to_thread(load_files, DATA_DIR)
                ids, release = set(catalog.names), None
            if not ids - {UNKNOWN}:
                raise ValueError("没有可下载的角色")
            directory = Path(R.img("priconne/unit", icon_name(UNKNOWN, 3)).path).expanduser().parent
            counts, failed, manifest_error = await IconDownloader(
                directory, service.autopcr.cache, service.assets
            ).download(set(ids), release)
            summary = "，".join(f"{key} {counts[key]}" for key in ("已下载", "已存在", "无对应资源", "失败"))
            message = f"角色头像处理完成：{summary}。"
            if manifest_error:
                message += f"\n官服资源清单不可用（{manifest_error}）。"
            if failed:
                message += "\n失败样例：" + "、".join(failed[:8]) + "。可重跑补齐。"
                sv.logger.warning("头像失败项：%s", "、".join(failed))
        except Exception as error:
            message = f"头像任务中止（{type(error).__name__}），请核对花名册、依赖和资源目录权限。"
            sv.logger.warning(message)
    try:
        await bot.send(ev, message)
    except Exception:
        sv.logger.warning("无法发送头像任务结果：%s", message)


@sucmd("pcr-roster-download-icons", force_private=False, aliases=("下载所有角色头像",))
async def icon_command(session):
    global icon_job
    if await reject_arguments(session):
        return
    if lock.locked() or (icon_job and not icon_job.done()):
        await session.send("已有花名册或头像任务在运行。")
        return
    icon_job = asyncio.create_task(download_job(session.bot, session.event))
    await session.send("已开始补齐角色头像，完成后会发送统计。")


# Must be available before Kanna's first Web request; no networking at import.
try:
    install_icon_compat(chara_module(), R)
except (ImportError, OSError, ValueError) as error:
    sv.logger.warning("头像兼容方法暂不可用（%s），同步花名册后会重试。", type(error).__name__)
