"""
rank_monitor.py - 排名监控核心逻辑

职责：
  - should_check()：根据 config 的 periods + check_config 判断本分钟是否检测
  - fetch_and_update()：查询单个 uid 的最新排名，对比 Redis 基准，返回 RankDiff
  - build_subscription_lines()：将 RankDiff 转换为订阅通知行（供 arena_service 聚合）
  - build_wanted_message()：将 RankDiff 转换为通缉通报消息（含上线/改名/攻击计数）

此模块不持有任何状态，所有方法为纯函数或接受注入的依赖。
"""

import asyncio
import math
import random
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from traceback import format_exc
from typing import Callable, Dict, List, Literal, Optional, Protocol, Tuple, Union

from typing_extensions import TypeAlias

from .arena_client import ApiException, get_profile
from .config_loader import TZ_CST, get_check_config, get_current_period
from .jjcdata import jjcdata
from .schema import (
    Bot,
    CheckConfigMap,
    Config,
    Logger,
    Period,
    SubscriptionItem,
    WantedItem,
)
from .subscription_manager import SubscriptionManager
from .wanted_manager import WantedDetail, WantedManager, Watcher


@dataclass
class RankDiff:
    """单次排名检测的结果，包含检测前后的全量信息。"""

    uid: str
    last_info: dict  # 检测前 Redis 缓存（含 user_name 等，可能为空 dict）
    new_info: dict  # 本次 API 返回的信息（已写回 Redis）
    last_ranks: Optional[Tuple[int, int]]  # (jjc, pjjc)，首次为 None
    new_ranks: Tuple[int, int]  # (jjc, pjjc)


# ── 频率判断 ──────────────────────────────────────────────────────────


class RandomInt(int):
    _rnd: Optional[random.Random]

    def __new__(cls, v: int, rnd: Optional[random.Random] = None):
        inst = super().__new__(v)
        inst._rnd = rnd
        return inst

    def next(self, rnd: Optional[random.Random] = None):
        _rnd = (rnd or self._rnd) or random
        return _rnd.randint(0, self)

    @property
    def random(self):
        return self._rnd


class RandomFloat(int):
    _rnd: Optional[random.Random]

    def __new__(cls, v: float, rnd: Optional[random.Random] = None):
        inst = super().__new__(v)
        inst._rnd = rnd
        return inst

    def next(self, rnd: Optional[random.Random] = None):
        _rnd = (rnd or self._rnd) or random
        return _rnd.random() * self

    @property
    def random(self):
        return self._rnd


DelayProvider: TypeAlias = Union[float, int, Callable[[], float], None]


class Delayer:
    @staticmethod
    def is_no_delay(delay: Union[int, float, None]):
        return (
            delay is None
            or (isinstance(delay, float) and math.isnan(delay))
            or delay <= 0
        )

    @staticmethod
    def random(delay: Union[int, float, None], rnd: random.Random = None):
        if delay is None or Delayer.is_no_delay(delay):
            return Delayer(None)
        _rnd = rnd or random
        if isinstance(delay, (RandomFloat, RandomInt)):
            return Delayer(lambda: delay.next(rnd))
        elif isinstance(delay, int):
            return Delayer(lambda: _rnd.randint(0, delay))
        else:
            return Delayer(lambda: _rnd.random() * delay)

    @staticmethod
    def fixed(delay: Union[int, float, None]):
        if delay is None or Delayer.is_no_delay(delay):
            return Delayer(None)
        if isinstance(delay, (RandomFloat, RandomInt)):
            return Delayer(lambda: delay.next())
        return Delayer(float(delay))

    def __init__(self, provider: DelayProvider):
        self._provider = provider

    async def wait(self):
        def resolve(p: DelayProvider):
            if callable(p):
                return p()
            elif isinstance(p, (RandomFloat, RandomInt)):
                return p.next()
            return p

        delay = resolve(self._provider)
        if delay is None or Delayer.is_no_delay(delay):
            return
        await asyncio.sleep(delay)


