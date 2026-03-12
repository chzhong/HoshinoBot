"""
service.py - pcrjjc2 Controller 层（USE_NEW_LOGIC = True 时生效）

职责：
  - 创建 SafeService（sv）
  - 模块导入时自完成订阅数据迁移 + ArenaService 初始化
  - 通缉/关注沿用旧逻辑：直接操作 wanted_binds.json 的 dict，不使用 WantedManager
  - 注册 cron 调度任务（订阅用新逻辑，通缉用旧逻辑）
  - 注册命令 handler（薄层：参数解析 + 权限判断 → 调用各模块方法）
"""

import json
import os
import time
from asyncio import Lock
from os.path import dirname, exists, join
from typing import Optional

from arena_client import ApiException, get_profile
from arena_service import ArenaService, render_subscription_status_cq
from config_loader import load_config
from jjcdata import jjcdata
from safeservice import SafeService
from subscriptions import LegacyBindConfig
from utils import send_summary
from wanted_manager import LegacyWantedBind, LegacyWantedConfig, LegacyWatchBind
from wanted_service import legacy_check_wanted_dict, legacy_should_check

sv_help = """【订阅管理】
[竞技场绑定 uid] 追加绑定（最多8个），默认双场推送
[竞技场查询] 查询本群绑定的 uid 实时排名
[详细查询 (uid)] 查询本群第一个uid（或指定uid）的详细信息
[订阅状态查询] 列出所有绑定的编号/uid/通知群/开关状态
[删除竞技场订阅 N] 按编号删除
[启用竞技场订阅 (N)] 启用 jjc 推送，不填N则操作全部
[停止竞技场订阅 (N)] 停止 jjc 推送，不填N则操作全部
[启用公主竞技场订阅 (N)] 启用 pjjc 推送，不填N则操作全部
[停止公主竞技场订阅 (N)] 停止 pjjc 推送，不填N则操作全部
[转移竞技场订阅 N] 将第N个订阅的通知群改为当前群

【群通缉】
[通缉 uid] 通缉uid，监控其上下线和排名变动
[逮捕 uid] 取消通缉 uid
[关注 uid] 关注uid（仅上线通知）
[取关 uid] 取消关注 uid
[通缉犯概要][lswts] 精简方式显示通缉犯状态

"""

sv = SafeService("竞技场推送", help_=sv_help, bundle="pcr查询")

cache_db = jjcdata()

# ── 自完成初始化 ──────────────────────────────────────────────────────
# 订阅：从 config.yaml 的 subscription.items 加载；
#       若 config.yaml 中无 items 且旧 binds.json 存在，则自动迁移并写回 config.yaml
# 通缉/关注：沿用旧格式，直接加载 wanted_binds.json

_curpath = dirname(__file__)
_binds_path = join(_curpath, "binds.json")
_binds_bak_path = join(_curpath, "binds.json.bak")
_wanted_path = join(_curpath, "wanted_binds.json")
_wanted_bak_path = join(_curpath, "wanted_binds.json.bak")

BACKUP_MIGRATED = False

_cfg = load_config()
_arena_svc = ArenaService(_cfg, cache_db, sv.logger)

# 若 config.yaml 中没有订阅数据，且旧 binds.json 存在，则迁移并写回
if not _arena_svc.subscription_manager._items and exists(_binds_path):
    sv.logger.info("[pcrjjc2] config.yaml 中无订阅数据，从 binds.json 自动迁移...")
    with open(_binds_path, encoding="utf-8") as _fp:
        _old_binds: LegacyBindConfig = json.load(_fp)
    _arena_svc.subscription_manager.migrate_from_old(_old_binds.get("arena_bind", {}))
    _arena_svc.save_config()
    if BACKUP_MIGRATED:
        os.rename(_binds_path, _binds_bak_path)

# 通缉/关注旧格式数据：{gid: [uid, ...]}
_wanted_root: LegacyWantedConfig = {"wanted_bind": {}, "watch_bind": {}}
if exists(_wanted_path):
    with open(_wanted_path, encoding="utf-8") as _fp:
        _wanted_root = json.load(_fp)
