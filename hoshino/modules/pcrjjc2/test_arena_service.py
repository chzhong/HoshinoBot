"""
test_arena_service.py - ArenaService 单元测试

使用 unittest.mock 隔离所有外部依赖：
  - arena_client.get_profile / get_profile_raw  → AsyncMock / 自定义 async side_effect
  - nonebot.get_bot                             → MagicMock (bot.send_group_msg = AsyncMock)
  - jjcdata (Redis DAO)                         → MagicMock
  - asyncio.sleep                               → patch 掉，避免实际等待

运行方式（在 HoshinoBot 根目录）：
    python hoshino/modules/pcrjjc2/test_arena_service.py

或在模块目录：
    python test_arena_service.py
"""

import asyncio
import os
import sys
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

# ── 导入链 stub ────────────────────────────────────────────────────────
# 导入链：arena_service → arena_client → pcrclient → hoshino.aiorequests → nonebot
# 以及 arena_service 自身 `from nonebot import get_bot`
# 全部在真实 import 发生前注入 sys.modules，避免触碰网络/Redis/bot 框架。

_nonebot_stub = MagicMock()
_nonebot_stub.message = MagicMock()  # hoshino/__init__.py: from nonebot.message import ...
sys.modules.setdefault("nonebot", _nonebot_stub)
sys.modules.setdefault("nonebot.message", MagicMock())

# hoshino 包本身及其子模块
_hoshino_stub = MagicMock()
sys.modules.setdefault("hoshino", _hoshino_stub)
sys.modules.setdefault("hoshino.aiorequests", MagicMock())

# pcrclient：stub 掉整个模块，暴露 ApiException 和 pcrclient 类
class _ApiException_cls(Exception):
    def __init__(self, msg="", code=0):
        super().__init__(msg)
        self.code = code

_pcrclient_stub = MagicMock()
_pcrclient_stub.ApiException = _ApiException_cls
_pcrclient_stub.pcrclient = MagicMock()
sys.modules.setdefault("pcrclient", _pcrclient_stub)

# arena_client：stub 掉整个模块；patch 目标是 arena_service.<name>，
# 所以这里只需保证 import 不报错，真正的行为由 patch() 控制。
_arena_client_stub = MagicMock()
_arena_client_stub.ApiException = _ApiException_cls
_arena_client_stub.get_profile = AsyncMock()
_arena_client_stub.get_profile_raw = AsyncMock()
_arena_client_stub._improve_user_info = MagicMock()
sys.modules.setdefault("arena_client", _arena_client_stub)

# schema 模块是真实文件（pcrjjc2/schema.py），无需 stub，可直接 import

# jjcdata（arena_service 用 `from jjcdata import jjcdata`）
# jjcdata 依赖 redis，需要 stub
sys.modules.setdefault("redis", MagicMock())
sys.modules.setdefault("jjcdata", MagicMock())

from config_loader import TZ_CST, load_config
from subscriptions import SubscriptionManager

_config = load_config()  # 使用真实 config.yaml，无网络依赖


# ── 辅助工厂 ──────────────────────────────────────────────────────────

def make_sub_mgr(*binds):
    """创建无 I/O 的 SubscriptionManager。binds: (qq, uid, gid) 元组。"""
    m = SubscriptionManager(items={})
    for qq, uid, gid in binds:
        m.add(qq, uid, gid)
    return m


def make_svc(*binds, sub_mgr=None, cache=None):
    """
    创建 ArenaService。
    sub_mgr: 直接传入已构造好的 SubscriptionManager（优先）；
    binds:   (qq, uid, gid) 元组，无 sub_mgr 时自动构造。
    """
    from arena_service import ArenaService
    from copy import deepcopy
    cfg = deepcopy(_config)
    m = sub_mgr if sub_mgr is not None else make_sub_mgr(*binds)
    cfg.subscription.items = m._items
    return ArenaService(cfg, cache or make_cache(), MagicMock())


