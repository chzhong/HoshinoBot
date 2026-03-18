"""
test_arena_service.py - ArenaService 单元测试

使用 unittest.mock 隔离所有外部依赖：
  - arena_client.get_profile / get_profile_raw  → AsyncMock / 自定义 async side_effect
  - nonebot.get_bot                             → MagicMock (bot.send_group_msg = AsyncMock)
  - jjcdata (Redis DAO)                         → MagicMock
  - asyncio.sleep                               → patch 掉，避免实际等待

运行方式（在 HoshinoBot 根目录）：
    TEST=1 python -m hoshino.modules.pcrjjc2.test_arena_service

注：TEST=1 环境变量必须设置，否则模块会被 stub 掉
"""
# ruff: noqa: E402

import asyncio
import os
import re
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

# ── 导入链 stub ────────────────────────────────────────────────────────
# 导入链：arena_service → arena_client → pcrclient → hoshino.aiorequests → nonebot
# 以及 arena_service 自身 `from nonebot import get_bot`
# 全部在真实 import 发生前注入 sys.modules，避免触碰网络/Redis/bot 框架。
# _nonebot_stub = MagicMock()
# _nonebot_stub.message = (
#     MagicMock()
# )  # hoshino/__init__.py: from nonebot.message import ...
# sys.modules.setdefault("nonebot", _nonebot_stub)
# sys.modules.setdefault("nonebot.message", MagicMock())
# # hoshino 包本身及其子模块
# _hoshino_stub = MagicMock()
# sys.modules.setdefault("hoshino", _hoshino_stub)
# sys.modules.setdefault("hoshino.aiorequests", MagicMock())
# # pcrclient：stub 掉整个模块，暴露 ApiException 和 pcrclient 类
# class _ApiException_cls(Exception):
#     def __init__(self, msg="", code=0):
#         super().__init__(msg)
#         self.code = code
# _pcrclient_stub = MagicMock()
# _pcrclient_stub.ApiException = _ApiException_cls
# _pcrclient_stub.pcrclient = MagicMock()
# sys.modules.setdefault("pcrclient", _pcrclient_stub)
# # arena_client：stub 掉整个模块；patch 目标是 arena_service.<name>，
# # 所以这里只需保证 import 不报错，真正的行为由 patch() 控制。
# _arena_client_stub = MagicMock()
# _arena_client_stub.ApiException = _ApiException_cls
# _arena_client_stub.get_profile = AsyncMock()
# _arena_client_stub.get_profile_raw = AsyncMock()
# _arena_client_stub._improve_user_info = MagicMock()
# sys.modules.setdefault("arena_client", _arena_client_stub)
# # schema 模块是真实文件（pcrjjc2/schema.py），无需 stub，可直接 import
# # jjcdata（arena_service 用 `from jjcdata import jjcdata`）
# # jjcdata 依赖 redis，需要 stub
# sys.modules.setdefault("redis", MagicMock())
# sys.modules.setdefault("jjcdata", MagicMock())
from ..config_loader import TZ_CST, load_config
from ..subscription_manager import SubscriptionManager

TEST_CONFIG = os.path.join(os.path.dirname(__file__), "_test_config.yaml")

_config = load_config(TEST_CONFIG)  # 使用真实 config.yaml，无网络依赖


# ── 辅助工厂 ──────────────────────────────────────────────────────────


def make_sub_mgr(*binds):
    """创建无 I/O 的 SubscriptionManager。binds: (qq, uid, gid) 元组。"""
    m = SubscriptionManager(items={})
    for qq, uid, gid in binds:
        m.add(qq, uid, gid)
    return m


def make_svc(
    *binds,
    sub_mgr=None,
    wanted_mgr=None,
    cache=None,
    bot=None,
    logger=None,
    reset_notice_levels=True,
):
    """
    创建 ArenaService。
    sub_mgr: 直接传入已构造好的 SubscriptionManager（优先）；
    wanted_mgr: 直接传入已构造好的 WantedManager（优先）；
    binds:   (qq, uid, gid) 元组，无 sub_mgr 时自动构造。
    """
    from copy import deepcopy

    from ..arena_service import ArenaService

    cfg = deepcopy(_config)
    m = sub_mgr if sub_mgr is not None else make_sub_mgr(*binds)
    cfg.subscription.items = m._items

    if wanted_mgr is not None:
        cfg.wanted_list.group = wanted_mgr._group
        cfg.wanted_list.personal = wanted_mgr._personal

    mock_bot = bot or MagicMock()
    mock_logger = logger or MagicMock()

    return ArenaService(
        cfg,
        cache or make_cache(),
        mock_bot,
        mock_logger,
        wanted_manager=wanted_mgr,
        config_path=TEST_CONFIG,
        reset_notice_levels=reset_notice_levels,
    )


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


def make_profile(
    uid,
    name="テスト",
    arena_rank=100,
    arena_group=5,
    grand_arena_rank=50,
    grand_arena_group=3,
):
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


def make_raw_profile(
    uid,
    name="テスト",
    arena_rank=100,
    arena_group=5,
    grand_arena_rank=50,
    grand_arena_group=3,
):
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
            "id": 100101,
            "unit_rarity": 3,
            "battle_rarity": 0,
            "unit_level": 1,
            "promotion_level": 1,
            "skin_data": {
                "icon_skin_id": 0,
                "sd_skin_id": 0,
                "still_skin_id": 0,
                "motion_id": 0,
            },
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


class TestSubscriptionCRUD(unittest.TestCase):
    """ArenaService 订阅 CRUD 方法（薄委托层，确保语义正确）。"""

    def _make_svc(self, *binds):
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
        sub_mgr = make_sub_mgr(
            ("QQ1", "1012345678901", "G1"),
            ("QQ1", "1012345678902", "G2"),
        )
        cache = make_cache(
            user_infos={
                "1012345678901": {
                    "user_name": "用户A",
                    "arena_rank": 50,
                    "arena_group": 5,
                    "grand_arena_rank": 20,
                    "grand_arena_group": 1,
                },
                "1012345678902": {},  # 无缓存
            }
        )
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
        svc = make_svc()
        self.assertEqual(svc.get_subscription_status_rows("QQ1"), [])

    def test_toggle_state_reflected(self):
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "G1"))
        sub_mgr.set_toggle("QQ1", 1, arena_on=False, grand_arena_on=True)
        svc = make_svc(sub_mgr=sub_mgr)
        rows = svc.get_subscription_status_rows("QQ1")
        self.assertFalse(rows[0].arena_on)
        self.assertTrue(rows[0].grand_arena_on)


class TestQueryGroupRanks(unittest.TestCase):
    """query_group_ranks：按群过滤订阅后逐一调用 API。"""

    @patch("hoshino.modules.pcrjjc2.arena_service.get_profile")
    def test_returns_only_gid_bindings(self, mock_get_profile):

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

    @patch("hoshino.modules.pcrjjc2.arena_service.get_profile")
    def test_empty_when_no_gid_binding(self, mock_get_profile):
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "G1"))
        svc = make_svc(sub_mgr=sub_mgr)

        ranks = run(svc.query_group_ranks("QQ1", "G_UNKNOWN"))
        self.assertEqual(ranks, [])
        mock_get_profile.assert_not_called()

    @patch("hoshino.modules.pcrjjc2.arena_service.get_profile")
    def test_propagates_api_exception(self, mock_get_profile):
        from ..arena_client import ApiException

        mock_get_profile.side_effect = async_raise(ApiException("error", 1))
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "G1"))
        svc = make_svc(sub_mgr=sub_mgr)

        with self.assertRaises(ApiException):
            run(svc.query_group_ranks("QQ1", "G1"))

    @patch("hoshino.modules.pcrjjc2.arena_service.get_profile")
    def test_rank_info_fields(self, mock_get_profile):

        mock_get_profile.side_effect = async_return(
            make_profile(
                "1012345678901",
                name="テスト",
                arena_rank=42,
                arena_group=7,
                grand_arena_rank=15,
                grand_arena_group=2,
            )
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

    @patch("hoshino.modules.pcrjjc2.arena_service._improve_user_info")
    @patch("hoshino.modules.pcrjjc2.arena_service.get_profile_raw")
    def test_uses_first_gid_binding_when_no_uid(self, mock_raw, mock_improve):
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

    @patch("hoshino.modules.pcrjjc2.arena_service._improve_user_info")
    @patch("hoshino.modules.pcrjjc2.arena_service.get_profile_raw")
    def test_uses_given_uid(self, mock_raw, mock_improve):
        raw = make_raw_profile("1012345678902")
        mock_raw.side_effect = async_return(raw)
        mock_improve.return_value = make_profile("1012345678902", name="指定用户")

        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "G1"))
        svc = make_svc(sub_mgr=sub_mgr)
        info = run(svc.query_detail("QQ1", "G1", uid_or_idx="1012345678902"))

        mock_raw.assert_called_once_with("1012345678902")
        self.assertEqual(info["user_name"], "指定用户")

    def test_raises_value_error_when_no_gid_binding_and_no_uid(self):
        svc = make_svc()
        with self.assertRaises(ValueError):
            run(svc.query_detail("QQ1", "G1"))

    def test_raises_value_error_when_gid_has_no_binding(self):
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "G2"))  # G1 无绑定
        svc = make_svc(sub_mgr=sub_mgr)
        with self.assertRaises(ValueError):
            run(svc.query_detail("QQ1", "G1"))


