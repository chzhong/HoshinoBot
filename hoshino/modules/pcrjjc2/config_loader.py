"""
config_loader.py - 加载并解析 pcrjjc2 的 config.yaml 配置文件，返回强类型 Config。

提供:
    - load_config(config_path?) -> Config
    - get_current_period(periods, now?) -> Optional[Period]
    - get_check_config(check_config_map, period_name) -> CheckConfig
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from os.path import dirname, exists, join
from typing import Dict, Final, List, Optional

import yaml
from schema import (
    CheckConfig,
    CheckConfigMap,
    CheckConfigMapDict,
    Config,
    ConfigDict,
    Period,
    PeriodDict,
    SubscriptionConfig,
    SubscriptionConfigDict,
    SubscriptionItem,
    SubscriptionMap,
)

TZ_CST = timezone(timedelta(hours=8))


CURRENT_CONFIG_VERSION: Final = 2
FIRST_CONFIG_VERSION: Final = 2


_DEFAULT_CHECK_CONFIG = CheckConfig(interval=5, delay=20)

_DEFAULT_PERIODS: List[Period] = [
    Period(
        name="settlement", description="结算时段（15:00排名刷新）", cron="0 15 * * *"
    ),
    Period(
        name="critical",
        description="卡点时间（每日排名结算前关键期）",
        cron="50-59 14 * * *",
    ),
    Period(
        name="hot", description="击剑时段（每日排名结算前活跃期）", cron="0-49 14 * * *"
    ),
    Period(name="cold", description="宵禁时段（深夜低活跃期）", cron="* 2-6 * * *"),
]

_SETTLEMENT_CHECK_CONFIG = CheckConfig(interval=0, delay=0)
"""
结算点的检测设置
"""

_DEFAULT_SUB_CONFIG = CheckConfig(interval=1, delay=15)
"""
订阅的默认检测间隔（1分钟）
"""

_DEFAULT_WANTED_CONFIG = CheckConfig(interval=5, delay=20)
"""
被通缉对象的默认检测间隔（5分钟）
"""

_DEFAULT_SUB_CHECK_CONFIGS: CheckConfigMap = {
    "default": _DEFAULT_SUB_CONFIG,
    "settlement": _SETTLEMENT_CHECK_CONFIG,
}

_DEFAULT_WANTED_CHECK_CONFIGS: CheckConfigMap = {
    "default": _DEFAULT_WANTED_CONFIG,
    "hot": CheckConfig(interval=2, delay=5),
    "critical": CheckConfig(interval=1, delay=0),
    "cold": CheckConfig(interval=15, delay=30),
    "settlement": _SETTLEMENT_CHECK_CONFIG,
}

_DEFAULT_CONFIG = Config(
    version=CURRENT_CONFIG_VERSION,
    periods=_DEFAULT_PERIODS,
    subscription=SubscriptionConfig(
        check_config=_DEFAULT_SUB_CHECK_CONFIGS,
        items={},
    ),
)

_SETTLEMENT_PERIOD = Period(
    name="settlement",
    description="结算时段（15:00排名刷新）",
    cron="0 15 * * *",
)


def _parse_periods(raw: List[PeriodDict]) -> List[Period]:
    periods = [Period.from_dict(p) for p in raw]
    if not any(p.name == "settlement" for p in periods):
        periods.insert(0, _SETTLEMENT_PERIOD)
    return periods


def _parse_check_configs(
    raw: CheckConfigMapDict, default: CheckConfig
) -> CheckConfigMap:
    result: CheckConfigMap = {}
    for name, v in raw.items():
        result[name] = CheckConfig.from_any(v)
    if "default" not in result:
        # 如果没有指定默认检测设置，则使用默认值。
        # 订阅对象和通缉对象的默认设置不同
        result["default"] = default
    # 强制指定结算点的检测逻辑
    result["settlement"] = _SETTLEMENT_CHECK_CONFIG
    return result


def _parse_subscriptions(raw: SubscriptionConfigDict) -> SubscriptionConfig:
    check_config_dict: Optional[CheckConfigMapDict] = None
    if "check_config" in raw:
        check_config_dict = raw["check_config"]
    if check_config_dict:
        check_config = _parse_check_configs(check_config_dict, _DEFAULT_SUB_CONFIG)
    else:
        check_config = _DEFAULT_SUB_CHECK_CONFIGS
    items: SubscriptionMap = {}
    if "items" in raw:
        items_map = raw["items"]
        for qq, subs in items_map.items():
            sub_item: List[SubscriptionItem] = []
            for sub in subs:
                sub_item.append(SubscriptionItem.from_dict(sub))
            items[qq] = sub_item
    return SubscriptionConfig(check_config=check_config, items=items)


def load_config(config_path: Optional[str] = None) -> Config:
    """加载 config.yaml 并解析为强类型 Config。文件不存在时返回内置默认值。"""
    path = config_path or join(dirname(__file__), "config.yaml")
    if not exists(path):
        return deepcopy(_DEFAULT_CONFIG)

    with open(path, encoding="utf-8") as f:
        data: ConfigDict = yaml.safe_load(f) or {}

    version = data.get("version", FIRST_CONFIG_VERSION)
    periods = _parse_periods(data.get("periods", []))
    subscriptions = _parse_subscriptions(data.get("subscription", {}))

    return Config(
        version=version,
        periods=periods,
        subscription=subscriptions,
    )


def localize_datetime(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TZ_CST)
    return dt.astimezone(TZ_CST)


def get_current_period(
    periods: List[Period], now: Optional[datetime] = None
) -> Optional[Period]:
    """
    返回当前时刻所属的时间段（按 periods 顺序，第一个匹配优先）。
    无匹配返回 None，调用方应回退到 'default' 配置。
    """
    try:
        from croniter import croniter
    except ImportError:
        return None

    if now is None:
        now = datetime.now(TZ_CST)

    now_min = localize_datetime(now.replace(second=0, microsecond=0))

    for p in periods:
        try:
            if croniter.match(p.cron, now_min):
                return p
        except Exception:
            continue

    return None


def save_config(config: Config, config_path: Optional[str] = None) -> None:
    """将 Config 序列化写回 config.yaml。"""
    path = config_path or join(dirname(__file__), "config.yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(
            config.to_dict(),
            f,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )


def get_check_config(
    check_config_map: Dict[str, CheckConfig], period_name: str
) -> CheckConfig:
    """根据时间段名称返回对应的 CheckConfig，不存在时回退到 'default'。"""
    return check_config_map.get(period_name) or check_config_map.get(
        "default", _DEFAULT_CHECK_CONFIG
    )