async def should_check(
    periods: List[Period],
    check_config: CheckConfigMap,
    now: Optional[datetime] = None,
) -> bool:
    """
    根据 periods + check_config 判断本分钟是否执行检测，并施加随机延迟。

    settlement（interval=0）：仅 15:00 触发一次，不延迟。
    其余时段：按 interval 取余，在 delay 范围内随机延迟后返回 True。
    """
    now = now or datetime.now(TZ_CST)
    period = get_current_period(periods, now=now)
    period_name = period.name if period else "default"
    cc = get_check_config(check_config, period_name)

    if cc.interval == 0:
        return now.hour == 15 and now.minute == 0

    check = (now.minute % cc.interval) == 0
    if check and cc.delay > 0:
        await asyncio.sleep(random.randint(0, cc.delay))
    return check


# ── API 查询 + Redis 更新 ─────────────────────────────────────────────


class RoundCache:
    """
    round_cache 类型：uid -> RankDiff（或 None 表示首次/查询失败已记录）
    """

    class Entry:
        def __init__(self, lock: asyncio.Lock, key: str, cache: "RoundCache"):
            self._lock = lock
            self._key = key
            self._container = cache

        def __bool__(self):
            return self._key in self._container

        @property
        def value(self):
            return self._container._cache.get(self._key, None)

        @value.setter
        def value(self, value: RankDiff):
            self._container._cache[self._key] = value

        async def __aenter__(self):
            await self._lock.acquire()
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            self._lock.release()
            return False

    def __init__(self):
        self._cache: Dict[str, Optional[RankDiff]] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def __contains__(self, key: str):
        return key in self._cache

    def __getitem__(self, key: str) -> "RoundCache.Entry":
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self.Entry(self._locks[key], key, self)

    def get(self, key: str) -> "RoundCache.Entry":
        return self.__getitem__(key)


class CheckContext:
    # periods: List[Period]
    # check_configs: CheckConfigMap

    def __init__(
        self,
        bot: Bot,
        logger: Logger,
        cache: jjcdata,
        config: Config,
        *,
        now: Optional[datetime] = None,
    ):
        now = now or datetime.now(TZ_CST)
        period = get_current_period(config.periods, now)
        period_name = period.name if period else "default"
        sub_check_config = get_check_config(
            config.subscription.check_config, period_name
        )
        wanted_check_config = get_check_config(
            config.wanted_list.check_config, period_name
        )

        self._bot = bot
        self._logger = logger
        self._cache = cache
        self._now = now
        self._current_period = period_name
        self._subscriptions_check_config = sub_check_config
        self._wanted_check_config = wanted_check_config
        self._round_cache: RoundCache = RoundCache()

    def get_id_lock(self, id_: str) -> asyncio.Lock:
        """每个 id 一把锁，防止对同一 id 并发重复请求"""
        if id_ not in self._round_cache_locks:
            self._round_cache_locks[id_] = asyncio.Lock()
        return self._round_cache_locks[id_]

    @property
    def bot(self):
        return self._bot

    @property
    def logger(self):
        return self._logger

    @property
    def now(self):
        return self._now

    @property
    def current_period(self):
        return self._current_period

    @property
    def cache(self):
        return self._cache

    @property
    def round_cache(self):
        return self._round_cache

    @property
    def should_reset_settlement_high_notice(self):
        return self._now.hour == 15 and self._now.minute == 0

    @property
    def should_reset_daily_high_notice(self):
        return self._now.hour == 5 and self._now.minute == 0

    async def should_check_subscription(self, *, delay: Optional[int] = None):
        """
        判断是否应该执行订阅检查。

        如果需要检查则会按配置随机延迟延时后返回 True, 否则会立即返回 False

        :param delaly: 强制延时时间(秒), 如果不指定使用配置值. 负数和零表示不延迟. 对结算时间不生效
        """
        now = self._now
        cc = self._subscriptions_check_config
        if cc.interval == 0:
            return now.hour == 15 and now.minute == 0

        delayer = Delayer.fixed(delay) if delay is not None else Delayer.random(cc.delay)

        check = (now.minute % cc.interval) == 0
        if check:
            await delayer.wait()
        return check

    async def should_check_wanted(
        self, wanted_list: List[WantedDetail], *, delay: Optional[int] = None
    ):
        """
        判断是否应该执行通缉检查。

        如果需要检查则会按配置随机延迟延时后返回待检列表, 否则会立即返回 None

        :param wanted_list: 待检查的通缉列表。
        :param delaly: 强制延时时间(秒), 如果不指定使用配置值. 负数和零表示不延迟. 对结算时间不生效
        """
        now = self._now
        cc = self._wanted_check_config
        if cc.interval == 0:
            if now.hour == 15 and now.minute == 0:
                return self._wanted_items
            else:
                return None

        delayer = Delayer.fixed(delay) if delay is not None else Delayer.random(cc.delay)

        check = (now.minute % cc.interval) == 0
        if check:  # 符合延迟要求，检测所有
            await delayer.wait()
            return wanted_list
        # 仅检测被标记为高频监控的通缉对象
        all_high_wanted: List[WantedDetail] = []
        for wanted in wanted_list:
            high_watchers = wanted.high_watchers
            if not high_watchers:
                continue
            all_high_wanted.append(WantedDetail(uid=wanted.uid, watchers=high_watchers))
        if all_high_wanted:
            await delayer.wait()
            return all_high_wanted
        else:
            return None


