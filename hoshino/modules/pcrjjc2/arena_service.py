"""
arena_service.py - 竞技场订阅排名检测 Service 层

ArenaService 持有配置、订阅管理器和 Redis DAO，对外提供：
  - should_check_subscriptions()：根据 config.yaml 时段判断本分钟是否需要检测
  - check_arena_subscriptions()：按用户→群→uid 遍历，本轮内存缓存去重，聚合通知
  - bind / unbind / set_toggle / move_group 等订阅管理操作
  - query_group_ranks()：查询当前群绑定 uid 的实时排名
  - query_detail()：查询单个 uid 的详细信息
  - get_subscription_status_rows()：返回全量订阅的表格行数据（供订阅状态查询）
"""

import asyncio
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from traceback import format_exc
from typing import Dict, List, Optional, Tuple

from .arena_client import ApiException, _improve_user_info, get_profile, get_profile_raw
from .config_loader import TZ_CST, get_check_config, get_current_period, save_config
from .jjcdata import jjcdata
from nonebot import get_bot
from .schema import Config, SubscriptionItem
from .subscriptions import SubscriptionManager
from .table_image import Cell, StyledText, render_table_as_cq


@dataclass
class RankInfo:
    """单个 uid 的实时排名查询结果（用于竞技场查询）。"""

    uid: str
    user_name: str
    arena_rank: int
    arena_group: int
    grand_arena_rank: int
    grand_arena_group: int


@dataclass
class SubStatusRow:
    """订阅状态表格的一行数据（用于订阅状态查询）。"""

    index: int  # 1-based 全局编号
    uid: str
    gid: str
    user_name: str  # 昵称，缓存中无则为 "-"
    arena_str: str  # "N场 M名" 或 "-"（兼容纯文本输出）
    grand_arena_str: str
    arena_on: bool
    grand_arena_on: bool
    # 原始数值，供富文本渲染着色；未缓存时为 None
    arena_rank: Optional[int] = None
    arena_group: Optional[int] = None
    grand_arena_rank: Optional[int] = None
    grand_arena_group: Optional[int] = None


@dataclass
class CheckSubscriptionContext:
    """
    单轮检测上下文，生命周期为一次 check_arena_subscriptions 调用。

    round_cache:  uid -> (last, ranks)
                  last:  本轮开始前的 Redis 基准，可为 None（首次）
                  ranks: 本次 API 返回的新排名
                  首次查询时填入并更新 Redis；命中缓存时直接复用，不再读写 Redis，
                  确保多个用户订阅同一 uid 时各自都能收到通知。
    bot:          nonebot bot 实例，在调用前由 check_arena_subscriptions 填充。
    """

    round_cache: Dict[str, Tuple[Optional[Tuple[int, int]], Tuple[int, int]]] = field(
        default_factory=dict
    )
    bot: object = None