class TestCheckArenaSubscriptions(unittest.TestCase):
    """check_arena_subscriptions：核心调度检测流程的端对端 mock 测试。"""

    def _run_check(self, sub_mgr, cache, profiles, delay=0):
        """
        patch get_profile，运行一次 check_arena_subscriptions。
        profiles: {uid: dict | Exception}
        delay: 检测延迟（秒），默认0表示无延迟
        返回 mock_bot（可检查 send_group_msg 调用）。
        """

        mock_bot = MagicMock()
        mock_bot.send_group_msg = AsyncMock()

        async def mock_get_profile(uid):
            result = profiles.get(uid)
            if isinstance(result, Exception):
                raise result
            if result is None:
                from ..arena_client import ApiException

                raise ApiException("not found", 6)
            return result

        # fmt: off
        with patch(
                "hoshino.modules.pcrjjc2.rank_monitor.get_profile",
                side_effect=mock_get_profile,
            ):
        # fmt: on
            from ..rank_monitor import CheckContext

            svc = make_svc(sub_mgr=sub_mgr, cache=cache, bot=mock_bot)
            ctx = CheckContext(
                bot=mock_bot,
                logger=svc._logger,
                cache=cache,
                config=svc._config,
            )
            run(svc.check_arena_subscriptions(ctx, delay=delay))

        return mock_bot

    def test_no_notification_on_first_check(self):
        """首次检测无基准，不发通知。"""
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "10001"))
        cache = make_cache()  # get_user_rank 返回 None
        bot = self._run_check(
            sub_mgr,
            cache,
            {"1012345678901": make_profile("1012345678901", arena_rank=100)},
        )
        bot.send_group_msg.assert_not_called()

    def test_notification_when_jjc_rank_drops(self):
        """jjc 排名下降（数值增大）时发通知。"""
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "10001"))
        ranks = {"1012345678901": (80, 50)}
        cache = make_cache(ranks=ranks, user_names={"1012345678901": "テスト"})
        profiles = {
            "1012345678901": make_profile(
                "1012345678901", arena_rank=100, grand_arena_rank=50
            )
        }

        bot = self._run_check(sub_mgr, cache, profiles)
        bot.send_group_msg.assert_called_once()
        msg = bot.send_group_msg.call_args[1]["message"]
        # 新格式：昵称: jjc: 80->100 (▼20) [CQ:at,qq=QQ1]
        self.assertIn("jjc", msg)
        self.assertIn("80->100", msg)
        self.assertIn("[CQ:at,qq=QQ1]", msg)
        # @ 应该在最后
        self.assertTrue(msg.endswith("[CQ:at,qq=QQ1]"), "@ 应该在消息末尾")

    def test_notification_when_pjjc_rank_drops(self):
        """pjjc 排名下降时发通知。"""
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "10001"))
        ranks = {"1012345678901": (100, 30)}
        cache = make_cache(ranks=ranks, user_names={"1012345678901": "テスト"})
        profiles = {
            "1012345678901": make_profile(
                "1012345678901", arena_rank=100, grand_arena_rank=50
            )
        }

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
        profiles = {
            "1012345678901": make_profile(
                "1012345678901", arena_rank=80, grand_arena_rank=30
            )
        }

        bot = self._run_check(sub_mgr, cache, profiles)
        bot.send_group_msg.assert_not_called()

    def test_no_notification_when_rank_unchanged(self):
        """排名不变不发通知。"""
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "10001"))
        ranks = {"1012345678901": (100, 50)}
        cache = make_cache(ranks=ranks)
        profiles = {
            "1012345678901": make_profile(
                "1012345678901", arena_rank=100, grand_arena_rank=50
            )
        }

        bot = self._run_check(sub_mgr, cache, profiles)
        bot.send_group_msg.assert_not_called()

    def test_arena_on_false_suppresses_jjc_notification(self):
        """arena_on=False 时 jjc 不通知，pjjc 变动时仍通知。"""
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "10001"))
        sub_mgr.set_toggle("QQ1", 1, arena_on=False, grand_arena_on=None)
        ranks = {"1012345678901": (80, 30)}
        cache = make_cache(ranks=ranks, user_names={"1012345678901": "テスト"})
        profiles = {
            "1012345678901": make_profile(
                "1012345678901", arena_rank=100, grand_arena_rank=50
            )
        }

        bot = self._run_check(sub_mgr, cache, profiles)
        bot.send_group_msg.assert_called_once()
        msg = bot.send_group_msg.call_args[1]["message"]
        lines = msg.splitlines()
        self.assertFalse(any(l.startswith("jjc：") for l in lines), "不应有 jjc 通知行")  # noqa: E741
        self.assertTrue(any("pjjc" in l for l in lines), "应有 pjjc 通知行")  # noqa: E741

    def test_grand_arena_on_false_suppresses_pjjc_notification(self):
        """grand_arena_on=False 时 pjjc 不通知，jjc 变动时仍通知。"""
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "10001"))
        sub_mgr.set_toggle("QQ1", 1, arena_on=None, grand_arena_on=False)
        ranks = {"1012345678901": (80, 30)}
        cache = make_cache(ranks=ranks, user_names={"1012345678901": "テスト"})
        profiles = {
            "1012345678901": make_profile(
                "1012345678901", arena_rank=100, grand_arena_rank=50
            )
        }

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
        profiles = {
            "1012345678901": make_profile(
                "1012345678901", arena_rank=100, grand_arena_rank=50
            )
        }

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
        # fmt: off
        with patch(
                "hoshino.modules.pcrjjc2.rank_monitor.get_profile",
                side_effect=counting_get_profile,
            ):
        # fmt: on
            from ..rank_monitor import CheckContext

            svc = make_svc(sub_mgr=sub_mgr, cache=cache, bot=mock_bot)
            ctx = CheckContext(
                bot=mock_bot,
                logger=svc._logger,
                cache=cache,
                config=svc._config,
            )
            run(svc.check_arena_subscriptions(ctx, delay=0))

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
            "1012345678901": make_profile(
                "1012345678901", name="用户A", arena_rank=100, grand_arena_rank=50
            ),
            "1012345678902": make_profile(
                "1012345678902", name="用户B", arena_rank=90, grand_arena_rank=40
            ),
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
            "1012345678901": make_profile(
                "1012345678901", name="用户A", arena_rank=100, grand_arena_rank=50
            ),
            "1012345678902": make_profile(
                "1012345678902", name="用户B", arena_rank=90, grand_arena_rank=40
            ),
        }

        bot = self._run_check(sub_mgr, cache, profiles)
        self.assertEqual(bot.send_group_msg.call_count, 2)
        sent_groups = {c[1]["group_id"] for c in bot.send_group_msg.call_args_list}
        self.assertEqual(sent_groups, {111, 222})

    def test_api_error_code6_skips_uid(self):
        """API 返回 code=6（uid 无效）时跳过该 uid，其余正常处理。"""
        from ..arena_client import ApiException

        sub_mgr = make_sub_mgr(
            ("QQ1", "1012345678901", "10001"),
            ("QQ1", "1012345678902", "10001"),
        )
        ranks = {"1012345678902": (60, 20)}
        cache = make_cache(ranks=ranks, user_names={"1012345678902": "用户B"})
        profiles = {
            "1012345678901": ApiException("invalid uid", 6),  # 用 Exception 表示抛出
            "1012345678902": make_profile(
                "1012345678902", name="用户B", arena_rank=90, grand_arena_rank=40
            ),
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
        profiles = {
            "1012345678901": make_profile(
                "1012345678901", arena_rank=100, grand_arena_rank=50
            )
        }

        mock_bot = MagicMock()
        mock_bot.send_group_msg = AsyncMock(side_effect=Exception("network error"))

        async def mock_get_profile(uid):
            return profiles[uid]

        # fmt: off
        with patch(
                "hoshino.modules.pcrjjc2.rank_monitor.get_profile",
                side_effect=mock_get_profile,
            ):
        # fmt: on
            from ..rank_monitor import CheckContext

            svc = make_svc(sub_mgr=sub_mgr, cache=cache, bot=mock_bot)
            ctx = CheckContext(
                bot=mock_bot,
                logger=svc._logger,
                cache=cache,
                config=svc._config,
            )
            # 不应该抛异常
            run(svc.check_arena_subscriptions(ctx, delay=0))

    def test_cache_updated_after_query(self):
        """查询后 Redis 基准应被更新为新排名。"""
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "10001"))
        stored_ranks = {"1012345678901": (80, 30)}
        cache = make_cache(ranks=stored_ranks)
        profiles = {
            "1012345678901": make_profile(
                "1012345678901", arena_rank=100, grand_arena_rank=50
            )
        }

        self._run_check(sub_mgr, cache, profiles)
        # 检查 cache_user_rank 被调用，且用新值更新
        cache.cache_user_rank.assert_called_with("1012345678901", (100, 50))


# ── 通缉监控测试 ──────────────────────────────────────────────────────


def make_wanted_mgr(*items):
    """
    创建无 I/O 的 WantedManager。
    items: (type, gid_or_qq, uid, **kwargs) 元组。
           type='group' 表示群通缉，type='personal' 表示个人通缉。
    """
    from ..schema import WantedItem, WantedListConfig
    from ..wanted_manager import WantedManager

    config = WantedListConfig(check_config={}, group={}, personal={})
    mgr = WantedManager(config)

    for item in items:
        if item[0] == "group":
            _, gid, uid, *rest = item
            kwargs = rest[0] if rest else {}
            mgr.add_group(gid, WantedItem(id=uid, gid=gid, **kwargs))
        elif item[0] == "personal":
            _, qq, uid, gid, *rest = item
            kwargs = rest[0] if rest else {}
            mgr.add_personal(qq, WantedItem(id=uid, gid=gid, **kwargs))

    return mgr


