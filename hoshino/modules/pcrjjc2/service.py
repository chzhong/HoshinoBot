"""
service.py - pcrjjc2 Controller 层

职责：
  - 创建 SafeService（sv）
  - 模块导入时自完成订阅数据迁移 + ArenaService 初始化
  - 注册 cron 调度任务
  - 注册命令 handler（薄层：参数解析 + 权限判断 → 调用各模块方法）
"""

import random
import time
from os.path import dirname, join
from typing import Optional, Tuple

from hoshino import get_bot
from hoshino.safeservice import SafeService

from .arena_client import ApiException, get_profile
from .arena_service import ArenaService, render_subscription_status_cq
from .config_loader import load_config
from .jjcdata import jjcdata
from .schema import WantedItem
from .service_help import sv_help

random.seed()

sv = SafeService("竞技场推送", help_=sv_help, bundle="pcr查询")

cache_db = jjcdata()

# ── 自完成初始化 ──────────────────────────────────────────────────────
# 订阅：从 config.yaml 的 subscription.items 加载；
#       若 config.yaml 中无 items 且旧 binds.json 存在，则自动迁移并写回 config.yaml
# 通缉：从 config.yaml 的 wanted-list 加载；
#       若 config.yaml 中无通缉数据且旧 wanted_binds.json 存在，则自动迁移并写回 config.yaml

_curpath = dirname(__file__)
_binds_path = join(_curpath, "binds.json")
_wanted_path = join(_curpath, "wanted_binds.json")

BACKUP_MIGRATED = True

_cfg = load_config()
_arena_svc = ArenaService(_cfg, cache_db, get_bot(), sv.logger)

# 自动迁移旧数据（若存在）
_arena_svc.migrate(
    binds_path=_binds_path, wanted_path=_wanted_path, backup=BACKUP_MIGRATED
)

# ============================================================
# 调度任务
# ============================================================


@sv.scheduled_job("cron", second=0)
async def on_schedule():
    if _arena_svc is None:
        return
    _arena_svc.on_schedule()


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


@sv.on_rex(r"^竞技场查询\s*(\d+)?$")
async def on_query_arena(bot, ev):
    """查询本群绑定的 uid 的实时排名。不带参数时查询所有，带 uid|idx 时查询单个。"""
    uid_or_idx = ev["match"].group(1)
    qq = str(ev["user_id"])
    gid = str(ev["group_id"])
    try:
        ranks = await _arena_svc.query_group_ranks(qq, gid, uid_or_idx)
    except ValueError as e:
        await bot.finish(ev, str(e), at_sender=True)
        return
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


@sv.on_rex(r"^详细查询\s*(.+)?$")
async def on_query_arena_detail(bot, ev):
    """查询单个 uid 的详细信息（uid|idx 省略时取本群第一个绑定）。"""
    uid_or_idx = ev["match"].group(1)
    if uid_or_idx:
        uid_or_idx = uid_or_idx.strip()
    qq = str(ev["user_id"])
    gid = str(ev["group_id"])
    try:
        info = await _arena_svc.query_detail(qq, gid, uid_or_idx)
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
# 群通缉指令（新逻辑）
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


def _parse_uid_or_idx(text: str, gid: str) -> Tuple[Optional[str], Optional[int]]:
    """
    解析 uid 或索引。
    返回 (uid, idx)，其中一个为 None。
    uid: 13位数字视为 uid
    idx: 其他数字视为索引（1-based）
    """
    text = text.strip()
    if not text.isdigit():
        return (None, None)
    if len(text) == 13:
        return (text, None)
    try:
        idx = int(text)
        return (None, idx)
    except ValueError:
        return (None, None)