class ArenaService:
    def __init__(
        self,
        config: Config,
        cache: jjcdata,
        logger,
    ):
        self._config = config
        self._sub_mgr = SubscriptionManager(items=config.subscription.items)
        self._cache = cache
        self._logger = logger

    @property
    def now(self) -> datetime:
        return datetime.now(TZ_CST)

    @property
    def subscription_manager(self) -> SubscriptionManager:
        return self._sub_mgr

    def save_config(self, config_path: Optional[str] = None) -> None:
        """将当前订阅 items 同步回 Config 并写入 config.yaml。"""
        self._config.subscription.items = self._sub_mgr._items
        save_config(self._config, config_path)

    # ------------------------------------------------------------------ #
    # 订阅 CRUD                                                            #
    # ------------------------------------------------------------------ #

    def bind(self, qq: str, uid: str, gid: str) -> str:
        """
        追加订阅。
        返回 'ok' / 'dup' / 'full'。
        """
        return self._sub_mgr.add(qq, uid, gid)

    def unbind(self, qq: str, index: int) -> bool:
        """按全局编号（1-based）删除订阅。"""
        return self._sub_mgr.remove(qq, index)

    def set_toggle(
        self,
        qq: str,
        index: Optional[int],
        arena_on: Optional[bool],
        grand_arena_on: Optional[bool],
    ) -> bool:
        """
        切换通知开关。
        index=None 时操作所有订阅；arena_on/grand_arena_on=None 时不修改该字段。
        """
        return self._sub_mgr.set_toggle(qq, index, arena_on, grand_arena_on)

    def move_group(self, qq: str, index: int, new_gid: str) -> bool:
        """将第 index 个订阅的通知群改为 new_gid。"""
        return self._sub_mgr.move_group(qq, index, new_gid)

    # ------------------------------------------------------------------ #
    # 查询                                                                 #
    # ------------------------------------------------------------------ #

    async def query_group_ranks(self, qq: str, gid: str) -> List[RankInfo]:
        """
        查询 qq 用户在 gid 群绑定的所有 uid 的实时排名。
        返回 RankInfo 列表，顺序与订阅列表一致。
        没有绑定时返回空列表。
        失败时抛 ApiException。
        """
        subs = self._sub_mgr.get_list_by_gid(qq, gid)
        result: List[RankInfo] = []
        for sub in subs:
            res = await get_profile(sub.id)
            self._cache.cache_user_name(sub.id, res["user_name"])
            result.append(
                RankInfo(
                    uid=sub.id,
                    user_name=res["user_name"],
                    arena_rank=res["arena_rank"],
                    arena_group=res["arena_group"],
                    grand_arena_rank=res["grand_arena_rank"],
                    grand_arena_group=res["grand_arena_group"],
                )
            )
        return result

    async def query_detail(self, qq: str, gid: str, uid: Optional[str] = None) -> dict:
        """
        查询单个 uid 的详细信息。
        uid 为 None 时取该用户在当前群的第一个订阅。
        返回展平后的 user_info dict（含 arena_time/grand_arena_time/clan_name）。
        uid 为空且当前群无绑定时抛 ValueError。
        失败时抛 ApiException。
        """
        if uid is None:
            subs = self._sub_mgr.get_list_by_gid(qq, gid)
            if not subs:
                raise ValueError("当前群未绑定竞技场")
            uid = subs[0].id
        raw = await get_profile_raw(uid)
        user_info = _improve_user_info(raw)
        # _improve_user_info 展平 profile["user_info"]，arena_time/grand_arena_time/clan_name 已在其中
        # cache_user_info 会 pop emblem/viewer_id，用浅拷贝避免影响返回值
        self._cache.cache_user_info(uid, dict(user_info))
        return user_info

    def get_subscription_status_rows(self, qq: str) -> List[SubStatusRow]:
        """
        返回 qq 用户所有订阅的状态行，供"订阅状态查询"渲染表格。
        从 Redis 缓存读取排名，未缓存时显示 '-'。
        """
        subs = self._sub_mgr.get_list(qq)
        rows: List[SubStatusRow] = []
        for i, s in enumerate(subs):
            info = self._cache.get_user_info(s.id) or {}
            user_name = info.get("user_name", "-")
            jjc_rank = info.get("arena_rank")
            jjc_group = info.get("arena_group")
            pjjc_rank = info.get("grand_arena_rank")
            pjjc_group = info.get("grand_arena_group")
            arena_str = f"{jjc_group}场 {jjc_rank}名" if jjc_rank is not None else "-"
            grand_str = (
                f"{pjjc_group}场 {pjjc_rank}名" if pjjc_rank is not None else "-"
            )
            rows.append(
                SubStatusRow(
                    index=i + 1,
                    uid=s.id,
                    gid=s.gid,
                    user_name=user_name,
                    arena_str=arena_str,
                    grand_arena_str=grand_str,
                    arena_on=s.arena_on,
                    grand_arena_on=s.grand_arena_on,
                    arena_rank=jjc_rank,
                    arena_group=jjc_group,
                    grand_arena_rank=pjjc_rank,
                    grand_arena_group=pjjc_group,
                )
            )
        return rows

    # ------------------------------------------------------------------ #
    # 调度                                                                 #
    # ------------------------------------------------------------------ #

    async def should_check_subscriptions(self, now: Optional[datetime] = None) -> bool:
        """
        根据 config 的 periods + subscription.check_config 判断本分钟是否检测。

        settlement（interval=0）：仅 15:00 触发一次，无延迟。
        其余时段：按 interval 取余，delay 范围内随机延迟后返回 True。
        """
        now = now or self.now
        period = get_current_period(self._config.periods, now=now)
        period_name = period.name if period else "default"
        cc = get_check_config(self._config.subscription.check_config, period_name)

        if cc.interval == 0:
            return now.hour == 15 and now.minute == 0

        check = (now.minute % cc.interval) == 0
        if check and cc.delay > 0:
            await asyncio.sleep(random.randint(0, cc.delay))
        return check

    async def check_arena_subscriptions(self) -> None:
        """
        遍历所有订阅，按 用户 → 群 → uid 的顺序逐步检测和通知。
        每个群聚合成一条 @ 消息，同一 uid 在本轮只查询一次 API。
        """
        ctx = CheckSubscriptionContext(bot=get_bot())

        # 按 qq 分组：qq -> {gid -> [SubscriptionItem]}
        by_user: Dict[str, Dict[str, List[SubscriptionItem]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for qq, item in self._sub_mgr.get_all_items():
            by_user[qq][item.gid].append(item)

        for qq, groups in by_user.items():
            await self._check_user_subscriptions(qq, groups, ctx)

    async def _check_user_subscriptions(
        self,
        qq: str,
        groups: Dict[str, List[SubscriptionItem]],
        ctx: CheckSubscriptionContext,
    ) -> None:
        """
        处理单个用户的所有订阅，按群分组后逐群聚合通知。
        """
        for gid, items in groups.items():
            await self._check_user_subscriptions_in_group(qq, gid, items, ctx)

    async def _check_user_subscriptions_in_group(
        self,
        qq: str,
        gid: str,
        items: List[SubscriptionItem],
        ctx: CheckSubscriptionContext,
    ) -> None:
        """
        处理单个用户在单个群的订阅列表。
        查询每个 uid（命中本轮缓存则跳过 API），比对基准，聚合变动行后发一条 @ 消息。
        """
        lines: List[str] = []

        for sub in items:
            uid = sub.id

            # 命中本轮缓存：直接取出 (last, ranks)，跳过 API 和 Redis 读写
            if uid in ctx.round_cache:
                last, ranks = ctx.round_cache[uid]
            else:
                try:
                    self._logger.info(f"[arena] querying uid={uid} for qq={qq}")
                    res = await get_profile(uid)
                    ranks = (res["arena_rank"], res["grand_arena_rank"])
                    # 记录昵称，方便提醒时附带
                    self._cache.cache_user_name(uid, res["user_name"])
                except ApiException as e:
                    self._logger.info(f"[arena] uid={uid} 查询出错\n{format_exc()}")
                    if e.code == 6:
                        self._logger.info(f"[arena] uid={uid} 无效，已跳过")
                    continue
                except Exception:
                    self._logger.info(f"[arena] uid={uid} 查询出错\n{format_exc()}")
                    continue

                # 读基准、更新 Redis、存入本轮缓存
                last = self._cache.get_user_rank(uid)
                self._cache.cache_user_rank(uid, ranks)
                ctx.round_cache[uid] = (last, ranks)

            if not last:
                continue  # 首次记录，无基准

            jjc_line: Optional[str] = None
            pjjc_line: Optional[str] = None
            if ranks[0] > last[0] and sub.arena_on:
                jjc_line = f"jjc：{last[0]}->{ranks[0]} ▼{ranks[0] - last[0]}"
            if ranks[1] > last[1] and sub.grand_arena_on:
                pjjc_line = f"pjjc：{last[1]}->{ranks[1]} ▼{ranks[1] - last[1]}"

            if not jjc_line and not pjjc_line:
                continue

            # 昵称
            user_name = self._cache.get_user_name(uid)
            lines.append(user_name)
            if jjc_line:
                lines.append(jjc_line)
            if pjjc_line:
                lines.append(pjjc_line)

        if lines:
            message = f"[CQ:at,qq={qq}]\n" + "\n".join(lines)
            try:
                await ctx.bot.send_group_msg(group_id=int(gid), message=message)
            except Exception:
                self._logger.info(
                    f"[arena] 发送通知失败 gid={gid} qq={qq}\n{format_exc()}"
                )


# ── 排名着色规则 ──────────────────────────────────────────────────────
# 1~30:   不附加颜色（安全区）
# 31~50:  橙红色（激战区）
# 51~100: 红色（低收益区）
# >100:   50% 灰色（挂机区，排名无意义）
_COLOR_RANK_SAFE = None  # 继承默认文字色
_COLOR_RANK_HOT = (210, 100, 30)  # 橙红
_COLOR_RANK_LOW = (200, 50, 50)  # 红
_COLOR_RANK_IDLE = (140, 140, 140)  # 50% 灰
_COLOR_NOTIFY_OFF = (
    140,
    140,
    140,
)  # 通知"关"的灰色（保持一致，提高压缩率，减少cq长度）


def _rank_color(rank: Optional[int]) -> Optional[tuple]:
    if rank is None:
        return None
    if rank <= 30:
        return _COLOR_RANK_SAFE
    if rank <= 50:
        return _COLOR_RANK_HOT
    if rank <= 100:
        return _COLOR_RANK_LOW
    return _COLOR_RANK_IDLE


def _rank_cell(group: Optional[int], rank: Optional[int], font_size: int) -> Cell:
    """
    构造双场单元格：
    - 场次用 75% 字号，固定3位宽度格式化（右对齐补空格）
    - 名次按规则着色，固定3位宽度格式化
    - 未缓存时显示 "-"
    """
    if rank is None:
        return Cell(content="-", align="center")

    small_size = max(int(font_size * 0.75), 8)
    group_str = f"{group:3d}场 " if group is not None else "  ? 场 "
    rank_str = f"{rank:3d}名"

    segs: List[StyledText] = [
        StyledText(group_str, size=small_size),
    ]
    color = _rank_color(rank)
    if color:
        segs.append(StyledText(rank_str, text_color=color))
    else:
        segs.append(StyledText(rank_str))

    return Cell(content=segs, align="right", valign="bottom")


def render_subscription_status_cq(rows_data: List[SubStatusRow]) -> str:
    """
    将订阅状态行列表渲染为富文本图片表格，返回 CQ 码字符串。
    由 service.py 的 send_arena_sub_status handler 调用。
    """
    from .table_image import _FONT_SIZE  # 读取当前字号常量，保持一致

    headers = ["#", "昵称", "UID", "通知群", "jjc", "pjjc", "通知"]
    rows = []
    for r in rows_data:
        # 通知开关列
        if r.arena_on and r.grand_arena_on:
            notify: Union[str, StyledText] = "开"
        elif r.arena_on:
            notify = StyledText("jjc", text_color=(50, 120, 200))
        elif r.grand_arena_on:
            notify = StyledText("pjjc", text_color=(50, 120, 200))
        else:
            notify = StyledText("关", text_color=_COLOR_NOTIFY_OFF)

        # 昵称列：最多10个汉字宽度，超出截断加省略号
        name = r.user_name
        if len(name) > 10:
            name = name[:9] + "…"

        rows.append(
            [
                Cell(content=str(r.index), align="center"),
                name,
                r.uid,
                r.gid,
                _rank_cell(r.arena_group, r.arena_rank, _FONT_SIZE),
                _rank_cell(r.grand_arena_group, r.grand_arena_rank, _FONT_SIZE),
                Cell(content=notify, align="center"),
            ]
        )

    return render_table_as_cq(
        headers=headers,
        rows=rows,
        title="竞技场订阅状态",
    )