async def fetch_and_update(
    ctx: CheckContext,
    uid: str,
) -> Optional[RankDiff]:
    """
    查询 uid 的最新排名，对比 Redis 基准，更新 Redis，并填入 round_cache。

    - 命中 round_cache 时直接复用，不再调 API 或读写 Redis。
    - 首次查询（Redis 无基准）：写入 Redis，返回 None（无法比对）。
    - 查询失败：记录日志，round_cache 存 None，返回 None。

    返回 RankDiff 或 None。
    """
    entry = ctx.round_cache[uid]
    async with entry:
        if entry:
            logger.info(f"[monitor] use cached result for uid={uid}")
            return entry.value
        else:
            logger = ctx.logger
            cache = ctx.cache

            try:
                logger.info(f"[monitor] querying uid={uid}")
                res = await get_profile(uid)
            except ApiException as e:
                logger.info(
                    f"[monitor] uid={uid} 查询失败 code={e.code}\n{format_exc()}"
                )
                entry.value = None
                return None
            except Exception:
                logger.info(f"[monitor] uid={uid} 查询异常\n{format_exc()}")
                return None

            new_ranks = (res["arena_rank"], res["grand_arena_rank"])
            last_info = cache.get_user_info(uid) or {}
            last_ranks = cache.get_user_rank(uid)  # (jjc, pjjc) 或 None

            # 更新 Redis
            cache.cache_user_info(uid, dict(res))
            cache.cache_user_rank(uid, new_ranks)

            if last_ranks is None:
                # 首次：无基准，不产生 diff
                entry.value = None
                return None

            diff = RankDiff(
                uid=uid,
                last_info=last_info,
                new_info=res,
                last_ranks=last_ranks,
                new_ranks=new_ranks,
            )
            entry.value = diff
            return diff


# ── 订阅通知行 ────────────────────────────────────────────────────────


def build_subscription_lines(
    sub: SubscriptionItem,
    diff: RankDiff,
) -> list:
    """
    根据 RankDiff 和订阅开关，生成订阅通知行列表（供 arena_service 聚合后整体发送）。
    排名下降（数字增大）才通知。返回空列表表示无需通知。

    格式：
    - 单条通报：昵称: jjc: 6->16 (▼10)
    - 多条通报：昵称:\njjc: 6->16 (▼10)\npjjc: 7->15 (▼8)
    """
    lines = []
    last_jjc, last_pjjc = diff.last_ranks
    new_jjc, new_pjjc = diff.new_ranks

    if new_jjc > last_jjc and sub.arena_on:
        lines.append(f"jjc: {last_jjc}->{new_jjc} (▼{new_jjc - last_jjc})")
    if new_pjjc > last_pjjc and sub.grand_arena_on:
        lines.append(f"pjjc: {last_pjjc}->{new_pjjc} (▼{new_pjjc - last_pjjc})")

    if not lines:
        return []

    user_name = diff.new_info.get("user_name") or diff.uid

    # 如果只有一条通报，不换行
    if len(lines) == 1:
        return [f"{user_name}: {lines[0]}"]
    else:
        # 多条通报，换行显示
        return [f"{user_name}:"] + lines


