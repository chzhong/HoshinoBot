"""
types.py - pcrjjc2 共享强类型定义

所有 dataclass 在此统一定义，避免循环导入。
"""

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Final, List, Optional, TypedDict, Union

from typing_extensions import TypeAlias

QQID: TypeAlias = int
QQGroupId: TypeAlias = int
PcrUid: TypeAlias = str


class CheckConfigDict(TypedDict):
    interval: int
    delay: Optional[int]


CheckConfigLike: TypeAlias = Union[CheckConfigDict, int, str]
CheckConfigMapDict: TypeAlias = Dict[str, CheckConfigLike]


@dataclass
class CheckConfig:
    interval: int  # 检测间隔（分钟）；0 表示仅触发一次（结算专用）
    delay: int = 20  # 触发后随机延迟上限（秒）

    def to_dict(self) -> CheckConfigDict:
        return asdict(self)

    def to_item(self) -> Union[int, CheckConfigDict]:
        if self.delay == 20:
            return self.interval
        return self.to_dict()

    @staticmethod
    def from_dict(d: CheckConfigDict) -> "CheckConfig":
        return CheckConfig(interval=int(d["interval"]), delay=d.get("delay", 20))

    @staticmethod
    def from_any(obj: Any) -> "CheckConfig":
        if isinstance(obj, int):
            return CheckConfig(interval=obj, delay=20)
        elif isinstance(obj, str) and obj.isdigit():
            return CheckConfig(interval=int(obj))
        elif isinstance(obj, dict):
            return CheckConfig.from_dict(obj)
        elif isinstance(obj, CheckConfig):
            return obj
        raise ValueError(f"cannot convert {obj} of type {type(obj)} into CheckConfig")


CheckConfigMap: TypeAlias = Dict[str, CheckConfig]


class PeriodDict(TypedDict):
    name: str
    description: Optional[str]
    cron: str


@dataclass
class Period:
    name: str
    description: Optional[str]
    cron: str

    def to_dict(self) -> PeriodDict:
        return asdict(self)

    @staticmethod
    def from_dict(d: PeriodDict) -> "Period":
        return Period(
            name=d["name"], description=d.get("description", ""), cron=d["cron"]
        )


class SubscriptionItemLikeDict(TypedDict):
    id: Union[str, int]  # PCR uid（13位）
    gid: Union[str, int]  # 绑定时所在群 id
    arena_on: Optional[bool]
    grand_arena_on: Optional[bool]


SubcriptionLikeMapDict: TypeAlias = Dict[str, List[SubscriptionItemLikeDict]]


class SubscriptionItemDict(TypedDict):
    id: str  # PCR uid（13位）
    gid: str  # 绑定时所在群 id
    arena_on: Optional[bool] = True
    grand_arena_on: Optional[bool] = True


@dataclass
class SubscriptionItem:
    """单个订阅项（对应 subscriptions.json 中的一条记录）。"""

    id: str  # PCR uid（13位）
    gid: str  # 绑定时所在群 id
    arena_on: Optional[bool] = True
    grand_arena_on: Optional[bool] = True

    def to_dict(self) -> SubscriptionItemDict:
        return asdict(self)

    def to_item(self) -> SubscriptionItemDict:
        d = self.to_dict()
        if self.arena_on:
            del d["arena_on"]
        if self.grand_arena_on:
            del d["grand_arena_on"]
        return d

    @staticmethod
    def from_dict(d: SubscriptionItemLikeDict) -> "SubscriptionItem":
        return SubscriptionItem(
            id=str(d["id"]),
            gid=str(d["gid"]),
            arena_on=bool(d.get("arena_on", True)),
            grand_arena_on=bool(d.get("grand_arena_on", True)),
        )


SubscriptionMap: TypeAlias = Dict[str, List[SubscriptionItem]]


class SubscriptionConfigDict(TypedDict):
    check_config: CheckConfigMapDict
    items: SubcriptionLikeMapDict