wanted_binds: LegacyWantedBind = _wanted_root.get("wanted_bind", {})
watch_binds: LegacyWatchBind = _wanted_root.get("watch_bind", {})
_wanted_lck = Lock()


def _save_wanted_binds() -> None:
    _wanted_root["wanted_bind"] = wanted_binds
    _wanted_root["watch_bind"] = watch_binds
    with open(_wanted_path, "w", encoding="utf-8") as fp:
        json.dump(_wanted_root, fp, ensure_ascii=False, indent=4)


# ============================================================
# 调度任务
# ============================================================


@sv.scheduled_job("cron", second=0)
async def on_arena_schedule():
    if _arena_svc is None:
        return
    if not await _arena_svc.should_check_subscriptions():
        sv.logger.info("[arena] skip")
        return
    await _arena_svc.check_arena_subscriptions()


@sv.scheduled_job("cron", second=0)
async def on_wanted_schedule():
    if not await legacy_should_check():
        sv.logger.info("[wanted] skip")
        return
    await legacy_check_wanted_dict(wanted_binds, watch_binds, cache_db, sv.logger)
    _save_wanted_binds()  # 持久化 code=6 自动清理的结果


# ============================================================
# 帮助
# ============================================================


@sv.on_fullmatch("竞技场帮助", only_to_me=False)
async def send_jjchelp(bot, ev):
    self_ids = bot._wsr_api_clients.keys()
    for sid in self_ids:
        gl = await bot.get_group_list(self_id=sid)
        msg = f"本Bot目前服务群数目{len(gl)}"
    await bot.send(ev, f"{sv_help}\n{msg}")


# ============================================================
# 订阅管理指令
# ============================================================


@sv.on_rex(r"^竞技场绑定 ?(\d{13})$")
async def on_arena_bind(bot, ev):
    pcr_uid = ev["match"].group(1)
    qq = str(ev["user_id"])
    gid = str(ev["group_id"])
    result = _arena_svc.bind(qq, pcr_uid, gid)
    if result == "ok":
        _arena_svc.save_config()
        await bot.finish(ev, "竞技场绑定成功", at_sender=True)
    elif result == "dup":
        await bot.finish(ev, f"uid {pcr_uid} 已在订阅列表中", at_sender=True)
    else:
        await bot.finish(
            ev, "订阅列表已满（上限8个），请先删除部分订阅", at_sender=True
        )


@sv.on_fullmatch("竞技场查询")
async def on_query_arena(bot, ev):
    """查询本群绑定的所有 uid 的实时排名（不显示 uid，仅昵称+场次+名次）。"""
    qq = str(ev["user_id"])
    gid = str(ev["group_id"])
    try:
        ranks = await _arena_svc.query_group_ranks(qq, gid)
    except ApiException as e:
        await bot.finish(ev, f"查询出错，{e}", at_sender=True)
        return
    if not ranks:
        await bot.finish(ev, "本群还未绑定竞技场", at_sender=True)
        return
    lines = []
    for r in ranks:
        lines.append(r.user_name)
        lines.append(f"  jjc：{r.arena_group}场 {r.arena_rank}名")
        lines.append(f"  pjjc：{r.grand_arena_group}场 {r.grand_arena_rank}名")
    await bot.finish(ev, "\n".join(lines), at_sender=True)


