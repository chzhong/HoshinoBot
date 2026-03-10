import datetime
import redis
import json

def time_to_str(timestamp):
    return timestamp.strftime('%Y-%m-%d %H:%M:%S')

def str_to_time(str):
    return datetime.datetime.strptime(str, '%Y-%m-%d %H:%M:%S')


class pjjcbot_database:
    def __init__(self):
        self.__redis_handle = redis.Redis(host='pcr-redis', port=6379, decode_responses=True)

    def get_today_str(self):
        date_format = '%Y-%m-%d'
        now = datetime.datetime.now()
        five_clock = datetime.datetime(now.year, now.month, now.day, 5)
        if now < five_clock:
            now -= datetime.timedelta(days=1)
        return now.strftime(date_format)

    def __get_key_name_lock_list(self, group_id):
        return "pcrbot:pjjc_lock:%s:%s" % (group_id, self.get_today_str())

    def __get_key_name_invisible_list(self, group_id, user_id):
        return "pcrbot:pjjc_invisible:%s:%s:%s" % (group_id, user_id, self.get_today_str())

    def __get_key_name_myrank(self, group_id):
        return "pcrbot:pjjc_rank:%s:%s" % (group_id, self.get_today_str())

    def __get_key_name_record(self, group_id):
        return "pcrbot:pjjc_action_record:%s" % (group_id)

    def set_lock_rank(self, rank, group_id, timestamp):
        key = self.__get_key_name_lock_list(group_id)
        self.__redis_handle.hset(key, rank, time_to_str(timestamp))
        self.__redis_handle.expire(key, 24*60*60)

    def del_lock_rank(self, rank, group_id):
        key = self.__get_key_name_lock_list(group_id)
        self.__redis_handle.hdel(key, rank)

    def get_lock_rank_by_rank(self, rank, group_id):
        key = self.__get_key_name_lock_list(group_id)
        return self.__redis_handle.hget(key, rank)

    def get_lock_rank(self, group_id):
        key = self.__get_key_name_lock_list(group_id)
        return self.__redis_handle.hgetall(key)

    def is_exist_in_lock_rank(self, rank, group_id):
        key = self.__get_key_name_lock_list(group_id)
        return self.__redis_handle.hexists(key, rank)

    def add_invisible_rank_for_user(self, rank, group_id, user_id, timestamp):
        key = self.__get_key_name_invisible_list(group_id, user_id)
        self.__redis_handle.rpush(key, rank, time_to_str(timestamp))
        self.__redis_handle.expire(key, 24*60*60)

    def del_invisible_rank_for_user(self, group_id, user_id):
        key = self.__get_key_name_invisible_list(group_id, user_id)
        self.__redis_handle.lpop(key)
        self.__redis_handle.lpop(key)

    def get_invisible_rank_for_user(self, group_id, user_id):
        key = self.__get_key_name_invisible_list(group_id, user_id)
        return self.__redis_handle.lrange(key, 0, -1)

    def get_visible_rank_for_user(self, group_id, user_id):
        invisibles = self.get_invisible_rank_for_user(group_id, user_id)
        locked = self.get_lock_rank(group_id)
        user_rank = self.query_user_rank(group_id, user_id)
        if user_rank:
            visibles = range(1, 11) if int(user_rank) <=3 else range(max(1, int(user_rank) - 10), int(user_rank))
        else:
            visibles = range(1, 11)
        visibles = list(visibles)
        for k, _ in locked.items():
            r = int(k)
            if r in visibles:
                visibles.remove(r)
        now = datetime.datetime.now()
        for i in range(0, len(invisibles), 2):
            r = int(invisibles[i])
            v = str_to_time(invisibles[i+1])
            if v > now and r in visibles:
                visibles.remove(r)
        return visibles

    def __add_user_rank(self, rank, group_id, user_id):
        key = self.__get_key_name_myrank(group_id)
        self.__redis_handle.hset(key, rank, user_id)
        self.__redis_handle.hset(key, user_id, rank)
        self.__redis_handle.expire(key, 24*60*60)

    def __del_user_rank(self, group_id, user_id):
        key = self.__get_key_name_myrank(group_id)
        rank = self.__redis_handle.hget(key, user_id)
        if rank:
            self.__redis_handle.hdel(key, rank, user_id)

    def set_user_rank(self, rank, group_id, user_id):
        self.__del_user_rank(group_id, user_id)
        self.__add_user_rank(rank, group_id, user_id)

    def get_user_rank(self, rank, group_id):
        key = self.__get_key_name_myrank(group_id)
        return self.__redis_handle.hget(key, rank)

    def query_user_rank(self, group_id, user_id):
        key = self.__get_key_name_myrank(group_id)
        return self.__redis_handle.hget(key, user_id)

    def record_lock_action(self, rank, user_id, group_id, timestamp):
        key = self.__get_key_name_record(group_id)
        item = (user_id, rank, timestamp.timestamp())
        item_s = json.dumps(item)
        self.__redis_handle.rpush(key, item_s)