@sv.on_rex(
    r"^群?通缉(jjc|pjjc)?\s*(\d{13})(?:\s+(.+))?$|^g?wanted(jjc|pjjc)?\s+(\d{13})(?:\s+(.+))?$"
)
async def on_group_wanted_add(bot, ev):
    """群通缉 [jjc|pjjc] uid [备注] / g?wanted [jjc|pjjc] uid [备注]"""
    # 判断是中文还是英文指令
    if ev["match"].group(2) is not None:
        # 中文指令
        arena_type = ev["match"].group(1)
        uid = ev["match"].group(2)
        note = ev["match"].group(3) or ""
    else:
        # 英文指令
        arena_type = ev["match"].group(4)
        uid = ev["match"].group(5)
        note = ev["match"].group(6) or ""

    gid = str(ev["group_id"])

    item = WantedItem(id=uid, gid=gid, note=note)

    # 根据 arena_type 设置开关
    if arena_type == "jjc":
        item.arena_on = True
        item.grand_arena_on = False
    elif arena_type == "pjjc":
        item.arena_on = False
        item.grand_arena_on = True

    result = _arena_svc.wanted_manager.add_group(gid, item)

    if result == "ok":
        _arena_svc.save_config()
        user_name = await _get_user_name(uid)
        arena_hint = ""
        if arena_type == "jjc":
            arena_hint = "（仅监控jjc）"
        elif arena_type == "pjjc":
            arena_hint = "（仅监控pjjc）"
        msg = f"通缉 {user_name or uid} 成功{arena_hint}"
        await bot.finish(ev, msg, at_sender=True)
    elif result == "dup":
        user_name = await _get_user_name(uid)
        await bot.finish(ev, f"{user_name or uid} 已被通缉", at_sender=True)
    else:  # full
        await bot.finish(
            ev, "群通缉已达上限（30人），请先逮捕部分通缉犯", at_sender=True
        )


@sv.on_rex(
    r"^群?(设置|取消|清空)?备注\s*(\d+)(?:\s+(.+))?$|^g?(set|clear)?-note\s+(\d+)(?:\s+(.+))?$"
)
async def on_group_wanted_note(bot, ev):
    """群[设置|取消|清空]备注 uid|idx [备注] / g?[set|clear]-note uid|idx [备注]"""
    # 判断是中文还是英文指令
    if ev["match"].group(2) is not None:
        # 中文指令
        action = ev["match"].group(1) or "设置"
        uid_or_idx_str = ev["match"].group(2)
        note = ev["match"].group(3) or ""
    else:
        # 英文指令
        action_en = ev["match"].group(4)  # None, 'set', or 'clear'
        uid_or_idx_str = ev["match"].group(5)
        note = ev["match"].group(6) or ""
        # 转换英文 action 为中文
        if action_en == "clear":
            action = "清空"
        else:
            action = "设置"

    gid = str(ev["group_id"])

    uid, idx = _parse_uid_or_idx(uid_or_idx_str, gid)

    # 获取 item
    if uid:
        item = _arena_svc.wanted_manager.get_group_by_uid(gid, uid)
    elif idx:
        item = _arena_svc.wanted_manager.get_group_by_index(gid, idx)
    else:
        await bot.finish(ev, "请输入有效的 uid 或编号", at_sender=True)
        return

    if not item:
        await bot.finish(ev, "未找到该通缉犯", at_sender=True)
        return

    # 处理备注
    if action in ["取消", "清空"]:
        note = ""

    if _arena_svc.wanted_manager.set_group_note(gid, item.id, note):
        _arena_svc.save_config()
        user_name = await _get_user_name(item.id)
        if note:
            await bot.finish(
                ev, f"已设置 {user_name or item.id} 的备注为：{note}", at_sender=True
            )
        else:
            await bot.finish(
                ev, f"已清空 {user_name or item.id} 的备注", at_sender=True
            )
    else:
        await bot.finish(ev, "设置失败", at_sender=True)


