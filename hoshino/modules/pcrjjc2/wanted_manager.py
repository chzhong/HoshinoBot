"""
wanted_manager.py - 通缉 v2 数据管理（新逻辑）

数据格式 wanted_v2.json:
{
    "group": {
        "GID": [
            {"uid": "1012345678901", "note": "备注", "watch_at": 3, "notice_level": 1}
        ]
    },
    "personal": {
        "QQ": {
            "group": "GID",
            "items": [
                {"uid": "1012345678901", "note": "备注", "watch_at": 3, "notice_level": 1}
            ]
        }
    }
}
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from os.path import dirname, exists, join
from typing import Dict, List, Optional, TypedDict

from typing_extensions import TypeAlias

_WANTED_V2_PATH = join(dirname(__file__), "wanted_v2.json")
_MAX_PERSONAL = 8


@dataclass
class Wanted:
    uid: str
    note: str = ""
    watch_at: int = 3  # 监控阈值（排名变动超过此值才通知）
    notice_level: int = 1  # 1=通缉（攻击时通知）, 2=关注（仅上线通知）

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Wanted":
        return Wanted(
            uid=str(d["uid"]),
            note=str(d.get("note", "")),
            watch_at=int(d.get("watch_at", 3)),
            notice_level=int(d.get("notice_level", 1)),
        )


@dataclass
class PersonalWanted:
    group: str  # 通知目标群
    items: List[Wanted]

    def to_dict(self) -> dict:
        return {
            "group": self.group,
            "items": [w.to_dict() for w in self.items],
        }

    @staticmethod
    def from_dict(d: dict) -> "PersonalWanted":
        return PersonalWanted(
            group=str(d["group"]),
            items=[Wanted.from_dict(x) for x in d.get("items", [])],
        )


class WantedManager:
    def __init__(self):
        self._data: dict = {"group": {}, "personal": {}}
        self._load()

    def _load(self):
        if exists(_WANTED_V2_PATH):
            with open(_WANTED_V2_PATH, encoding="utf-8") as f:
                self._data = json.load(f)
        if "group" not in self._data:
            self._data["group"] = {}
        if "personal" not in self._data:
            self._data["personal"] = {}

    def save(self):
        with open(_WANTED_V2_PATH, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=4)

    # ------------------------------------------------------------------ #
    # 群通缉                                                               #
    # ------------------------------------------------------------------ #

    def list_group(self, gid: str) -> List[Wanted]:
        raw = self._data["group"].get(str(gid), [])
        return [Wanted.from_dict(x) for x in raw]

    def add_group(self, gid: str, wanted: Wanted) -> bool:
        """添加群通缉。若已存在则返回 False，否则返回 True。"""
        gid = str(gid)
        existing = self.list_group(gid)
        if any(w.uid == wanted.uid for w in existing):
            return False
        existing.append(wanted)
        self._data["group"][gid] = [w.to_dict() for w in existing]
        self.save()
        return True

    def remove_group(self, gid: str, uid: str) -> bool:
        """删除群通缉。若不存在则返回 False。"""
        gid = str(gid)
        uid = str(uid)
        existing = self.list_group(gid)
        new_list = [w for w in existing if w.uid != uid]
        if len(new_list) == len(existing):
            return False
        if new_list:
            self._data["group"][gid] = [w.to_dict() for w in new_list]
        else:
            self._data["group"].pop(gid, None)
        self.save()
        return True

    # ------------------------------------------------------------------ #
    # 个人通缉                                                             #
    # ------------------------------------------------------------------ #

    def list_personal(self, qq: str) -> Optional[PersonalWanted]:
        raw = self._data["personal"].get(str(qq))
        if raw is None:
            return None
        return PersonalWanted.from_dict(raw)

    def add_personal(self, qq: str, gid: str, wanted: Wanted) -> str:
        """
        添加个人通缉（绑定到 gid 群）。
        返回值:
            'ok'   - 成功
            'dup'  - 已存在
            'full' - 已达上限
        """
        qq = str(qq)
        gid = str(gid)
        pw = self.list_personal(qq)
        if pw is None:
            pw = PersonalWanted(group=gid, items=[])

        if any(w.uid == wanted.uid for w in pw.items):
            return "dup"
        if len(pw.items) >= _MAX_PERSONAL:
            return "full"

        pw.items.append(wanted)
        self._data["personal"][qq] = pw.to_dict()
        self.save()
        return "ok"

    def remove_personal(self, qq: str, uid: str) -> bool:
        """删除个人通缉。若不存在则返回 False。"""
        qq = str(qq)
        uid = str(uid)
        pw = self.list_personal(qq)
        if pw is None:
            return False
        new_items = [w for w in pw.items if w.uid != uid]
        if len(new_items) == len(pw.items):
            return False
        if new_items:
            pw.items = new_items
            self._data["personal"][qq] = pw.to_dict()
        else:
            self._data["personal"].pop(qq, None)
        self.save()
        return True

    # ------------------------------------------------------------------ #
    # 迁移                                                                 #
    # ------------------------------------------------------------------ #

    def migrate_from_old(
        self, old_wanted: LegacyWantedBind, old_watch: LegacyWatchBind
    ):
        """
        从旧数据迁移。
        old_wanted: wanted_bind  { gid: [uid, ...] }  -> group wanted, notice_level=1
        old_watch:  watch_bind   { gid: [uid, ...] }  -> group watched, notice_level=2
        不覆盖已有数据。
        """
        for gid, uid_list in old_wanted.items():
            gid = str(gid)
            if gid in self._data["group"]:
                continue  # 已有数据，跳过
            items = [
                Wanted(uid=str(uid), watch_at=3, notice_level=1).to_dict()
                for uid in uid_list
            ]
            self._data["group"][gid] = items

        for gid, uid_list in old_watch.items():
            gid = str(gid)
            existing = {w["uid"] for w in self._data["group"].get(gid, [])}
            extra = [
                Wanted(uid=str(uid), watch_at=3, notice_level=2).to_dict()
                for uid in uid_list
                if str(uid) not in existing
            ]
            if extra:
                self._data["group"].setdefault(gid, []).extend(extra)

        self.save()


LegacyWantedBind: TypeAlias = Dict[str, List[str]]
LegacyWatchBind: TypeAlias = Dict[str, List[str]]


class LegacyWantedConfig(TypedDict):
    wanted_bind: Optional[LegacyWantedBind]
    watch_bind: Optional[LegacyWatchBind]
