"""
test_utils.py - pcrjjc2 工具类单元测试

覆盖：config_loader、subscriptions、wanted_manager、table_image
这些类都是纯逻辑，无需 mock 外部依赖，直接实例化测试。

运行方式（在 HoshinoBot 根目录）：
    TEST=1 python -m hoshino.modules.pcrjjc2.test_utils

注：TEST=1 环境变量必须设置，否则模块会被 stub 掉
"""
# ruff: noqa: E402

import json
import os
import sys
import tempfile
from datetime import datetime

import yaml as _yaml
from PIL import Image as PILImage

# ── 辅助 ──────────────────────────────────────────────────────────────
PASS = 0
FAIL = 0


def check(label, got, expected):
    global PASS, FAIL
    if got == expected:
        print(f"  OK  {label}")
        PASS += 1
    else:
        print(f"  FAIL {label}")
        print(f"       got={got!r}")
        print(f"       expected={expected!r}")
        FAIL += 1


def section(name):
    print(f"\n{'=' * 50}")
    print(f"  {name}")
    print(f"{'=' * 50}")


# ── 1. config_loader ──────────────────────────────────────────────────
section("config_loader: load_config")

from ..config_loader import (
    TZ_CST,
    get_check_config,
    get_current_period,
    load_config,
)

# 使用不存在的文件路径，确保返回默认配置而不是加载已存在的 config.yaml
cfg = load_config("__nonexistent__.yaml")  # 返回 Config 对象

check("periods 不为空", len(cfg.periods) > 0, True)
check(
    "settlement 时段存在",
    any(p.name == "settlement" for p in cfg.periods),
    True,
)
check("check-config default 存在", "default" in cfg.subscription.check_config, True)

section("config_loader: get_current_period")

periods = cfg.periods
cc_map = cfg.subscription.check_config


def mkt(h: int, m: int):
    """构造 UTC+8 时间（固定偏移，避免 pytz LMT 问题）"""
    return datetime(2026, 3, 10, h, m, 0, tzinfo=TZ_CST)


test_cases = [
    (mkt(15, 0), "settlement"),
    (mkt(15, 1), None),  # settlement 只占1分钟
    (mkt(14, 59), "critical"),
    (mkt(14, 50), "critical"),
    (mkt(14, 49), "hot"),
    (mkt(14, 0), "hot"),
    (mkt(3, 0), "cold"),
    (mkt(2, 0), "cold"),
    (mkt(17, 30), None),  # 下午5点半 -> default
    (mkt(10, 0), None),  # 上午10点 -> default
]

for now, expected_name in test_cases:
    p = get_current_period(periods, now=now)
    got_name = p.name if p else None
    label = f"{now.strftime('%H:%M')} -> {expected_name or 'default'}"
    check(label, got_name, expected_name)

section("config_loader: get_check_config (subscription)")

# 订阅侧：config.yaml 不存在时走内置默认值 _DEFAULT_SUB_CHECK_CONFIGS
# 只有 default(interval=1) 和 settlement(interval=0)；
# hot/critical/cold 未配置，回退到 default(interval=1)
sub_cc_map = cfg.subscription.check_config
check(
    "sub settlement interval=0", get_check_config(sub_cc_map, "settlement").interval, 0
)
check("sub default interval=1", get_check_config(sub_cc_map, "default").interval, 1)
check("sub hot -> default interval=1", get_check_config(sub_cc_map, "hot").interval, 1)
check(
    "sub critical -> default interval=1",
    get_check_config(sub_cc_map, "critical").interval,
    1,
)
check(
    "sub cold -> default interval=1", get_check_config(sub_cc_map, "cold").interval, 1
)
check(
    "sub unknown -> default interval=1",
    get_check_config(sub_cc_map, "unknown").interval,
    1,
)

section("config_loader: get_check_config (wanted, built-in defaults)")

# 通缉侧：独立的内置配置 _DEFAULT_WANTED_CHECK_CONFIGS
# hot/critical/cold/default/settlement 各自独立设定
from ..config_loader import _DEFAULT_WANTED_CHECK_CONFIGS

wanted_cc_map = _DEFAULT_WANTED_CHECK_CONFIGS
check(
    "wanted settlement interval=0",
    get_check_config(wanted_cc_map, "settlement").interval,
    0,
)
check("wanted hot interval=2", get_check_config(wanted_cc_map, "hot").interval, 2)
check(
    "wanted critical interval=1",
    get_check_config(wanted_cc_map, "critical").interval,
    1,
)
check("wanted cold interval=15", get_check_config(wanted_cc_map, "cold").interval, 15)
check(
    "wanted default interval=5", get_check_config(wanted_cc_map, "default").interval, 5
)
check(
    "wanted unknown -> default=5",
    get_check_config(wanted_cc_map, "unknown").interval,
    5,
)

section("config_loader: _parse_check_configs 强制补全逻辑")

# 无论用户配置了什么，_parse_check_configs 保证：
# 1. 缺少 default 时补充传入的 default 值
# 2. settlement 强制覆盖为 interval=0
from ..config_loader import _DEFAULT_SUB_CONFIG, _DEFAULT_WANTED_CONFIG

check("sub default interval", _DEFAULT_SUB_CONFIG.interval, 1)
check("wanted default interval", _DEFAULT_WANTED_CONFIG.interval, 5)

# 验证 _parse_check_configs 对缺省 default 的补全行为
from ..config_loader import _parse_check_configs

parsed_no_default = _parse_check_configs({"hot": {"interval": 2}}, _DEFAULT_SUB_CONFIG)
check("parse: missing default补全sub=1", parsed_no_default["default"].interval, 1)
check(
    "parse: settlement强制覆盖interval=0", parsed_no_default["settlement"].interval, 0
)

parsed_with_default = _parse_check_configs(
    {"default": {"interval": 3}, "hot": {"interval": 2}}, _DEFAULT_WANTED_CONFIG
)
check("parse: 已有default不覆盖", parsed_with_default["default"].interval, 3)
check("parse: settlement仍强制=0", parsed_with_default["settlement"].interval, 0)