@sv.on_rex(
    r"^群?(设置|修改|更改)?通缉级别\s*(\d+)\s+(\d)$|^g?notice-level\s+(\d+)\s+(\d)$"
)
async def on_group_wanted_level(bot, ev):
    """群[设置|修改|更改]通缉级别 uid|idx level / g?notice-level uid|idx level"""
    # 判断是中文还是英文指令
    if ev["match"].group(2) is not None:
        # 中文指令
        uid_or_idx_str = ev["match"].group(2)
        level = int(ev["match"].group(3))
    else:
        # 英文指令
        uid_or_idx_str = ev["match"].group(4)
        level = int(ev["match"].group(5))

    gid = str(ev["group_id"])

    if level < 0 or level > 5:
        await bot.finish(ev, "通缉级别范围为 0-5", at_sender=True)
        return

    uid, idx = _parse_uid_or_idx(uid_or_idx_str, gid)

    # 获取 item
    if uid:
        item = _arena_svc.wanted_manager.get_group_by_uid(gid, uid)
    elif idx:
        item = _arena_svc.wanted_manager.get_group_by_index(gid, idx)
    else:
        await bot.finish(ev, "请输入有效的 uid 或编号", at_sender=True)
        return

    if not item:
        await bot.finish(ev, "未找到该通缉犯", at_sender=True)
        return

    if _arena_svc.wanted_manager.set_group_notice_level(gid, item.id, level):
        _arena_svc.save_config()
        user_name = await _get_user_name(item.id)
        await bot.finish(
            ev, f"已将 {user_name or item.id} 的通缉级别设为 {level}", at_sender=True
        )
    else:
        await bot.finish(ev, "设置失败", at_sender=True)


@sv.on_rex(
    r"^群?(开启|关闭|取消)?通报(jjc|pjjc)\s*(\d+)$|^g(un|not-)?notice-(jjc|pjjc)\s+(\d+)$"
)
async def on_group_wanted_toggle(bot, ev):
    """群[开启|关闭|取消]通报[jjc|pjjc] uid|idx / g[un|not-]notice-[jjc|pjjc] uid|idx"""
    # 判断是中文还是英文指令
    if ev["match"].group(2) is not None:
        # 中文指令
        action = ev["match"].group(1) or "开启"
        arena_type = ev["match"].group(2)
        uid_or_idx_str = ev["match"].group(3)
        enable = action == "开启"
    else:
        # 英文指令
        prefix = ev["match"].group(4)  # None, 'un', or 'not-'
        arena_type = ev["match"].group(5)
        uid_or_idx_str = ev["match"].group(6)
        enable = prefix is None  # 无前缀表示开启，有前缀表示关闭

    gid = str(ev["group_id"])

    uid, idx = _parse_uid_or_idx(uid_or_idx_str, gid)

    if uid:
        item = _arena_svc.wanted_manager.get_group_by_uid(gid, uid)
    elif idx:
        item = _arena_svc.wanted_manager.get_group_by_index(gid, idx)
    else:
        await bot.finish(ev, "请输入有效的 uid 或编号", at_sender=True)
        return

    if not item:
        await bot.finish(ev, "未找到该通缉犯", at_sender=True)
        return

    if arena_type == "jjc":
        success = _arena_svc.wanted_manager.set_group_watch_toggle(
            gid, item.id, arena_on=enable
        )
    else:  # pjjc
        success = _arena_svc.wanted_manager.set_group_watch_toggle(
            gid, item.id, grand_arena_on=enable
        )

    if success:
        _arena_svc.save_config()
        user_name = await _get_user_name(item.id)
        action_desc = "开启" if enable else "关闭"
        await bot.finish(
            ev,
            f"已{action_desc} {user_name or item.id} 的{arena_type}通报",
            at_sender=True,
        )
    else:
        await bot.finish(ev, "设置失败", at_sender=True)


