"""
pcrdata 对外接口。
优先使用静态 pcr_data.CHARA_NAME，fallback 到数据库。
"""
import json
import os
from collections import OrderedDict
from typing import Dict, List, Optional

from .pcr_data import CHARA_NAME as _STATIC_CHARA_NAME
from .dbmgr import instance as _db


def _dedupe_names(names: List[str]) -> List[str]:
    seen = set()
    result = []
    for name in names:
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result


def get_unit_name(unit_id: int) -> List[str]:
    """
    返回 unit_id 对应的所有名称列表。
    unit_id 可以是 6 位（如 100101）或 4 位 chara_id（如 1001）。
    找不到时返回 ["新角色？"]。
    """
    # 统一转为 4 位 chara_id
    chara_id = unit_id // 100 if unit_id > 9999 else unit_id

    # 优先静态数据
    if chara_id in _STATIC_CHARA_NAME:
        return _STATIC_CHARA_NAME[chara_id]

    # fallback 数据库
    db_names = _db.get_unit_names()
    # 数据库 unit_id 是 6 位，尝试精确匹配和 chara_id 前缀匹配
    if unit_id in db_names:
        return [db_names[unit_id]]
    for uid, name in db_names.items():
        if uid // 100 == chara_id:
            return [name]

    return ["新角色？"]


def dump_chara_name_json(path: str, with_version: bool = False) -> None:
    """
    合并静态数据和数据库新数据，写入 JSON 文件。
    静态数据优先，数据库补充新角色。
    格式：{"__manifest_ver__": "...", chara_id_str: [...names]}
    """
    result: OrderedDict = OrderedDict()

    if with_version and _db.ver:
        result["__manifest_ver__"] = _db.ver

    # 静态数据优先写入（保持原顺序，并按顺序去重）
    for chara_id, names in _STATIC_CHARA_NAME.items():
        result[str(chara_id)] = _dedupe_names(names)

    # 数据库补充静态数据没有的角色
    db_names = _db.get_unit_names()
    for unit_id, name in db_names.items():
        chara_id = unit_id // 100
        key = str(chara_id)
        if key not in result:
            result[key] = [name]

    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=4)