# ── 通缉通报消息 ──────────────────────────────────────────────────────


class NoticeSwitch(Protocol):
    arena_on: bool
    grand_arena_on: bool
    note: str  # 备注


def _check_key(d1: dict, d2: dict, key: str) -> bool:
    return key in d1 and key in d2


def build_wanted_message(
    item: NoticeSwitch,
    diff: RankDiff,
    cache: jjcdata,
) -> Optional[str]:
    """
    根据 RankDiff 和通缉条目的开关，生成通缉通报消息字符串。
    返回 None 表示本次无需通报。

    通缉逻辑（与旧 legacy 一致）：
      - 上线检测：last_login_time 距上次 > 3分钟 → 显示上线时间
      - 改名检测：user_name 变化 → 显示新名
      - jjc 排名上升（数字减小）→ 攻击计数 +1，只要 item.arena_on 且 watch_at 含 jjc
      - pjjc 排名上升 → 同理
      - 排名下降（数字增大）→ 也通报（被打了），不计攻击
    """
    last = diff.last_info
    new = diff.new_info
    last_jjc, last_pjjc = diff.last_ranks
    new_jjc, new_pjjc = diff.new_ranks

    watch_jjc = item.arena_on
    watch_pjjc = item.grand_arena_on

    # 上线检测
    if (
        _check_key(new, last, "last_login_time")
        and (new["last_login_time"] - last.get("last_login_time", 0)) > 60 * 3
    ):
        login_time = time.strftime("%H:%M", time.localtime(new["last_login_time"]))
        login_notice = f"于{login_time}上线"
        arrest_notice = "注意逮捕"
    else:
        login_notice = ""
        arrest_notice = ""

    # 改名检测
    if _check_key(new, last, "user_name") and new["user_name"] != last.get("user_name"):
        change_name_notice = f" 改名为 {new['user_name']}(UID: {diff.uid}) "
    else:
        change_name_notice = ""

    # jjc 排名变动
    jjc_notice = ""
    if watch_jjc and new_jjc != last_jjc:
        diff_n = new_jjc - last_jjc
        direction = "下降" if diff_n > 0 else "上升"
        if diff_n < 0:
            cache.cache_user_jjc_challenge(diff.uid)
        jjc_notice = f"\njjc：{last_jjc}->{new_jjc} {direction}{abs(diff_n)}名"

    # pjjc 排名变动
    pjjc_notice = ""
    if watch_pjjc and new_pjjc != last_pjjc:
        diff_n = new_pjjc - last_pjjc
        direction = "下降" if diff_n > 0 else "上升"
        if diff_n < 0:
            cache.cache_user_pjjc_challenge(diff.uid)
        pjjc_notice = f"\npjjc：{last_pjjc}->{new_pjjc} {direction}{abs(diff_n)}名"

    has_change = login_notice or change_name_notice or jjc_notice or pjjc_notice
    if not has_change:
        return None

    # 构造显示名称（包含备注）
    user_name = new.get("user_name") or diff.uid
    user_dname = last.get("user_dname")
    note = item.note

    # 判断是否为佑树（user_dname 存在且与 user_name 不同）
    is_yuki = user_dname and user_dname != user_name

    if is_yuki:
        # 佑树：佑树 (备注) 或 佑树 user_dname
        if note:
            display_name = f"佑树 ({note})"
        else:
            display_name = user_dname
    else:
        # 非佑树：user_name (备注) 或 user_name
        if note:
            display_name = f"{user_name} ({note})"
        else:
            display_name = user_name

    msg = f"通缉犯 {display_name} " + login_notice + change_name_notice
    msg += jjc_notice + pjjc_notice
    if jjc_notice or pjjc_notice:
        msg += "\n"
    msg += arrest_notice
    return msg