@sv.on_rex(r"^群?逮捕(jjc|pjjc)?\s*(\d+)$|^g(unwanted|capture)(-jjc|-pjjc)?\s+(\d+)$")
async def on_group_wanted_arrest(bot, ev):
    """群逮捕[jjc|pjjc] uid|idx / g[unwanted|capture][-jjc|-pjjc] uid|idx"""
    # 判断是中文还是英文指令
    if ev["match"].group(2) is not None:
        # 中文指令
        arena_type = ev["match"].group(1)  # None, 'jjc', or 'pjjc'
        uid_or_idx_str = ev["match"].group(2)
    else:
        # 英文指令
        arena_suffix = ev["match"].group(4)  # None, '-jjc', or '-pjjc'
        uid_or_idx_str = ev["match"].group(5)
        # 转换英文 arena_suffix 为 arena_type
        if arena_suffix == "-jjc":
            arena_type = "jjc"
        elif arena_suffix == "-pjjc":
            arena_type = "pjjc"
        else:
            arena_type = None

    gid = str(ev["group_id"])

    uid, idx = _parse_uid_or_idx(uid_or_idx_str, gid)

    if uid:
        item = _arena_svc.wanted_manager.get_group_by_uid(gid, uid)
    elif idx:
        item = _arena_svc.wanted_manager.get_group_by_index(gid, idx)
    else:
        await bot.finish(ev, "请输入有效的 uid 或编号", at_sender=True)
        return

    if not item:
        await bot.finish(ev, "未找到该通缉犯", at_sender=True)
        return

    user_name = await _get_user_name(item.id)

    # 如果指定了 arena_type，只关闭对应通报
    if arena_type:
        if arena_type == "jjc":
            _arena_svc.wanted_manager.set_group_watch_toggle(
                gid, item.id, arena_on=False
            )
            _arena_svc.save_config()
            await bot.finish(
                ev, f"已关闭 {user_name or item.id} 的jjc通报", at_sender=True
            )
        else:  # pjjc
            _arena_svc.wanted_manager.set_group_watch_toggle(
                gid, item.id, grand_arena_on=False
            )
            _arena_svc.save_config()
            await bot.finish(
                ev, f"已关闭 {user_name or item.id} 的pjjc通报", at_sender=True
            )
    else:
        # 没有指定 arena_type，删除整个通缉
        if _arena_svc.wanted_manager.remove_group(gid, item.id):
            _arena_svc.save_config()
            await bot.finish(ev, f"已逮捕通缉犯 {user_name or item.id}", at_sender=True)
        else:
            await bot.finish(ev, "逮捕失败", at_sender=True)


# ============================================================
# 个人通缉指令（新逻辑）
# ============================================================