class TestCheckWanted(unittest.TestCase):
    """check_wanted：通缉监控流程的端对端 mock 测试。"""

    def _run_check_wanted(self, wanted_mgr, cache, profiles, now=None, delay=0):
        """
        patch get_profile，运行一次 check_wanted。
        profiles: {uid: dict | Exception}
        delay: 检测延迟（秒），默认0表示无延迟
        返回 mock_bot（可检查 send_group_msg 调用）。
        """
        mock_bot = MagicMock()
        mock_bot.send_group_msg = AsyncMock()
        mock_logger = MagicMock()

        async def mock_get_profile(uid):
            result = profiles.get(uid)
            if isinstance(result, Exception):
                raise result
            if result is None:
                from ..arena_client import ApiException

                raise ApiException("not found", 6)
            return result

        # fmt: off
        with patch(
                "hoshino.modules.pcrjjc2.rank_monitor.get_profile",
                side_effect=mock_get_profile,
            ):
        # fmt: on
            svc = make_svc(wanted_mgr=wanted_mgr, cache=cache, bot=mock_bot, logger=mock_logger)
            # 创建 CheckContext
            from .. import rank_monitor

            ctx = rank_monitor.CheckContext(
                bot=mock_bot,
                logger=mock_logger,
                cache=cache,
                config=svc._config,
                now=now or mkt(10, 0),
            )
            run(svc.check_wanted(ctx, delay=delay))

        return mock_bot

    def test_no_notification_on_first_check(self):
        """首次检测无基准，不发通知。"""
        wanted_mgr = make_wanted_mgr(("group", "10001", "1012345678901"))
        cache = make_cache()  # get_user_rank 返回 None
        bot = self._run_check_wanted(
            wanted_mgr,
            cache,
            {"1012345678901": make_profile("1012345678901", arena_rank=100)},
        )
        bot.send_group_msg.assert_not_called()

    def test_group_wanted_notification_on_rank_change(self):
        """群通缉：排名变化时发通知。"""
        wanted_mgr = make_wanted_mgr(("group", "10001", "1012345678901"))
        ranks = {"1012345678901": (80, 50)}
        user_infos = {
            "1012345678901": {
                "user_name": "テスト",
                "user_dname": "テスト",
                "last_login_time": 0,
            }
        }
        cache = make_cache(ranks=ranks, user_infos=user_infos)
        profiles = {
            "1012345678901": make_profile(
                "1012345678901", name="テスト", arena_rank=100, grand_arena_rank=50
            )
        }

        bot = self._run_check_wanted(wanted_mgr, cache, profiles)
        bot.send_group_msg.assert_called_once()
        call_args = bot.send_group_msg.call_args
        self.assertEqual(call_args[1]["group_id"], 10001)
        msg = call_args[1]["message"]
        self.assertIn("通缉犯", msg)
        self.assertIn("テスト", msg)
        self.assertIn("jjc", msg)
        self.assertIn("80->100", msg)

    def test_personal_wanted_notification_with_at(self):
        """个人通缉：排名变化时发通知，包含 @ 通缉者。"""
        wanted_mgr = make_wanted_mgr(("personal", "QQ1", "1012345678901", "10001"))
        ranks = {"1012345678901": (80, 50)}
        user_infos = {
            "1012345678901": {
                "user_name": "テスト",
                "user_dname": "テスト",
                "last_login_time": 0,
            }
        }
        cache = make_cache(ranks=ranks, user_infos=user_infos)
        profiles = {
            "1012345678901": make_profile(
                "1012345678901", name="テスト", arena_rank=100, grand_arena_rank=50
            )
        }

        bot = self._run_check_wanted(wanted_mgr, cache, profiles)
        bot.send_group_msg.assert_called_once()
        msg = bot.send_group_msg.call_args[1]["message"]
        self.assertIn("[CQ:at,qq=QQ1]", msg)
        self.assertIn("通缉犯", msg)

    def test_both_group_and_personal_wanted(self):
        """群+个人都通缉：通报在前，@ 在后。"""
        wanted_mgr = make_wanted_mgr(
            ("group", "10001", "1012345678901"),
            ("personal", "QQ1", "1012345678901", "10001"),
            ("personal", "QQ2", "1012345678901", "10001"),
        )
        ranks = {"1012345678901": (80, 50)}
        user_infos = {
            "1012345678901": {
                "user_name": "テスト",
                "user_dname": "テスト",
                "last_login_time": 0,
            }
        }
        cache = make_cache(ranks=ranks, user_infos=user_infos)
        profiles = {
            "1012345678901": make_profile(
                "1012345678901", name="テスト", arena_rank=100, grand_arena_rank=50
            )
        }

        bot = self._run_check_wanted(wanted_mgr, cache, profiles)
        bot.send_group_msg.assert_called_once()
        msg = bot.send_group_msg.call_args[1]["message"]
        # 通报在前
        self.assertIn("通缉犯", msg)
        # @ 在后
        self.assertIn("[CQ:at,qq=QQ1]", msg)
        self.assertIn("[CQ:at,qq=QQ2]", msg)
        # @ 应该在通报之后
        msg_lines = msg.split("\n")
        at_line_idx = next(i for i, line in enumerate(msg_lines) if "[CQ:at" in line)
        wanted_line_idx = next(
            i for i, line in enumerate(msg_lines) if "通缉犯" in line
        )
        self.assertLess(wanted_line_idx, at_line_idx, "通报应在 @ 之前")

    def test_multiple_personal_wanted_only(self):
        """仅个人通缉（多人）：每人一条消息，@ 在前。"""
        wanted_mgr = make_wanted_mgr(
            ("personal", "QQ1", "1012345678901", "10001"),
            ("personal", "QQ2", "1012345678902", "10001"),
        )
        ranks = {
            "1012345678901": (80, 50),
            "1012345678902": (90, 60),
        }
        user_infos = {
            "1012345678901": {
                "user_name": "テスト1",
                "user_dname": "テスト1",
                "last_login_time": 0,
            },
            "1012345678902": {
                "user_name": "テスト2",
                "user_dname": "テスト2",
                "last_login_time": 0,
            },
        }
        cache = make_cache(ranks=ranks, user_infos=user_infos)
        profiles = {
            "1012345678901": make_profile(
                "1012345678901", name="テスト1", arena_rank=100, grand_arena_rank=50
            ),
            "1012345678902": make_profile(
                "1012345678902", name="テスト2", arena_rank=110, grand_arena_rank=70
            ),
        }

        bot = self._run_check_wanted(wanted_mgr, cache, profiles)
        self.assertEqual(bot.send_group_msg.call_count, 2)
        # 检查每条消息都有 @
        for call in bot.send_group_msg.call_args_list:
            msg = call[1]["message"]
            self.assertIn("[CQ:at,qq=", msg)

    def test_watch_at_bitmask_jjc_only(self):
        """arena_on=True, grand_arena_on=False（仅 jjc）：只通报 jjc 变化。"""
        wanted_mgr = make_wanted_mgr(
            (
                "group",
                "10001",
                "1012345678901",
                {"arena_on": True, "grand_arena_on": False},
            )
        )
        ranks = {"1012345678901": (80, 30)}
        user_infos = {
            "1012345678901": {
                "user_name": "テスト",
                "user_dname": "テスト",
                "last_login_time": 0,
            }
        }
        cache = make_cache(ranks=ranks, user_infos=user_infos)
        profiles = {
            "1012345678901": make_profile(
                "1012345678901", name="テスト", arena_rank=100, grand_arena_rank=50
            )
        }

        bot = self._run_check_wanted(wanted_mgr, cache, profiles)
        bot.send_group_msg.assert_called_once()
        msg = bot.send_group_msg.call_args[1]["message"]
        self.assertIn("jjc", msg)
        self.assertNotIn("pjjc", msg)

    def test_watch_at_bitmask_pjjc_only(self):
        """arena_on=False, grand_arena_on=True（仅 pjjc）：只通报 pjjc 变化。"""
        wanted_mgr = make_wanted_mgr(
            (
                "group",
                "10001",
                "1012345678901",
                {"arena_on": False, "grand_arena_on": True},
            )
        )
        ranks = {"1012345678901": (80, 30)}
        user_infos = {
            "1012345678901": {
                "user_name": "テスト",
                "user_dname": "テスト",
                "last_login_time": 0,
            }
        }
        cache = make_cache(ranks=ranks, user_infos=user_infos)
        profiles = {
            "1012345678901": make_profile(
                "1012345678901", name="テスト", arena_rank=100, grand_arena_rank=50
            )
        }

        bot = self._run_check_wanted(wanted_mgr, cache, profiles)
        bot.send_group_msg.assert_called_once()
        msg = bot.send_group_msg.call_args[1]["message"]
        lines = msg.splitlines()
        self.assertFalse(any(l.startswith("jjc：") for l in lines), "不应有 jjc 通知行")  # noqa: E741
        self.assertTrue(any("pjjc" in l for l in lines), "应有 pjjc 通知行")  # noqa: E741

    def test_arena_on_false_suppresses_jjc(self):
        """arena_on=False 时不通报 jjc 变化。"""
        wanted_mgr = make_wanted_mgr(
            ("group", "10001", "1012345678901", {"arena_on": False})
        )
        ranks = {"1012345678901": (80, 30)}
        user_infos = {
            "1012345678901": {
                "user_name": "テスト",
                "user_dname": "テスト",
                "last_login_time": 0,
            }
        }
        cache = make_cache(ranks=ranks, user_infos=user_infos)
        profiles = {
            "1012345678901": make_profile(
                "1012345678901", name="テスト", arena_rank=100, grand_arena_rank=50
            )
        }

        bot = self._run_check_wanted(wanted_mgr, cache, profiles)
        bot.send_group_msg.assert_called_once()
        msg = bot.send_group_msg.call_args[1]["message"]
        lines = msg.splitlines()
        self.assertFalse(any(l.startswith("jjc：") for l in lines), "不应有 jjc 通知行")  # noqa: E741
        self.assertTrue(any("pjjc" in l for l in lines), "应有 pjjc 通知行")  # noqa: E741

    def test_no_notification_when_no_change(self):
        """排名不变时不发通知。"""
        wanted_mgr = make_wanted_mgr(("group", "10001", "1012345678901"))
        ranks = {"1012345678901": (100, 50)}
        user_infos = {
            "1012345678901": {
                "user_name": "テスト",
                "user_dname": "テスト",
                "last_login_time": 0,
            }
        }
        cache = make_cache(ranks=ranks, user_infos=user_infos)
        profiles = {
            "1012345678901": make_profile(
                "1012345678901", name="テスト", arena_rank=100, grand_arena_rank=50
            )
        }

        bot = self._run_check_wanted(wanted_mgr, cache, profiles)
        bot.send_group_msg.assert_not_called()

    def test_round_cache_deduplication(self):
        """同一 uid 被多人通缉时，只查询一次 API。"""
        wanted_mgr = make_wanted_mgr(
            ("group", "10001", "1012345678901"),
            ("personal", "QQ1", "1012345678901", "10001"),
            ("personal", "QQ2", "1012345678901", "10001"),
        )
        ranks = {"1012345678901": (80, 50)}
        user_infos = {
            "1012345678901": {
                "user_name": "テスト",
                "user_dname": "テスト",
                "last_login_time": 0,
            }
        }
        cache = make_cache(ranks=ranks, user_infos=user_infos)
        profiles = {
            "1012345678901": make_profile(
                "1012345678901", name="テスト", arena_rank=100, grand_arena_rank=50
            )
        }

        call_count = 0

        async def counting_get_profile(uid):
            nonlocal call_count
            call_count += 1
            result = profiles.get(uid)
            if result is None:
                from ..arena_client import ApiException

                raise ApiException("not found", 6)
            return result

        mock_bot = MagicMock()
        mock_bot.send_group_msg = AsyncMock()
        mock_logger = MagicMock()

        # fmt: off
        with patch(
                "hoshino.modules.pcrjjc2.rank_monitor.get_profile",
                side_effect=counting_get_profile,
            ):
        # fmt: on
            svc = make_svc(wanted_mgr=wanted_mgr, cache=cache, bot=mock_bot, logger=mock_logger)
            from .. import rank_monitor

            ctx = rank_monitor.CheckContext(
                bot=mock_bot,
                logger=mock_logger,
                cache=cache,
                config=svc._config,
                now=mkt(10, 0),
            )
            run(svc.check_wanted(ctx, delay=0))

        # 应该只调用一次 get_profile
        self.assertEqual(call_count, 1, "同一 uid 应该只查询一次 API")


