"""
types.py - pcrjjc2 共享强类型定义

所有 dataclass 在此统一定义，避免循环导入。
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, TypedDict, Union

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

    check_config: CheckConfigMap
    items: SubscriptionMap = field(default_factory=dict)

    def to_dict(self) -> "SubscriptionConfigDict":
        return asdict(self)


class ConfigDict(TypedDict):
    version: Optional[int]
    periods: List[PeriodDict]
    subscription: SubscriptionConfigDict


@dataclass
class Config:
    """顶层配置，对应整个 config.yaml 解析结果。"""

    version: Optional[int]
    periods: List[Period]
    subscription: SubscriptionConfig

    def to_dict(self) -> "SubscriptionConfigDict":
        return asdict(self)


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