@sv.on_rex(
    r"^(个人)?标记(jjc|pjjc)?\s*(\d{13})(?:\s+(.+))?$|^mark(-jjc|-pjjc)?\s+(\d{13})(?:\s+(.+))?$"
)
async def on_personal_wanted_add(bot, ev):
    """(个人)?标记[jjc|pjjc] uid [备注] / mark[-jjc|-pjjc] uid [备注]"""
    # 解析匹配组
    if ev["match"].group(1) is not None or ev["match"].group(3) is not None:
        # 中文命令
        arena_type = ev["match"].group(2)  # None, 'jjc', or 'pjjc'
        uid = ev["match"].group(3)
        note = ev["match"].group(4) or ""
    else:
        # 英文命令
        arena_flag = ev["match"].group(5)  # None, '-jjc', or '-pjjc'
        uid = ev["match"].group(6)
        note = ev["match"].group(7) or ""
        arena_type = arena_flag[1:] if arena_flag else None  # 去掉前导 '-'

    qq = str(ev["user_id"])
    gid = str(ev["group_id"])

    # 检查是否已存在
    existing = _arena_svc.wanted_manager.get_personal_by_uid(qq, uid)

    if existing:
        # 已存在，更新通报开关
        if arena_type == "jjc":
            _arena_svc.wanted_manager.set_personal_watch_toggle(qq, uid, arena_on=True)
            _arena_svc.save_config()
            user_name = await _get_user_name(uid)
            await bot.finish(
                ev,
                f"{user_name or uid} 已在个人通缉列表中，已开启jjc通报",
                at_sender=True,
            )
        elif arena_type == "pjjc":
            _arena_svc.wanted_manager.set_personal_watch_toggle(
                qq, uid, grand_arena_on=True
            )
            _arena_svc.save_config()
            user_name = await _get_user_name(uid)
            await bot.finish(
                ev,
                f"{user_name or uid} 已在个人通缉列表中，已开启pjjc通报",
                at_sender=True,
            )
        else:
            user_name = await _get_user_name(uid)
            await bot.finish(
                ev, f"{user_name or uid} 已在个人通缉列表中", at_sender=True
            )
    else:
        # 新增
        item = WantedItem(id=uid, gid=gid, by=qq, note=note)

        # 根据 arena_type 设置开关
        if arena_type == "jjc":
            item.arena_on = True
            item.grand_arena_on = False
        elif arena_type == "pjjc":
            item.arena_on = False
            item.grand_arena_on = True

        result = _arena_svc.wanted_manager.add_personal(qq, item)

        if result == "ok":
            _arena_svc.save_config()
            user_name = await _get_user_name(uid)
            arena_hint = ""
            if arena_type == "jjc":
                arena_hint = "（仅监控jjc）"
            elif arena_type == "pjjc":
                arena_hint = "（仅监控pjjc）"
            msg = f"标记 {user_name or uid} 成功{arena_hint}"
            await bot.finish(ev, msg, at_sender=True)
        elif result == "dup":
            user_name = await _get_user_name(uid)
            await bot.finish(ev, f"{user_name or uid} 已被标记", at_sender=True)
        else:  # full
            await bot.finish(
                ev, "个人通缉已达上限（8人），请先取消部分标记", at_sender=True
            )


@sv.on_rex(
    r"^个人(设置|取消|清空)?备注\s*(\d+)(?:\s+(.+))?$|^(set-|clear-)?mark-note\s+(\d+)(?:\s+(.+))?$"
)
async def on_personal_wanted_note(bot, ev):
    """个人[设置|取消|清空]备注 uid|idx [备注] / [set-|clear-]mark-note uid|idx [备注]"""
    # 解析匹配组
    if ev["match"].group(1) is not None or ev["match"].group(2) is not None:
        # 中文命令
        action = ev["match"].group(1) or "设置"
        uid_or_idx_str = ev["match"].group(2)
        note = ev["match"].group(3) or ""
    else:
        # 英文命令
        action_flag = ev["match"].group(4)  # None, 'set-', or 'clear-'
        uid_or_idx_str = ev["match"].group(5)
        note = ev["match"].group(6) or ""
        if action_flag == "set-":
            action = "设置"
        elif action_flag == "clear-":
            action = "清空"
        else:
            action = "设置"

    qq = str(ev["user_id"])
    uid, idx = _parse_uid_or_idx(uid_or_idx_str, "")  # gid 参数不需要

    # 获取 item
    if uid:
        item = _arena_svc.wanted_manager.get_personal_by_uid(qq, uid)
    elif idx:
        item = _arena_svc.wanted_manager.get_personal_by_index(qq, idx)
    else:
        await bot.finish(
            ev, "格式错误，请使用：个人备注 uid|编号 备注内容", at_sender=True
        )
        return

    if not item:
        await bot.finish(ev, "未找到该标记", at_sender=True)
        return

    # 处理备注
    if action in ["取消", "清空"]:
        note = ""
    elif action == "设置":
        if not note:
            await bot.finish(ev, "设置备注时不能为空", at_sender=True)
            return
        if len(note) > 10:
            await bot.finish(ev, "备注最多10个字符", at_sender=True)
            return

    if _arena_svc.wanted_manager.set_personal_note(qq, item.id, note):
        _arena_svc.save_config()
        user_name = await _get_user_name(item.id)
        if note:
            await bot.finish(
                ev, f"已设置 {user_name or item.id} 的备注为：{note}", at_sender=True
            )
        else:
            await bot.finish(
                ev, f"已清空 {user_name or item.id} 的备注", at_sender=True
            )
    else:
        await bot.finish(ev, "设置失败", at_sender=True)