@dataclass
class SubscriptionConfig:
    """订阅相关配置，包含检测时段配置和订阅数据（运行时由 SubscriptionManager 填充）。"""

    check_config: CheckConfigMap = field(default_factory=dict)
    items: SubscriptionMap = field(default_factory=dict)

    def to_dict(self) -> SubscriptionConfigDict:
        d: SubscriptionConfigDict = {
            "check_config": {},
            "items": {},
        }
        for name, cfg in self.check_config.items():
            d["check_config"][name] = cfg.to_item()
        for qq, subs in self.items.items():
            d["items"][qq] = list(map(lambda item: item.to_item(), subs))
        return d


class BaseWantedItemDict(TypedDict):
    id: str  # 通缉对象的 uid
    note: Optional[str]
    watch_at: Optional[int]
    notice_level: Optional[int]
    arena_on: Optional[bool]
    grand_arena_on: Optional[bool]


class PersonalWantedItemDict(BaseWantedItemDict):
    gid: str  # 通缉群


class GroupWantedItemDict(BaseWantedItemDict):
    by: Optional[str]  # 通缉者的 qq


PersonalWantedListDict: TypeAlias = Dict[str, List[PersonalWantedItemDict]]
GroupWantedListDict: TypeAlias = Dict[str, List[Union[GroupWantedItemDict, str, int]]]

WATCH_AT_NONE: Final = 0
WATCH_AT_ARENA: Final = 1
WATCH_AT_GRAND_ARENA: Final = 2
WATCH_AT_BOTH: Final = WATCH_AT_ARENA | WATCH_AT_GRAND_ARENA

NOTICE_LEVEL_NONE: Final = 0
NOTICE_LEVEL_DEFAULT: Final = 1
NOTICE_LEVEL_ATTENTION: Final = 2
NOTICE_LEVEL_HIGH_BEFORE_SETTLEMENT: Final = 3
NOTICE_LEVEL_HIGH_TODAY: Final = 4
NOTICE_LEVEL_HIGH: Final = 5


@dataclass
class WantedItem:
    id: str  # 通缉对象的 uid
    gid: str  # 通缉消息发送群。群通缉同群号
    by: str = ""  # 通缉者的 qq。个人通缉同个人 qq 号
    note: str = ""
    watch_at: int = WATCH_AT_BOTH
    notice_level: int = NOTICE_LEVEL_DEFAULT
    arena_on: bool = True    # jjc 通知开关
    grand_arena_on: bool = True  # pjjc 通知开关

    def to_dict(self) -> Union[PersonalWantedItemDict, GroupWantedItemDict]:
        return asdict(self)

    def _to_item(self) -> Union[PersonalWantedItemDict, GroupWantedItemDict]:
        """序列化为简化 dict，省略默认值字段。"""
        d = self.to_dict()
        if not self.note:
            d.pop("note", None)
        if self.watch_at == WATCH_AT_BOTH:
            d.pop("watch_at", None)
        if self.notice_level == NOTICE_LEVEL_DEFAULT:
            d.pop("notice_level", None)
        if self.arena_on:
            d.pop("arena_on", None)
        if self.grand_arena_on:
            d.pop("grand_arena_on", None)
        return d

    @property
    def _is_all_default(self) -> bool:
        return (
            not self.note
            and self.watch_at == WATCH_AT_BOTH
            and self.notice_level == NOTICE_LEVEL_DEFAULT
            and self.arena_on
            and self.grand_arena_on
        )

    def to_personal_item(self) -> PersonalWantedItemDict:
        d: PersonalWantedItemDict = self._to_item()
        d.pop("by", None)
        return d

    def to_group_item(self) -> Union[str, GroupWantedItemDict]:
        """序列化为群通缉条目。全默认且无通缉者时简化为纯 uid 字符串。"""
        if self._is_all_default and not self.by:
            return self.id
        d: GroupWantedItemDict = self._to_item()
        d.pop("gid", None)
        if not self.by:
            d.pop("by", None)
        return d

    @staticmethod
    def from_dict(d: Union[PersonalWantedItemDict, GroupWantedItemDict]) -> "WantedItem":
        gid = d.get("gid")
        by = d.get("by")
        return WantedItem(
            id=str(d["id"]),
            gid=str(gid) if gid else "",
            by=str(by) if by else "",
            note=d.get("note", ""),
            watch_at=d.get("watch_at", WATCH_AT_BOTH),
            notice_level=d.get("notice_level", NOTICE_LEVEL_DEFAULT),
            arena_on=bool(d.get("arena_on", True)),
            grand_arena_on=bool(d.get("grand_arena_on", True)),
        )

    @staticmethod
    def from_personal_item(
        by: str, obj: Union[PersonalWantedItemDict, "WantedItem"]
    ) -> "WantedItem":
        if isinstance(obj, dict):
            item = WantedItem.from_dict(obj)
            item.by = by
            return item
        elif isinstance(obj, WantedItem):
            if obj.by == by:
                return obj
            item = deepcopy(obj)
            item.by = by
            return item
        raise ValueError(f"cannot convert {obj} of type {type(obj)} into WantedItem")

    @staticmethod
    def from_group_item(
        gid: str, obj: Union[int, str, GroupWantedItemDict, "WantedItem"]
    ) -> "WantedItem":
        if isinstance(obj, (str, int)):
            return WantedItem(id=str(obj), gid=gid)
        elif isinstance(obj, dict):
            item = WantedItem.from_dict(obj)
            item.gid = gid
            return item
        elif isinstance(obj, WantedItem):
            if obj.gid == gid:
                return obj
            item = deepcopy(obj)
            item.gid = gid
            return item
        raise ValueError(f"cannot convert {obj} of type {type(obj)} into WantedItem")


