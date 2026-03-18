"""
wanted_manager.py - 通缉数据内存管理

WantedManager 持有 WantedListConfig 中的 group/personal 两张表，
提供 CRUD 操作。加载和保存由 config_loader + ArenaService.save_config 负责，
本模块不做任何文件 I/O。
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, TypedDict

from typing_extensions import TypeAlias

from .schema import (
    NOTICE_LEVEL_HIGH,
    AddWatchSubResult,
    WantedItem,
    WantedListConfig,
    is_attention_level,
    is_high_notice_level,
)

_MAX_GROUP = 30
_MAX_PERSONAL = 8


@dataclass
class Watcher:
    """
    通缉者(群或个人)
    """

    id: str  # 通缉人的 QQ，群通缉者为空
    gid: str  # 通知群
    level: int  # 通缉级别
    arena_on: bool
    grand_arena_on: bool

    def should_notice_arena(self, hour: int):
        """
        判断在给定的小时是否应该通告jjc排名变化
        """
        # notice_level = 0 时不通报排名变化
        if self.level == 0:
            return False
        return self.arena_on or (hour == 14 and self.is_attention_level)

    def should_notice_grand_arena(self, hour: int):
        """
        判断在给定的小时是否应该通告pjjc排名变化
        """
        # notice_level = 0 时不通报排名变化
        if self.level == 0:
            return False
        return self.grand_arena_on or (hour == 14 and self.is_attention_level)

    @property
    def is_attention_level(self):
        """
        判断一个通缉者是否要求关注。关注意味着14:00~14:59期间强制通报双场排名变化。
        """
        return is_attention_level(self.level)

    @property
    def is_high_level(self):
        """
        判断一个通缉者是否要求高频通知。高频意味着1分钟检测和通报一次。
        """
        return is_high_notice_level(self.level)

    @property
    def _sort_level(self):
        return NOTICE_LEVEL_HIGH if self.is_high_level else self.level


def sort_watchers(watchers: List[Watcher]) -> List[Watcher]:
    """
    按群号、通缉者qq 号和通知级别排序
    """
    return sorted(watchers, key=lambda w: (w.gid, w.id, -w._sort_level))


@dataclass
class WantedDetail:
    """
    被通缉人的通缉人详细状况
    """

    uid: str  # 被通缉人的 UID
    watchers: List[Watcher]  # 通缉此人的所有群和个人

    @property
    def high_watchers(self) -> List[Watcher]:
        """
        通缉犯被要求高频通知的群和个人
        """
        return list(filter(lambda w: is_high_notice_level(w.level), self.watchers))


class WantedManager:
    """
    通缉数据的内存 CRUD 管理器。
    group   格式：{ gid: [WantedItem, ...] }
    personal格式：{ qq:  [WantedItem, ...] }  每条 item.gid 独立
    不持有文件路径，不负责 I/O。
    """

    def __init__(self, config: WantedListConfig):
        self._check_config = config.check_config
        self._group: Dict[str, List[WantedItem]] = config.group
        self._personal: Dict[str, List[WantedItem]] = config.personal

    # ------------------------------------------------------------------ #
    # 群通缉                                                               #
    # ------------------------------------------------------------------ #

    def list_group(self, gid: str) -> List[WantedItem]:
        """返回群 gid 的通缉列表（可能为空列表）。"""
        return list(self._group.get(str(gid), []))

    def add_group(self, gid: str, item: WantedItem) -> AddWatchSubResult:
        """
        添加群通缉。
        返回值：'ok' / 'dup' / 'full'
        """
        gid = str(gid)
        existing = self.list_group(gid)
        if any(w.id == item.id for w in existing):
            return "dup"
        if len(existing) >= _MAX_GROUP:
            return "full"
        item.gid = gid
        existing.append(item)
        self._group[gid] = existing
        return "ok"

    def remove_group(self, gid: str, uid: str) -> bool:
        """删除群通缉。若不存在返回 False。"""
        gid = str(gid)
        uid = str(uid)
        existing = self.list_group(gid)
        new_list = [w for w in existing if w.id != uid]
        if len(new_list) == len(existing):
            return False
        if new_list:
            self._group[gid] = new_list
        else:
            self._group.pop(gid, None)
        return True

    def set_group_notice_level(self, gid: str, uid: str, level: int) -> bool:
        """设置群通缉条目的 notice_level。返回 False 表示未找到。"""
        for item in self._group.get(str(gid), []):
            if item.id == str(uid):
                item.notice_level = level
                return True
        return False

    def set_group_watch_toggle(
        self,
        gid: str,
        uid: str,
        arena_on: Optional[bool] = None,
        grand_arena_on: Optional[bool] = None,
    ) -> bool:
        """切换群通缉条目的 jjc/pjjc 通知开关。返回 False 表示未找到。"""
        for item in self._group.get(str(gid), []):
            if item.id == str(uid):
                if arena_on is not None:
                    item.arena_on = arena_on
                if grand_arena_on is not None:
                    item.grand_arena_on = grand_arena_on
                return True
        return False

    def set_group_note(self, gid: str, uid: str, note: str) -> bool:
        """设置群通缉条目的备注。返回 False 表示未找到。"""
        for item in self._group.get(str(gid), []):
            if item.id == str(uid):
                item.note = note
                return True
        return False

    def get_group_by_uid(self, gid: str, uid: str) -> Optional[WantedItem]:
        """按 uid 获取群通缉项。返回 None 表示未找到。"""
        for item in self._group.get(str(gid), []):
            if item.id == str(uid):
                return item
        return None

    def get_group_by_index(self, gid: str, idx: int) -> Optional[WantedItem]:
        """按索引（1-based）获取群通缉项。返回 None 表示索引越界。"""
        items = self.list_group(gid)
        if 1 <= idx <= len(items):
            return items[idx - 1]
        return None

    # ------------------------------------------------------------------ #
    # 个人通缉                                                             #
    # ------------------------------------------------------------------ #

    def list_personal(self, qq: str) -> List[WantedItem]:
        """返回用户 qq 的个人通缉列表（可能为空列表）。"""
        return list(self._personal.get(str(qq), []))

    def add_personal(self, qq: str, item: WantedItem) -> str:
        """
        添加个人通缉（item.gid 已由调用方填入目标群）。
        返回值：'ok' / 'dup' / 'full'
        """
        qq = str(qq)
        existing = self.list_personal(qq)
        if any(w.id == item.id for w in existing):
            return "dup"
        if len(existing) >= _MAX_PERSONAL:
            return "full"
        item.by = qq
        existing.append(item)
        self._personal[qq] = existing
        return "ok"

    def remove_personal(self, qq: str, uid: str) -> bool:
        """删除个人通缉。若不存在返回 False。"""
        qq = str(qq)
        uid = str(uid)
        existing = self.list_personal(qq)
        new_list = [w for w in existing if w.id != uid]
        if len(new_list) == len(existing):
            return False
        if new_list:
            self._personal[qq] = new_list
        else:
            self._personal.pop(qq, None)
        return True

    def set_personal_notice_level(self, qq: str, uid: str, level: int) -> bool:
        """设置个人通缉条目的 notice_level。返回 False 表示未找到。"""
        for item in self._personal.get(str(qq), []):
            if item.id == str(uid):
                item.notice_level = level
                return True
        return False

    def set_personal_watch_toggle(
        self,
        qq: str,
        uid: str,
        arena_on: Optional[bool] = None,
        grand_arena_on: Optional[bool] = None,
    ) -> bool:
        """切换个人通缉条目的 jjc/pjjc 通知开关。返回 False 表示未找到。"""
        for item in self._personal.get(str(qq), []):
            if item.id == str(uid):
                if arena_on is not None:
                    item.arena_on = arena_on
                if grand_arena_on is not None:
                    item.grand_arena_on = grand_arena_on
                return True
        return False

    def set_personal_note(self, qq: str, uid: str, note: str) -> bool:
        """设置个人通缉条目的备注。返回 False 表示未找到。"""
        for item in self._personal.get(str(qq), []):
            if item.id == str(uid):
                item.note = note
                return True
        return False

    def get_personal_by_uid(self, qq: str, uid: str) -> Optional[WantedItem]:
        """按 uid 获取个人通缉项。返回 None 表示未找到。"""
        for item in self._personal.get(str(qq), []):
            if item.id == str(uid):
                return item
        return None

    def get_personal_by_index(self, qq: str, idx: int) -> Optional[WantedItem]:
        """按索引（1-based）获取个人通缉项。返回 None 表示索引越界。"""
        items = self.list_personal(qq)
        if 1 <= idx <= len(items):
            return items[idx - 1]
        return None

    # ------------------------------------------------------------------ #
    # 全量遍历（供调度任务）                                               #
    # ------------------------------------------------------------------ #

    def get_all_group_items(self) -> List[Tuple[str, WantedItem]]:
        """返回所有群通缉 (gid, item) 列表。"""
        result: List[Tuple[str, WantedItem]] = []
        for gid, items in self._group.items():
            for item in items:
                result.append((gid, item))
        return result

    def get_all_personal_items(self) -> List[Tuple[str, WantedItem]]:
        """返回所有个人通缉 (qq, item) 列表。"""
        result: List[Tuple[str, WantedItem]] = []
        for qq, items in self._personal.items():
            for item in items:
                result.append((qq, item))
        return result

    def get_wanted_list_for_monitor(self) -> List[WantedDetail]:
        """
        返回一个适合监控查询的通缉列表 [ {uid, watchers} ]
        将群通缉和个人通缉合并，按 uid 分组。
        """
        # uid -> List[Watcher]
        uid_to_watchers: Dict[str, List[Watcher]] = {}

        # 收集群通缉
        for gid, items in self._group.items():
            for item in items:
                uid = item.id
                if uid not in uid_to_watchers:
                    uid_to_watchers[uid] = []
                uid_to_watchers[uid].append(
                    Watcher(
                        id="",  # 群通缉者 id 为空
                        gid=gid,
                        level=item.notice_level,
                        arena_on=item.arena_on,
                        grand_arena_on=item.grand_arena_on,
                    )
                )

        # 收集个人通缉
        for qq, items in self._personal.items():
            for item in items:
                uid = item.id
                if uid not in uid_to_watchers:
                    uid_to_watchers[uid] = []
                uid_to_watchers[uid].append(
                    Watcher(
                        id=qq,  # 个人通缉者 id 为 qq
                        gid=item.gid,
                        level=item.notice_level,
                        arena_on=item.arena_on,
                        grand_arena_on=item.grand_arena_on,
                    )
                )

        # 转换为 WantedDetail 列表
        result = []
        for uid, watchers in uid_to_watchers.items():
            result.append(WantedDetail(uid=uid, watchers=sort_watchers(watchers)))
        return result

    # ------------------------------------------------------------------ #
    # 迁移                                                                 #
    # ------------------------------------------------------------------ #

    def migrate_from_old(self, old_wanted: "LegacyWantedBind") -> None:
        """
        从旧 wanted_binds.json 的 wanted_bind 字典迁移为群通缉。
        old_wanted: { gid: [uid, ...] }  -> group, notice_level=1
        不覆盖已有数据。
        """
        for gid, uid_list in old_wanted.items():
            gid = str(gid)
            if gid in self._group:
                continue
            self._group[gid] = [WantedItem(id=str(uid), gid=gid) for uid in uid_list]


LegacyWantedBind: TypeAlias = Dict[str, List[str]]
LegacyWatchBind: TypeAlias = Dict[str, List[str]]


class LegacyWantedConfig(TypedDict):
    wanted_bind: Optional[LegacyWantedBind]
    watch_bind: Optional[LegacyWatchBind]