@sv.on_rex(
    r"^个人(设置|修改|更改)?通缉级别\s*(\d+)\s+(\d)$|^mark-notice-level\s+(\d+)\s+(\d)$"
)
async def on_personal_wanted_level(bot, ev):
    """个人[设置|修改|更改]通缉级别 uid|idx level / mark-notice-level uid|idx level"""
    # 解析匹配组
    if ev["match"].group(1) is not None or ev["match"].group(2) is not None:
        # 中文命令
        uid_or_idx_str = ev["match"].group(2)
        level = int(ev["match"].group(3))
    else:
        # 英文命令
        uid_or_idx_str = ev["match"].group(4)
        level = int(ev["match"].group(5))

    qq = str(ev["user_id"])

    if level < 0 or level > 5:
        await bot.finish(ev, "通缉级别范围为 0-5", at_sender=True)
        return

    uid, idx = _parse_uid_or_idx(uid_or_idx_str, "")

    # 获取 item
    if uid:
        item = _arena_svc.wanted_manager.get_personal_by_uid(qq, uid)
    elif idx:
        item = _arena_svc.wanted_manager.get_personal_by_index(qq, idx)
    else:
        await bot.finish(
            ev, "格式错误，请使用：个人通缉级别 uid|编号 级别", at_sender=True
        )
        return

    if not item:
        await bot.finish(ev, "未找到该标记", at_sender=True)
        return

    if _arena_svc.wanted_manager.set_personal_notice_level(qq, item.id, level):
        _arena_svc.save_config()
        user_name = await _get_user_name(item.id)
        await bot.finish(
            ev, f"已将 {user_name or item.id} 的通缉级别设为 {level}", at_sender=True
        )
    else:
        await bot.finish(ev, "设置失败", at_sender=True)


@sv.on_rex(r"^(群|个人)?(缓和|注意|(今日|重点)?(关照|击剑))通缉犯\s*(\d+)$")
async def on_wanted_level_shortcut(bot, ev):
    """统一的通缉级别快捷指令：(群|个人)?(缓和|注意|(今日|重点)?(关照|击剑))通缉犯 uid|idx"""
    prefix = ev["match"].group(1)  # None, '群', or '个人'
    action = ev["match"].group(2)  # '缓和', '注意', '关照', '击剑', '今日关照', etc.
    modifier = ev["match"].group(4)  # None, '今日', or '重点'
    uid_or_idx_str = ev["match"].group(6)

    # 确定级别
    if action == "缓和":
        level = 1
    elif action == "注意":
        level = 2
    elif modifier == "今日":
        level = 4
    elif modifier == "重点":
        level = 5
    else:  # 关照或击剑，无修饰词
        level = 3

    qq = str(ev["user_id"])
    gid = str(ev["group_id"])
    uid, idx = _parse_uid_or_idx(uid_or_idx_str, gid)

    # 判断是群通缉还是个人通缉
    is_personal = prefix == "个人"
    is_group = prefix == "群" or prefix is None  # 无前缀默认为群通缉

    if is_personal:
        # 个人通缉
        if uid:
            item = _arena_svc.wanted_manager.get_personal_by_uid(qq, uid)
        elif idx:
            item = _arena_svc.wanted_manager.get_personal_by_index(qq, idx)
        else:
            return  # 忽略格式错误

        if not item:
            return  # 忽略未找到

        if _arena_svc.wanted_manager.set_personal_notice_level(qq, item.id, level):
            _arena_svc.save_config()
            user_name = await _get_user_name(item.id)
            level_desc = {
                1: "缓和",
                2: "注意",
                3: "结算前高频",
                4: "今日高频",
                5: "永久高频",
            }
            await bot.finish(
                ev,
                f"已调整对 {user_name or item.id} 的通缉（级别→{level}，{level_desc[level]}）",
                at_sender=True,
            )
    elif is_group:
        # 群通缉
        if uid:
            item = _arena_svc.wanted_manager.get_group_by_uid(gid, uid)
        elif idx:
            item = _arena_svc.wanted_manager.get_group_by_index(gid, idx)
        else:
            return  # 忽略格式错误

        if not item:
            return  # 忽略未找到

        if _arena_svc.wanted_manager.set_group_notice_level(gid, item.id, level):
            _arena_svc.save_config()
            user_name = await _get_user_name(item.id)
            level_desc = {
                1: "缓和",
                2: "注意",
                3: "结算前高频",
                4: "今日高频",
                5: "永久高频",
            }
            await bot.finish(
                ev,
                f"已调整对 {user_name or item.id} 的通缉（级别→{level}，{level_desc[level]}）",
                at_sender=True,
            )


