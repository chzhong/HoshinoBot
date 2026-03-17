"""
arena_service.py - 竞技场订阅排名检测 Service 层

ArenaService 持有配置、订阅管理器、通缉管理器和 Redis DAO，对外提供：
  - should_check_subscriptions()：根据 config.yaml 时段判断本分钟是否需要检测订阅
  - check_arena_subscriptions()：调用 rank_monitor.check_subscriptions() 执行订阅监控
  - should_check_wanted()：根据 config.yaml 时段判断本分钟是否需要检测通缉
  - check_wanted()：调用 rank_monitor.check_wanted() 执行通缉监控
  - bind / unbind / set_toggle / move_group 等订阅管理操作
  - query_group_ranks()：查询当前群绑定 uid 的实时排名
  - query_detail()：查询单个 uid 的详细信息
  - get_subscription_status_rows()：返回全量订阅的表格行数据（供订阅状态查询）
"""

import asyncio
import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from os.path import exists
from typing import List, Optional, Tuple, Union

from . import rank_monitor
from .arena_client import _improve_user_info, get_profile, get_profile_raw
from .config_loader import TZ_CST, save_config
from .jjcdata import jjcdata
from .schema import (
    NOTICE_LEVEL_DEFAULT,
    NOTICE_LEVEL_HIGH_BEFORE_SETTLEMENT,
    NOTICE_LEVEL_HIGH_TODAY,
    Bot,
    Config,
    Logger,
    SubscriberArenaGroups,
    WantedItem,
)
from .subscription_manager import SubscriptionManager
from .table_image import (
    CELL_FONT_SIZE,  # 读取当前字号常量，保持一致
    Cell,
    Header,
    StyledText,
    image_to_cq,
    render_table,
)
from .wanted_manager import WantedManager
from .wanted_summary_formatter import WantedSummaryRow


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
    arena_str: str  # "5场 50名" 或 "-"
    grand_arena_str: str  # "1场 20名" 或 "-"
    arena_on: bool
    grand_arena_on: bool
    # 原始数值，供富文本渲染着色；未缓存时为 None
    arena_rank: Optional[int] = None
    arena_group: Optional[int] = None
    grand_arena_rank: Optional[int] = None
    grand_arena_group: Optional[int] = None


