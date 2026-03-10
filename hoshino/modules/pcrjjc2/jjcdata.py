import datetime
from typing import Tuple
import redis
import json
import os

def time_to_str(timestamp):
    return timestamp.strftime('%Y-%m-%d %H:%M:%S')

def str_to_time(str):
    return datetime.datetime.strptime(str, '%Y-%m-%d %H:%M:%S')

ONE_DAY = datetime.timedelta(days=1)

def pcr_today():
    now = datetime.datetime.now()
    if now.hour < 5:
        today = now - ONE_DAY
    else:
        today = now
    return today.strftime('%Y-%m-%d')

def intify(d, k):
    if k in d:
        d[k] = int(d[k])

def pcr_end_of_today():
    now = datetime.datetime.now()
    if now.hour < 5:
        eot = now.replace(hour=5, minute=0, second=0, microsecond=0)
    else:
        eot = now.replace(hour=5, minute=0, second=0, microsecond=0) + ONE_DAY
    return int(eot.timestamp())

class jjcdata:
    def __init__(self):
        self._redis = redis.Redis(host='pcr-redis', port=6379, decode_responses=True)

    def cache_user_rank(self, uid, ranks: Tuple[int, int]):
        key = f'pcrbot:user:{uid}'
        self._redis.hmset(key, {
            'arena_rank': ranks[0],
            'grand_arena_rank': ranks[1]
        })

    def get_user_rank(self, uid):
        key = f'pcrbot:user:{uid}'
        ranks = self._redis.hmget(key, ('arena_rank', 'grand_arena_rank'))
        if not ranks[0] and not ranks[1]:
            return None
        else:
            return (int(ranks[0]), int(ranks[1]))

    def cache_user_info(self, uid, user_info: dict):
        """
        User Example
        {
            'viewer_id': 1184975198736, 'user_name': '紫泪魔瞳i', 'user_comment': '请多关照。', 
            'team_level': 181, 'team_exp': 511758, 
            'emblem': {'emblem_id': 10201273, 'ex_value': 0}, 
            'last_login_time': 1669999871, 
            'arena_rank': 20, 'arena_group': 19, 'arena_time': 1654567200, 
            'grand_arena_rank': 14, 'grand_arena_group': 1, 'grand_arena_time': 1664506800, 
            'open_story_num': 1877, 'unit_num': 127, 'total_power': 3133517, 
            'tower_cleared_floor_num': 480, 'tower_cleared_ex_quest_count': 27, 'friend_num': 8}
        """
        key = f'pcrbot:user:{uid}'
        user_info.pop('emblem')
        user_info.pop('viewer_id')
        self._redis.hmset(key, user_info)

    def get_user_info(self, uid):
        info_key = f'pcrbot:user:{uid}'
        user_info = self._redis.hgetall(info_key)
        if not user_info:
            return {}
        today = pcr_today()
        intify(user_info, 'team_level')
        intify(user_info, 'team_exp')
        intify(user_info, 'last_login_time')
        intify(user_info, 'arena_rank')
        intify(user_info, 'arena_group')
        intify(user_info, 'arena_time')
        intify(user_info, 'grand_arena_rank')
        intify(user_info, 'grand_arena_group')
        intify(user_info, 'grand_arena_time')
        intify(user_info, 'open_story_num')
        intify(user_info, 'unit_num')
        intify(user_info, 'total_power')
        intify(user_info, 'tower_cleared_floor_num')
        intify(user_info, 'tower_cleared_ex_quest_count')
        intify(user_info, 'friend_num')

        jjc_key = f'pcrbot:jjc_challenge:{today}:{uid}'
        jjc_challenge = self._redis.get(jjc_key) or 0
        pjjc_key = f'pcrbot:pjjc_challenge:{today}:{uid}'
        pjjc_challenge = self._redis.get(pjjc_key) or 0
        user_info['arena_challenge'] = jjc_challenge
        user_info['grand_arena_challenge'] = pjjc_challenge
        return user_info

    def cache_user_jjc_challenge(self, uid):
        today = pcr_today()
        key = f'pcrbot:jjc_challenge:{today}:{uid}'
        self._redis.incr(key)
        self._redis.expireat(key, pcr_end_of_today())

    def cache_user_pjjc_challenge(self, uid):
        today = pcr_today()
        key = f'pcrbot:pjjc_challenge:{today}:{uid}'
        self._redis.incr(key)
        self._redis.expireat(key, pcr_end_of_today())

class charadata:

    def __init__(self) -> None:
        curpath = os.path.dirname(__file__)
        self._name_json_path = os.path.join(curpath, 'CHARA_NAME.json')
        if os.path.exists(self._name_json_path):
            with open(self._name_json_path, 'r') as fp:
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
            return names[0] if names else ''
        if unit_id > 100000:
            chara_id = int(unit_id / 100)
            return self.get_chara_name(chara_id)
        return ''


    
