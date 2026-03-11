"""
arena_client.py - PCR API 客户端封装（DAO 层）

封装 pcrclient 的登录、API 调用和用户信息处理。
全模块共用单一实例，内部管理锁和登录状态，调用方无需关心并发细节。
"""

from asyncio import Lock
from json import load
from os.path import dirname, join

from jjcdata import charadata
from pcrclient import ApiException, pcrclient

_curpath = dirname(__file__)

with open(join(_curpath, "account.json")) as _fp:
    _acinfo = load(_fp)

_client = pcrclient()
_qlck = Lock()
_chara_db = charadata()

# 验证码锁定状态（由 service.py 的 /pcrval 指令写入）
validating = False


def _distriglish_name(user_info: dict) -> str:
    if user_info["user_name"] != "佑树":
        user_info["user_dname"] = user_info["user_name"]
        return user_info["user_name"]
    avatar_name = user_info.get("avatar_unit_name", "???")
    clan_name = user_info.get("clan_name", "?")
    if avatar_name:
        dname = f"{user_info['user_name']}        @{clan_name} ({avatar_name}头)"
    else:
        uid = str(user_info["viewer_id"])
        dname = f"{user_info['user_name']}        @{clan_name} (UID: ...{uid[-3:]})"
    user_info["user_dname"] = dname
    return dname


def _improve_user_info(profile: dict) -> dict:
    """将 profile 响应展平为 user_info，附加公会名、头像角色名、区别名。"""
    res = profile["user_info"]
    res["clan_name"] = profile["clan_name"]
    res["avatar_unit_id"] = profile["favorite_unit"]["id"]
    res["avatar_unit_name"] = _chara_db.get_chara_name(res["avatar_unit_id"])
    _distriglish_name(res)
    return res


async def get_profile(uid: str) -> dict:
    """
    查询用户 profile 并返回展平后的 user_info。
    包含公会名、头像角色名、区别名（user_dname）。
    """
    if validating:
        raise ApiException("账号被风控，请联系管理员输入验证码并重新登录", -1)
    async with _qlck:
        while _client.shouldLogin:
            await _client.login()
        profile = await _client.callapi(
            "/profile/get_profile", {"target_viewer_id": int(uid)}
        )
    return _improve_user_info(profile)


async def get_profile_raw(uid: str) -> dict:
    """
    查询用户 profile，返回原始响应（不展平），用于详细查询。
    """
    if validating:
        raise ApiException("账号被风控，请联系管理员输入验证码并重新登录", -1)
    async with _qlck:
        while _client.shouldLogin:
            await _client.login()
        return await _client.callapi(
            "/profile/get_profile", {"target_viewer_id": int(uid)}
        )