class TestCheckContextShouldCheck(unittest.TestCase):
    """CheckContext.should_check_subscription 各时段逻辑。

    订阅侧 check_config（_DEFAULT_SUB_CHECK_CONFIGS）：
      - settlement: interval=0  → 仅 15:00 触发，delay=0
      - default:    interval=1  → 每分钟都触发，delay=15
      hot/critical/cold 未在订阅 cc_map 中配置，均回退到 default(interval=1)。
    """

    def _make_ctx(self, now):
        """创建 CheckContext 用于测试 should_check_subscription"""
        from .. import rank_monitor

        mock_bot = MagicMock()
        mock_logger = MagicMock()
        cache = make_cache()
        svc = make_svc(bot=mock_bot, cache=cache, logger=mock_logger)

        return rank_monitor.CheckContext(
            bot=mock_bot,
            logger=mock_logger,
            cache=cache,
            config=svc._config,
            now=now,
        )

    @patch("hoshino.modules.pcrjjc2.rank_monitor.asyncio.sleep", new_callable=AsyncMock)
    def test_settlement_at_1500(self, _sleep):
        # 15:00 命中 settlement(interval=0) → 触发
        ctx = self._make_ctx(mkt(15, 0))
        self.assertTrue(run(ctx.should_check_subscription()))

    @patch("hoshino.modules.pcrjjc2.rank_monitor.asyncio.sleep", new_callable=AsyncMock)
    def test_settlement_not_at_1501(self, _sleep):
        # 15:01 不匹配 settlement cron，回退到 default(interval=1) → 每分钟触发
        ctx = self._make_ctx(mkt(15, 1))
        self.assertTrue(run(ctx.should_check_subscription()))

    @patch("hoshino.modules.pcrjjc2.rank_monitor.asyncio.sleep", new_callable=AsyncMock)
    def test_critical_falls_back_to_default_interval1(self, _sleep):
        # critical 在订阅 cc_map 中未配置，回退到 default(interval=1) → 每分钟触发
        ctx1 = self._make_ctx(mkt(14, 59))
        self.assertTrue(run(ctx1.should_check_subscription()))
        ctx2 = self._make_ctx(mkt(14, 55))
        self.assertTrue(run(ctx2.should_check_subscription()))

    @patch("hoshino.modules.pcrjjc2.rank_monitor.asyncio.sleep", new_callable=AsyncMock)
    def test_hot_falls_back_to_default_interval1(self, _sleep):
        # hot 在订阅 cc_map 中未配置，回退到 default(interval=1) → 每分钟触发（含奇数分钟）
        ctx1 = self._make_ctx(mkt(14, 0))
        self.assertTrue(run(ctx1.should_check_subscription()))
        ctx2 = self._make_ctx(mkt(14, 1))
        self.assertTrue(run(ctx2.should_check_subscription()))
        ctx3 = self._make_ctx(mkt(14, 3))
        self.assertTrue(run(ctx3.should_check_subscription()))

    @patch("hoshino.modules.pcrjjc2.rank_monitor.asyncio.sleep", new_callable=AsyncMock)
    def test_default_interval1_triggers_every_minute(self, _sleep):
        # default: interval=1 → 任意分钟都触发
        ctx1 = self._make_ctx(mkt(10, 0))
        self.assertTrue(run(ctx1.should_check_subscription()))
        ctx2 = self._make_ctx(mkt(10, 3))
        self.assertTrue(run(ctx2.should_check_subscription()))
        ctx3 = self._make_ctx(mkt(10, 7))
        self.assertTrue(run(ctx3.should_check_subscription()))

    @patch("hoshino.modules.pcrjjc2.rank_monitor.asyncio.sleep", new_callable=AsyncMock)
    def test_delay_called_when_triggering(self, mock_sleep):
        # default(interval=1, delay=15) 触发时应调用 sleep
        ctx = self._make_ctx(mkt(10, 0))
        run(ctx.should_check_subscription())
        mock_sleep.assert_called_once()

    @patch("hoshino.modules.pcrjjc2.rank_monitor.asyncio.sleep", new_callable=AsyncMock)
    def test_no_delay_at_settlement(self, mock_sleep):
        # settlement(interval=0, delay=0) 触发时 delay=0，不应调用 sleep
        ctx = self._make_ctx(mkt(15, 0))
        run(ctx.should_check_subscription())
        mock_sleep.assert_not_called()


class TestDelayBehavior(unittest.TestCase):
    """测试延迟功能"""

    @patch("hoshino.modules.pcrjjc2.rank_monitor.asyncio.sleep", new_callable=AsyncMock)
    def test_subscription_check_with_delay(self, mock_sleep):
        """订阅检测：使用 delay=1 秒，验证延迟被调用"""
        sub_mgr = make_sub_mgr(("QQ1", "1012345678901", "10001"))
        cache = make_cache(ranks={"1012345678901": (100, 50)})
        profiles = {"1012345678901": make_profile("1012345678901", arena_rank=110)}

        mock_bot = MagicMock()
        mock_bot.send_group_msg = AsyncMock()

        async def mock_get_profile(uid):
            return profiles[uid]

        with patch(
            "hoshino.modules.pcrjjc2.rank_monitor.get_profile",
            side_effect=mock_get_profile,
        ):
            from ..rank_monitor import CheckContext

            svc = make_svc(sub_mgr=sub_mgr, cache=cache, bot=mock_bot)
            ctx = CheckContext(
                bot=mock_bot,
                logger=svc._logger,
                cache=cache,
                config=svc._config,
            )
            run(svc.check_arena_subscriptions(ctx, delay=1))

        # 验证 sleep 被调用
        mock_sleep.assert_called()
        # 验证延迟时间在合理范围内（0-1秒）
        call_args = mock_sleep.call_args[0][0]
        self.assertGreaterEqual(call_args, 0)
        self.assertLessEqual(call_args, 1)

    @patch("hoshino.modules.pcrjjc2.rank_monitor.asyncio.sleep", new_callable=AsyncMock)
    def test_wanted_check_with_high_delay(self, mock_sleep):
        """通缉检测：使用 delay=5 秒（模拟高延迟），验证延迟被调用"""
        wanted_mgr = make_wanted_mgr(("group", "10001", "1012345678901"))
        cache = make_cache(ranks={"1012345678901": (100, 50)})
        profiles = {"1012345678901": make_profile("1012345678901", arena_rank=110)}

        mock_bot = MagicMock()
        mock_bot.send_group_msg = AsyncMock()
        mock_logger = MagicMock()

        async def mock_get_profile(uid):
            return profiles[uid]

        with patch(
            "hoshino.modules.pcrjjc2.rank_monitor.get_profile",
            side_effect=mock_get_profile,
        ):
            svc = make_svc(
                wanted_mgr=wanted_mgr, cache=cache, bot=mock_bot, logger=mock_logger
            )
            from .. import rank_monitor

            ctx = rank_monitor.CheckContext(
                bot=mock_bot,
                logger=mock_logger,
                cache=cache,
                config=svc._config,
                now=mkt(10, 0),
            )
            run(svc.check_wanted(ctx, delay=5))

        # 验证 sleep 被调用
        mock_sleep.assert_called()
        # 验证延迟时间在合理范围内（0-5秒）
        call_args = mock_sleep.call_args[0][0]
        self.assertGreaterEqual(call_args, 0)
        self.assertLessEqual(call_args, 5)

    @patch("hoshino.modules.pcrjjc2.rank_monitor.asyncio.sleep", new_callable=AsyncMock)
    def test_multiple_subscriptions_with_delay(self, mock_sleep):
        """多个订阅检测：使用 delay=0.1 秒，验证每个检测都有延迟"""
        sub_mgr = make_sub_mgr(
            ("QQ1", "1012345678901", "10001"),
            ("QQ1", "1012345678902", "10001"),
            ("QQ1", "1012345678903", "10001"),
        )
        cache = make_cache(
            ranks={
                "1012345678901": (100, 50),
                "1012345678902": (200, 60),
                "1012345678903": (300, 70),
            }
        )
        profiles = {
            "1012345678901": make_profile("1012345678901", arena_rank=110),
            "1012345678902": make_profile("1012345678902", arena_rank=210),
            "1012345678903": make_profile("1012345678903", arena_rank=310),
        }

        mock_bot = MagicMock()
        mock_bot.send_group_msg = AsyncMock()

        async def mock_get_profile(uid):
            return profiles[uid]

        with patch(
            "hoshino.modules.pcrjjc2.rank_monitor.get_profile",
            side_effect=mock_get_profile,
        ):
            from ..rank_monitor import CheckContext

            svc = make_svc(sub_mgr=sub_mgr, cache=cache, bot=mock_bot)
            ctx = CheckContext(
                bot=mock_bot,
                logger=svc._logger,
                cache=cache,
                config=svc._config,
            )
            run(svc.check_arena_subscriptions(ctx, delay=0.1))

        # 验证 sleep 被调用（至少一次）
        mock_sleep.assert_called()
        # 验证延迟时间在合理范围内（0-0.1秒）
        for call in mock_sleep.call_args_list:
            delay_val = call[0][0]
            self.assertGreaterEqual(delay_val, 0)
            self.assertLessEqual(delay_val, 0.1)