# ── 订阅监控 ──────────────────────────────────────────────────────────


async def check_subscriptions(
    ctx: CheckContext,
    subscription_manager: SubscriptionManager,
    *,
    delay: Optional[int] = None,
):
    logger = ctx.logger
    check = await ctx.should_check_subscription(delay=delay)
    if not check:
        logger.info('[monitor] skipped subscription check')
        return

    logger.info('[monitor] checking ranks for subscribers...')

    # 按 qq 分组：qq -> {gid -> [SubscriptionItem]}
    by_user: Dict[str, Dict[str, List[SubscriptionItem]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for qq, item in subscription_manager.get_all_items():
        if qq == "0":
            # 跳过 QQ=0 订阅（旧关注迁移数据，不发通知）
            continue
        by_user[qq][item.gid].append(item)

    for qq, groups in by_user.items():
        for gid, items in groups.items():
            await _check_user_subscriptions_in_group(ctx, qq, gid, items)

    logger.info('[monitor] done checking ranks for subscribers.')


async def _check_user_subscriptions_in_group(
    ctx: CheckContext,
    qq: str,
    gid: str,
    items: List[SubscriptionItem],
) -> None:
    """
    处理单个用户在单个群的订阅列表。
    查询每个 uid（命中本轮缓存则跳过 API），比对基准，聚合变动行后发一条 @ 消息。
    """
    cache = ctx.cache
    logger = ctx.logger
    bot = ctx.bot
    lines: List[str] = []

    for sub in items:
        uid = sub.id

        # 命中本轮缓存：直接取出 diff，跳过 API 和 Redis 读写
        diff = await fetch_and_update(ctx, uid)
        if diff is None:
            continue  # 首次记录或查询失败

        # 使用 build_subscription_lines 生成通知行
        sub_lines = build_subscription_lines(sub, diff)
        lines.extend(sub_lines)

    if lines:
        message = "\\n".join(lines) + f" [CQ:at,qq={qq}]"
        try:
            await bot.send_group_msg(group_id=int(gid), message=message)
        except Exception:
            logger.info(
                f"[monitor] 发送订阅通知失败 gid={gid} qq={qq}\\n{format_exc()}"
            )


# ── 通缉监控 ──────────────────────────────────────────────────────────
WantedMessageGroupKey: TypeAlias = Literal["personal_only", "both", "group_only"]


async def check_wanted(
    ctx: CheckContext, wanted_manager: WantedManager, *, delay: Optional[int] = None
):
    """
    遍历所有通缉条目，先检测所有 uid 的变更状态，再分群计算通知信息并发送。

    发送顺序（同一群内）：
    1. 单独个人通报（@ 人在前，通报在后）
    2. 群+人都通缉的（通报在前，@ 人在后）
    3. 单独群通缉的
    """
    logger = ctx.logger
    wanted_items_all = wanted_manager.get_wanted_list_for_monitor()
    wanted_items_to_check = await ctx.should_check_wanted(wanted_items_all, delay=delay)
    if not wanted_items_to_check:
        logger.info('[monitor] skipped wanted check')
        return

    logger.info('[monitor] checking wanted ranks...')
    # 第一步：检测所有 uid 的变更状态
    # uid -> (WantedDetail, RankDiff)
    uid_diffs: Dict[str, Tuple[WantedDetail, RankDiff]] = {}
    for wanted_detail in wanted_items_to_check:
        diff = await fetch_and_update(ctx, wanted_detail.uid)
        if diff is not None:
            uid_diffs[wanted_detail.uid] = (wanted_detail, diff)

    logger.info('[monitor] done checking wanted ranks.')

    if not uid_diffs:
        return  # 没有任何变更

    # 第二步：按群分组，计算通知信息
    # gid -> {
    #   'personal_only': [(qq, uid, msg), ...],  # 仅个人通缉
    #   'both': [(uid, msg, [qq, ...]), ...],     # 群+个人都通缉
    #   'group_only': [(uid, msg), ...]           # 仅群通缉
    # }
    group_messages: Dict[str, Dict[WantedMessageGroupKey, list]] = defaultdict(
        lambda: {"personal_only": [], "both": [], "group_only": []}
    )

    for uid, (wanted_detail, diff) in uid_diffs.items():
        # 按 gid 分组 watchers
        gid_watchers: Dict[str, List[Watcher]] = defaultdict(list)
        for watcher in wanted_detail.watchers:
            gid_watchers[watcher.gid].append(watcher)

        # 对每个 gid，判断是群通缉、个人通缉还是两者都有
        for gid, watchers in gid_watchers.items():
            group_watchers = [w for w in watchers if w.id == ""]
            personal_watchers = [w for w in watchers if w.id != ""]

            has_group = len(group_watchers) > 0
            has_personal = len(personal_watchers) > 0

            # 根据通缉类型确定 arena_on 和 grand_arena_on
            hour = ctx.now.hour
            if has_personal and not has_group:
                # 纯个人通缉：任意个人 watcher 要求就开启
                arena_on = any(w.should_notice_arena(hour) for w in personal_watchers)
                grand_arena_on = any(
                    w.should_notice_grand_arena(hour) for w in personal_watchers
                )
            elif has_group and has_personal:
                # 个人+群通缉：任意 watcher 要求就开启
                arena_on = any(w.should_notice_arena(hour) for w in watchers)
                grand_arena_on = any(
                    w.should_notice_grand_arena(hour) for w in watchers
                )
            else:
                # 单群通缉：只看群 watcher
                arena_on = any(w.should_notice_arena(hour) for w in group_watchers)
                grand_arena_on = any(
                    w.should_notice_grand_arena(hour) for w in group_watchers
                )

            # 构造临时 WantedItem 用于生成消息
            temp_item = WantedItem(
                id=uid,
                gid=gid,
                notice_level=1,  # not used in build_wanted_message
                arena_on=arena_on,
                grand_arena_on=grand_arena_on,
            )
            msg = build_wanted_message(temp_item, diff, ctx.cache)
            if msg is None:
                continue  # 无需通报

            if has_personal and not has_group:
                # 仅个人通缉
                for w in personal_watchers:
                    group_messages[gid]["personal_only"].append((w.id, uid, msg))
            elif has_group and has_personal:
                # 群+个人都通缉
                qq_list = [w.id for w in personal_watchers]
                group_messages[gid]["both"].append((uid, msg, qq_list))
            elif has_group and not has_personal:
                # 仅群通缉
                group_messages[gid]["group_only"].append((uid, msg))

    # 第三步：按顺序发送消息
    for gid, messages in group_messages.items():
        # 1. 单独个人通报（@ 人在前，通报在后）
        for qq, uid, msg in messages["personal_only"]:
            full_msg = f"[CQ:at,qq={qq}]\n{msg}"
            try:
                await ctx.bot.send_group_msg(group_id=int(gid), message=full_msg)
            except Exception:
                ctx.logger.info(
                    f"[monitor] 发送个人通缉通知失败 gid={gid} qq={qq} uid={uid}\n{format_exc()}"
                )

        # 2. 群+人都通缉的（通报在前，@ 人在后）
        for uid, msg, qq_list in messages["both"]:
            at_list = [f"[CQ:at,qq={qq}]" for qq in qq_list]
            full_msg = f"{msg}\n" + " ".join(at_list)
            try:
                await ctx.bot.send_group_msg(group_id=int(gid), message=full_msg)
            except Exception:
                ctx.logger.info(
                    f"[monitor] 发送群+个人通缉通知失败 gid={gid} uid={uid}\n{format_exc()}"
                )

        # 3. 单独群通缉的
        for uid, msg in messages["group_only"]:
            try:
                await ctx.bot.send_group_msg(group_id=int(gid), message=msg)
            except Exception:
                ctx.logger.info(
                    f"[monitor] 发送群通缉通知失败 gid={gid} uid={uid}\n{format_exc()}"
                )
