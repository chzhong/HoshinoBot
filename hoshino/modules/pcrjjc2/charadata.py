import json
import os

try:
    from hoshino.modules.pcrdata.api import (
        dump_chara_name_json as _pcrdata_dump_chara_name_json,
    )
    from hoshino.modules.pcrdata.api import get_unit_name as _pcrdata_get_unit_name

    _USE_PCRDATA = True
except ImportError:
    _pcrdata_get_unit_name = None
    _pcrdata_dump_chara_name_json = None
    _USE_PCRDATA = False


class charadata:
    def __init__(self) -> None:
        curpath = os.path.dirname(__file__)
        self._name_json_path = os.path.join(curpath, "CHARA_NAME.json")
        self._latest_name_json_path = os.path.join(curpath, "CHARA_NAME.latest.json")
        self._loaded = False
        self._chara_cache = {}

        for path in (self._name_json_path, self._latest_name_json_path):
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as fp:
                    self._chara_cache = json.load(fp)
                    self._loaded = True
                break

    @property
    def loaded(self):
        return self._loaded

    @property
    def chara_name_path(self):
        return self._name_json_path

    def _get_local_name(self, unit_id):
        key = str(unit_id)
        if key in self._chara_cache:
            names = self._chara_cache[key]
            if isinstance(names, list):
                return names[0] if names else ""
            return str(names)
        if unit_id > 100000:
            return self._get_local_name(int(unit_id / 100))
        return ""

    def get_chara_name(self, unit_id):
        """
        'favorite_unit': {'id': 109801, 'unit_rarity': 5, 'battle_rarity': 0, 'unit_level': 181, 'promotion_level': 14, 'skin_data': {'icon_skin_id': 0, 'sd_skin_id': 0, 'still_skin_id': 0, 'motion_id': 0}}
        """
        unit_id = int(unit_id)
        if _USE_PCRDATA and _pcrdata_get_unit_name:
            names = _pcrdata_get_unit_name(unit_id)
            if names:
                return names[0]
        return self._get_local_name(unit_id)


def _dump_latest_json():
    if not _USE_PCRDATA or not _pcrdata_dump_chara_name_json:
        raise RuntimeError("pcrdata 不可用，无法导出 CHARA_NAME.latest.json")
    curpath = os.path.dirname(__file__)
    out_path = os.path.join(curpath, "CHARA_NAME.latest.json")
    _pcrdata_dump_chara_name_json(out_path, with_version=True)
    print(f"updated: {out_path}")


if __name__ == "__main__":
    _dump_latest_json()