class TestRaceCondition(unittest.TestCase):
    """测试并发场景下的 race-condition 处理"""

    def test_subscription_then_wanted_no_duplicate_api_call(self):
        """订阅检测先执行，通缉检测后执行，同一 uid 不重复请求 API（delay=0）"""
        # 准备数据：同一个 uid 既有订阅又有通缉
        uid = "1012345678901"
        sub_mgr = make_sub_mgr(("QQ1", uid, "10001"))
        wanted_mgr = make_wanted_mgr(("group", "10001", uid))
        cache = make_cache(ranks={uid: (100, 50)})
        profile = make_profile(uid, arena_rank=110)

        call_count = 0

        async def mock_get_profile(u):
            nonlocal call_count
            call_count += 1
            return profile

        mock_bot = MagicMock()
        mock_bot.send_group_msg = AsyncMock()
        mock_logger = MagicMock()

        with patch(
            "hoshino.modules.pcrjjc2.rank_monitor.get_profile",
            side_effect=mock_get_profile,
        ):
            svc = make_svc(
                sub_mgr=sub_mgr,
                wanted_mgr=wanted_mgr,
                cache=cache,
                bot=mock_bot,
                logger=mock_logger,
            )
            from .. import rank_monitor

            ctx = rank_monitor.CheckContext(
                bot=mock_bot,
                logger=mock_logger,
                cache=cache,
                config=svc._config,
                now=mkt(10, 0),
            )

            # 先执行订阅检测
            run(svc.check_arena_subscriptions(ctx, delay=0))
            # 再执行通缉检测（使用同一个 ctx，会命中 round_cache）
            run(svc.check_wanted(ctx, delay=0))

        # 验证：API 只被调用了 1 次（第二次命中 CheckContext 的 round_cache）
        self.assertEqual(call_count, 1)

    def test_wanted_then_subscription_no_duplicate_api_call(self):
        """通缉检测先执行，订阅检测后执行，同一 uid 不重复请求 API（delay=0）"""
        uid = "1012345678901"
        sub_mgr = make_sub_mgr(("QQ1", uid, "10001"))
        wanted_mgr = make_wanted_mgr(("group", "10001", uid))
        cache = make_cache(ranks={uid: (100, 50)})
        profile = make_profile(uid, arena_rank=110)

        call_count = 0

        async def mock_get_profile(u):
            nonlocal call_count
            call_count += 1
            return profile

        mock_bot = MagicMock()
        mock_bot.send_group_msg = AsyncMock()
        mock_logger = MagicMock()

        with patch(
            "hoshino.modules.pcrjjc2.rank_monitor.get_profile",
            side_effect=mock_get_profile,
        ):
            svc = make_svc(
                sub_mgr=sub_mgr,
                wanted_mgr=wanted_mgr,
                cache=cache,
                bot=mock_bot,
                logger=mock_logger,
            )
            from .. import rank_monitor

            ctx = rank_monitor.CheckContext(
                bot=mock_bot,
                logger=mock_logger,
                cache=cache,
                config=svc._config,
                now=mkt(10, 0),
            )

            # 先执行通缉检测
            run(svc.check_wanted(ctx, delay=0))
            # 再执行订阅检测（使用同一个 ctx，会命中 round_cache）
            run(svc.check_arena_subscriptions(ctx, delay=0))

        # 验证：API 只被调用了 1 次（第二次命中 CheckContext 的 round_cache）
        self.assertEqual(call_count, 1)

    def test_concurrent_check_with_overlapping_uids(self):
        """订阅和通缉并发执行，多个重叠 uid，验证 round_cache 去重（delay=0）"""
        # 准备数据：3个 uid，都既有订阅又有通缉
        uids = ["1012345678901", "1012345678902", "1012345678903"]
        sub_mgr = make_sub_mgr(
            ("QQ1", uids[0], "10001"),
            ("QQ1", uids[1], "10001"),
            ("QQ2", uids[2], "10001"),
        )
        wanted_mgr = make_wanted_mgr(
            ("group", "10001", uids[0]),
            ("group", "10001", uids[1]),
            ("personal", "QQ2", uids[2], "10001"),
        )
        cache = make_cache(
            ranks={
                uids[0]: (100, 50),
                uids[1]: (200, 60),
                uids[2]: (300, 70),
            }
        )
        profiles = {
            uids[0]: make_profile(uids[0], arena_rank=110),
            uids[1]: make_profile(uids[1], arena_rank=210),
            uids[2]: make_profile(uids[2], arena_rank=310),
        }

        call_counts = {uid: 0 for uid in uids}

        async def mock_get_profile(u):
            call_counts[u] += 1
            return profiles[u]

        mock_bot = MagicMock()
        mock_bot.send_group_msg = AsyncMock()
        mock_logger = MagicMock()

        with patch(
            "hoshino.modules.pcrjjc2.rank_monitor.get_profile",
            side_effect=mock_get_profile,
        ):
            svc = make_svc(
                sub_mgr=sub_mgr,
                wanted_mgr=wanted_mgr,
                cache=cache,
                bot=mock_bot,
                logger=mock_logger,
            )
            from .. import rank_monitor

            ctx = rank_monitor.CheckContext(
                bot=mock_bot,
                logger=mock_logger,
                cache=cache,
                config=svc._config,
                now=mkt(10, 0),
            )

            # 并发执行订阅和通缉检测
            async def concurrent_check():
                await asyncio.gather(
                    svc.check_arena_subscriptions(ctx, delay=0),
                    svc.check_wanted(ctx, delay=0),
                )

            run(concurrent_check())

        # 验证：每个 uid 的 API 调用次数
        # 由于是并发执行，round_cache 可能无法完全去重（取决于执行顺序）
        # 但每个 uid 最多被调用 2 次（订阅和通缉各一次）
        for uid in uids:
            self.assertLessEqual(
                call_counts[uid],
                2,
                f"uid {uid} 被调用了 {call_counts[uid]} 次，超过预期的最多 2 次",
            )


class TestGetWantedSummaryRows(unittest.TestCase):
    """get_wanted_summary_rows：通缉犯概要数据行生成测试。"""

    def test_empty_wanted_list(self):
        """无通缉时返回空列表。"""
        wanted_mgr = make_wanted_mgr()
        sub_mgr = make_sub_mgr()
        cache = make_cache()
        svc = make_svc(wanted_mgr=wanted_mgr, sub_mgr=sub_mgr, cache=cache)

        group_rows, personal_rows = svc.get_wanted_summary_rows("QQ1", "10001")
        self.assertEqual(len(group_rows), 0)
        self.assertEqual(len(personal_rows), 0)

    def test_group_wanted_only(self):
        """仅群通缉：返回群通缉行。"""
        wanted_mgr = make_wanted_mgr(
            ("group", "10001", "1012345678901", {"note": "坏人"}),
            ("group", "10001", "1012345678902"),
        )
        sub_mgr = make_sub_mgr()
        user_infos = {
            "1012345678901": {
                "user_name": "テスト1",
                "arena_group": 5,
                "arena_rank": 100,
                "grand_arena_group": 1,
                "grand_arena_rank": 50,
                "last_login_time": 1710000000,
            },
            "1012345678902": {
                "user_name": "テスト2",
                "arena_group": 3,
                "arena_rank": 200,
                "grand_arena_group": 2,
                "grand_arena_rank": 80,
                "last_login_time": 1710000000,
            },
        }
        cache = make_cache(user_infos=user_infos)
        svc = make_svc(wanted_mgr=wanted_mgr, sub_mgr=sub_mgr, cache=cache)

        group_rows, personal_rows = svc.get_wanted_summary_rows("QQ1", "10001")
        self.assertEqual(len(group_rows), 2)
        self.assertEqual(len(personal_rows), 0)

        # 检查第一行数据
        row1 = group_rows[0]
        self.assertEqual(row1.index, 1)
        self.assertEqual(row1.uid, "1012345678901")
        self.assertEqual(row1.user_name, "テスト1")
        self.assertEqual(row1.note, "坏人")
        self.assertEqual(row1.arena_group, 5)
        self.assertEqual(row1.arena_rank, 100)
        self.assertEqual(row1.arena_str, "5场 100名")
        self.assertEqual(row1.grand_arena_str, "1场 50名")

    def test_personal_wanted_only(self):
        """仅个人通缉：返回个人通缉行。"""
        wanted_mgr = make_wanted_mgr(
            ("personal", "QQ1", "1012345678901", "10001", {"note": "仇人"}),
            ("personal", "QQ1", "1012345678902", "10001"),
        )
        sub_mgr = make_sub_mgr()
        user_infos = {
            "1012345678901": {
                "user_name": "テスト1",
                "arena_group": 5,
                "arena_rank": 100,
                "grand_arena_group": 1,
                "grand_arena_rank": 50,
                "last_login_time": 1710000000,
            },
            "1012345678902": {
                "user_name": "テスト2",
                "arena_group": 3,
                "arena_rank": 200,
                "grand_arena_group": 2,
                "grand_arena_rank": 80,
                "last_login_time": 1710000000,
            },
        }
        cache = make_cache(user_infos=user_infos)
        svc = make_svc(wanted_mgr=wanted_mgr, sub_mgr=sub_mgr, cache=cache)

        group_rows, personal_rows = svc.get_wanted_summary_rows("QQ1", "10001")
        self.assertEqual(len(group_rows), 0)
        self.assertEqual(len(personal_rows), 2)

        # 检查第一行数据
        row1 = personal_rows[0]
        self.assertEqual(row1.index, 1)
        self.assertEqual(row1.uid, "1012345678901")
        self.assertEqual(row1.user_name, "テスト1")
        self.assertEqual(row1.note, "仇人")

    def test_both_group_and_personal_wanted(self):
        """群+个人通缉：分别返回。"""
        wanted_mgr = make_wanted_mgr(
            ("group", "10001", "1012345678901"),
            ("personal", "QQ1", "1012345678902", "10001"),
        )
        sub_mgr = make_sub_mgr()
        user_infos = {
            "1012345678901": {
                "user_name": "テスト1",
                "arena_group": 5,
                "arena_rank": 100,
                "grand_arena_group": 1,
                "grand_arena_rank": 50,
                "last_login_time": 1710000000,
            },
            "1012345678902": {
                "user_name": "テスト2",
                "arena_group": 3,
                "arena_rank": 200,
                "grand_arena_group": 2,
                "grand_arena_rank": 80,
                "last_login_time": 1710000000,
            },
        }
        cache = make_cache(user_infos=user_infos)
        svc = make_svc(wanted_mgr=wanted_mgr, sub_mgr=sub_mgr, cache=cache)

        group_rows, personal_rows = svc.get_wanted_summary_rows("QQ1", "10001")
        self.assertEqual(len(group_rows), 1)
        self.assertEqual(len(personal_rows), 1)
        self.assertEqual(group_rows[0].uid, "1012345678901")
        self.assertEqual(personal_rows[0].uid, "1012345678902")

    def test_same_arena_group_highlighting(self):
        """同场高亮：same_arena_group 标记正确。"""
        wanted_mgr = make_wanted_mgr(
            ("group", "10001", "1012345678901"),  # 5场
            ("group", "10001", "1012345678902"),  # 3场
        )
        # QQ1 订阅了一个 5场 的 uid
        sub_mgr = make_sub_mgr(("QQ1", "1012345678903", "10001"))
        user_infos = {
            "1012345678901": {
                "user_name": "テスト1",
                "arena_group": 5,
                "arena_rank": 100,
                "grand_arena_group": 1,
                "grand_arena_rank": 50,
                "last_login_time": 1710000000,
            },
            "1012345678902": {
                "user_name": "テスト2",
                "arena_group": 3,
                "arena_rank": 200,
                "grand_arena_group": 2,
                "grand_arena_rank": 80,
                "last_login_time": 1710000000,
            },
            "1012345678903": {
                "arena_group": 5,
                "grand_arena_group": 1,
            },
        }
        cache = make_cache(user_infos=user_infos)
        svc = make_svc(wanted_mgr=wanted_mgr, sub_mgr=sub_mgr, cache=cache)

        group_rows, _ = svc.get_wanted_summary_rows("QQ1", "10001")
        self.assertEqual(len(group_rows), 2)
        # 第一个通缉犯（5场）与订阅同场
        self.assertTrue(group_rows[0].same_arena_group)
        # 第二个通缉犯（3场）与订阅不同场
        self.assertFalse(group_rows[1].same_arena_group)

    def test_filter_type_group_only(self):
        """filter_type='group'：只返回群通缉。"""
        wanted_mgr = make_wanted_mgr(
            ("group", "10001", "1012345678901"),
            ("personal", "QQ1", "1012345678902", "10001"),
        )
        sub_mgr = make_sub_mgr()
        user_infos = {
            "1012345678901": {
                "user_name": "テスト1",
                "arena_group": 5,
                "arena_rank": 100,
                "grand_arena_group": 1,
                "grand_arena_rank": 50,
                "last_login_time": 1710000000,
            },
            "1012345678902": {
                "user_name": "テスト2",
                "arena_group": 3,
                "arena_rank": 200,
                "grand_arena_group": 2,
                "grand_arena_rank": 80,
                "last_login_time": 1710000000,
            },
        }
        cache = make_cache(user_infos=user_infos)
        svc = make_svc(wanted_mgr=wanted_mgr, sub_mgr=sub_mgr, cache=cache)

        group_rows, personal_rows = svc.get_wanted_summary_rows(
            "QQ1", "10001", filter_type="group"
        )
        self.assertEqual(len(group_rows), 1)
        self.assertEqual(len(personal_rows), 0)

    def test_filter_type_personal_only(self):
        """filter_type='personal'：只返回个人通缉。"""
        wanted_mgr = make_wanted_mgr(
            ("group", "10001", "1012345678901"),
            ("personal", "QQ1", "1012345678902", "10001"),
        )
        sub_mgr = make_sub_mgr()
        user_infos = {
            "1012345678901": {
                "user_name": "テスト1",
                "arena_group": 5,
                "arena_rank": 100,
                "grand_arena_group": 1,
                "grand_arena_rank": 50,
                "last_login_time": 1710000000,
            },
            "1012345678902": {
                "user_name": "テスト2",
                "arena_group": 3,
                "arena_rank": 200,
                "grand_arena_group": 2,
                "grand_arena_rank": 80,
                "last_login_time": 1710000000,
            },
        }
        cache = make_cache(user_infos=user_infos)
        svc = make_svc(wanted_mgr=wanted_mgr, sub_mgr=sub_mgr, cache=cache)

        group_rows, personal_rows = svc.get_wanted_summary_rows(
            "QQ1", "10001", filter_type="personal"
        )
        self.assertEqual(len(group_rows), 0)
        self.assertEqual(len(personal_rows), 1)

    def test_missing_user_info_fallback(self):
        """缓存中无用户信息时，使用 uid 作为 user_name。"""
        wanted_mgr = make_wanted_mgr(("group", "10001", "1012345678901"))
        sub_mgr = make_sub_mgr()
        cache = make_cache()  # 空缓存
        svc = make_svc(wanted_mgr=wanted_mgr, sub_mgr=sub_mgr, cache=cache)

        group_rows, _ = svc.get_wanted_summary_rows("QQ1", "10001")
        self.assertEqual(len(group_rows), 1)
        # 无缓存时，user_name 应该是 uid
        self.assertEqual(group_rows[0].user_name, "1012345678901")
        self.assertEqual(group_rows[0].arena_group, 0)
        self.assertEqual(group_rows[0].arena_rank, 0)