# ── 1b. config_loader: save/load round-trip ───────────────────────────
section("config_loader: save/load round-trip")

from ..config_loader import (
    _DEFAULT_PERIODS,
    _DEFAULT_SUB_CHECK_CONFIGS,
    _DEFAULT_WANTED_CHECK_CONFIGS,
    save_config,
)
from ..schema import (
    NOTICE_LEVEL_ATTENTION,
    NOTICE_LEVEL_DEFAULT,
    Config,
    SubscriptionConfig,
    SubscriptionItem,
    WantedItem,
    WantedListConfig,
)


def _make_full_config():
    """构造含完整数据的 Config 用于 round-trip 测试。"""

    sub_items = {
        "1234567890": [
            SubscriptionItem(id="1012345678901", gid="987654321"),
            SubscriptionItem(id="1012345678902", gid="987654321", arena_on=False),
        ],
        "1234567891": [
            SubscriptionItem(id="1012345678903", gid="987654321", grand_arena_on=False),
        ],
    }
    group_wanted = {
        "987654321": [
            WantedItem(id="1012345678901", gid="987654321"),  # 全默认 -> uid字符串
            WantedItem(id="1012345678902", gid="987654321", note="坏人"),
            WantedItem(id="1012345678903", gid="987654321", arena_on=False),
            WantedItem(
                id="1012345678904",
                gid="987654321",
                notice_level=NOTICE_LEVEL_ATTENTION,
            ),
        ],
    }
    personal_wanted = {
        "1234567890": [
            WantedItem(
                id="1012345678905", gid="987654321", by="1234567890", note="仇人"
            ),
        ],
    }
    return Config(
        version=2,
        periods=_DEFAULT_PERIODS,
        subscription=SubscriptionConfig(
            check_config=_DEFAULT_SUB_CHECK_CONFIGS, items=sub_items
        ),
        wanted_list=WantedListConfig(
            check_config=_DEFAULT_WANTED_CHECK_CONFIGS,
            group=group_wanted,
            personal=personal_wanted,
        ),
    )


# ── round-trip helper ──
def _round_trip(cfg):
    """保存到临时文件再 load 回来，返回 (yaml_str, loaded_cfg)。"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        tmp = f.name
    try:
        save_config(cfg, tmp)
        with open(tmp, encoding="utf-8") as f:
            yaml_str = f.read()
        loaded = load_config(tmp)
    finally:
        os.unlink(tmp)
    return yaml_str, loaded


# ── 1. 无数据默认 Config 保存/恢复 ──
# 传入不存在的路径，确保返回默认配置而不是加载已存在的 config.yaml
default_cfg = load_config("__nonexistent__.yaml")  # 无 config.yaml 时的默认值
yaml_str, rt = _round_trip(default_cfg)
check("RT-default: periods 数量一致", len(rt.periods), len(default_cfg.periods))
check(
    "RT-default: subscription.check_config default 存在",
    "default" in rt.subscription.check_config,
    True,
)
check("RT-default: wanted_list.group 为空", rt.wanted_list.group, {})
check("RT-default: wanted_list.personal 为空", rt.wanted_list.personal, {})

# ── 2. 完整数据 round-trip ──
full_cfg = _make_full_config()
yaml_str, rt2 = _round_trip(full_cfg)

# subscription items
check(
    "RT-full: subscription qq 数量",
    len(rt2.subscription.items),
    2,
)
rt2_subs_0 = rt2.subscription.items.get("1234567890", [])
check("RT-full: sub[0] id", rt2_subs_0[0].id, "1012345678901")
check("RT-full: sub[0] gid", rt2_subs_0[0].gid, "987654321")
check("RT-full: sub[0] arena_on=True（默认省略后恢复）", rt2_subs_0[0].arena_on, True)
check("RT-full: sub[1] arena_on=False（保留）", rt2_subs_0[1].arena_on, False)
check(
    "RT-full: sub[1] grand_arena_on=True（默认省略后恢复）",
    rt2_subs_0[1].grand_arena_on,
    True,
)

# wanted_list group
rt2_group = rt2.wanted_list.group.get("987654321", [])
check("RT-full: group 通缉数量=4", len(rt2_group), 4)
check("RT-full: group[0] id", rt2_group[0].id, "1012345678901")
check("RT-full: group[0] arena_on=True（默认恢复）", rt2_group[0].arena_on, True)
check(
    "RT-full: group[0] notice_level=1（默认恢复）",
    rt2_group[0].notice_level,
    NOTICE_LEVEL_DEFAULT,
)
check("RT-full: group[1] note 保留", rt2_group[1].note, "坏人")
check("RT-full: group[2] arena_on=False 保留", rt2_group[2].arena_on, False)
check(
    "RT-full: group[3] notice_level=2 保留",
    rt2_group[3].notice_level,
    NOTICE_LEVEL_ATTENTION,
)

# wanted_list personal
rt2_personal = rt2.wanted_list.personal.get("1234567890", [])
check("RT-full: personal 数量=1", len(rt2_personal), 1)
check("RT-full: personal[0] id", rt2_personal[0].id, "1012345678905")
check("RT-full: personal[0] gid", rt2_personal[0].gid, "987654321")
check("RT-full: personal[0] note 保留", rt2_personal[0].note, "仇人")
check(
    "RT-full: personal[0] by 不在 personal_item（从 qq key 恢复）",
    rt2_personal[0].by,
    "1234567890",
)

# wanted_list check_config round-trip
rt2_wcc = rt2.wanted_list.check_config
check(
    "RT-full: wanted cc default interval=5",
    rt2_wcc.get("default", None) and rt2_wcc["default"].interval,
    5,
)
check(
    "RT-full: wanted cc hot interval=2",
    rt2_wcc.get("hot", None) and rt2_wcc["hot"].interval,
    2,
)
check(
    "RT-full: wanted cc cold delay=30",
    rt2_wcc.get("cold", None) and rt2_wcc["cold"].delay,
    30,
)
check(
    "RT-full: wanted cc settlement interval=0（强制）",
    rt2_wcc["settlement"].interval,
    0,
)

# ── 3. yaml 简化写法验证 ──
# 全默认 WantedItem 应序列化为纯 uid 字符串（而非 dict）
raw = _yaml.safe_load(yaml_str)
group_raw = raw.get("wanted_list", {}).get("group", {}).get("987654321", [])
check(
    "yaml-simplified: group[0] 全默认序列化为 uid 字符串",
    isinstance(group_raw[0], str),
    True,
)
check(
    "yaml-simplified: group[0] uid 值正确",
    group_raw[0],
    "1012345678901",
)
check(
    "yaml-simplified: group[1] 有备注序列化为 dict",
    isinstance(group_raw[1], dict),
    True,
)
check(
    "yaml-simplified: group[1] dict 中无 gid 字段（群通缉省略）",
    "gid" not in group_raw[1],
    True,
)
check(
    "yaml-simplified: group[1] dict 中无 by 字段（空时省略）",
    "by" not in group_raw[1],
    True,
)

# subscription 全默认条目应省略 arena_on/grand_arena_on
sub_raw = raw.get("subscription", {}).get("items", {}).get("1234567890", [])
check(
    "yaml-simplified: sub[0] 全默认省略 arena_on",
    "arena_on" not in sub_raw[0],
    True,
)
check(
    "yaml-simplified: sub[1] arena_on=False 保留",
    sub_raw[1].get("arena_on") == False,
    True,
)

# check_config 纯 interval（delay=20）时简化为整数
cc_raw = raw.get("wanted_list", {}).get("check_config", {})
check(
    "yaml-simplified: wanted cc default(interval=5,delay=20) 简化为整数",
    cc_raw.get("default") == 5,
    True,
)
check(
    "yaml-simplified: wanted cc hot(delay=5≠20) 保存为 dict",
    isinstance(cc_raw.get("hot"), dict),
    True,
)

# ── 4. 旧格式 config.yaml（无 wanted_list 段）能正常加载 ──
old_yaml = """
subscription:
  check_config:
    default: 1
  items:
    '9876543210':
      - id: '1012345678901'
        gid: '111222333'
