from typing import Optional, TypedDict

#from typing_extensions import Never


class Emblem(TypedDict):
    emblem_id: int
    ex_value: int


class UserInfo(TypedDict):
    viewer_id: int
    user_name: str
    user_comment: str
    team_level: int
    team_exp: int
    emblem: "Emblem"
    last_login_time: int
    arena_rank: int
    arena_group: int
    grand_arena_rank: int
    grand_arena_group: int
    open_story_num: int
    unit_num: int
    total_power: int
    tower_cleared_floor_num: int
    tower_cleared_ex_quest_count: int
    friend_num: int


class FavoriteUnit(TypedDict):
    id: int
    promotion_level: int


class Profile(TypedDict):
    user_info: UserInfo
    clan_name: str
    favorite_unit: FavoriteUnit


class UserInfoEx(UserInfo):
    clan_name: str
    avatar_unit_id: int
    avatar_unit_name: Optional[str]
    avatar_unit_rank: Optional[int]
    user_dname: Optional[str]


class UserInfoExtra(TypedDict):
    arena_mining: Optional[bool]
    arena_challenge: Optional[int]
    grand_arena_mining: Optional[bool]
    grand_arena_challenge: Optional[int]


class UserInfoCache(UserInfoEx, UserInfoExtra):
    emblem: None
    viewer_id: None