def make_cache(ranks=None, user_names=None, user_infos=None):
    """
    创建 jjcdata mock。
    ranks:      {uid: (arena_rank, grand_arena_rank)}
    user_names: {uid: name}
    user_infos: {uid: dict}  供 get_user_info 返回
    """
    ranks = dict(ranks or {})
    user_names = dict(user_names or {})
    user_infos = dict(user_infos or {})

    cache = MagicMock()
    cache.get_user_rank.side_effect = lambda uid: ranks.get(uid)
    cache.cache_user_rank.side_effect = lambda uid, r: ranks.update({uid: r})
    cache.get_user_name.side_effect = lambda uid: user_names.get(uid, uid)
    cache.cache_user_name.side_effect = lambda uid, n: user_names.update({uid: n})
    cache.get_user_info.side_effect = lambda uid: user_infos.get(uid, {})
    cache.cache_user_info = MagicMock()
    return cache


def make_profile(uid, name="テスト", arena_rank=100, arena_group=5,
                 grand_arena_rank=50, grand_arena_group=3):
    """构造 get_profile 返回值（展平后的 user_info dict）。"""
    return {
        "viewer_id": int(uid),
        "user_name": name,
        "user_dname": name,
        "arena_rank": arena_rank,
        "arena_group": arena_group,
        "grand_arena_rank": grand_arena_rank,
        "grand_arena_group": grand_arena_group,
        "user_comment": "",
        "last_login_time": 0,
        "total_power": 0,
        "team_level": 0,
        "unit_num": 0,
        "arena_time": 0,
        "grand_arena_time": 0,
        "clan_name": "テストクラン",
    }


def make_raw_profile(uid, name="テスト", arena_rank=100, arena_group=5,
                     grand_arena_rank=50, grand_arena_group=3):
    """构造 get_profile_raw 返回值（原始 profile 结构）。"""
    return {
        "user_info": {
            "viewer_id": int(uid),
            "user_name": name,
            "user_comment": "",
            "team_level": 0,
            "team_exp": 0,
            "emblem": {"emblem_id": 0, "ex_value": 0},
            "last_login_time": 0,
            "arena_rank": arena_rank,
            "arena_group": arena_group,
            "arena_time": 0,
            "grand_arena_rank": grand_arena_rank,
            "grand_arena_group": grand_arena_group,
            "grand_arena_time": 0,
            "open_story_num": 0,
            "unit_num": 0,
            "total_power": 0,
            "tower_cleared_floor_num": 0,
            "tower_cleared_ex_quest_count": 0,
            "friend_num": 0,
        },
        "clan_name": "テストクラン",
        "favorite_unit": {
            "id": 100101, "unit_rarity": 3, "battle_rarity": 0,
            "unit_level": 1, "promotion_level": 1,
            "skin_data": {"icon_skin_id": 0, "sd_skin_id": 0,
                          "still_skin_id": 0, "motion_id": 0},
        },
    }


def mkt(h, m):
    return datetime(2026, 3, 10, h, m, 0, tzinfo=TZ_CST)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def async_return(value):
    """返回一个 async def，每次调用都 return value。"""
    async def _inner(*args, **kwargs):
        return value
    return _inner


def async_raise(exc):
    """返回一个 async def，每次调用都 raise exc。"""
    async def _inner(*args, **kwargs):
        raise exc
    return _inner


# ── 测试类 ────────────────────────────────────────────────────────────