class TestWantedSummaryFormatter(unittest.TestCase):
    """通缉概要格式化器测试。"""

    def setUp(self):
        from ..table_image import StyledText
        from ..wanted_summary_formatter import WantedSummaryFormatter

        self.formatter = WantedSummaryFormatter(now_hour=10)
        self.StyledText = StyledText

    def _make_row(self, **kwargs):
        from ..wanted_summary_formatter import WantedSummaryRow

        defaults = dict(
            index=1,
            uid="1012345678901",
            user_name="テスト",
            avatar_unit_name=None,
            clan_name=None,
            arena_group=5,
            arena_rank=100,
            arena_challenges=3,
            arena_on=True,
            arena_mining=False,
            grand_arena_group=1,
            grand_arena_rank=50,
            grand_arena_challenges=2,
            grand_arena_on=True,
            grand_arena_mining=False,
            last_login_time=1710000000,
            note="",
            notice_level=1,
            same_arena_group=False,
            same_grand_arena_group=False,
            arena_str="5场 100名",
            grand_arena_str="1场 50名",
        )
        defaults.update(kwargs)
        return WantedSummaryRow(**defaults)

    def test_normal_name_cell(self):
        """普通昵称直接显示字符串。"""
        row = self._make_row(user_name="テスト")
        cells = self.formatter.format_row(row)
        self.assertEqual(cells[1].content, "テスト")  # 第1列是昵称（第0列是编号）

    def test_yuki_with_clan_only(self):
        """佑树 + 公会名：上标为公会名，无下标。"""
        row = self._make_row(
            user_name="佑树", clan_name="骑士团", avatar_unit_name=None
        )
        cells = self.formatter.format_row(row)
        content = cells[1].content  # 第1列是昵称
        self.assertIsInstance(content, self.StyledText)
        self.assertEqual(content.text, "佑树")
        self.assertIsNotNone(content.sup)
        self.assertIn("骑士团", content.sup.text)
        self.assertIsNone(content.sub)

    def test_yuki_with_avatar_only(self):
        """佑树 + 头像：下标为头像名，无上标。"""
        row = self._make_row(user_name="佑树", clan_name=None, avatar_unit_name="春田")
        cells = self.formatter.format_row(row)
        content = cells[1].content  # 第1列是昵称
        self.assertIsInstance(content, self.StyledText)
        self.assertEqual(content.text, "佑树")
        self.assertIsNone(content.sup)
        self.assertIsNotNone(content.sub)
        self.assertIn("春田", content.sub.text)

    def test_yuki_with_clan_and_avatar(self):
        """佑树 + 公会名 + 头像：上标为公会名（灰色），下标为头像（灰色）。"""
        from ..wanted_summary_formatter import _COLOR_DARK_GRAY

        row = self._make_row(
            user_name="佑树", clan_name="骑士团", avatar_unit_name="春田"
        )
        cells = self.formatter.format_row(row)
        content = cells[1].content  # 第1列是昵称
        self.assertIsInstance(content, self.StyledText)
        self.assertEqual(content.text, "佑树")
        # 上标：公会名，灰色
        self.assertIsNotNone(content.sup)
        self.assertIn("骑士团", content.sup.text)
        self.assertEqual(content.sup.text_color, _COLOR_DARK_GRAY)
        # 下标：头像，灰色
        self.assertIsNotNone(content.sub)
        self.assertIn("春田", content.sub.text)
        self.assertEqual(content.sub.text_color, _COLOR_DARK_GRAY)

    def test_yuki_no_extra_info(self):
        """佑树但无公会名和头像：直接显示字符串。"""
        row = self._make_row(user_name="佑树", clan_name=None, avatar_unit_name=None)
        cells = self.formatter.format_row(row)
        self.assertEqual(cells[1].content, "佑树")

    def test_yuki_render_to_image(self):
        """佑树上下标能正常渲染为图片（不抛异常）。"""
        from ..wanted_summary_formatter import render_wanted_summary_as_cq

        row = self._make_row(
            user_name="佑树", clan_name="骑士团", avatar_unit_name="春田"
        )
        result = render_wanted_summary_as_cq([row], [], now_hour=10)
        self.assertTrue(result.startswith("[CQ:image,file=base64://"))


class TestWantedCommandRegex(unittest.TestCase):
    """测试群通缉命令的正则表达式"""

    def test_group_wanted_add(self):
        """测试：群通缉[jjc|pjjc] uid [备注]"""
        pattern = re.compile(r"^群?通缉(jjc|pjjc)?\s+(\d{13})(?:\s+(.+))?$")

        # 基本通缉
        m = pattern.match("通缉 1234567890123")
        self.assertIsNotNone(m)
        self.assertIsNone(m.group(1))  # arena_type
        self.assertEqual(m.group(2), "1234567890123")  # uid
        self.assertIsNone(m.group(3))  # note

        # 群通缉
        m = pattern.match("群通缉 1234567890123")
        self.assertIsNotNone(m)
        self.assertIsNone(m.group(1))

        # 通缉 jjc
        m = pattern.match("通缉jjc 1234567890123")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "jjc")
        self.assertEqual(m.group(2), "1234567890123")

        # 通缉 pjjc 带备注
        m = pattern.match("群通缉pjjc 1234567890123 这是坏人")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "pjjc")
        self.assertEqual(m.group(2), "1234567890123")
        self.assertEqual(m.group(3), "这是坏人")

        # 带空格的备注
        m = pattern.match("通缉 1234567890123 备注 有 空格")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(3), "备注 有 空格")

        # 不匹配：uid 不是 13 位
        m = pattern.match("通缉 123456")
        self.assertIsNone(m)

    def test_group_wanted_note(self):
        """测试：群[设置|取消|清空]备注 uid|idx [备注]"""
        pattern = re.compile(r"^群?(设置|取消|清空)?备注\s+(\d+)(?:\s+(.+))?$")

        # 设置备注（uid）
        m = pattern.match("设置备注 1234567890123 新备注")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "设置")
        self.assertEqual(m.group(2), "1234567890123")
        self.assertEqual(m.group(3), "新备注")

        # 备注（默认设置）
        m = pattern.match("备注 1234567890123 新备注")
        self.assertIsNotNone(m)
        self.assertIsNone(m.group(1))  # 默认为"设置"
        self.assertEqual(m.group(2), "1234567890123")
        self.assertEqual(m.group(3), "新备注")

        # 群备注（索引）
        m = pattern.match("群备注 5 备注内容")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(2), "5")
        self.assertEqual(m.group(3), "备注内容")

        # 取消备注
        m = pattern.match("取消备注 1234567890123")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "取消")
        self.assertEqual(m.group(2), "1234567890123")
        self.assertIsNone(m.group(3))

        # 清空备注
        m = pattern.match("群清空备注 10")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "清空")
        self.assertEqual(m.group(2), "10")

    def test_group_wanted_level(self):
        """测试：群[设置|修改|更改]通缉级别 uid|idx level"""
        pattern = re.compile(r"^群?(设置|修改|更改)?通缉级别\s+(\d+)\s+(\d)$")

        # 设置通缉级别
        m = pattern.match("设置通缉级别 1234567890123 3")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "设置")
        self.assertEqual(m.group(2), "1234567890123")
        self.assertEqual(m.group(3), "3")

        # 群修改通缉级别（索引）
        m = pattern.match("群修改通缉级别 5 2")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "修改")
        self.assertEqual(m.group(2), "5")
        self.assertEqual(m.group(3), "2")

        # 更改通缉级别
        m = pattern.match("更改通缉级别 1234567890123 0")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "更改")

        # 不匹配：级别不是单个数字
        m = pattern.match("设置通缉级别 1234567890123 10")
        self.assertIsNone(m)

    def test_group_wanted_ease(self):
        """测试：群缓和通缉犯 uid|idx"""
        pattern = re.compile(r"^群?缓和通缉犯\s+(\d+)$")

        m = pattern.match("缓和通缉犯 1234567890123")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "1234567890123")

        m = pattern.match("群缓和通缉犯 5")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "5")

    def test_group_wanted_attention(self):
        """测试：群注意通缉犯 uid|idx"""
        pattern = re.compile(r"^群?注意通缉犯\s+(\d+)$")

        m = pattern.match("注意通缉犯 1234567890123")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "1234567890123")

        m = pattern.match("群注意通缉犯 10")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "10")

    def test_group_wanted_high(self):
        """测试：群[今日|重点][关照|击剑]通缉犯 uid|idx"""
        pattern = re.compile(r"^群?(今日|重点)?(关照|击剑)通缉犯\s+(\d+)$")

        # 关照通缉犯（level=3）
        m = pattern.match("关照通缉犯 1234567890123")
        self.assertIsNotNone(m)
        self.assertIsNone(m.group(1))  # modifier
        self.assertEqual(m.group(2), "关照")
        self.assertEqual(m.group(3), "1234567890123")

        # 今日关照通缉犯（level=4）
        m = pattern.match("今日关照通缉犯 5")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "今日")
        self.assertEqual(m.group(2), "关照")
        self.assertEqual(m.group(3), "5")

        # 重点击剑通缉犯（level=5）
        m = pattern.match("群重点击剑通缉犯 1234567890123")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "重点")
        self.assertEqual(m.group(2), "击剑")
        self.assertEqual(m.group(3), "1234567890123")

        # 击剑通缉犯（level=3）
        m = pattern.match("击剑通缉犯 10")
        self.assertIsNotNone(m)
        self.assertIsNone(m.group(1))
        self.assertEqual(m.group(2), "击剑")
        self.assertEqual(m.group(3), "10")

    def test_group_wanted_toggle(self):
        """测试：群[开启|关闭|取消]通报[jjc|pjjc] uid|idx"""
        pattern = re.compile(r"^群?(开启|关闭|取消)?通报(jjc|pjjc)\s+(\d+)$")

        # 开启通报jjc
        m = pattern.match("开启通报jjc 1234567890123")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "开启")
        self.assertEqual(m.group(2), "jjc")
        self.assertEqual(m.group(3), "1234567890123")

        # 通报pjjc（默认开启）
        m = pattern.match("通报pjjc 5")
        self.assertIsNotNone(m)
        self.assertIsNone(m.group(1))  # 默认"开启"
        self.assertEqual(m.group(2), "pjjc")
        self.assertEqual(m.group(3), "5")

        # 群关闭通报jjc
        m = pattern.match("群关闭通报jjc 10")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "关闭")
        self.assertEqual(m.group(2), "jjc")

        # 取消通报pjjc
        m = pattern.match("取消通报pjjc 1234567890123")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "取消")
        self.assertEqual(m.group(2), "pjjc")

    def test_group_wanted_arrest(self):
        """测试：群逮捕[jjc|pjjc] uid|idx"""
        pattern = re.compile(r"^群?逮捕(jjc|pjjc)?\s+(\d+)$")

        # 逮捕（删除整个通缉）
        m = pattern.match("逮捕 1234567890123")
        self.assertIsNotNone(m)
        self.assertIsNone(m.group(1))
        self.assertEqual(m.group(2), "1234567890123")

        # 群逮捕jjc（只关闭jjc通报）
        m = pattern.match("群逮捕jjc 5")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "jjc")
        self.assertEqual(m.group(2), "5")

        # 逮捕pjjc（只关闭pjjc通报）
        m = pattern.match("逮捕pjjc 1234567890123")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "pjjc")
        self.assertEqual(m.group(2), "1234567890123")


