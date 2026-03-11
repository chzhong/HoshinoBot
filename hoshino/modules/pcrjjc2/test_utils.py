"""
test_utils.py - pcrjjc2 工具类单元测试

覆盖：config_loader、subscriptions、wanted_manager、table_image
这些类都是纯逻辑，无需 mock 外部依赖，直接实例化测试。

运行方式（在 HoshinoBot 根目录）：
    python hoshino/modules/pcrjjc2/test_utils.py

或在模块目录：
    python test_utils.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from datetime import datetime

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

from config_loader import TZ_CST, get_check_config, get_current_period, load_config

cfg = load_config()  # 返回 Config 对象

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
check("sub settlement interval=0",          get_check_config(sub_cc_map, "settlement").interval, 0)
check("sub default interval=1",             get_check_config(sub_cc_map, "default").interval, 1)
check("sub hot -> default interval=1",      get_check_config(sub_cc_map, "hot").interval, 1)
check("sub critical -> default interval=1", get_check_config(sub_cc_map, "critical").interval, 1)
check("sub cold -> default interval=1",     get_check_config(sub_cc_map, "cold").interval, 1)
check("sub unknown -> default interval=1",  get_check_config(sub_cc_map, "unknown").interval, 1)

section("config_loader: get_check_config (wanted, built-in defaults)")

# 通缉侧：独立的内置配置 _DEFAULT_WANTED_CHECK_CONFIGS
# hot/critical/cold/default/settlement 各自独立设定
from config_loader import _DEFAULT_WANTED_CHECK_CONFIGS
wanted_cc_map = _DEFAULT_WANTED_CHECK_CONFIGS
check("wanted settlement interval=0", get_check_config(wanted_cc_map, "settlement").interval, 0)
check("wanted hot interval=2",        get_check_config(wanted_cc_map, "hot").interval, 2)
check("wanted critical interval=1",   get_check_config(wanted_cc_map, "critical").interval, 1)
check("wanted cold interval=15",      get_check_config(wanted_cc_map, "cold").interval, 15)
check("wanted default interval=5",    get_check_config(wanted_cc_map, "default").interval, 5)
check("wanted unknown -> default=5",  get_check_config(wanted_cc_map, "unknown").interval, 5)

section("config_loader: _parse_check_configs 强制补全逻辑")

# 无论用户配置了什么，_parse_check_configs 保证：
# 1. 缺少 default 时补充传入的 default 值
# 2. settlement 强制覆盖为 interval=0
from config_loader import _DEFAULT_SUB_CONFIG, _DEFAULT_WANTED_CONFIG
check("sub default interval",    _DEFAULT_SUB_CONFIG.interval,    1)
check("wanted default interval", _DEFAULT_WANTED_CONFIG.interval, 5)

# 验证 _parse_check_configs 对缺省 default 的补全行为
from config_loader import _parse_check_configs
parsed_no_default = _parse_check_configs({"hot": {"interval": 2}}, _DEFAULT_SUB_CONFIG)
check("parse: missing default补全sub=1",      parsed_no_default["default"].interval, 1)
check("parse: settlement强制覆盖interval=0",  parsed_no_default["settlement"].interval, 0)

parsed_with_default = _parse_check_configs({"default": {"interval": 3}, "hot": {"interval": 2}}, _DEFAULT_WANTED_CONFIG)
check("parse: 已有default不覆盖",              parsed_with_default["default"].interval, 3)
check("parse: settlement仍强制=0",             parsed_with_default["settlement"].interval, 0)

# ── 2. subscriptions ──────────────────────────────────────────────────
section("subscriptions: SubscriptionManager")

from subscriptions import SubscriptionManager


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

from wanted_manager import Wanted, WantedManager


def make_wanted_mgr():
    m = WantedManager.__new__(WantedManager)
    m._data = {"group": {}, "personal": {}}
    return m


wm = make_wanted_mgr()

# group
check(
    "add group ok", wm.add_group("G1", Wanted(uid="1012345678901", note="坏人")), True
)
check("add group dup", wm.add_group("G1", Wanted(uid="1012345678901")), False)
check("list group 1", len(wm.list_group("G1")), 1)
check("list group note", wm.list_group("G1")[0].note, "坏人")
check("rm group ok", wm.remove_group("G1", "1012345678901"), True)
check("rm group miss", wm.remove_group("G1", "1012345678901"), False)
check("list group 0", len(wm.list_group("G1")), 0)

# personal
check(
    "add personal ok",
    wm.add_personal("P1", "G1", Wanted(uid="1012345678901", note="坏人")),
    "ok",
)
check(
    "add personal dup",
    wm.add_personal("P1", "G1", Wanted(uid="1012345678901")),
    "dup",
)
pw = wm.list_personal("P1")
check("personal group", pw.group, "G1")
check("personal items=1", len(pw.items), 1)
check("personal note", pw.items[0].note, "坏人")
check("rm personal ok", wm.remove_personal("P1", "1012345678901"), True)
check("rm personal miss", wm.remove_personal("P1", "1012345678901"), False)
check("personal after rm", wm.list_personal("P1"), None)

# personal full
wm2 = make_wanted_mgr()
for i in range(8):
    wm2.add_personal("P2", "G1", Wanted(uid=f"101234567890{i}"))
check(
    "personal full",
    wm2.add_personal("P2", "G1", Wanted(uid="1099999999999")),
    "full",
)

# migrate
wm3 = make_wanted_mgr()
old_wanted = {"G1": ["1012345678901", "1012345678902"]}
old_watch = {"G1": ["1012345678903"]}
wm3.migrate_from_old(old_wanted, old_watch)
items = wm3.list_group("G1")
check("migrate group len=3", len(items), 3)
check("migrate wanted notice=1", items[0].notice_level, 1)
check("migrate watch notice=2", items[2].notice_level, 2)
check("no duplicate uid", len({i.uid for i in items}), 3)

# ── 4. table_image ─────────────────────────────────────────────────────
section("table_image: render_table")

from PIL import Image as PILImage
from table_image import render_table, render_table_as_cq, render_table_as_file

TEST_HEADERS = ["编号", "昵称", "UID", "通知群", "jjc", "pjjc", "通知"]
TEST_ROWS = [
    ["1", "用户A", "1012345678901", "12345678", "100场 50名", "1场 20名", "开"],
    ["2", "用户B", "1012345678902", "87654321", "-", "-", "jjc"],
]

img = render_table(headers=TEST_HEADERS, rows=TEST_ROWS, title="竞技场订阅状态")
check("render_table returns Image", isinstance(img, PILImage.Image), True)
check("image has size", img.size[0] > 0 and img.size[1] > 0, True)

cq = render_table_as_cq(headers=TEST_HEADERS, rows=TEST_ROWS, title="竞技场订阅状态")
check(
    "render_table_as_cq starts with cqcode",
    cq.startswith("[CQ:image,file=base64://"),
    True,
)
check("non-empty cq", len(cq) > 200, True)

out_path = os.path.join(os.path.dirname(__file__), "_test_table_output.png")
render_table_as_file(
    headers=TEST_HEADERS, rows=TEST_ROWS, path=out_path, title="竞技场订阅状态"
)
check("render_table_as_file creates file", os.path.exists(out_path), True)
print(f"       图片已保存到: {out_path}")

# ── 5. 迁移集成测试（读取真实数据文件） ───────────────────────────────
section("migration: binds.json + wanted_binds.json → new format")

import json
import tempfile
import shutil

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
    all_valid_ids = all(len(item.id) == 13 and item.id.isdigit()
                        for _, item in all_items)
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
    check("迁移 arena_on 字段正确", subs_for_qq[0].arena_on, bool(first_info.get("arena_on", True)))

    # ── 通缉迁移 ──────────────────────────────────────────────
    from wanted_manager import WantedManager

    def make_wanted_mgr_empty():
        m = WantedManager.__new__(WantedManager)
        m._data = {"group": {}, "personal": {}}
        return m

    wm_m = make_wanted_mgr_empty()
    wm_m.migrate_from_old(wanted_bind, watch_bind)

    # 各群 uid 去重后合计（同 uid 在 wanted+watch 里只算一次，同一 gid 不重复统计）
    all_gids = set(list(wanted_bind.keys()) + list(watch_bind.keys()))
    migrated_total = sum(len(wm_m.list_group(gid)) for gid in all_gids)
    expected_unique = sum(
        len({*wanted_bind.get(gid, []), *watch_bind.get(gid, [])})
        for gid in all_gids
    )
    check("迁移后通缉总数（去重）== 期望", migrated_total, expected_unique)

    # wanted 条目 notice_level=1，watch 条目 notice_level=2
    for gid, uids in wanted_bind.items():
        items = wm_m.list_group(gid)
        uid_to_level = {i.uid: i.notice_level for i in items}
        for uid in uids:
            check(f"wanted uid {uid[-4:]} notice_level=1",
                  uid_to_level.get(uid), 1)
        break  # 只抽检第一个群

    for gid, uids in watch_bind.items():
        items = wm_m.list_group(gid)
        uid_to_level = {i.uid: i.notice_level for i in items}
        for uid in uids:
            # 若同时在 wanted 里则 notice_level=1（wanted 优先），否则 =2
            expected_level = 1 if uid in wanted_bind.get(gid, []) else 2
            check(f"watch uid {uid[-4:]} notice_level={expected_level}",
                  uid_to_level.get(uid), expected_level)
        break  # 只抽检第一个群

    # 迁移幂等
    wm_m.migrate_from_old(wanted_bind, watch_bind)
    migrated_total2 = sum(len(wm_m.list_group(gid)) for gid in all_gids)
    check("通缉迁移幂等（二次迁移不增加数据）", migrated_total2, migrated_total)

# ── 结果汇总 ──────────────────────────────────────────────────────────
section("结果")
total = PASS + FAIL
print(f"  通过: {PASS}/{total}")
if FAIL:
    print(f"  失败: {FAIL}/{total}")
    sys.exit(1)
else:
    print("  全部通过！")