@sv.on_rex(
    r"^个人(开启|关闭|取消)?通报(jjc|pjjc)\s*(\d+)$|^mark-(un|not-)?notice-(jjc|pjjc)\s+(\d+)$"
)
async def on_personal_wanted_toggle(bot, ev):
    """个人[开启|关闭|取消]通报[jjc|pjjc] uid|idx / mark-[un|not-]notice-[jjc|pjjc] uid|idx"""
    # 解析匹配组
    if ev["match"].group(1) is not None or ev["match"].group(2) is not None:
        # 中文命令
        action = ev["match"].group(1) or "开启"
        arena_type = ev["match"].group(2)  # 'jjc' or 'pjjc'
        uid_or_idx_str = ev["match"].group(3)
    else:
        # 英文命令
        action_flag = ev["match"].group(4)  # None, 'un', or 'not-'
        arena_type = ev["match"].group(5)  # 'jjc' or 'pjjc'
        uid_or_idx_str = ev["match"].group(6)
        action = "关闭" if action_flag else "开启"

    qq = str(ev["user_id"])
    enable = action == "开启"

    uid, idx = _parse_uid_or_idx(uid_or_idx_str, "")

    if uid:
        item = _arena_svc.wanted_manager.get_personal_by_uid(qq, uid)
    elif idx:
        item = _arena_svc.wanted_manager.get_personal_by_index(qq, idx)
    else:
        await bot.finish(
            ev, f"格式错误，请使用：个人通报{arena_type} uid|编号", at_sender=True
        )
        return

    if not item:
        await bot.finish(ev, "未找到该标记", at_sender=True)
        return

    if arena_type == "jjc":
        success = _arena_svc.wanted_manager.set_personal_watch_toggle(
            qq, item.id, arena_on=enable
        )
    else:  # pjjc
        success = _arena_svc.wanted_manager.set_personal_watch_toggle(
            qq, item.id, grand_arena_on=enable
        )

    if success:
        _arena_svc.save_config()
        user_name = await _get_user_name(item.id)
        action_desc = "开启" if enable else "关闭"
        await bot.finish(
            ev,
            f"已{action_desc} {user_name or item.id} 的{arena_type}通报",
            at_sender=True,
        )
    else:
        await bot.finish(ev, "设置失败", at_sender=True)


