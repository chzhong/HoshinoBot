import json
import os


class charadata:
    def __init__(self) -> None:
        curpath = os.path.dirname(__file__)
        self._name_json_path = os.path.join(curpath, "CHARA_NAME.json")
        if os.path.exists(self._name_json_path):
            with open(self._name_json_path, "r") as fp:
                self._chara_cache = json.load(fp)
                self._loaded = True
        else:
            self._loaded = False
            self._chara_cache = {}

    @property
    def loaded(self):
        return self._loaded

    @property
    def chara_name_path(self):
        return self._name_json_path

    def get_chara_name(self, unit_id):
        """
        'favorite_unit': {'id': 109801, 'unit_rarity': 5, 'battle_rarity': 0, 'unit_level': 181, 'promotion_level': 14, 'skin_data': {'icon_skin_id': 0, 'sd_skin_id': 0, 'still_skin_id': 0, 'motion_id': 0}}
        """
        unit_id = int(unit_id)
        key = str(unit_id)
        if key in self._chara_cache:
            names = self._chara_cache[key]
            return names[0] if names else ""
        if unit_id > 100000:
            chara_id = int(unit_id / 100)
            return self.get_chara_name(chara_id)
        return ""