class TestPersonalWantedCommandRegex(unittest.TestCase):
    """测试个人通缉命令的正则表达式"""

    def test_personal_wanted_add(self):
        """测试：(个人)?标记(jjc|pjjc)? uid (备注)? / mark(-jjc|-pjjc)? uid (备注)?"""
        pattern = re.compile(
            r"^(个人)?标记(jjc|pjjc)?\s+(\d{13})(?:\s+(.+))?$|^mark(-jjc|-pjjc)?\s+(\d{13})(?:\s+(.+))?$"
        )

        # 标记 uid
        m = pattern.match("标记 1234567890123")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(3) or m.group(6), "1234567890123")

        # 个人标记 uid 备注
        m = pattern.match("个人标记 1234567890123 这是坏人")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "个人")
        self.assertEqual(m.group(3), "1234567890123")
        self.assertEqual(m.group(4), "这是坏人")

        # 标记jjc uid
        m = pattern.match("标记jjc 1234567890123")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(2), "jjc")
        self.assertEqual(m.group(3), "1234567890123")

        # mark-pjjc uid 备注
        m = pattern.match("mark-pjjc 1234567890123 bad guy")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(5), "-pjjc")
        self.assertEqual(m.group(6), "1234567890123")
        self.assertEqual(m.group(7), "bad guy")

    def test_personal_wanted_note(self):
        """测试：个人(设置|取消|清空)?备注 uid|idx (备注)? / (set-|clear-)?mark-note uid|idx (备注)?"""
        pattern = re.compile(
            r"^个人(设置|取消|清空)?备注\s+(\d+)(?:\s+(.+))?$|^(set-|clear-)?mark-note\s+(\d+)(?:\s+(.+))?$"
        )

        # 个人设置备注 uid 备注
        m = pattern.match("个人设置备注 1234567890123 新备注")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "设置")
        self.assertEqual(m.group(2), "1234567890123")
        self.assertEqual(m.group(3), "新备注")

        # 个人备注 idx 备注（默认设置）
        m = pattern.match("个人备注 5 备注内容")
        self.assertIsNotNone(m)
        self.assertIsNone(m.group(1))
        self.assertEqual(m.group(2), "5")
        self.assertEqual(m.group(3), "备注内容")

        # 个人清空备注 uid
        m = pattern.match("个人清空备注 1234567890123")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "清空")

        # set-mark-note idx 备注
        m = pattern.match("set-mark-note 10 new note")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(4), "set-")
        self.assertEqual(m.group(5), "10")
        self.assertEqual(m.group(6), "new note")

        # clear-mark-note uid
        m = pattern.match("clear-mark-note 1234567890123")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(4), "clear-")
        self.assertEqual(m.group(5), "1234567890123")

    def test_personal_wanted_level(self):
        """测试：个人(设置|修改|更改)?通缉级别 uid|idx lvl / mark-notice-level uid|idx lvl"""
        pattern = re.compile(
            r"^个人(设置|修改|更改)?通缉级别\s+(\d+)\s+(\d)$|^mark-notice-level\s+(\d+)\s+(\d)$"
        )

        # 个人设置通缉级别 uid level
        m = pattern.match("个人设置通缉级别 1234567890123 3")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "设置")
        self.assertEqual(m.group(2), "1234567890123")
        self.assertEqual(m.group(3), "3")

        # mark-notice-level idx level
        m = pattern.match("mark-notice-level 5 2")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(4), "5")
        self.assertEqual(m.group(5), "2")

    def test_personal_wanted_ease(self):
        """测试：个人缓和通缉犯 uid|idx"""
        pattern = re.compile(r"^个人缓和通缉犯\s+(\d+)$")

        m = pattern.match("个人缓和通缉犯 1234567890123")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "1234567890123")

    def test_personal_wanted_attention(self):
        """测试：个人注意通缉犯 uid|idx"""
        pattern = re.compile(r"^个人注意通缉犯\s+(\d+)$")

        m = pattern.match("个人注意通缉犯 5")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "5")

    def test_personal_wanted_high(self):
        """测试：个人(今日|重点)?(关照|击剑)通缉犯 uid|idx"""
        pattern = re.compile(r"^个人(今日|重点)?(关照|击剑)通缉犯\s+(\d+)$")

        # 个人关照通缉犯 uid
        m = pattern.match("个人关照通缉犯 1234567890123")
        self.assertIsNotNone(m)
        self.assertIsNone(m.group(1))
        self.assertEqual(m.group(2), "关照")
        self.assertEqual(m.group(3), "1234567890123")

        # 个人今日击剑通缉犯 idx
        m = pattern.match("个人今日击剑通缉犯 5")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "今日")
        self.assertEqual(m.group(2), "击剑")
        self.assertEqual(m.group(3), "5")

        # 个人重点关照通缉犯 uid
        m = pattern.match("个人重点关照通缉犯 1234567890123")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "重点")

    def test_personal_wanted_toggle(self):
        """测试：个人(开启|关闭|取消)?通报(jjc|pjjc) uid|idx / mark-(un|not-)?notice-(jjc|pjjc) uid|idx"""
        pattern = re.compile(
            r"^个人(开启|关闭|取消)?通报(jjc|pjjc)\s+(\d+)$|^mark-(un|not-)?notice-(jjc|pjjc)\s+(\d+)$"
        )

        # 个人开启通报jjc uid
        m = pattern.match("个人开启通报jjc 1234567890123")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "开启")
        self.assertEqual(m.group(2), "jjc")
        self.assertEqual(m.group(3), "1234567890123")

        # 个人通报pjjc idx（默认开启）
        m = pattern.match("个人通报pjjc 5")
        self.assertIsNotNone(m)
        self.assertIsNone(m.group(1))
        self.assertEqual(m.group(2), "pjjc")
        self.assertEqual(m.group(3), "5")

        # mark-unnotice-jjc uid
        m = pattern.match("mark-unnotice-jjc 1234567890123")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(4), "un")
        self.assertEqual(m.group(5), "jjc")
        self.assertEqual(m.group(6), "1234567890123")

        # mark-notice-pjjc idx
        m = pattern.match("mark-notice-pjjc 10")
        self.assertIsNotNone(m)
        self.assertIsNone(m.group(4))
        self.assertEqual(m.group(5), "pjjc")
        self.assertEqual(m.group(6), "10")

    def test_personal_wanted_unmark(self):
        """测试：(个人)?取消标记(jjc|pjjc)? uid|idx / unmark(-jjc|-pjjc)? uid|idx"""
        pattern = re.compile(
            r"^(个人)?取消标记(jjc|pjjc)?\s+(\d+)$|^unmark(-jjc|-pjjc)?\s+(\d+)$"
        )

        # 取消标记 uid（删除整个通缉）
        m = pattern.match("取消标记 1234567890123")
        self.assertIsNotNone(m)
        self.assertIsNone(m.group(2))
        self.assertEqual(m.group(3), "1234567890123")

        # 个人取消标记jjc idx（只关闭jjc通报）
        m = pattern.match("个人取消标记jjc 5")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "个人")
        self.assertEqual(m.group(2), "jjc")
        self.assertEqual(m.group(3), "5")

        # unmark-pjjc uid
        m = pattern.match("unmark-pjjc 1234567890123")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(4), "-pjjc")
        self.assertEqual(m.group(5), "1234567890123")

        # unmark idx
        m = pattern.match("unmark 10")
        self.assertIsNotNone(m)
        self.assertIsNone(m.group(4))
        self.assertEqual(m.group(5), "10")