class TestShouldCheckSubscriptions(unittest.TestCase):
    """ArenaService.should_check_subscriptions 各时段逻辑。

    订阅侧 check_config（_DEFAULT_SUB_CHECK_CONFIGS）：
      - settlement: interval=0  → 仅 15:00 触发，delay=0
      - default:    interval=1  → 每分钟都触发，delay=15
      hot/critical/cold 未在订阅 cc_map 中配置，均回退到 default(interval=1)。
    """

    def _make_svc(self):
        from arena_service import ArenaService
        return make_svc()

    @patch("arena_service.asyncio.sleep", new_callable=AsyncMock)
    def test_settlement_at_1500(self, _sleep):
        # 15:00 命中 settlement(interval=0) → 触发
        svc = self._make_svc()
        self.assertTrue(run(svc.should_check_subscriptions(now=mkt(15, 0))))

    @patch("arena_service.asyncio.sleep", new_callable=AsyncMock)
    def test_settlement_not_at_1501(self, _sleep):
        # 15:01 不匹配 settlement cron，回退到 default(interval=1) → 每分钟触发
        svc = self._make_svc()
        self.assertTrue(run(svc.should_check_subscriptions(now=mkt(15, 1))))

    @patch("arena_service.asyncio.sleep", new_callable=AsyncMock)
    def test_critical_falls_back_to_default_interval1(self, _sleep):
        # critical 在订阅 cc_map 中未配置，回退到 default(interval=1) → 每分钟触发
        svc = self._make_svc()
        self.assertTrue(run(svc.should_check_subscriptions(now=mkt(14, 59))))
        self.assertTrue(run(svc.should_check_subscriptions(now=mkt(14, 55))))

    @patch("arena_service.asyncio.sleep", new_callable=AsyncMock)
    def test_hot_falls_back_to_default_interval1(self, _sleep):
        # hot 在订阅 cc_map 中未配置，回退到 default(interval=1) → 每分钟触发（含奇数分钟）
        svc = self._make_svc()
        self.assertTrue(run(svc.should_check_subscriptions(now=mkt(14, 0))))
        self.assertTrue(run(svc.should_check_subscriptions(now=mkt(14, 1))))
        self.assertTrue(run(svc.should_check_subscriptions(now=mkt(14, 3))))

    @patch("arena_service.asyncio.sleep", new_callable=AsyncMock)
    def test_default_interval1_triggers_every_minute(self, _sleep):
        # default: interval=1 → 任意分钟都触发
        svc = self._make_svc()
        self.assertTrue(run(svc.should_check_subscriptions(now=mkt(10, 0))))
        self.assertTrue(run(svc.should_check_subscriptions(now=mkt(10, 3))))
        self.assertTrue(run(svc.should_check_subscriptions(now=mkt(10, 7))))

    @patch("arena_service.asyncio.sleep", new_callable=AsyncMock)
    def test_delay_called_when_triggering(self, mock_sleep):
        # default(interval=1, delay=15) 触发时应调用 sleep
        svc = self._make_svc()
        run(svc.should_check_subscriptions(now=mkt(10, 0)))
        mock_sleep.assert_called_once()

    @patch("arena_service.asyncio.sleep", new_callable=AsyncMock)
    def test_no_delay_at_settlement(self, mock_sleep):
        # settlement(interval=0, delay=0) 触发时 delay=0，不应调用 sleep
        svc = self._make_svc()
        run(svc.should_check_subscriptions(now=mkt(15, 0)))
        mock_sleep.assert_not_called()


class TestSubscriptionCRUD(unittest.TestCase):
    """ArenaService 订阅 CRUD 方法（薄委托层，确保语义正确）。"""

    def _make_svc(self, *binds):
        from arena_service import ArenaService
        return make_svc(*binds)

    def test_bind_ok(self):
        svc = self._make_svc()
        self.assertEqual(svc.bind("QQ1", "1012345678901", "G1"), "ok")

    def test_bind_dup(self):
        svc = self._make_svc(("QQ1", "1012345678901", "G1"))
        self.assertEqual(svc.bind("QQ1", "1012345678901", "G1"), "dup")

    def test_bind_full(self):
        svc = self._make_svc()
        for i in range(8):
            svc.bind("QQ1", f"101234567890{i}", "G1")
        self.assertEqual(svc.bind("QQ1", "1099999999999", "G1"), "full")

    def test_unbind_ok(self):
        svc = self._make_svc(("QQ1", "1012345678901", "G1"))
        self.assertTrue(svc.unbind("QQ1", 1))

    def test_unbind_oob(self):
        svc = self._make_svc(("QQ1", "1012345678901", "G1"))
        self.assertFalse(svc.unbind("QQ1", 99))

    def test_set_toggle_arena_off(self):
        svc = self._make_svc(("QQ1", "1012345678901", "G1"))
        self.assertTrue(svc.set_toggle("QQ1", 1, arena_on=False, grand_arena_on=None))
        self.assertFalse(svc._sub_mgr.get_list("QQ1")[0].arena_on)
        self.assertTrue(svc._sub_mgr.get_list("QQ1")[0].grand_arena_on)

    def test_set_toggle_all_grand_off(self):
        svc = self._make_svc(
            ("QQ1", "1012345678901", "G1"),
            ("QQ1", "1012345678902", "G1"),
        )
        svc.set_toggle("QQ1", None, arena_on=None, grand_arena_on=False)
        self.assertTrue(all(not s.grand_arena_on for s in svc._sub_mgr.get_list("QQ1")))

    def test_move_group_ok(self):
        svc = self._make_svc(("QQ1", "1012345678901", "G1"))
        self.assertTrue(svc.move_group("QQ1", 1, "G2"))
        self.assertEqual(svc._sub_mgr.get_list("QQ1")[0].gid, "G2")

    def test_move_group_oob(self):
        svc = self._make_svc(("QQ1", "1012345678901", "G1"))
        self.assertFalse(svc.move_group("QQ1", 99, "G2"))