@sv.on_rex(r"^详细查询 ?(\d{13})?$")
async def on_query_arena_detail(bot, ev):
    """查询单个 uid 的详细信息（uid 省略时取本群第一个绑定）。"""
    uid = ev["match"].group(1)
    qq = str(ev["user_id"])
    gid = str(ev["group_id"])
    try:
        info = await _arena_svc.query_detail(qq, gid, uid)
    except ValueError as e:
        await bot.finish(ev, str(e), at_sender=True)
        return
    except ApiException as e:
        await bot.finish(ev, f"查询出错，{e}", at_sender=True)
        return
    arena_str = time.strftime("%Y-%m-%d", time.localtime(info.get("arena_time", 0)))
    grand_str = time.strftime(
        "%Y-%m-%d", time.localtime(info.get("grand_arena_time", 0))
    )
    dname_hint = (
        f"(区别名: {info['user_dname']})"
        if info.get("user_dname") != info.get("user_name")
        else ""
    )
    await bot.finish(
        ev,
        f"""
uid：{info["viewer_id"]}
昵称：{info["user_name"]} {dname_hint}
公会：{info.get("clan_name", "")}
简介：{info.get("user_comment", "")}
最后上线：{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(info.get("last_login_time", 0)))}
jjc：{info["arena_rank"]}
pjjc：{info["grand_arena_rank"]}
战力：{info.get("total_power", "-")}
等级：{info.get("team_level", "-")}
jjc场次：{info["arena_group"]}
jjc创建日：{arena_str}
pjjc场次：{info["grand_arena_group"]}
pjjc创建日：{grand_str}
角色数：{info.get("unit_num", "-")}
""",
        at_sender=True,
    )


@sv.on_fullmatch(("订阅状态查询", "查询订阅状态"))
async def send_arena_sub_status(bot, ev):
    """列出该用户所有订阅（含编号、uid、通知群、开关），用于管理操作。"""
    qq = str(ev["user_id"])
    rows_data = _arena_svc.get_subscription_status_rows(qq)
    if not rows_data:
        await bot.finish(ev, "您还未绑定竞技场", at_sender=True)
        return
    img = render_subscription_status_cq(rows_data)
    await bot.finish(ev, img, at_sender=True)


@sv.on_rex(r"(启用|停止)(公主)?竞技场订阅 ?(\d+)?")
async def change_arena_sub(bot, ev):
    is_grand = ev["match"].group(2) is not None
    enable = ev["match"].group(1) == "启用"
    action_str = ev["match"].group(0).split(" ")[0]
    qq = str(ev["user_id"])
    index_str = ev["match"].group(3)
    index = int(index_str) if index_str else None

    if is_grand:
        changed = _arena_svc.set_toggle(qq, index, arena_on=None, grand_arena_on=enable)
    else:
        changed = _arena_svc.set_toggle(qq, index, arena_on=enable, grand_arena_on=None)

    if changed:
        _arena_svc.save_config()
        await bot.finish(ev, f"{action_str}成功", at_sender=True)
    else:
        await bot.finish(ev, "您还未绑定竞技场或编号无效", at_sender=True)


@sv.on_prefix("删除竞技场订阅")
async def delete_arena_sub(bot, ev):
    qq = str(ev["user_id"])
    text = ev.message.extract_plain_text().strip()
    if not text:
        rows_data = _arena_svc.get_subscription_status_rows(qq)
        if not rows_data:
            await bot.finish(ev, "您还未绑定竞技场", at_sender=True)
            return
        lines = [
            f"{r.index}. {r.uid} (jjc:{'开' if r.arena_on else '关'} pjjc:{'开' if r.grand_arena_on else '关'})"
            for r in rows_data
        ]
        await bot.finish(
            ev,
            "请指定编号，例如：删除竞技场订阅 1\n当前订阅：\n" + "\n".join(lines),
            at_sender=True,
        )
        return
    try:
        index = int(text)
    except ValueError:
        await bot.finish(ev, "请输入有效编号（数字）", at_sender=True)
        return
    if _arena_svc.unbind(qq, index):
        _arena_svc.save_config()
        await bot.finish(ev, f"删除订阅 {index} 成功", at_sender=True)
    else:
        await bot.finish(ev, f"编号 {index} 不存在", at_sender=True)


@sv.on_prefix("转移竞技场订阅")
async def move_arena_sub(bot, ev):
    """将指定编号订阅的通知群改为当前群。"""
    qq = str(ev["user_id"])
    gid = str(ev["group_id"])
    text = ev.message.extract_plain_text().strip()
    if not text:
        await bot.finish(ev, "请指定编号，例如：转移竞技场订阅 1", at_sender=True)
        return
    try:
        index = int(text)
    except ValueError:
        await bot.finish(ev, "请输入有效编号（数字）", at_sender=True)
        return
    if _arena_svc.move_group(qq, index, gid):
        _arena_svc.save_config()
        await bot.finish(ev, f"订阅 {index} 的通知群已改为当前群", at_sender=True)
    else:
        await bot.finish(ev, f"编号 {index} 不存在", at_sender=True)