PersonalWantedListMap: TypeAlias = Dict[str, List[WantedItem]]
GroupWantedListMap: TypeAlias = Dict[str, List[WantedItem]]


class WantedListConfigDict(TypedDict):
    check_config: CheckConfigMapDict
    group: GroupWantedListDict
    personal: PersonalWantedListDict


@dataclass
class WantedListConfig:
    check_config: CheckConfigMap = field(default_factory=dict)
    group: GroupWantedListMap = field(default_factory=dict)
    personal: PersonalWantedListMap = field(default_factory=dict)

    def to_dict(self):
        d: WantedListConfigDict = {"check_config": {}}
        for name, cfg in self.check_config.items():
            d["check_config"][name] = cfg.to_item()
        group_config: GroupWantedListDict = {}
        for gid, gwl in self.group.items():
            items = list(map(lambda item: item.to_group_item(), gwl))
            group_config[gid] = items
        d["group"] = group_config
        personal_config: PersonalWantedListDict = {}
        for qq, pwl in self.personal.items():
            items = list(map(lambda item: item.to_personal_item(), pwl))
            personal_config[qq] = items
        d["personal"] = personal_config

        return d


class ConfigDict(TypedDict):
    version: Optional[int]
    periods: List[PeriodDict]
    subscription: SubscriptionConfigDict
    wanted_list: WantedListConfigDict


@dataclass
class Config:
    """顶层配置，对应整个 config.yaml 解析结果。"""

    version: Optional[int]
    periods: List[Period]
    subscription: SubscriptionConfig
    wanted_list: WantedListConfig = field(default_factory=WantedListConfig)

    def to_dict(self) -> ConfigDict:
        d: ConfigDict = {"periods": []}
        if self.version:
            d["version"] = self.version
        for p in self.periods:
            d["periods"].append(p.to_dict())
        if self.subscription:
            d["subscription"] = self.subscription.to_dict()
        if self.wanted_list:
            d["wanted_list"] = self.wanted_list.to_dict()
        return d


# See profile_example.json
@dataclass
class PcrEmblem:
    emblem_id: int
    ex_value: 0


@dataclass
class PcrUserInfo:
    viewer_id: int
    user_name: str
    user_comment: str
    team_level: int
    team_exp: int
    emblem: PcrEmblem
    last_login_time: int
    arena_rank: int
    arena_group: int
    grand_arena_rank: int
    grand_arena_group: int
    open_story_num: int
    unit_num: int
    total_power: int
    tower_cleared_floor_num: int
    tower_cleared_ex_quest_count: int
    friend_num: int