class TestGetSubscriptionStatusRows(unittest.TestCase):
    """get_subscription_status_rows：从 Redis 缓存组装表格行。"""

    def test_rows_with_partial_cache(self):
        from arena_service import ArenaService
        sub_mgr = make_sub_mgr(
            ("QQ1", "1012345678901", "G1"),
            ("QQ1", "1012345678902", "G2"),
        )
        cache = make_cache(user_infos={
            "1012345678901": {
                "user_name": "用户A",
                "arena_rank": 50, "arena_group": 5,
                "grand_arena_rank": 20, "grand_arena_group": 1,
            },
            "1012345678902": {},  # 无缓存
        })
        svc = make_svc(sub_mgr=sub_mgr, cache=cache)
        rows = svc.get_subscription_status_rows("QQ1")

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].index, 1)
        self.assertEqual(rows[0].user_name, "用户A")
        self.assertEqual(rows[0].arena_str, "5场 50名")
        self.assertEqual(rows[0].grand_arena_str, "1场 20名")
        self.assertEqual(rows[0].gid, "G1")
        self.assertTrue(rows[0].arena_on)
        self.assertTrue(rows[0].grand_arena_on)

        self.assertEqual(rows[1].user_name, "-")
        self.assertEqual(rows[1].arena_str, "-")
        self.assertEqual(rows[1].grand_arena_str, "-")
        self.assertEqual(rows[1].gid, "G2")

    def test_empty_when_no_subscriptions(self):
        from arena_service import ArenaService
        svc = make_svc()
        self.assertEqual(svc.get_subscription_status_rows("QQ1"), [])

    def test_toggle_state_reflected(self):
        from arena_service import ArenaService
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "G1"))
        sub_mgr.set_toggle("QQ1", 1, arena_on=False, grand_arena_on=True)
        svc = make_svc(sub_mgr=sub_mgr)
        rows = svc.get_subscription_status_rows("QQ1")
        self.assertFalse(rows[0].arena_on)
        self.assertTrue(rows[0].grand_arena_on)