class ArenaService:
    _config_path: Optional[str] = None

    def __init__(
        self,
        config: Config,
        cache: jjcdata,
        bot: Bot,
        logger: Logger,
        wanted_manager: Optional[WantedManager] = None,
        *,
        config_path: Optional[str] = None,
        reset_notice_levels: Optional[bool] = True,
    ):
        self._config_path = config_path
        self._config = config
        self._sub_mgr = SubscriptionManager(items=config.subscription.items)
        self._wanted_mgr = wanted_manager or WantedManager(config.wanted_list)
        self._cache = cache
        self._bot = bot
        self._logger = logger
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name="check-worker"
        )
        self._loop_thread.start()

        # 启动时重置 notice_level（清理临时提升的级别）
        if reset_notice_levels:
            self._reset_notice_levels_on_startup()

    @property
    def bot(self) -> Bot:
        return self._bot

    @property
    def logger(self) -> Logger:
        return self._logger

    @property
    def now(self) -> datetime:
        return datetime.now(TZ_CST)

    @property
    def subscription_manager(self) -> SubscriptionManager:
        return self._sub_mgr

    @property
    def wanted_manager(self) -> WantedManager:
        return self._wanted_mgr

    def save_config(self, config_path: Optional[str] = None) -> None:
        """将当前订阅 items 和通缉数据同步回 Config 并写入 config.yaml。"""
        self._config.subscription.items = self._sub_mgr._items
        self._config.wanted_list.group = self._wanted_mgr._group
        self._config.wanted_list.personal = self._wanted_mgr._personal
        save_config(self._config, config_path or self._config_path)

    def migrate(
        self,
        binds_path: Optional[str] = None,
        wanted_path: Optional[str] = None,
        backup: bool = False,
    ) -> None:
        """
        从旧数据文件迁移订阅和通缉数据到 config.yaml。

        Args:
            binds_path: 旧订阅数据文件路径（binds.json）
            wanted_path: 旧通缉数据文件路径（wanted_binds.json）
            backup: 是否在迁移后重命名旧文件为 .bak
        """

        migrated = False

        # 迁移订阅数据
        if binds_path and exists(binds_path) and not self._sub_mgr._items:
            self._logger.info(
                f"[pcrjjc2] config.yaml 中无订阅数据，从 {binds_path} 自动迁移..."
            )
            with open(binds_path, encoding="utf-8") as fp:
                old_binds = json.load(fp)
            self._sub_mgr.migrate_from_old(old_binds.get("arena_bind", {}))
            migrated = True
            if backup:
                os.rename(binds_path, binds_path + ".bak")

        # 迁移通缉数据
        if wanted_path and exists(wanted_path) and not self._wanted_mgr._group:
            self._logger.info(
                f"[pcrjjc2] config.yaml 中无通缉数据，从 {wanted_path} 自动迁移..."
            )
            with open(wanted_path, encoding="utf-8") as fp:
                old_wanted = json.load(fp)
            self._wanted_mgr.migrate_from_old(old_wanted.get("wanted_bind", {}))
            migrated = True
            if backup:
                os.rename(wanted_path, wanted_path + ".bak")

        # 保存迁移结果
        if migrated:
            self.save_config()

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

    async def query_group_ranks(
        self, qq: str, gid: str, uid_or_idx: Optional[str] = None
    ) -> List[RankInfo]:
        """
        查询 qq 用户在 gid 群绑定的 uid 的实时排名。
        uid_or_idx 为 None 时查询所有绑定。
        uid_or_idx 为 13 位数字时视为 uid，查询单个。
        uid_or_idx 为其他数字时视为索引（1-based），查询单个。
        返回 RankInfo 列表。
        没有绑定时返回空列表。
        失败时抛 ApiException。
        """
        if uid_or_idx is None:
            # 查询所有绑定
            subs = self._sub_mgr.get_list_by_gid(qq, gid)
        elif len(uid_or_idx) == 13 and uid_or_idx.isdigit():
            # 13位数字，视为 uid
            subs = self._sub_mgr.get_list_by_gid(qq, gid)
            subs = [s for s in subs if s.id == uid_or_idx]
        else:
            # 尝试解析为索引
            try:
                idx = int(uid_or_idx)
                all_subs = self._sub_mgr.get_list(qq)
                if 1 <= idx <= len(all_subs):
                    target_sub = all_subs[idx - 1]
                    # 只返回该订阅（如果它在当前群）
                    if target_sub.gid == gid:
                        subs = [target_sub]
                    else:
                        subs = []
                else:
                    raise ValueError(f"索引 {idx} 超出范围（1-{len(all_subs)}）")
            except ValueError as e:
                if "索引" in str(e):
                    raise
                raise ValueError(f"无效的 uid 或索引：{uid_or_idx}")

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

    async def query_detail(
        self, qq: str, gid: str, uid_or_idx: Optional[str] = None
    ) -> dict:
        """
        查询单个 uid 的详细信息。
        uid_or_idx 为 None 时取该用户在当前群的第一个订阅。
        uid_or_idx 为 13 位数字时视为 uid。
        uid_or_idx 为其他数字时视为索引（1-based）。
        返回展平后的 user_info dict（含 arena_time/grand_arena_time/clan_name）。
        uid 为空且当前群无绑定时抛 ValueError。
        失败时抛 ApiException。
        """
        uid = None
        if uid_or_idx is None:
            subs = self._sub_mgr.get_list_by_gid(qq, gid)
            if not subs:
                raise ValueError("当前群未绑定竞技场")
            uid = subs[0].id
        elif len(uid_or_idx) == 13 and uid_or_idx.isdigit():
            # 13位数字，视为 uid
            uid = uid_or_idx
        else:
            # 尝试解析为索引
            try:
                idx = int(uid_or_idx)
                all_subs = self._sub_mgr.get_list(qq)
                if 1 <= idx <= len(all_subs):
                    uid = all_subs[idx - 1].id
                else:
                    raise ValueError(f"索引 {idx} 超出范围（1-{len(all_subs)}）")
            except ValueError as e:
                if "索引" in str(e):
                    raise
                raise ValueError(f"无效的 uid 或索引：{uid_or_idx}")

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

    def get_wanted_summary_rows(
        self, sender_qq: str, sender_gid: str, filter_type: Optional[str] = None
    ) -> Tuple[List[WantedSummaryRow], List[WantedSummaryRow]]:
        """
        返回通缉犯概要的数据行，供"通缉犯概要"渲染表格。

        :param sender_qq: 命令发送者的 QQ 号
        :param sender_gid: 命令发送群号
        :param filter_type: 筛选类型 - None(全部), "group"(仅群通缉), "personal"(仅个人通缉)
        :return: (群通缉行列表, 个人通缉行列表)
        """
        # 获取命令发送者的场号集合
        sender_groups = self._sub_mgr.get_subscriber_arena_groups(
            sender_qq, self._cache
        )

        group_rows: List[WantedSummaryRow] = []
        personal_rows: List[WantedSummaryRow] = []

        # 群通缉
        if filter_type is None or filter_type == "group":
            group_items = self._wanted_mgr.list_group(sender_gid)

            for i, item in enumerate(group_items):
                row = self._build_wanted_summary_row(
                    index=i + 1,
                    item=item,
                    sender_groups=sender_groups,
                )
                if row:
                    group_rows.append(row)

        # 个人通缉
        if filter_type is None or filter_type == "personal":
            personal_items = self._wanted_mgr.list_personal(sender_qq)
            for i, item in enumerate(personal_items):
                row = self._build_wanted_summary_row(
                    index=i + 1,
                    item=item,
                    sender_groups=sender_groups,
                )
                if row:
                    personal_rows.append(row)

        return group_rows, personal_rows

    def _build_wanted_summary_row(
        self,
        index: int,
        item: WantedItem,  # WantedItem
        sender_groups: SubscriberArenaGroups,  # SubscriberArenaGroups
    ) -> Optional[WantedSummaryRow]:
        """构建单个通缉犯概要行。"""
        uid = item.id
        info = self._cache.get_user_info(uid) or {}

        # 基本信息
        user_name = info.get("user_name", uid)
        avatar_unit_name = info.get("avatar_unit_name")
        clan_name = info.get("clan_name")

        # 竞技场信息
        arena_group = info.get("arena_group", 0)
        arena_rank = info.get("arena_rank", 0)

        arena_challenges = info.get("arena_challenge", 0)
        arena_mining = info.get("arena_mining", None)

        grand_arena_group = info.get("grand_arena_group", 0)
        grand_arena_rank = info.get("grand_arena_rank", 0)
        grand_arena_challenges = info.get("grand_arena_challenge", 0)
        grand_arena_mining = info.get("grand_arena_mining", None)

        # 上线时间
        last_login_time = info.get("last_login_time", 0)

        # 是否同场
        same_arena_group = (
            arena_group in sender_groups.arena_groups if arena_group else False
        )
        same_grand_arena_group = (
            grand_arena_group in sender_groups.grand_arena_groups
            if grand_arena_group
            else False
        )

        arena_str = (
            f"{arena_group}场 {arena_rank}名" if arena_group and arena_rank else "-"
        )
        grand_arena_str = (
            f"{grand_arena_group}场 {grand_arena_rank}名"
            if grand_arena_group and grand_arena_rank
            else "-"
        )

        return WantedSummaryRow(
            index=index,
            uid=uid,
            user_name=user_name,
            avatar_unit_name=avatar_unit_name,
            clan_name=clan_name,
            arena_group=arena_group,
            arena_rank=arena_rank,
            arena_challenges=arena_challenges,
            arena_on=item.arena_on,
            arena_mining=arena_mining,
            grand_arena_group=grand_arena_group,
            grand_arena_rank=grand_arena_rank,
            grand_arena_challenges=grand_arena_challenges,
            grand_arena_on=item.grand_arena_on,
            grand_arena_mining=grand_arena_mining,
            last_login_time=last_login_time,
            note=item.note,
            notice_level=item.notice_level,
            same_arena_group=same_arena_group,
            same_grand_arena_group=same_grand_arena_group,
            arena_str=arena_str,
            grand_arena_str=grand_arena_str,
        )

    # ------------------------------------------------------------------ #
    # 调度                                                                 #
    # ------------------------------------------------------------------ #

    async def on_schedule(self, *, sync: bool = False, now: Optional[datetime] = None):
        """
        执行定时任务

        :param sync: True 表示在当前线程执行并等待结果；False 会在专用线程执行
        """
        if sync:
            await self.check(now)
        else:
            asyncio.run_coroutine_threadsafe(
                self.check(now),
                self._loop,
            )

    async def check(self, now: Optional[datetime] = None, delay: Optional[int] = None):
        """
        检测订阅和通缉
        """
        self._logger.info("[arena_service] checking ranks on schedule...")
        ctx = rank_monitor.CheckContext(
            bot=self._bot,
            logger=self._logger,
            cache=self._cache,
            config=self._config,
            now=now,
        )
        await asyncio.gather(
            self.check_arena_subscriptions(ctx, now=now, delay=delay),
            self.check_wanted(ctx, now=now, delay=delay),
        )

    async def check_arena_subscriptions(
        self,
        ctx: rank_monitor.CheckContext,
        *,
        now: Optional[datetime] = None,
        delay: Optional[int] = None,
    ) -> None:
        """
        遍历所有订阅，按 用户 → 群 → uid 的顺序逐步检测和通知。
        每个群聚合成一条 @ 消息，同一 uid 在本轮只查询一次 API。
        委托给 rank_monitor.check_subscriptions() 执行。
        """
        #self._logger.info("[arena_service] checking ranks for subscribers...")
        await rank_monitor.check_subscriptions(ctx, self._sub_mgr, delay=delay)

    async def check_wanted(
        self,
        ctx: rank_monitor.CheckContext,
        *,
        now: Optional[datetime] = None,
        delay: Optional[int] = None,
    ) -> None:
        """
        遍历所有通缉条目，先收集所有要检测的 uid，批量检测，然后根据结果分发消息。
        委托给 rank_monitor.check_wanted() 执行。
        检测后处理 notice_level 降级（settlement/次日5点）。
        """
        #self._logger.info("[arena_service] checking wanted ranks...")
        await rank_monitor.check_wanted(ctx, self._wanted_mgr, delay=delay)

        # notice_level 降级逻辑

        now = ctx.now
        need_save = False

        # 15:00 settlement：level=2/3 → level=1
        if now.hour == 15 and now.minute == 0:
            need_save = self._reset_notice_level(
                NOTICE_LEVEL_HIGH_BEFORE_SETTLEMENT, NOTICE_LEVEL_DEFAULT
            )

        # 次日 05:00：level=4 → level=1
        if now.hour == 5 and now.minute == 0:
            need_save = (
                self._reset_notice_level(NOTICE_LEVEL_HIGH_TODAY, NOTICE_LEVEL_DEFAULT)
                or need_save
            )

        if need_save:
            self.save_config()

    def _reset_notice_level(self, from_level: int, to_level: int) -> bool:
        """
        将所有 notice_level == from_level 的通缉项重置为 to_level。
        返回是否有修改。
        """
        modified = False

        # 群通缉
        for gid, items in self._wanted_mgr._group.items():
            for item in items:
                if item.notice_level == from_level:
                    item.notice_level = to_level
                    modified = True

        # 个人通缉
        for qq, items in self._wanted_mgr._personal.items():
            for item in items:
                if item.notice_level == from_level:
                    item.notice_level = to_level
                    modified = True

        return modified

    def _reset_notice_levels_on_startup(self) -> None:
        """
        启动时重置临时提升的 notice_level。
        仅重置 level=3 (HIGH_BEFORE_SETTLEMENT) → level=1 (DEFAULT)。
        """

        need_save = self._reset_notice_level(
            NOTICE_LEVEL_HIGH_BEFORE_SETTLEMENT, NOTICE_LEVEL_DEFAULT
        )

        if need_save:
            self.save_config()


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


def render_subscription_status(rows_data: List[SubStatusRow]):
    """
    将订阅状态行列表渲染为富文本图片表格。
    """

    headers = [
        Header("#", align="center"),
        Header("昵称", min_width="21em"),
        Header("UID", min_width="14em"),
        Header("通知群", align="center", min_width="12em"),
        Header("战斗竞技场", align="center"),
        Header("公主竞技场", align="center"),
        Header("通知", align="center"),
    ]
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
                _rank_cell(r.arena_group, r.arena_rank, CELL_FONT_SIZE),
                _rank_cell(r.grand_arena_group, r.grand_arena_rank, CELL_FONT_SIZE),
                Cell(content=notify, align="center"),
            ]
        )

    return render_table(
        headers=headers,
        rows=rows,
        title="竞技场订阅状态",
    )


def render_subscription_status_cq(rows_data: List[SubStatusRow]) -> str:
    """
    将订阅状态行列表渲染为富文本图片表格，返回 CQ 码字符串。
    由 service.py 的 send_arena_sub_status handler 调用。
    """

    return image_to_cq(render_subscription_status(rows_data))
