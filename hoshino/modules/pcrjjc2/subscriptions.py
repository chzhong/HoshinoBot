"""
subscriptions.py - 订阅数据内存管理

SubscriptionManager 持有内存中的订阅 items dict，提供 CRUD 操作。
加载和保存由 config_loader 负责，不在此模块进行文件 I/O。
"""

from __future__ import annotations

from typing import Dict, List, Optional, TypedDict

from typing_extensions import TypeAlias

from schema import SubscriptionItem

_MAX_SUBS = 8

# SubscriptionItem 直接从 schema 重导出，供外部 import
__all__ = ["SubscriptionManager", "SubscriptionItem"]


class SubscriptionManager:
    """
    订阅数据的内存 CRUD 管理器。
    items 格式：{ qq: [SubscriptionItem, ...] }
    不持有文件路径，不负责 I/O。
    """

    def __init__(self, items: Optional[Dict[str, List[SubscriptionItem]]] = None):
        self._items: Dict[str, List[SubscriptionItem]] = items or {}

    # ------------------------------------------------------------------ #
    # CRUD                                                                 #
    # ------------------------------------------------------------------ #

    def get_list(self, qq: str) -> List[SubscriptionItem]:
        """返回 qq 用户的订阅列表（可能为空列表）。"""
        return list(self._items.get(str(qq), []))

    def get_list_by_gid(self, qq: str, gid: str) -> List[SubscriptionItem]:
        """返回 qq 用户在指定群的订阅列表。"""
        return [s for s in self.get_list(qq) if s.gid == str(gid)]

    def get_all_items(self) -> List[tuple]:
        """
        返回所有订阅的 (qq: str, item: SubscriptionItem) 列表，供调度任务遍历。
        """
        result = []
        for qq, subs in self._items.items():
            for item in subs:
                result.append((str(qq), item))
        return result

    def add(
        self,
        qq: str,
        uid: str,
        gid: str,
        arena_on: bool = True,
        grand_arena_on: bool = True,
    ) -> str:
        """
        尝试追加订阅。
        返回值：'ok' / 'dup' / 'full'
        """
        qq = str(qq)
        uid = str(uid)
        gid = str(gid)

        existing = self.get_list(qq)
        if any(s.id == uid for s in existing):
            return "dup"
        if len(existing) >= _MAX_SUBS:
            return "full"

        existing.append(
            SubscriptionItem(id=uid, gid=gid, arena_on=arena_on, grand_arena_on=grand_arena_on)
        )
        self._items[qq] = existing
        return "ok"

    def remove(self, qq: str, index: int) -> bool:
        """
        按 1-based 编号删除订阅。
        返回 True 表示删除成功，False 表示编号超界。
        """
        qq = str(qq)
        existing = self.get_list(qq)
        idx = index - 1
        if idx < 0 or idx >= len(existing):
            return False
        del existing[idx]
        if existing:
            self._items[qq] = existing
        else:
            self._items.pop(qq, None)
        return True

    def set_toggle(
        self,
        qq: str,
        index: Optional[int],
        arena_on: Optional[bool],
        grand_arena_on: Optional[bool],
    ) -> bool:
        """
        切换开关。
        index=None 时操作所有订阅；arena_on/grand_arena_on=None 时不修改该字段。
        返回 True 表示操作了至少一项。
        """
        qq = str(qq)
        existing = self.get_list(qq)
        if not existing:
            return False

        changed = False
        for i, sub in enumerate(existing):
            if index is not None and (i + 1) != index:
                continue
            if arena_on is not None:
                sub.arena_on = arena_on
                changed = True
            if grand_arena_on is not None:
                sub.grand_arena_on = grand_arena_on
                changed = True

        if changed:
            self._items[qq] = existing
        return changed

    def move_group(self, qq: str, index: int, new_gid: str) -> bool:
        """
        将第 index（1-based）个订阅的通知群改为 new_gid。
        返回 True 表示修改成功，False 表示编号超界。
        """
        qq = str(qq)
        new_gid = str(new_gid)
        existing = self.get_list(qq)
        idx = index - 1
        if idx < 0 or idx >= len(existing):
            return False
        existing[idx].gid = new_gid
        self._items[qq] = existing
        return True

    # ------------------------------------------------------------------ #
    # 迁移                                                                 #
    # ------------------------------------------------------------------ #

    def migrate_from_old(self, old_binds: LegacyArenaBind) -> None:
        """
        从旧 binds.json 的 arena_bind 字典迁移。
        old_binds 格式: { qq: {id, uid, gid, arena_on, grand_arena_on} }
        不覆盖已有数据。
        """
        for qq, info in old_binds.items():
            qq = str(qq)
            if qq in self._items:
                continue  # 已有数据，跳过
            self._items[qq] = [
                SubscriptionItem(
                    id=str(info["id"]),
                    gid=str(info["gid"]),
                    arena_on=bool(info.get("arena_on", True)),
                    grand_arena_on=bool(info.get("grand_arena_on", True)),
                )
            ]


class LegacyArenaBindItem(TypedDict):
    id: int  # game id
    uid: int  # qq
    gid: int  # qq group id
    arena_on: Optional[bool]
    grand_arena_on: Optional[bool]


LegacyArenaBind: TypeAlias = Dict[str, LegacyArenaBindItem]


class LegacyBindConfig(TypedDict):
    arena_bind: LegacyArenaBind