# ============================================================
# 群通缉指令
# ============================================================


async def _get_user_name(uid: str) -> Optional[str]:
    info = cache_db.get_user_info(uid)
    if info and "user_name" in info:
        return info["user_name"]
    try:
        res = await get_profile(uid)
        cache_db.cache_user_info(uid, res)
        return res["user_name"]
    except ApiException:
        return None


@sv.on_rex(r"^通缉 ?(\d{13})$")
async def on_wanted_bind(bot, ev):
    gid = str(ev["group_id"])
    uid = ev["match"].group(1)
    l = wanted_binds[gid] if gid in wanted_binds else []
    changed = False
    async with _wanted_lck:
        if len(l) >= 30:
            await bot.finish(
                ev, "最大通缉上限为25人，请移除部分目标后再添加新目标。", at_sender=True
            )
            return
        if uid not in l:
            l.append(uid)
            wanted_binds[gid] = l
            _save_wanted_binds()
            changed = True
    user_name = await _get_user_name(uid)
    if changed:
        msg = f"通缉 {user_name} 成功" if user_name else "通缉成功"
    else:
        msg = f"{user_name} 已被通缉" if user_name else "目标已被通缉"
    await bot.finish(ev, msg, at_sender=True)


@sv.on_rex(r"^关注 ?(\d{13})$")
async def on_watch_bind(bot, ev):
    gid = str(ev["group_id"])
    uid = ev["match"].group(1)
    w = watch_binds[gid] if gid in watch_binds else []
    changed = False
    async with _wanted_lck:
        if uid not in w:
            w.append(uid)
            watch_binds[gid] = w
            _save_wanted_binds()
            changed = True
    user_name = await _get_user_name(uid)
    if changed:
        msg = f"关注 {user_name} 成功" if user_name else "关注成功"
    else:
        msg = f"{user_name} 已被关注" if user_name else "目标已被关注"
    await bot.finish(ev, msg, at_sender=True)


@sv.on_rex(r"^逮捕 ?(\d{13})$")
async def on_arrest_bind(bot, ev):
    gid = str(ev["group_id"])
    uid = ev["match"].group(1)
    l = wanted_binds[gid] if gid in wanted_binds else []
    changed = False
    async with _wanted_lck:
        if uid in l:
            l.remove(uid)
            wanted_binds[gid] = l
            _save_wanted_binds()
            changed = True
    user_name = await _get_user_name(uid)
    if changed:
        msg = f"已逮捕通缉犯 {user_name}" if user_name else "已逮捕通缉犯"
    else:
        msg = f"{user_name} 未被通缉" if user_name else "目标未被通缉"
    await bot.finish(ev, msg, at_sender=True)


@sv.on_rex(r"^取关 ?(\d{13})$")
async def on_unwatch_bind(bot, ev):
    gid = str(ev["group_id"])
    uid = ev["match"].group(1)
    l = watch_binds[gid] if gid in watch_binds else []
    changed = False
    async with _wanted_lck:
        if uid in l:
            l.remove(uid)
            watch_binds[gid] = l
            _save_wanted_binds()
            changed = True
    user_name = await _get_user_name(uid)
    if changed:
        msg = f"已取关 {user_name}" if user_name else "已取关"
    else:
        msg = f"{user_name} 未被关注" if user_name else "目标未被关注"
    await bot.finish(ev, msg, at_sender=True)


@sv.on_fullmatch(("通缉犯概要", "lswts"))
async def send_wanted_summary(bot, ev):
    gid = str(ev["group_id"])
    async with _wanted_lck:
        ids = list(wanted_binds.get(gid, []))
        wids = list(watch_binds.get(gid, []))
    if wids:
        ids.append("watch")
        ids.extend(wids)
    try:
        await send_summary(ids, cache_db, bot, ev)
    except ApiException as e:
        await bot.finish(ev, f"查询出错，{e}", at_sender=True)