"""
with tempfile.NamedTemporaryFile(
    mode="w", suffix=".yaml", delete=False, encoding="utf-8"
) as f:
    f.write(old_yaml)
    old_path = f.name
try:
    old_cfg = load_config(old_path)
finally:
    os.unlink(old_path)
check("旧格式: wanted_list.group 为空", old_cfg.wanted_list.group, {})
check(
    "旧格式: wanted_list.check_config default 存在",
    "default" in old_cfg.wanted_list.check_config,
    True,
)
check("旧格式: subscription items 正常加载", len(old_cfg.subscription.items), 1)
check("旧格式: qq key 为字符串", "9876543210" in old_cfg.subscription.items, True)

# ── 5. 写回后 gid/qq key 为引号字符串不变为 int ──
check(
    "yaml key: qq/gid 写回 yaml 后仍为 str（yaml 加引号）",
    isinstance(list(rt2.subscription.items.keys())[0], str),
    True,
)

# ── 2. subscriptions ──────────────────────────────────────────────────
section("subscriptions: SubscriptionManager")

from ..subscription_manager import SubscriptionManager


def make_sub_mgr():
    return SubscriptionManager(items={})


mgr = make_sub_mgr()

check("add ok", mgr.add("111", "1012345678901", "G1"), "ok")
check("add dup", mgr.add("111", "1012345678901", "G1"), "dup")
check("add second ok", mgr.add("111", "1012345678902", "G1"), "ok")
check("add third diff gid", mgr.add("111", "1012345678903", "G2"), "ok")
check("get_list len", len(mgr.get_list("111")), 3)

# get_list_by_gid
g1_subs = mgr.get_list_by_gid("111", "G1")
check("get_list_by_gid G1 len=2", len(g1_subs), 2)
g2_subs = mgr.get_list_by_gid("111", "G2")
check("get_list_by_gid G2 len=1", len(g2_subs), 1)
check("get_list_by_gid unknown=0", len(mgr.get_list_by_gid("111", "G9")), 0)

# remove
check("remove idx=1 (uid 901)", mgr.remove("111", 1), True)
check("list after rm", len(mgr.get_list("111")), 2)
check("list[0] uid after rm", mgr.get_list("111")[0].id, "1012345678902")
check("remove oob", mgr.remove("111", 99), False)
check("remove unknown qq", mgr.remove("999", 1), False)

# move_group
mgr_mv = make_sub_mgr()
mgr_mv.add("111", "1012345678901", "G1")
mgr_mv.add("111", "1012345678902", "G1")
check("move_group ok", mgr_mv.move_group("111", 1, "G2"), True)
check("move_group gid changed", mgr_mv.get_list("111")[0].gid, "G2")
check("move_group oob", mgr_mv.move_group("111", 99, "G3"), False)

# full
mgr2 = make_sub_mgr()
for i in range(8):
    mgr2.add("222", f"101234567890{i}", "1")
check("add when full", mgr2.add("222", "1099999999999", "1"), "full")

# set_toggle
mgr3 = make_sub_mgr()
mgr3.add("333", "1012345678901", "1")
mgr3.add("333", "1012345678902", "1")
check(
    "toggle index=1 arena off",
    mgr3.set_toggle("333", 1, arena_on=False, grand_arena_on=None),
    True,
)
check("arena_on after toggle", mgr3.get_list("333")[0].arena_on, False)
check("grand unchanged", mgr3.get_list("333")[0].grand_arena_on, True)
check(
    "toggle all grand off",
    mgr3.set_toggle("333", None, arena_on=None, grand_arena_on=False),
    True,
)
check("both grand off", all(not s.grand_arena_on for s in mgr3.get_list("333")), True)

# get_all_items
mgr5 = make_sub_mgr()
mgr5.add("A", "1012345678901", "G1")
mgr5.add("A", "1012345678902", "G2")
mgr5.add("B", "1012345678903", "G1")
all_items = mgr5.get_all_items()
check("get_all_items len=3", len(all_items), 3)
all_qq = [qq for qq, _ in all_items]
check("get_all_items contains A", "A" in all_qq, True)
check("get_all_items contains B", "B" in all_qq, True)

# migrate
mgr4 = make_sub_mgr()
old_binds = {
    "444": {
        "id": "1012345678901",
        "uid": "444",
        "gid": "555",
        "arena_on": True,
        "grand_arena_on": False,
    },
}
mgr4.migrate_from_old(old_binds)
subs = mgr4.get_list("444")
check("migrate len=1", len(subs), 1)
check("migrate id", subs[0].id, "1012345678901")
check("migrate grand_arena", subs[0].grand_arena_on, False)
# migrate skip if already exists
mgr4.migrate_from_old(
    {
        "444": {
            "id": "1012345678999",
            "gid": "1",
            "arena_on": True,
            "grand_arena_on": True,
        }
    }
)
check("migrate skip existing", len(mgr4.get_list("444")), 1)

# ── 3. wanted_manager ─────────────────────────────────────────────────
section("wanted_manager: WantedManager")

from ..wanted_manager import WantedManager


def make_wanted_mgr():
    """创建空的 WantedManager 用于测试"""
    config = WantedListConfig(
        check_config={},  # 空配置，测试不需要
        group={},
        personal={},
    )
    return WantedManager(config)


wm = make_wanted_mgr()

# 群通缉
check(
    "add group ok",
    wm.add_group("G1", WantedItem(id="1012345678901", gid="G1", note="坏人")),
    "ok",
)
check(
    "add group dup",
    wm.add_group("G1", WantedItem(id="1012345678901", gid="G1")),
    "dup",
)
check("list group 1", len(wm.list_group("G1")), 1)
check("list group note", wm.list_group("G1")[0].note, "坏人")
check("rm group ok", wm.remove_group("G1", "1012345678901"), True)
check("rm group miss", wm.remove_group("G1", "1012345678901"), False)
check("list group 0", len(wm.list_group("G1")), 0)

# 个人通缉
check(
    "add personal ok",
    wm.add_personal("P1", WantedItem(id="1012345678901", gid="G1", note="坏人")),
    "ok",
)
check(
    "add personal dup",
    wm.add_personal("P1", WantedItem(id="1012345678901", gid="G1")),
    "dup",
)
pw = wm.list_personal("P1")
check("personal items=1", len(pw), 1)
check("personal gid", pw[0].gid, "G1")
check("personal note", pw[0].note, "坏人")
check("rm personal ok", wm.remove_personal("P1", "1012345678901"), True)
check("rm personal miss", wm.remove_personal("P1", "1012345678901"), False)
check("personal after rm", len(wm.list_personal("P1")), 0)

# 个人通缉上限
wm2 = make_wanted_mgr()
for i in range(8):
    wm2.add_personal("P2", WantedItem(id=f"101234567890{i}", gid="G1"))
check(
    "personal full",
    wm2.add_personal("P2", WantedItem(id="1099999999999", gid="G1")),
    "full",
)

# 群通缉上限
wm3 = make_wanted_mgr()
for i in range(30):
    wm3.add_group("G1", WantedItem(id=f"101234567{i:04d}", gid="G1"))
check(
    "group full",
    wm3.add_group("G1", WantedItem(id="1099999999999", gid="G1")),
    "full",
)

# 迁移
wm4 = make_wanted_mgr()
old_wanted = {"G1": ["1012345678901", "1012345678902"]}
wm4.migrate_from_old(old_wanted)
items = wm4.list_group("G1")
check("migrate group len=2", len(items), 2)
check("migrate wanted notice=1", items[0].notice_level, 1)
check("no duplicate uid", len({i.id for i in items}), 2)

# get_wanted_list_for_monitor
wm5 = make_wanted_mgr()
wm5.add_group("G1", WantedItem(id="1012345678901", gid="G1", notice_level=1))
wm5.add_group("G1", WantedItem(id="1012345678902", gid="G1", notice_level=2))
wm5.add_personal("P1", WantedItem(id="1012345678901", gid="G1", notice_level=1))
wm5.add_personal("P2", WantedItem(id="1012345678903", gid="G2", notice_level=3))

wanted_list = wm5.get_wanted_list_for_monitor()
check("monitor list len", len(wanted_list), 3)  # 3 个不同的 uid

# 检查 uid=1012345678901 有 2 个 watcher（群+个人）
detail_1 = next((d for d in wanted_list if d.uid == "1012345678901"), None)
check("detail_1 exists", detail_1 is not None, True)
check("detail_1 watchers=2", len(detail_1.watchers), 2)

# 检查 uid=1012345678902 有 1 个 watcher（仅群）
detail_2 = next((d for d in wanted_list if d.uid == "1012345678902"), None)
check("detail_2 exists", detail_2 is not None, True)
check("detail_2 watchers=1", len(detail_2.watchers), 1)
check("detail_2 watcher is group", detail_2.watchers[0].id, "")

# 检查 uid=1012345678903 有 1 个 watcher（仅个人）
detail_3 = next((d for d in wanted_list if d.uid == "1012345678903"), None)
check("detail_3 exists", detail_3 is not None, True)
check("detail_3 watchers=1", len(detail_3.watchers), 1)
check("detail_3 watcher is personal", detail_3.watchers[0].id, "P2")

# notice_level 设置
wm6 = make_wanted_mgr()
wm6.add_group("G1", WantedItem(id="1012345678901", gid="G1"))
check("set group notice ok", wm6.set_group_notice_level("G1", "1012345678901", 3), True)
check("group notice updated", wm6.list_group("G1")[0].notice_level, 3)
check(
    "set group notice miss", wm6.set_group_notice_level("G1", "9999999999999", 3), False
)

wm6.add_personal("P1", WantedItem(id="1012345678902", gid="G1"))
check(
    "set personal notice ok",
    wm6.set_personal_notice_level("P1", "1012345678902", 4),
    True,
)
check("personal notice updated", wm6.list_personal("P1")[0].notice_level, 4)
check(
    "set personal notice miss",
    wm6.set_personal_notice_level("P1", "9999999999999", 4),
    False,
)

# watch_at 开关
wm7 = make_wanted_mgr()
wm7.add_group("G1", WantedItem(id="1012345678901", gid="G1"))
check(
    "set group toggle ok",
    wm7.set_group_watch_toggle(
        "G1", "1012345678901", arena_on=False, grand_arena_on=True
    ),
    True,
)
item = wm7.list_group("G1")[0]
check("group arena_on=False", item.arena_on, False)
check("group grand_arena_on=True", item.grand_arena_on, True)
check(
    "set group toggle miss",
    wm7.set_group_watch_toggle("G1", "9999999999999", arena_on=True),
    False,
)

wm7.add_personal("P1", WantedItem(id="1012345678902", gid="G1"))
check(
    "set personal toggle ok",
    wm7.set_personal_watch_toggle(
        "P1", "1012345678902", arena_on=True, grand_arena_on=False
    ),
    True,
)
item2 = wm7.list_personal("P1")[0]
check("personal arena_on=True", item2.arena_on, True)
check("personal grand_arena_on=False", item2.grand_arena_on, False)
check(
    "set personal toggle miss",
    wm7.set_personal_watch_toggle("P1", "9999999999999", arena_on=True),
    False,
)

# 备注设置
wm8 = make_wanted_mgr()
wm8.add_group("G1", WantedItem(id="1012345678901", gid="G1", note="旧备注"))
check("set group note ok", wm8.set_group_note("G1", "1012345678901", "新备注"), True)
check("group note updated", wm8.list_group("G1")[0].note, "新备注")
check("set group note miss", wm8.set_group_note("G1", "9999999999999", "备注"), False)

wm8.add_personal("P1", WantedItem(id="1012345678902", gid="G1", note="旧备注"))
check(
    "set personal note ok", wm8.set_personal_note("P1", "1012345678902", "新备注"), True
)
check("personal note updated", wm8.list_personal("P1")[0].note, "新备注")
check(
    "set personal note miss",
    wm8.set_personal_note("P1", "9999999999999", "备注"),
    False,
)

# 按 uid 查询
wm9 = make_wanted_mgr()
wm9.add_group("G1", WantedItem(id="1012345678901", gid="G1", note="坏人"))
wm9.add_group("G1", WantedItem(id="1012345678902", gid="G1"))
item_by_uid = wm9.get_group_by_uid("G1", "1012345678901")
check("get group by uid found", item_by_uid is not None, True)
check("get group by uid note", item_by_uid.note, "坏人")
check("get group by uid miss", wm9.get_group_by_uid("G1", "9999999999999"), None)

wm9.add_personal("P1", WantedItem(id="1012345678903", gid="G1", note="仇人"))
item_by_uid_p = wm9.get_personal_by_uid("P1", "1012345678903")
check("get personal by uid found", item_by_uid_p is not None, True)
check("get personal by uid note", item_by_uid_p.note, "仇人")
check("get personal by uid miss", wm9.get_personal_by_uid("P1", "9999999999999"), None)

# 按索引查询
wm10 = make_wanted_mgr()
wm10.add_group("G1", WantedItem(id="1012345678901", gid="G1", note="第一个"))
wm10.add_group("G1", WantedItem(id="1012345678902", gid="G1", note="第二个"))
wm10.add_group("G1", WantedItem(id="1012345678903", gid="G1", note="第三个"))
item_idx1 = wm10.get_group_by_index("G1", 1)
check("get group by idx 1 found", item_idx1 is not None, True)
check("get group by idx 1 note", item_idx1.note, "第一个")
item_idx2 = wm10.get_group_by_index("G1", 2)
check("get group by idx 2 note", item_idx2.note, "第二个")
check("get group by idx 0 oob", wm10.get_group_by_index("G1", 0), None)
check("get group by idx 4 oob", wm10.get_group_by_index("G1", 4), None)

wm10.add_personal("P1", WantedItem(id="1012345678904", gid="G1", note="个人第一"))
wm10.add_personal("P1", WantedItem(id="1012345678905", gid="G1", note="个人第二"))
item_idx_p1 = wm10.get_personal_by_index("P1", 1)
check("get personal by idx 1 found", item_idx_p1 is not None, True)
check("get personal by idx 1 note", item_idx_p1.note, "个人第一")
item_idx_p2 = wm10.get_personal_by_index("P1", 2)
check("get personal by idx 2 note", item_idx_p2.note, "个人第二")
check("get personal by idx 0 oob", wm10.get_personal_by_index("P1", 0), None)
check("get personal by idx 3 oob", wm10.get_personal_by_index("P1", 3), None)

# ── 4. table_image ─────────────────────────────────────────────────────
section("table_image: comprehensive features test")

from ..table_image import (
    Cell,
    Header,
    StyledText,
    render_table,
    render_table_as_cq,
    render_table_as_file,
)

# 综合测试表格，包含所有特性
# 三列：测试项 | 示例 | 说明
COMPREHENSIVE_HEADERS = [
    Header(content="测试项", align="center", min_width="8em"),
    Header(content="示例", align="center", min_width="20em"),
    Header(content="说明", align="left", min_width="14em"),
]
COMPREHENSIVE_ROWS = [
    # 基本文本
    ["基本文本", "这是基本文本", "默认左对齐"],
    # 水平对齐
    [
        "水平对齐",
        Cell(content="左对齐", align="left"),
        "align=left",
    ],
    [
        "水平对齐",
        Cell(content="居中", align="center"),
        "align=center",
    ],
    [
        "水平对齐",
        Cell(content="右对齐", align="right"),
        "align=right",
    ],
    # 多行文本
    ["多行文本", "第一行\n第二行\n第三行", "\\n 换行"],
    # 上标
    [
        "上标",
        [StyledText(text="x", sup="2"), " 或 ", StyledText(text="E=mc", sup="2")],
        "sup=",
    ],
    # 下标
    [
        "下标",
        [StyledText(text="H", sub="2"), "O 或 ", StyledText(text="CO", sub="2")],
        "sub=",
    ],
    # 上下标同时
    ["上下标", StyledText(text="a", sup="n", sub="i"), "sup= + sub="],
    # 颜色
    [
        "颜色",
        [
            StyledText(text="红色 ", text_color=(200, 50, 50)),
            StyledText(text="蓝色 ", text_color=(50, 100, 200)),
            StyledText(text="绿色", text_color=(50, 160, 50)),
        ],
        "text_color=(R,G,B)",
    ],
    # 字号
    [
        "字号",
        [
            StyledText(text="大(20) ", size=20),
            StyledText(text="默认 ", size=None),
            StyledText(text="小(10)", size=10),
        ],
        "size=",
    ],
    # Emoji 字体
    [
        "Emoji字体",
        [
            StyledText(text="⚔️", font="emoji.ttf"),
            StyledText(text="🔇", font="emoji.ttf"),
            StyledText(text="⚠️", font="emoji.ttf"),
            StyledText(text=" 普通文字混排"),
        ],
        "font='emoji.ttf'",
    ],
    # 背景色
    [
        "背景色",
        Cell(content="高亮背景", bg_color=(255, 255, 150), align="center"),
        "bg_color=",
    ],
    # 固定列宽（min_width）
    [
        "固定列宽",
        Cell(content="此列最小20em宽", min_width="20em", align="center"),
        "min_width='Nem'",
    ],
    # 跨列
    [Cell(content="跨列单元格（colspan=3）", colspan=3, align="center"), "", ""],
    # 复杂组合
    [
        "综合",
        [
            StyledText(text="H", sub="2"),
            " + ",
            StyledText(text="O", sub="2"),
            " → ",
            StyledText(text="H", sub="2"),
            StyledText(text="O", text_color=(50, 160, 50)),
            "\n",
            StyledText(text="E=mc", text_color=(200, 50, 50)),
            StyledText(text="2", sup="2", text_color=(200, 50, 50)),
        ],
        "多特性组合",
    ],
]

# 测试 render_table
img = render_table(
    headers=COMPREHENSIVE_HEADERS, rows=COMPREHENSIVE_ROWS, title="表格特性综合测试"
)
check("render_table returns Image", isinstance(img, PILImage.Image), True)
check("image has size", img.size[0] > 0 and img.size[1] > 0, True)

# 测试 render_table_as_cq
cq = render_table_as_cq(
    headers=COMPREHENSIVE_HEADERS, rows=COMPREHENSIVE_ROWS, title="表格特性综合测试"
)
check(
    "render_table_as_cq starts with cqcode",
    cq.startswith("[CQ:image,file=base64://"),
    True,
)
check("non-empty cq", len(cq) > 200, True)

# 测试 render_table_as_file
out_path = os.path.join(os.path.dirname(__file__), "_test_table.png")
render_table_as_file(
    headers=COMPREHENSIVE_HEADERS,
    rows=COMPREHENSIVE_ROWS,
    path=out_path,
    title="表格特性综合测试",
)
check("render_table_as_file creates file", os.path.exists(out_path), True)
print(f"       综合测试图片已保存到: {out_path}")

# ── 5. 迁移集成测试（读取真实数据文件） ───────────────────────────────
section("migration: binds.json + wanted_binds.json → new format")


_DIR = os.path.dirname(__file__)
_BINDS_PATH = os.path.join(_DIR, "binds.json")
_WANTED_PATH = os.path.join(_DIR, "wanted_binds.json")

if not os.path.exists(_BINDS_PATH) or not os.path.exists(_WANTED_PATH):
    print("  SKIP  binds.json / wanted_binds.json 不存在，跳过迁移测试")
else:
    with open(_BINDS_PATH, encoding="utf-8") as f:
        raw_binds = json.load(f)
    with open(_WANTED_PATH, encoding="utf-8") as f:
        raw_wanted = json.load(f)

    arena_bind = raw_binds.get("arena_bind", {})
    wanted_bind = raw_wanted.get("wanted_bind", {})
    watch_bind = raw_wanted.get("watch_bind", {})

    # ── 订阅迁移 ──────────────────────────────────────────────
    mgr_m = make_sub_mgr()
    mgr_m.migrate_from_old(arena_bind)

    all_items = mgr_m.get_all_items()
    check("迁移后订阅数 == 原始 arena_bind 条数", len(all_items), len(arena_bind))

    # 每条迁移结果 id 应为 13 位字符串
    all_valid_ids = all(
        len(item.id) == 13 and item.id.isdigit() for _, item in all_items
    )
    check("所有迁移 uid 为 13 位数字", all_valid_ids, True)

    # gid 不为空
    all_valid_gids = all(item.gid for _, item in all_items)
    check("所有迁移 gid 非空", all_valid_gids, True)

    # 幂等性：再次迁移不产生重复
    mgr_m.migrate_from_old(arena_bind)
    check("迁移幂等（二次迁移不增加数据）", len(mgr_m.get_all_items()), len(arena_bind))

    # 抽样验证：取第一条原始记录，检查字段对应
    first_qq, first_info = next(iter(arena_bind.items()))
    subs_for_qq = mgr_m.get_list(first_qq)
    check("迁移后可按 qq 查到订阅", len(subs_for_qq) >= 1, True)
    check("迁移 id 字段正确", subs_for_qq[0].id, str(first_info["id"]))
    check("迁移 gid 字段正确", subs_for_qq[0].gid, str(first_info["gid"]))
    check(
        "迁移 arena_on 字段正确",
        subs_for_qq[0].arena_on,
        bool(first_info.get("arena_on", True)),
    )

    # ── 通缉迁移 ──────────────────────────────────────────────
    from ..schema import WantedListConfig
    from ..wanted_manager import WantedManager

    def make_wanted_mgr_empty():
        config = WantedListConfig(check_config={}, group={}, personal={})
        return WantedManager(config)

    wm_m = make_wanted_mgr_empty()
    wm_m.migrate_from_old(wanted_bind)

    # 迁移后通缉总数应等于 wanted_bind 中的 uid 总数（去重）
    all_wanted_gids = set(wanted_bind.keys())
    migrated_total = sum(len(wm_m.list_group(gid)) for gid in all_wanted_gids)
    expected_unique = sum(len(set(wanted_bind.get(gid, []))) for gid in all_wanted_gids)
    check("迁移后通缉总数（去重）== 期望", migrated_total, expected_unique)

    # wanted 条目 notice_level=1（默认）
    for gid, uids in wanted_bind.items():
        items = wm_m.list_group(gid)
        uid_to_level = {i.id: i.notice_level for i in items}
        for uid in uids:
            check(f"wanted uid {uid[-4:]} notice_level=1", uid_to_level.get(uid), 1)
        break  # 只抽检第一个群

    # 迁移幂等
    wm_m.migrate_from_old(wanted_bind)
    migrated_total2 = sum(len(wm_m.list_group(gid)) for gid in all_wanted_gids)
    check("通缉迁移幂等（二次迁移不增加数据）", migrated_total2, migrated_total)

    # ── watch_bind 迁移到订阅（QQ=0）──────────────────────────
    from ..subscription_manager import SubscriptionManager

    sub_mgr_m = SubscriptionManager(items={})
    sub_mgr_m.migrate_from_old_watch(watch_bind)

    # 迁移后应该有 QQ=0 的订阅
    qq0_subs = sub_mgr_m.get_list("0")
    all_watch_uids = set()
    for gid, uids in watch_bind.items():
        all_watch_uids.update(uids)
    check("watch_bind 迁移到 QQ=0 订阅", len(qq0_subs), len(all_watch_uids))

    # 检查 gid 字段正确
    for gid, uids in watch_bind.items():
        for uid in uids:
            sub = next((s for s in qq0_subs if s.id == uid), None)
            if sub:
                check(f"watch uid {uid[-4:]} gid={gid}", sub.gid, gid)
        break  # 只抽检第一个群

    # 迁移幂等
    sub_mgr_m.migrate_from_old_watch(watch_bind)
    qq0_subs2 = sub_mgr_m.get_list("0")
    check("watch 迁移幂等（二次迁移不增加数据）", len(qq0_subs2), len(qq0_subs))

# ── 6. wanted_summary_formatter ──────────────────────────────────────
section("wanted_summary_formatter: format_headers")

from ..wanted_summary_formatter import (
    MINE_SIGN,
    MUTE_SIGN,
    WantedSummaryFormatter,
    WantedSummaryRow,
    render_wanted_summary_as_cq,
)

formatter = WantedSummaryFormatter(now_hour=10)
headers = formatter.format_headers()

check("headers 长度为 7", len(headers), 7)
check("第1列为编号", headers[0].content, "#")
check("第2列为昵称", headers[1].content, "昵称")
check("第3列为战斗竞技场", headers[2].content, "战斗竞技场")
check("第4列为公主竞技场", headers[3].content, "公主竞技场")
check("第5列为上线时间", headers[4].content, "上线时间")
check("第6列为UID", headers[5].content, "UID")
check("第7列为备注", headers[6].content, "备注")

# 检查表头背景色
from ..wanted_summary_formatter import _COLOR_DEEP_BLUE, _COLOR_RED_BRICK

check("战斗竞技场表头背景色", headers[2].bg_color, _COLOR_RED_BRICK)
check("公主竞技场表头背景色", headers[3].bg_color, _COLOR_DEEP_BLUE)

section("wanted_summary_formatter: format_row (normal)")

# 创建测试数据：正常状态
row_normal = WantedSummaryRow(
    index="1",
    uid="1012345678901",
    user_name="测试用户",
    avatar_unit_name=None,
    clan_name="测试公会",
    arena_group=123,
    arena_rank=50,
    arena_challenges=5,
    arena_mining=False,
    arena_on=True,
    grand_arena_group=456,
    grand_arena_rank=80,
    grand_arena_challenges=3,
    grand_arena_mining=False,
    grand_arena_on=True,
    last_login_time=1710000000,
    note="测试备注",
    notice_level=1,
    same_arena_group=False,
    same_grand_arena_group=False,
    arena_str="-jjc-",
    grand_arena_str="-pjjc-",
)

row_cells = formatter.format_row(row_normal)
check("row 长度为 7", len(row_cells), 7)
check("编号单元格内容", row_cells[0].content, "1")
check("昵称单元格内容", row_cells[1].content, "测试用户")
check("UID单元格内容", row_cells[5].content, "1012345678901")

section("wanted_summary_formatter: format_row (佑树)")

# 创建测试数据：佑树（默认名）
row_yuki = WantedSummaryRow(
    index="2",
    uid="1012345678902",
    user_name="佑树",
    avatar_unit_name=None,
    clan_name="测试公会",
    arena_group=123,
    arena_rank=50,
    arena_challenges=5,
    arena_mining=False,
    arena_on=True,
    grand_arena_group=456,
    grand_arena_rank=80,
    grand_arena_challenges=3,
    grand_arena_mining=False,
    grand_arena_on=True,
    last_login_time=1710000000,
    note="",
    notice_level=1,
    same_arena_group=False,
    same_grand_arena_group=False,
    arena_str="-jjc2-",
    grand_arena_str="-pjjc2-",
)

row_yuki_cells = formatter.format_row(row_yuki)
# 佑树的昵称单元格应该是 StyledText，包含上标（公会名）
name_cell_content = row_yuki_cells[1].content  # 第1列是昵称（第0列是编号）
check("佑树昵称单元格是 StyledText", isinstance(name_cell_content, StyledText), True)
check("佑树昵称文本", name_cell_content.text, "佑树")
check("佑树有上标（公会名）", name_cell_content.sup is not None, True)
if name_cell_content.sup:
    check("佑树上标包含公会名", "测试公会" in name_cell_content.sup.text, True)

# 测试佑树带头像
row_yuki_avatar = WantedSummaryRow(
    index="2b",
    uid="1012345678902",
    user_name="佑树",
    avatar_unit_name="春田",
    clan_name="测试公会",
    arena_group=123,
    arena_rank=50,
    arena_challenges=5,
    arena_mining=False,
    arena_on=True,
    grand_arena_group=456,
    grand_arena_rank=80,
    grand_arena_challenges=3,
    grand_arena_mining=False,
    grand_arena_on=True,
    last_login_time=1710000000,
    note="",
    notice_level=1,
    same_arena_group=False,
    same_grand_arena_group=False,
    arena_str="-jjc2b-",
    grand_arena_str="-pjjc2b-",
)

row_yuki_avatar_cells = formatter.format_row(row_yuki_avatar)
name_cell_avatar = row_yuki_avatar_cells[1].content
check(
    "佑树（带头像）昵称单元格是 StyledText",
    isinstance(name_cell_avatar, StyledText),
    True,
)
check("佑树（带头像）有上标", name_cell_avatar.sup is not None, True)
check("佑树（带头像）有下标", name_cell_avatar.sub is not None, True)
if name_cell_avatar.sub:
    check("佑树下标包含头像", "春田" in name_cell_avatar.sub.text, True)

section("wanted_summary_formatter: format_row (same arena group)")

# 创建测试数据：同场
row_same_arena = WantedSummaryRow(
    index="3",
    uid="1012345678903",
    user_name="同场用户",
    avatar_unit_name=None,
    clan_name="",
    arena_group=123,
    arena_rank=50,
    arena_challenges=5,
    arena_mining=False,
    arena_on=True,
    grand_arena_group=456,
    grand_arena_rank=80,
    grand_arena_challenges=3,
    grand_arena_mining=False,
    grand_arena_on=True,
    last_login_time=1710000000,
    note="",
    notice_level=1,
    same_arena_group=True,
    same_grand_arena_group=True,
    arena_str="-jjc3-",
    grand_arena_str="-pjjc3-",
)

row_same_cells = formatter.format_row(row_same_arena)
# 同场时应该有背景色
from ..wanted_summary_formatter import _COLOR_DEEP_BLUE_LIGHT, _COLOR_RED_BRICK_LIGHT

check("同场jjc背景色", row_same_cells[2].bg_color, _COLOR_RED_BRICK_LIGHT)
check("同场pjjc背景色", row_same_cells[3].bg_color, _COLOR_DEEP_BLUE_LIGHT)

section("wanted_summary_formatter: format_row (mining)")

# 创建测试数据：挖矿中
row_mining = WantedSummaryRow(
    index="4",
    uid="1012345678904",
    user_name="挖矿用户",
    avatar_unit_name=None,
    clan_name="",
    arena_group=123,
    arena_rank=15001,
    arena_challenges=0,
    arena_mining=True,
    arena_on=True,
    grand_arena_group=456,
    grand_arena_rank=6000,
    grand_arena_challenges=0,
    grand_arena_mining=True,
    grand_arena_on=True,
    last_login_time=1710000000,
    note="",
    notice_level=1,
    same_arena_group=False,
    same_grand_arena_group=False,
    arena_str="-jjc4-",
    grand_arena_str="-pjjc4-",
)

row_mining_cells = formatter.format_row(row_mining)
# 挖矿状态应该在单元格内容中包含 ⛏️
# 由于内容是 StyledText 列表，我们检查是否包含 ⛏️ 符号
arena_cell_content = row_mining_cells[2].content
has_mining_icon = any(
    MINE_SIGN in (seg.text if hasattr(seg, "text") else seg)
    for seg in arena_cell_content
)
check("挖矿状态包含⛏️", has_mining_icon, True)

section("wanted_summary_formatter: format_row (arena_on=False)")

# 创建测试数据：不通报
row_muted = WantedSummaryRow(
    index="5",
    uid="1012345678905",
    user_name="不通报用户",
    avatar_unit_name=None,
    clan_name="",
    arena_group=123,
    arena_rank=50,
    arena_challenges=5,
    arena_mining=False,
    arena_on=False,
    grand_arena_group=456,
    grand_arena_rank=80,
    grand_arena_challenges=3,
    grand_arena_mining=False,
    grand_arena_on=False,
    last_login_time=1710000000,
    note="",
    notice_level=1,
    same_arena_group=False,
    same_grand_arena_group=False,
    arena_str="-jjc5-",
    grand_arena_str="-pjjc5-",
)

row_muted_cells = formatter.format_row(row_muted)
# 不通报状态应该在单元格内容中包含 🔇
arena_cell_content = row_muted_cells[2].content
has_mute_icon = any(
    MUTE_SIGN in (seg.text if hasattr(seg, "text") else seg)
    for seg in arena_cell_content
)
check("不通报状态包含🔇", has_mute_icon, True)

section("wanted_summary_formatter: render_wanted_summary")

# 测试渲染函数
group_rows = [row_normal, row_same_arena]
personal_rows = [row_mining]

result = render_wanted_summary_as_cq(group_rows, personal_rows, now_hour=10)
# 结果应该是 CQ 码字符串
check("render 返回 CQ 码", result.startswith("[CQ:image,file=base64://"), True)

# 测试空列表
result_empty = render_wanted_summary_as_cq([], [], now_hour=10)
check("空列表返回提示文字", result_empty, "暂无通缉犯")

# ── 结果汇总 ──────────────────────────────────────────────────────────
section("结果")
total = PASS + FAIL
print(f"  通过: {PASS}/{total}")
if FAIL:
    print(f"  失败: {FAIL}/{total}")
    sys.exit(1)
else:
    print("  全部通过！")