class TestQueryGroupRanks(unittest.TestCase):
    """query_group_ranks：按群过滤订阅后逐一调用 API。"""

    @patch("arena_service.get_profile")
    def test_returns_only_gid_bindings(self, mock_get_profile):
        from arena_service import ArenaService

        async def _profile(uid):
            return make_profile(uid, name=f"用户{uid[-3:]}")

        mock_get_profile.side_effect = _profile
        sub_mgr = make_sub_mgr(
            ("QQ1", "1012345678901", "G1"),
            ("QQ1", "1012345678902", "G1"),
            ("QQ1", "1012345678903", "G2"),  # 不在 G1
        )
        svc = make_svc(sub_mgr=sub_mgr)
        ranks = run(svc.query_group_ranks("QQ1", "G1"))

        self.assertEqual(len(ranks), 2)
        self.assertEqual(ranks[0].uid, "1012345678901")
        self.assertEqual(ranks[1].uid, "1012345678902")
        self.assertEqual(mock_get_profile.call_count, 2)

    @patch("arena_service.get_profile")
    def test_empty_when_no_gid_binding(self, mock_get_profile):
        from arena_service import ArenaService
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "G1"))
        svc = make_svc(sub_mgr=sub_mgr)

        ranks = run(svc.query_group_ranks("QQ1", "G_UNKNOWN"))
        self.assertEqual(ranks, [])
        mock_get_profile.assert_not_called()

    @patch("arena_service.get_profile")
    def test_propagates_api_exception(self, mock_get_profile):
        from arena_service import ArenaService
        from arena_client import ApiException

        mock_get_profile.side_effect = async_raise(ApiException("error", 1))
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "G1"))
        svc = make_svc(sub_mgr=sub_mgr)

        with self.assertRaises(ApiException):
            run(svc.query_group_ranks("QQ1", "G1"))

    @patch("arena_service.get_profile")
    def test_rank_info_fields(self, mock_get_profile):
        from arena_service import ArenaService

        mock_get_profile.side_effect = async_return(
            make_profile("1012345678901", name="テスト", arena_rank=42, arena_group=7,
                         grand_arena_rank=15, grand_arena_group=2)
        )
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "G1"))
        svc = make_svc(sub_mgr=sub_mgr)
        ranks = run(svc.query_group_ranks("QQ1", "G1"))

        self.assertEqual(ranks[0].user_name, "テスト")
        self.assertEqual(ranks[0].arena_rank, 42)
        self.assertEqual(ranks[0].arena_group, 7)
        self.assertEqual(ranks[0].grand_arena_rank, 15)
        self.assertEqual(ranks[0].grand_arena_group, 2)


class TestQueryDetail(unittest.TestCase):
    """query_detail：详细查询，uid 省略时取本群第一个绑定。"""

    @patch("arena_service._improve_user_info")
    @patch("arena_service.get_profile_raw")
    def test_uses_first_gid_binding_when_no_uid(self, mock_raw, mock_improve):
        from arena_service import ArenaService
        raw = make_raw_profile("1012345678901")
        mock_raw.side_effect = async_return(raw)
        mock_improve.return_value = make_profile("1012345678901", name="テスト")

        sub_mgr = make_sub_mgr(
            ("QQ1", "1012345678901", "G1"),
            ("QQ1", "1012345678902", "G1"),
        )
        svc = make_svc(sub_mgr=sub_mgr)
        info = run(svc.query_detail("QQ1", "G1"))

        mock_raw.assert_called_once_with("1012345678901")
        self.assertEqual(info["user_name"], "テスト")

    @patch("arena_service._improve_user_info")
    @patch("arena_service.get_profile_raw")
    def test_uses_given_uid(self, mock_raw, mock_improve):
        from arena_service import ArenaService
        raw = make_raw_profile("1012345678902")
        mock_raw.side_effect = async_return(raw)
        mock_improve.return_value = make_profile("1012345678902", name="指定用户")

        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "G1"))
        svc = make_svc(sub_mgr=sub_mgr)
        info = run(svc.query_detail("QQ1", "G1", uid="1012345678902"))

        mock_raw.assert_called_once_with("1012345678902")
        self.assertEqual(info["user_name"], "指定用户")

    def test_raises_value_error_when_no_gid_binding_and_no_uid(self):
        from arena_service import ArenaService
        svc = make_svc()
        with self.assertRaises(ValueError):
            run(svc.query_detail("QQ1", "G1"))

    def test_raises_value_error_when_gid_has_no_binding(self):
        from arena_service import ArenaService
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "G2"))  # G1 无绑定
        svc = make_svc(sub_mgr=sub_mgr)
        with self.assertRaises(ValueError):
            run(svc.query_detail("QQ1", "G1"))