class TestSubscriptionStatusImage(unittest.TestCase):
    """订阅状态图片渲染测试（覆盖各种场景）"""

    def test_render_subscription_status_image(self):
        """生成订阅状态图片，覆盖各种场景"""
        import os

        # 创建测试数据，覆盖各种场景
        sub_mgr = make_sub_mgr(
            ("QQ1", "1012345678901", "G1"),  # 正常订阅
            ("QQ1", "1012345678902", "G2"),  # 无缓存
            ("QQ1", "1012345678903", "G1"),  # 只开jjc
            ("QQ1", "1012345678904", "G1"),  # 只开pjjc
            ("QQ1", "1012345678905", "G2"),  # 全关
            ("QQ1", "1012345678906", "G1"),  # 长昵称
        )

        # 设置不同的通知开关
        sub_mgr.set_toggle("QQ1", 3, arena_on=True, grand_arena_on=False)  # 只开jjc
        sub_mgr.set_toggle("QQ1", 4, arena_on=False, grand_arena_on=True)  # 只开pjjc
        sub_mgr.set_toggle("QQ1", 5, arena_on=False, grand_arena_on=False)  # 全关

        cache = make_cache(
            user_infos={
                "1012345678901": {
                    "user_name": "普通用户",
                    "arena_rank": 50,
                    "arena_group": 5,
                    "grand_arena_rank": 20,
                    "grand_arena_group": 1,
                },
                # 1012345678902 无缓存
                "1012345678903": {
                    "user_name": "只开jjc",
                    "arena_rank": 100,
                    "arena_group": 10,
                    "grand_arena_rank": 200,
                    "grand_arena_group": 2,
                },
                "1012345678904": {
                    "user_name": "只开pjjc",
                    "arena_rank": 150,
                    "arena_group": 15,
                    "grand_arena_rank": 300,
                    "grand_arena_group": 3,
                },
                "1012345678905": {
                    "user_name": "全关闭",
                    "arena_rank": 200,
                    "arena_group": 20,
                    "grand_arena_rank": 400,
                    "grand_arena_group": 4,
                },
                "1012345678906": {
                    "user_name": "这是一个非常非常长的昵称需要截断",
                    "arena_rank": 250,
                    "arena_group": 25,
                    "grand_arena_rank": 500,
                    "grand_arena_group": 5,
                },
            }
        )

        svc = make_svc(sub_mgr=sub_mgr, cache=cache)
        rows = svc.get_subscription_status_rows("QQ1")

        # 验证行数
        self.assertEqual(len(rows), 6)

        # 调用实际的渲染函数生成图片
        from ..arena_service import render_subscription_status
        from ..table_image import save_image

        img = render_subscription_status(rows)

        # 保存图片
        output_path = os.path.join(os.path.dirname(__file__), "_test_arena_sub.png")
        output_rgb_path = os.path.join(
            os.path.dirname(__file__), "_test_arena_sub.rgb.png"
        )
        save_image(img, output_path, use_palette=True)
        save_image(img, output_rgb_path)

        # 验证文件生成
        self.assertTrue(os.path.exists(output_path))
        print(f"订阅状态图片已保存到: {output_path}")


class TestWantedSummaryImage(unittest.TestCase):
    """通缉概要图片渲染测试（覆盖各种场景）"""

    def test_render_wanted_summary_image(self):
        """生成通缉概要图片，覆盖各种场景"""
        import os

        # 创建测试数据，覆盖各种场景
        # 场景1：普通用户（群通缉，有备注，notice_level=1，默认不显示标志）
        # 场景2：挖矿用户（测试最长文本，notice_level=2，mock_now.hour=14，显示 ⚠️）
        # 场景3：同场用户（背景高亮，notice_level=3，mock_now.hour=14，显示 ⚠️🤺）
        # 场景4：不通报（notice_level=0，显示 🔇）
        # 场景5：notice_level=2，mock_now.hour!=14，不显示标志
        # 场景6：notice_level=3，mock_now.hour!=14，不显示标志
        # 场景7：佑树+工会名+头像（个人通缉，notice_level=1）
        # 场景8：有备注（个人通缉，notice_level=4，显示 ⚠️🤺🤺⚠️）
        # 场景9：jjc挖矿，pjjc正常（notice_level=5，显示 🤺🤺🤺🤺）

        wanted_mgr = make_wanted_mgr(
            (
                "group",
                "10001",
                "1012345678901",
                {"note": "普通用户", "notice_level": 1},
            ),
            (
                "group",
                "10001",
                "1012345678902",
                {"notice_level": 2},
            ),  # 挖矿用户，mock_now.hour=14
            (
                "group",
                "10001",
                "1012345678903",
                {"notice_level": 3},
            ),  # 同场用户，mock_now.hour=14
            ("group", "10001", "1012345678907", {"notice_level": 0}),  # 不通报
            (
                "group",
                "10001",
                "1012345678908",
                {"notice_level": 2},
            ),  # notice_level=2，mock_now.hour!=14
            (
                "group",
                "10001",
                "1012345678909",
                {"notice_level": 3},
            ),  # notice_level=3，mock_now.hour!=14
            ("personal", "QQ1", "1012345678904", "10001", {"notice_level": 1}),  # 佑树
            (
                "personal",
                "QQ1",
                "1012345678905",
                "10001",
                {"note": "喜欢改名是吧", "notice_level": 4},
            ),
            (
                "personal",
                "QQ1",
                "1012345678906",
                "10001",
                {"notice_level": 5},
            ),  # jjc挖矿，永久高优先级
        )

        sub_mgr = make_sub_mgr(
            ("QQ1", "1012345678904", "10001"),  # 佑树的订阅（用于获取同场信息）
        )

        cache = make_cache(
            user_infos={
                "1012345678901": {
                    "user_name": "普通用户",
                    "arena_rank": 50,
                    "arena_group": 5,
                    "grand_arena_rank": 20,
                    "grand_arena_group": 1,
                    "arena_challenge": 3,
                    "grand_arena_challenge": 2,
                    "last_login_time": 1710000000,
                    "clan_name": "测试公会",
                    "avatar_unit_name": "春田",
                },
                "1012345678902": {
                    "user_name": "挖矿用户名字很长需要测试最长文本宽度",
                    "arena_rank": 0,
                    "arena_group": 0,
                    "grand_arena_rank": 100,
                    "grand_arena_group": 10,
                    "arena_challenge": 0,
                    "grand_arena_challenge": 1,
                    "arena_mining": True,  # 挖矿标记
                    "last_login_time": 1710003600,
                    "clan_name": "挖矿公会名字也很长",
                    "avatar_unit_name": "角色名也很长",
                },
                "1012345678903": {
                    "user_name": "同场 L3@14",
                    "arena_rank": 100,
                    "arena_group": 5,  # 与普通用户同场
                    "grand_arena_rank": 200,
                    "grand_arena_group": 2,
                    "arena_challenge": 5,
                    "grand_arena_challenge": 3,
                    "last_login_time": 1710007200,
                },
                "1012345678904": {
                    "user_name": "佑树",
                    "arena_rank": 7,
                    "arena_group": 5,
                    "grand_arena_rank": 300,
                    "grand_arena_group": 3,
                    "arena_challenge": 24,
                    "grand_arena_challenge": 4,
                    "last_login_time": 1710010800,
                    "clan_name": "超级佑树军团",
                    "avatar_unit_name": "优衣（新年）",
                },
                "1012345678905": {
                    "user_name": "有备注",
                    "arena_rank": 200,
                    "arena_group": 20,
                    "grand_arena_rank": 40,
                    "grand_arena_group": 3,
                    "arena_challenge": 1,
                    "grand_arena_challenge": 109,
                    "last_login_time": 1710014400,
                },
                "1012345678906": {
                    "user_name": "jjc挖矿",
                    "arena_rank": 0,
                    "arena_group": 0,
                    "grand_arena_rank": 500,
                    "grand_arena_group": 5,
                    "arena_challenge": 0,
                    "grand_arena_challenge": 2,
                    "arena_mining": True,  # jjc挖矿
                    "last_login_time": 1710018000,
                },
                "1012345678907": {
                    "user_name": "不通报用户",
                    "arena_rank": 150,
                    "arena_group": 15,
                    "grand_arena_rank": 250,
                    "grand_arena_group": 25,
                    "arena_challenge": 1,
                    "grand_arena_challenge": 1,
                    "last_login_time": 1710021600,
                },
                "1012345678908": {
                    "user_name": "L2非14点",
                    "arena_rank": 80,
                    "arena_group": 8,
                    "grand_arena_rank": 180,
                    "grand_arena_group": 18,
                    "arena_challenge": 2,
                    "grand_arena_challenge": 2,
                    "last_login_time": 1710025200,
                },
                "1012345678909": {
                    "user_name": "L3非14点",
                    "arena_rank": 90,
                    "arena_group": 9,
                    "grand_arena_rank": 190,
                    "grand_arena_group": 19,
                    "arena_challenge": 3,
                    "grand_arena_challenge": 3,
                    "last_login_time": 1710028800,
                },
            }
        )

        svc = make_svc(
            wanted_mgr=wanted_mgr,
            sub_mgr=sub_mgr,
            cache=cache,
            reset_notice_levels=False,
        )
        group_rows, personal_rows = svc.get_wanted_summary_rows("QQ1", "10001")

        # 验证行数
        self.assertEqual(len(group_rows), 6)  # 添加了更多场景
        self.assertEqual(len(personal_rows), 3)

        # 为 notice_level=2 和 3 的行添加 mock_now 属性
        from datetime import datetime

        for row in group_rows + personal_rows:
            if row.notice_level == 2:
                # 场景2（挖矿用户）：mock_now.hour=14，显示 ⚠️
                if row.uid == "1012345678902":
                    row.mock_now = datetime(2024, 3, 11, 14, 0, 0)
                # 场景5：mock_now.hour!=14，不显示标志
                elif row.uid == "1012345678908":
                    row.mock_now = datetime(2024, 3, 11, 10, 0, 0)
            elif row.notice_level == 3:
                # 场景3（同场用户）：mock_now.hour=14，显示 ⚠️🤺
                if row.uid == "1012345678903":
                    row.mock_now = datetime(2024, 3, 11, 14, 0, 0)
                # 场景6：mock_now.hour!=14，不显示标志
                elif row.uid == "1012345678909":
                    row.mock_now = datetime(2024, 3, 11, 10, 0, 0)

        # 调用实际的渲染函数生成图片
        from ..table_image import save_image
        from ..wanted_summary_formatter import render_wanted_summary

        img = render_wanted_summary(group_rows, personal_rows, now_hour=10)

        # 保存图片
        output_path = os.path.join(os.path.dirname(__file__), "_test_arena_wanted.png")
        output_rgb_path = os.path.join(
            os.path.dirname(__file__), "_test_arena_wanted.rgb.png"
        )
        save_image(img, output_path, use_palette=True)
        save_image(img, output_rgb_path)

        # 验证文件生成
        self.assertTrue(os.path.exists(output_path))
        print(f"通缉概要图片已保存到: {output_path}")


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
    if os.path.exists(TEST_CONFIG):
        os.remove(TEST_CONFIG)