@sv.on_rex(r"^(个人)?取消标记(jjc|pjjc)?\s*(\d+)$|^unmark(-jjc|-pjjc)?\s+(\d+)$")
async def on_personal_wanted_unmark(bot, ev):
    """(个人)?取消标记[jjc|pjjc] uid|idx / unmark[-jjc|-pjjc] uid|idx"""
    # 解析匹配组
    if ev["match"].group(1) is not None or ev["match"].group(3) is not None:
        # 中文命令
        arena_type = ev["match"].group(2)  # None, 'jjc', or 'pjjc'
        uid_or_idx_str = ev["match"].group(3)
    else:
        # 英文命令
        arena_flag = ev["match"].group(4)  # None, '-jjc', or '-pjjc'
        uid_or_idx_str = ev["match"].group(5)
        arena_type = arena_flag[1:] if arena_flag else None  # 去掉前导 '-'

    qq = str(ev["user_id"])
    uid, idx = _parse_uid_or_idx(uid_or_idx_str, "")

    if uid:
        item = _arena_svc.wanted_manager.get_personal_by_uid(qq, uid)
    elif idx:
        item = _arena_svc.wanted_manager.get_personal_by_index(qq, idx)
    else:
        await bot.finish(ev, "格式错误，请使用：取消标记 uid|编号", at_sender=True)
        return

    if not item:
        await bot.finish(ev, "未找到该标记", at_sender=True)
        return

    user_name = await _get_user_name(item.id)

    # 如果指定了 arena_type，只关闭对应通报
    if arena_type:
        if arena_type == "jjc":
            _arena_svc.wanted_manager.set_personal_watch_toggle(
                qq, item.id, arena_on=False
            )
            _arena_svc.save_config()
            await bot.finish(
                ev, f"已关闭 {user_name or item.id} 的jjc通报", at_sender=True
            )
        else:  # pjjc
            _arena_svc.wanted_manager.set_personal_watch_toggle(
                qq, item.id, grand_arena_on=False
            )
            _arena_svc.save_config()
            await bot.finish(
                ev, f"已关闭 {user_name or item.id} 的pjjc通报", at_sender=True
            )
    else:
        # 没有指定 arena_type，删除整个标记
        if _arena_svc.wanted_manager.remove_personal(qq, item.id):
            _arena_svc.save_config()
            await bot.finish(ev, f"已取消标记 {user_name or item.id}", at_sender=True)
        else:
            await bot.finish(ev, "取消失败", at_sender=True)


@sv.on_fullmatch(("个人通缉犯概要", "我的通缉", "lspwts"))
async def send_my_wanted(bot, ev):
    """列出个人通缉列表。"""
    qq = str(ev["user_id"])
    gid = str(ev["group_id"])
    _, personal_rows = _arena_svc.get_wanted_summary_rows(
        qq, gid, filter_type="personal"
    )
    if not personal_rows:
        await bot.finish(ev, "您还没有个人通缉", at_sender=True)
        return
    from .wanted_summary_formatter import render_wanted_summary_as_cq

    msg = render_wanted_summary_as_cq([], personal_rows)
    await bot.finish(ev, msg, at_sender=False)


@sv.on_fullmatch(("群通缉犯概要", "群通缉", "lsgwts"))
async def send_group_wanted_summary(bot, ev):
    """群通缉犯概要 - 只显示群通缉"""
    qq = str(ev["user_id"])
    gid = str(ev["group_id"])
    group_rows, _ = _arena_svc.get_wanted_summary_rows(qq, gid, filter_type="group")
    from .wanted_summary_formatter import render_wanted_summary_as_cq

    if not group_rows:
        await bot.finish(ev, "本群还没有群通缉", at_sender=False)
        return

    msg = render_wanted_summary_as_cq(group_rows, [])
    await bot.finish(ev, msg, at_sender=False)


@sv.on_fullmatch(("通缉犯概要", "lswts"))
async def send_wanted_summary(bot, ev):
    qq = str(ev["user_id"])
    gid = str(ev["group_id"])
    group_rows, personal_rows = _arena_svc.get_wanted_summary_rows(qq, gid)
    from .wanted_summary_formatter import render_wanted_summary_as_cq

    msg = render_wanted_summary_as_cq(group_rows, personal_rows)
    await bot.finish(ev, msg, at_sender=False)