class TestCheckArenaSubscriptions(unittest.TestCase):
    """check_arena_subscriptions：核心调度检测流程的端对端 mock 测试。"""

    def _run_check(self, sub_mgr, cache, profiles):
        """
        patch get_profile 和 get_bot，运行一次 check_arena_subscriptions。
        profiles: {uid: dict | Exception}
        返回 mock_bot（可检查 send_group_msg 调用）。
        """
        from arena_service import ArenaService

        mock_bot = MagicMock()
        mock_bot.send_group_msg = AsyncMock()

        async def mock_get_profile(uid):
            result = profiles.get(uid)
            if isinstance(result, Exception):
                raise result
            if result is None:
                from arena_client import ApiException
                raise ApiException("not found", 6)
            return result

        with patch("arena_service.get_profile", side_effect=mock_get_profile), \
             patch("arena_service.get_bot", return_value=mock_bot):
            svc = make_svc(sub_mgr=sub_mgr, cache=cache)
            run(svc.check_arena_subscriptions())

        return mock_bot

    def test_no_notification_on_first_check(self):
        """首次检测无基准，不发通知。"""
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "10001"))
        cache = make_cache()  # get_user_rank 返回 None
        bot = self._run_check(sub_mgr, cache,
                               {"1012345678901": make_profile("1012345678901", arena_rank=100)})
        bot.send_group_msg.assert_not_called()

    def test_notification_when_jjc_rank_drops(self):
        """jjc 排名下降（数值增大）时发通知。"""
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "10001"))
        ranks = {"1012345678901": (80, 50)}
        cache = make_cache(ranks=ranks, user_names={"1012345678901": "テスト"})
        profiles = {"1012345678901": make_profile("1012345678901", arena_rank=100, grand_arena_rank=50)}

        bot = self._run_check(sub_mgr, cache, profiles)
        bot.send_group_msg.assert_called_once()
        msg = bot.send_group_msg.call_args[1]["message"]
        self.assertIn("jjc", msg)
        self.assertIn("80->100", msg)
        self.assertIn("[CQ:at,qq=QQ1]", msg)

    def test_notification_when_pjjc_rank_drops(self):
        """pjjc 排名下降时发通知。"""
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "10001"))
        ranks = {"1012345678901": (100, 30)}
        cache = make_cache(ranks=ranks, user_names={"1012345678901": "テスト"})
        profiles = {"1012345678901": make_profile("1012345678901", arena_rank=100, grand_arena_rank=50)}

        bot = self._run_check(sub_mgr, cache, profiles)
        bot.send_group_msg.assert_called_once()
        msg = bot.send_group_msg.call_args[1]["message"]
        self.assertIn("pjjc", msg)
        self.assertIn("30->50", msg)

    def test_no_notification_when_rank_improves(self):
        """排名上升（数值减小）不发通知。"""
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "10001"))
        ranks = {"1012345678901": (100, 50)}
        cache = make_cache(ranks=ranks)
        profiles = {"1012345678901": make_profile("1012345678901", arena_rank=80, grand_arena_rank=30)}

        bot = self._run_check(sub_mgr, cache, profiles)
        bot.send_group_msg.assert_not_called()

    def test_no_notification_when_rank_unchanged(self):
        """排名不变不发通知。"""
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "10001"))
        ranks = {"1012345678901": (100, 50)}
        cache = make_cache(ranks=ranks)
        profiles = {"1012345678901": make_profile("1012345678901", arena_rank=100, grand_arena_rank=50)}

        bot = self._run_check(sub_mgr, cache, profiles)
        bot.send_group_msg.assert_not_called()

    def test_arena_on_false_suppresses_jjc_notification(self):
        """arena_on=False 时 jjc 不通知，pjjc 变动时仍通知。"""
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "10001"))
        sub_mgr.set_toggle("QQ1", 1, arena_on=False, grand_arena_on=None)
        ranks = {"1012345678901": (80, 30)}
        cache = make_cache(ranks=ranks, user_names={"1012345678901": "テスト"})
        profiles = {"1012345678901": make_profile("1012345678901", arena_rank=100, grand_arena_rank=50)}

        bot = self._run_check(sub_mgr, cache, profiles)
        bot.send_group_msg.assert_called_once()
        msg = bot.send_group_msg.call_args[1]["message"]
        lines = msg.splitlines()
        self.assertFalse(any(l.startswith("jjc：") for l in lines), "不应有 jjc 通知行")
        self.assertTrue(any("pjjc" in l for l in lines), "应有 pjjc 通知行")

    def test_grand_arena_on_false_suppresses_pjjc_notification(self):
        """grand_arena_on=False 时 pjjc 不通知，jjc 变动时仍通知。"""
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "10001"))
        sub_mgr.set_toggle("QQ1", 1, arena_on=None, grand_arena_on=False)
        ranks = {"1012345678901": (80, 30)}
        cache = make_cache(ranks=ranks, user_names={"1012345678901": "テスト"})
        profiles = {"1012345678901": make_profile("1012345678901", arena_rank=100, grand_arena_rank=50)}

        bot = self._run_check(sub_mgr, cache, profiles)
        bot.send_group_msg.assert_called_once()
        msg = bot.send_group_msg.call_args[1]["message"]
        self.assertIn("jjc", msg)
        self.assertNotIn("pjjc", msg)

    def test_both_off_no_notification(self):
        """arena_on=False 且 grand_arena_on=False 时完全不通知。"""
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "10001"))
        sub_mgr.set_toggle("QQ1", 1, arena_on=False, grand_arena_on=False)
        ranks = {"1012345678901": (80, 30)}
        cache = make_cache(ranks=ranks)
        profiles = {"1012345678901": make_profile("1012345678901", arena_rank=100, grand_arena_rank=50)}

        bot = self._run_check(sub_mgr, cache, profiles)
        bot.send_group_msg.assert_not_called()

    def test_round_cache_dedup(self):
        """同一 uid 被多个用户订阅时，API 只调用一次（本轮缓存命中）。"""
        sub_mgr = make_sub_mgr(
            ("QQ1", "1012345678901", "10001"),
            ("QQ2", "1012345678901", "10002"),  # 同一个 uid，不同用户/群
        )
        ranks = {"1012345678901": (80, 30)}
        cache = make_cache(ranks=ranks, user_names={"1012345678901": "テスト"})

        call_count = 0

        async def counting_get_profile(uid):
            nonlocal call_count
            call_count += 1
            return make_profile(uid, arena_rank=100, grand_arena_rank=50)

        mock_bot = MagicMock()
        mock_bot.send_group_msg = AsyncMock()
        with patch("arena_service.get_profile", side_effect=counting_get_profile), \
             patch("arena_service.get_bot", return_value=mock_bot):
            from arena_service import ArenaService
            svc = make_svc(sub_mgr=sub_mgr, cache=cache)
            run(svc.check_arena_subscriptions())

        self.assertEqual(call_count, 1, "同一 uid 应只查询一次 API")
        # 两个用户订阅同一 uid，round_cache 保留旧基准，各自独立比对后都发通知
        self.assertEqual(mock_bot.send_group_msg.call_count, 2)

    def test_grouped_notification_per_group(self):
        """同一用户多个 uid 在同一群时，聚合为一条 @ 消息。"""
        sub_mgr = make_sub_mgr(
            ("QQ1", "1012345678901", "10001"),
            ("QQ1", "1012345678902", "10001"),
        )
        ranks = {
            "1012345678901": (80, 30),
            "1012345678902": (60, 20),
        }
        cache = make_cache(
            ranks=ranks,
            user_names={"1012345678901": "用户A", "1012345678902": "用户B"},
        )
        profiles = {
            "1012345678901": make_profile("1012345678901", name="用户A", arena_rank=100, grand_arena_rank=50),
            "1012345678902": make_profile("1012345678902", name="用户B", arena_rank=90, grand_arena_rank=40),
        }

        bot = self._run_check(sub_mgr, cache, profiles)
        self.assertEqual(bot.send_group_msg.call_count, 1, "同一群应只发一条消息")
        msg = bot.send_group_msg.call_args[1]["message"]
        self.assertIn("用户A", msg)
        self.assertIn("用户B", msg)

    def test_two_groups_two_messages(self):
        """同一用户在两个群各有订阅，各发一条消息到对应群。"""
        sub_mgr = make_sub_mgr(
            ("QQ1", "1012345678901", "111"),
            ("QQ1", "1012345678902", "222"),
        )
        ranks = {
            "1012345678901": (80, 30),
            "1012345678902": (60, 20),
        }
        cache = make_cache(
            ranks=ranks,
            user_names={"1012345678901": "用户A", "1012345678902": "用户B"},
        )
        profiles = {
            "1012345678901": make_profile("1012345678901", name="用户A", arena_rank=100, grand_arena_rank=50),
            "1012345678902": make_profile("1012345678902", name="用户B", arena_rank=90, grand_arena_rank=40),
        }

        bot = self._run_check(sub_mgr, cache, profiles)
        self.assertEqual(bot.send_group_msg.call_count, 2)
        sent_groups = {c[1]["group_id"] for c in bot.send_group_msg.call_args_list}
        self.assertEqual(sent_groups, {111, 222})

    def test_api_error_code6_skips_uid(self):
        """API 返回 code=6（uid 无效）时跳过该 uid，其余正常处理。"""
        from arena_client import ApiException
        sub_mgr = make_sub_mgr(
            ("QQ1", "1012345678901", "10001"),
            ("QQ1", "1012345678902", "10001"),
        )
        ranks = {"1012345678902": (60, 20)}
        cache = make_cache(ranks=ranks, user_names={"1012345678902": "用户B"})
        profiles = {
            "1012345678901": ApiException("invalid uid", 6),  # 用 Exception 表示抛出
            "1012345678902": make_profile("1012345678902", name="用户B", arena_rank=90, grand_arena_rank=40),
        }

        bot = self._run_check(sub_mgr, cache, profiles)
        bot.send_group_msg.assert_called_once()
        msg = bot.send_group_msg.call_args[1]["message"]
        self.assertIn("用户B", msg)

    def test_send_failure_does_not_raise(self):
        """send_group_msg 抛异常时，主流程继续，不向上传播。"""
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "10001"))
        ranks = {"1012345678901": (80, 30)}
        cache = make_cache(ranks=ranks, user_names={"1012345678901": "テスト"})
        profiles = {"1012345678901": make_profile("1012345678901", arena_rank=100, grand_arena_rank=50)}

        mock_bot = MagicMock()
        mock_bot.send_group_msg = AsyncMock(side_effect=Exception("network error"))

        async def mock_get_profile(uid):
            return profiles[uid]

        with patch("arena_service.get_profile", side_effect=mock_get_profile), \
             patch("arena_service.get_bot", return_value=mock_bot):
            from arena_service import ArenaService
            svc = make_svc(sub_mgr=sub_mgr, cache=cache)
            # 不应该抛异常
            run(svc.check_arena_subscriptions())

    def test_cache_updated_after_query(self):
        """查询后 Redis 基准应被更新为新排名。"""
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "10001"))
        stored_ranks = {"1012345678901": (80, 30)}
        cache = make_cache(ranks=stored_ranks)
        profiles = {"1012345678901": make_profile("1012345678901", arena_rank=100, grand_arena_rank=50)}

        self._run_check(sub_mgr, cache, profiles)
        # 检查 cache_user_rank 被调用，且用新值更新
        cache.cache_user_rank.assert_called_with("1012345678901", (100, 50))


# ── 运行 ──────────────────────────────────────────────────────────────

class _GroupedResult(unittest.TextTestResult):
    """在每个 TestCase 类首个测试前打印分组标题。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._current_class = None

    def startTest(self, test):
        cls = type(test)
        if cls is not self._current_class:
            self._current_class = cls
            self.stream.writeln(f"\n{'=' * 60}")
            self.stream.writeln(f"  {cls.__name__}")
            doc = cls.__doc__ or ""
            if doc.strip():
                self.stream.writeln(f"  {doc.strip()}")
            self.stream.writeln(f"{'=' * 60}")
        super().startTest(test)


class _GroupedRunner(unittest.TextTestRunner):
    resultclass = _GroupedResult


if __name__ == "__main__":
    unittest.main(testRunner=_GroupedRunner, verbosity=2)
