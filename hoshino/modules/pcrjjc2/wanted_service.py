"""
wanted_service.py - 通缉监控 Service 层

职责：
  - legacy_should_check()：旧的硬编码时段判断（通缉暂用旧逻辑）
  - legacy_check_wanted_dict()：通缉/关注 uid 的排名和上线检测（旧 dict 格式数据）
"""

import asyncio
import random
import time
from copy import deepcopy
from datetime import datetime
from traceback import format_exc
from typing import Dict, List

import pytz
from nonebot import get_bot

from .arena_client import ApiException, get_profile
from .jjcdata import jjcdata

_tz = pytz.timezone("Asia/Shanghai")
random.seed()


async def legacy_should_check(
    *,
    interval: int = 5,
    hot_hours: tuple = (14,),
    hot_interval: int = 2,
    cold_hours: tuple = (2, 3, 4, 5, 6),
    cold_interval: int = 15,
) -> bool:
    """
    旧版时段判断逻辑（硬编码），用于通缉监控。
    与 legacy.py 中的 should_check() 行为一致。
    """
    now = datetime.now(_tz)
    is_hot = now.hour in hot_hours
    is_cold = now.hour in cold_hours

    check = False
    delay = not (now.hour == 15 and now.minute == 0)
    max_delay = 30

    if is_hot:
        check = (now.minute % hot_interval) == 0 or now.minute in (57, 59)
        max_delay = 5
    elif is_cold:
        check = (now.minute % cold_interval) == 0
        max_delay = 30
    else:
        check = (now.minute % interval) == 0
        max_delay = 15

    if check and delay:
        dt = random.randint(0, max_delay)
        await asyncio.sleep(dt)
    return check


def _check_key(d1: Dict, d2: Dict, key: str) -> bool:
    return key in d1 and key in d2


async def legacy_check_wanted_dict(
    wanted_binds: Dict[str, List[str]],
    watch_binds: Dict[str, List[str]],
    cache: jjcdata,
    logger,
) -> None:
    """
    遍历群通缉/关注列表（旧 dict 格式），检测上线、改名、排名变动，推送群消息。
    数据格式与 legacy.py 一致：
        wanted_binds = {gid: [uid, ...]}
        watch_binds  = {gid: [uid, ...]}

    参数：
        wanted_binds - 群通缉 dict（直接引用，供 code=6 时自动清理）
        watch_binds  - 群关注 dict
        cache        - jjcdata Redis DAO 实例
        logger       - sv.logger
    """
    bot = get_bot()
    wanted_notice: Dict[str, str] = {}

    bind_cache = deepcopy(wanted_binds)
    watch_cache = deepcopy(watch_binds)

    for gid in bind_cache:
        wanted_list = bind_cache[gid]
        watch_list = watch_cache.get(gid, [])
        scan_list = list(wanted_list) + [uid for uid in watch_list if uid not in wanted_list]

        for uid in scan_list:
            is_watch_only = uid not in wanted_list

            if uid in wanted_notice:
                msg = wanted_notice[uid]
                if msg != "__NOT_CHANGED__":
                    await bot.send_group_msg(group_id=int(gid), message=msg)
                continue

            try:
                logger.info(f"[wanted] querying uid={uid} for group={gid}")
                res = await get_profile(uid)

                last = cache.get_user_info(uid)
                cache.cache_user_info(uid, res)
                if not last:
                    wanted_notice[uid] = "__NOT_CHANGED__"
                    continue

                # 上线检测
                if (
                    _check_key(res, last, "last_login_time")
                    and (res["last_login_time"] - last["last_login_time"]) > 60 * 3
                ):
                    dt = time.strftime("%H:%M", time.localtime(res["last_login_time"]))
                    login_notice = f"于{dt}上线"
                    wanted_info = "注意逮捕"
                else:
                    login_notice = ""
                    wanted_info = ""

                # 改名检测
                if (
                    _check_key(res, last, "user_name")
                    and res["user_name"] != last["user_name"]
                ):
                    change_name_notice = f" 改名为 {res['user_name']}(UID: {uid}) "
                else:
                    change_name_notice = ""

                # jjc 排名变动
                if res["arena_rank"] != last["arena_rank"]:
                    diff = res["arena_rank"] - last["arena_rank"]
                    change_str = "下降" if diff > 0 else "上升"
                    if diff < 0:
                        cache.cache_user_jjc_challenge(uid)
                    else:
                        is_watch_only = False  # 排名下降时关注也发通知
                    jjc_notice = f"\njjc：{last['arena_rank']}->{res['arena_rank']} {change_str}{abs(diff)}名"
                else:
                    jjc_notice = ""

                # pjjc 排名变动
                if res["grand_arena_rank"] != last["grand_arena_rank"]:
                    diff = res["grand_arena_rank"] - last["grand_arena_rank"]
                    change_str = "下降" if diff > 0 else "上升"
                    if diff < 0:
                        cache.cache_user_pjjc_challenge(uid)
                    else:
                        is_watch_only = False
                    pjjc_notice = f"\npjjc：{last['grand_arena_rank']}->{res['grand_arena_rank']} {change_str}{abs(diff)}名"
                else:
                    pjjc_notice = ""

                if not is_watch_only and (login_notice or change_name_notice or jjc_notice or pjjc_notice):
                    last_name = last.get("user_dname") or last.get("user_name", uid)
                    msg = f"通缉犯 {last_name} " + login_notice + change_name_notice
                    msg += jjc_notice + pjjc_notice
                    if jjc_notice or pjjc_notice:
                        msg += "\n"
                    msg += wanted_info
                    wanted_notice[uid] = msg
                    await bot.send_group_msg(group_id=int(gid), message=msg)
                else:
                    wanted_notice[uid] = "__NOT_CHANGED__"

            except ApiException as e:
                logger.info(f"[wanted] uid={uid} 查询出错\n{format_exc()}")
                if e.code == 6:
                    logger.info(f"[wanted] uid={uid} 无效，已自动移除")
                    if gid in wanted_binds and uid in wanted_binds[gid]:
                        wanted_binds[gid].remove(uid)
            except Exception:
                logger.info(f"[wanted] uid={uid} 查询出错\n{format_exc()}")

