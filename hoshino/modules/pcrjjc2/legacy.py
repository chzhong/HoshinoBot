from json import load, dump
from nonebot import get_bot, on_command
from hoshino import priv
from hoshino.typing import NoticeSession
from .pcrclient import pcrclient, ApiException
from .jjcdata import jjcdata, charadata
from asyncio import Lock
from os.path import dirname, join, exists
from copy import deepcopy
from traceback import format_exc
from .safeservice import SafeService
from datetime import datetime
from typing import Dict
from .utils import send_summary

import time
import pytz
import random
import asyncio

tz = pytz.timezone('Asia/Shanghai')
random.seed()

cache_db = jjcdata()
chara_db = charadata()

async def should_check(*,
                 interval=5,  # 默认检测间隔
                 hot_hours=(14,), hot_interval=2,  # 击剑时间和检测间隔
                 cold_hours=(2, 3, 4, 5, 6), cold_interval=15  # 宵禁时间和检测间隔
                 ):
    global tz
    now = datetime.now(tz)
    is_hot_hour = now.hour in hot_hours
    is_cold_hour = now.hour in cold_hours

    check_data = False
    delay = not (now.hour == 15 and now.minute == 0)
    max_delay = 30
    if is_hot_hour:
        check_data = (now.minute % hot_interval) == 0 or now.minute in (57,59) 
        max_delay = 5
    elif is_cold_hour:
        check_data = (now.minute % cold_interval) == 0
        max_delay = 30
    else:
        check_data = (now.minute % interval) == 0
        max_delay = 15
    if check_data and delay:
        dt = random.randint(0, max_delay)
        sv.logger.info(f'Random delay {dt} seconds before query')
        await asyncio.sleep(dt)
    return check_data


sv_help = '''[竞技场绑定 uid] 绑定竞技场排名变动推送，默认双场均启用，仅排名降低时推送
[竞技场查询 (uid)] 查询竞技场简要信息
[停止竞技场订阅] 停止战斗竞技场排名变动推送
[停止公主竞技场订阅] 停止公主竞技场排名变动推送
[启用竞技场订阅] 启用战斗竞技场排名变动推送
[启用公主竞技场订阅] 启用公主竞技场排名变动推送
[删除竞技场订阅] 删除竞技场排名变动推送绑定
[竞技场订阅状态] 查看排名变动推送绑定状态
[详细查询 (uid)] 查询详细状态
[通缉 (uid)] 通缉uid，监控其上下线和排名变动
[逮捕 (uid)] 取消通缉 uid
[通缉犯状态][lswt] 显示所有通缉犯的状态（不会触发查询）
[通缉犯概要][lswts] 以精简方式显示通缉犯状态（不会触发查询）
[通缉犯查询][cxwt] 查询所有通缉犯的最新状态
[通缉犯列表][cxwts] 以精简方式显示所有通缉犯的最新状态
'''

sv = SafeService('竞技场推送',help_=sv_help, bundle='pcr查询')

@sv.on_fullmatch('竞技场帮助', only_to_me=False)
async def send_jjchelp(bot, ev):
    self_ids = bot._wsr_api_clients.keys()
    for sid in self_ids:
        gl = await bot.get_group_list(self_id=sid)
        msg = f"本Bot目前服务群数目{len(gl)}"
    await bot.send(ev, f'{sv_help}\n{msg}')

curpath = dirname(__file__)
config = join(curpath, 'binds.json')
root = {
    'arena_bind' : {}
}

wanted_config = join(curpath, 'wanted_binds.json')
wanted_root = {
    'wanted_bind' : {},
    'watch_bind': {}
}

if not chara_db.loaded:
    sv.logger.warn(f'Failed to load character name from {chara_db.chara_name_path}')


cache = {}
client = None
lck = Lock()

if exists(config):
    with open(config) as fp:
        root = load(fp)

if exists(wanted_config):
    with open(wanted_config) as fp:
        wanted_root = load(fp)

binds = root['arena_bind']
wanted_binds = wanted_root['wanted_bind']
watch_binds = wanted_root.get('watch_bind', {})

captcha_lck = Lock()

with open(join(curpath, 'account.json')) as fp:
    acinfo = load(fp)

bot = get_bot()
validate = None
validating = False
acfirst = False


async def captchaVerifier(gt, challenge, userid):
    global acfirst, validating
    if not acfirst:
        await captcha_lck.acquire()
        acfirst = True

    if acinfo['admin'] == 0:
        bot.logger.error('captcha is required while admin qq is not set, so the login can\'t continue')
    else:
        url = f"https://help.tencentbot.top/geetest/?captcha_type=1&challenge={challenge}&gt={gt}&userid={userid}&gs=1"
        await bot.send_private_msg(
            user_id = acinfo['admin'],
            message = f'pcr账号登录需要验证码，请完成以下链接中的验证内容后将第一行validate=后面的内容复制，并用指令/pcrval xxxx将内容发送给机器人完成验证\n验证链接：{url}'
        )
    validating = True
    await captcha_lck.acquire()
    validating = False
    return validate

async def errlogger(msg):
    await bot.send_private_msg(
        user_id = acinfo['admin'],
        message = f'pcrjjc2登录错误：{msg}'
    )

#bclient = bsdkclient(acinfo, captchaVerifier, errlogger)
client = pcrclient()

qlck = Lock()

def distriglish_name(user_info):
    if user_info['user_name'] != '佑树':
        user_info['user_dname'] = user_info['user_name']
        return user_info['user_name']
    avatar_name = user_info.get('avatar_unit_name', '???')
    clan_name = user_info.get('clan_name', '?')
    if avatar_name:
        dname = f"{user_info['user_name']}        @{clan_name} ({avatar_name}头)"
    else:
        uid = str(user_info['viewer_id'])
        dname = f"{user_info['user_name']}        @{clan_name} (UID: ...{uid[-3:]})"
    user_info['user_dname'] = dname
    return dname

def improve_user_info(profile):
    res = profile['user_info']
    # 把用户工会信息和头像信息放入 user_info 方便查询
    res['clan_name'] = profile['clan_name']
    res['avatar_unit_id'] = profile['favorite_unit']['id']
    res['avatar_unit_name'] = chara_db.get_chara_name(res['avatar_unit_id'])
    distriglish_name(res)
    return res


async def query(id: str):
    if validating:
        raise ApiException('账号被风控，请联系管理员输入验证码并重新登录', -1)
    async with qlck:
        while client.shouldLogin:
            await client.login()
        profile = (await client.callapi('/profile/get_profile', {
        'target_viewer_id': int(id)
        }))
        return improve_user_info(profile)

async def arena_query(id: str):
    if validating:
        raise ApiException('账号被风控，请联系管理员输入验证码并重新登录', -1)
    async with qlck:
        while client.shouldLogin:
            await client.login()
        res = (await client.callapi('/profile/get_profile', {
            'target_viewer_id': int(id)
            }))
        return res

def save_binds():
    with open(config, 'w') as fp:
        dump(root, fp, indent=4)

def save_wanted_binds():
    with open(wanted_config, 'w') as fp:
        dump(wanted_root, fp, indent=4)

@sv.on_rex(r'^竞技场绑定 ?(\d{13})$')
async def on_arena_bind(bot, ev):
    global binds, lck

    async with lck:
        uid = str(ev['user_id'])
        last = binds[uid] if uid in binds else None

        binds[uid] = {
            'id': ev['match'].group(1),
            'uid': uid,
            'gid': str(ev['group_id']),
            'arena_on': last is None or last['arena_on'],
            'grand_arena_on': last is None or last['grand_arena_on'],
        }
        save_binds()

    await bot.finish(ev, '竞技场绑定成功', at_sender=True)

@sv.on_rex(r'^竞技场查询 ?(\d{13})?$')
async def on_query_arena(bot, ev):
    global binds, lck

    robj = ev['match']
    id = robj.group(1)

    async with lck:
        if id == None:
            uid = str(ev['user_id'])
            if not uid in binds:
                await bot.finish(ev, '您还未绑定竞技场', at_sender=True)
                return
            else:
                id = binds[uid]['id']
        try:
            res = await query(id)
            await bot.finish(ev,
f'''
jjc：{res["arena_rank"]}
pjjc：{res["grand_arena_rank"]}''', at_sender=True)
        except ApiException as e:
            await bot.finish(ev, f'查询出错，{e}', at_sender=True)

@sv.on_rex(r'^详细查询 ?(\d{13})?$')
async def on_query_arena_all(bot, ev):
    global binds, lck

    robj = ev['match']
    id = robj.group(1)

    async with lck:
        if id == None:
            uid = str(ev['user_id'])
            if not uid in binds:
                return
            else:
                id = binds[uid]['id']
        try:
            res = await arena_query(id)
            #sv.logger.info(f'detail profile of {id}: {res}')

            arena_time = int (res['user_info']['arena_time'])
            arena_date = time.localtime(arena_time)
            arena_str = time.strftime('%Y-%m-%d',arena_date)

            grand_arena_time = int (res['user_info']['grand_arena_time'])
            grand_arena_date = time.localtime(grand_arena_time)
            grand_arena_str = time.strftime('%Y-%m-%d',grand_arena_date)

            user_info = improve_user_info(res)
            #sv.logger.info(f'detail profile of {id}: {user_info}')
            cache_db.cache_user_info(id, user_info)

            dname_hint = f'(区别名: {user_info["user_dname"]})' if user_info["user_dname"] != user_info["user_name"] else ''

            await bot.finish(ev,
f'''
uid：{id}
昵称：{user_info["user_name"]} {dname_hint}
公会：{res['clan_name']}
简介：{user_info["user_comment"]}
最后上线：{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(user_info['last_login_time']))}
jjc：{user_info["arena_rank"]}
pjjc：{user_info["grand_arena_rank"]}
战力：{user_info["total_power"]}
等级：{user_info["team_level"]}
jjc场次：{user_info["arena_group"]}
jjc创建日：{arena_str}
pjjc场次：{user_info["grand_arena_group"]}
pjjc创建日：{grand_arena_str}
角色数：{user_info["unit_num"]}
''', at_sender=True)
        except ApiException as e:
            await bot.finish(ev, f'查询出错，{e}', at_sender=True)

@sv.on_rex('(启用|停止)(公主)?竞技场订阅')
async def change_arena_sub(bot, ev):
    global binds, lck

    key = 'arena_on' if ev['match'].group(2) is None else 'grand_arena_on'
    uid = str(ev['user_id'])

    async with lck:
        if not uid in binds:
            await bot.send(ev,'您还未绑定竞技场',at_sender=True)
        else:
            binds[uid][key] = ev['match'].group(1) == '启用'
            save_binds()
            await bot.finish(ev, f'{ev["match"].group(0)}成功', at_sender=True)

@on_command('/pcrval')
async def validate(session):
    global binds, lck, validate
    if session.ctx['user_id'] == acinfo['admin']:
        validate = session.ctx['message'].extract_plain_text().strip()[8:]
        captcha_lck.release()

@sv.on_prefix('删除竞技场订阅')
async def delete_arena_sub(bot,ev):
    global binds, lck

    uid = str(ev['user_id'])

    if ev.message[0].type == 'at':
        if not priv.check_priv(ev, priv.SUPERUSER):
            await bot.finish(ev, '删除他人订阅请联系维护', at_sender=True)
            return
        uid = str(ev.message[0].data['qq'])
    elif len(ev.message) == 1 and ev.message[0].type == 'text' and not ev.message[0].data['text']:
        uid = str(ev['user_id'])


    if not uid in binds:
        await bot.finish(ev, '未绑定竞技场', at_sender=True)
        return

    async with lck:
        binds.pop(uid)
        save_binds()

    await bot.finish(ev, '删除竞技场订阅成功', at_sender=True)

@sv.on_fullmatch('竞技场订阅状态')
async def send_arena_sub_status(bot,ev):
    global binds, lck
    uid = str(ev['user_id'])


    if not uid in binds:
        await bot.send(ev,'您还未绑定竞技场', at_sender=True)
    else:
        info = binds[uid]
        await bot.finish(ev,
    f'''
    当前竞技场绑定ID：{info['id']}
    竞技场订阅：{'开启' if info['arena_on'] else '关闭'}
    公主竞技场订阅：{'开启' if info['grand_arena_on'] else '关闭'}''',at_sender=True)


#@sv.scheduled_job('interval', minutes=1)
@sv.scheduled_job('cron', second=0)
async def on_arena_schedule():
    global binds, lck
    if not await should_check(interval=2,hot_interval=1):
        sv.logger.info(f'Skip rank query')
        return

    bot = get_bot()

    bind_cache = {}

    async with lck:
        bind_cache = deepcopy(binds)


    for user in bind_cache:
        info = bind_cache[user]
        try:
            sv.logger.info(f'querying {info["id"]} for {info["uid"]}')
            res = await query(info['id'])
            res = (res['arena_rank'], res['grand_arena_rank'])

            last = cache_db.get_user_rank(user)
            cache_db.cache_user_rank(user, res)
            if not last:
                continue
            #if user not in cache:
            #    cache[user] = res
            #    continue
            #
            #last = cache[user]
            #cache[user] = res

            if res[0] > last[0] and info['arena_on']:
                await bot.send_group_msg(
                    group_id = int(info['gid']),
                    message = f'[CQ:at,qq={info["uid"]}]jjc：{last[0]}->{res[0]} ▼{res[0]-last[0]}'
                )

            if res[1] > last[1] and info['grand_arena_on']:
                await bot.send_group_msg(
                    group_id = int(info['gid']),
                    message = f'[CQ:at,qq={info["uid"]}]pjjc：{last[1]}->{res[1]} ▼{res[1]-last[1]}'
                )
        except ApiException as e:
            sv.logger.info(f'对{info["id"]}的检查出错\n{format_exc()}')
            if e.code == 6:

                async with lck:
                    binds.pop(user)
                    save_binds()
                sv.logger.info(f'已经自动删除错误的uid={info["id"]}')
        except:
            sv.logger.info(f'对{info["id"]}的检查出错\n{format_exc()}')

@sv.on_notice('group_decrease.leave')
async def leave_notice(session: NoticeSession):
    global lck, binds
    uid = str(session.ctx['user_id'])

    async with lck:
        if uid in binds:
            binds.pop(uid)
            save_binds()

async def get_user_name(uid):
    info = cache_db.get_user_info(uid)
    if not info or 'user_name' not in info:
        try:
            info = await query(uid)
            cache_db.cache_user_info(uid, info)
            user_name = info['user_name']
        except ApiException as e:
            user_name = None
            sv.logger.info(f'对{id}的检查出错\n{format_exc()}')
    else:
        user_name = info['user_name']
    return user_name

@sv.on_rex(r'^通缉 ?(\d{13})$')
async def on_wanted_bind(bot, ev):
    global wanted_binds, lck
    gid = str(ev['group_id'])
    l = wanted_binds[gid] if gid in wanted_binds else []
    changed = False
    async with lck:
        uid = ev['match'].group(1)
        if len(l) >= 30:
            await bot.finish(ev, '最大通缉上限为25人，请移除部分目标后再添加新目标。', at_sender=True)
            return 
        if uid not in l:
            l.append(uid)
            wanted_binds[gid] = l
            save_wanted_binds()
            changed = True
    user_name = await get_user_name(uid)
    if changed:
        msg = f'通缉 {user_name} 成功' if user_name else '通缉成功'
    else:
        msg = f'{user_name} 已被通缉' if user_name else '目标已被通缉'
    await bot.finish(ev, msg, at_sender=True)


@sv.on_rex(r'^关注 ?(\d{13})$')
async def on_wanted_bind(bot, ev):
    global watch_binds, lck
    gid = str(ev['group_id'])
    w = watch_binds[gid] if gid in watch_binds else []
    changed = False
    async with lck:
        uid = ev['match'].group(1)
        if uid not in w:
            w.append(uid)
            watch_binds[gid] = w
            save_wanted_binds()
            changed = True
    user_name = await get_user_name(uid)
    if changed:
        msg = f'关注 {user_name} 成功' if user_name else '关注成功'
    else:
        msg = f'{user_name} 已被关注' if user_name else '目标已被关注'
    await bot.finish(ev, msg, at_sender=True)



@sv.on_rex(r'^逮捕 ?(\d{13})$')
async def on_arrest_bind(bot, ev):
    global wanted_binds, lck
    gid = str(ev['group_id'])
    l = wanted_binds[gid] if gid in wanted_binds else []
    changed = False
    async with lck:
        uid = ev['match'].group(1)
        if uid in l:
            l.remove(uid)
            wanted_binds[gid] = l
            save_wanted_binds()
            changed = True
    user_name = await get_user_name(uid)
    if changed:
        msg = f'已逮捕通缉犯 {user_name}' if user_name else '已逮捕通缉犯'
    else:
        msg = f'{user_name} 未被通缉' if user_name else '目标未被通缉'
    await bot.finish(ev, msg, at_sender=True)


@sv.on_rex(r'^取关 ?(\d{13})$')
async def on_arrest_bind(bot, ev):
    global watch_binds, lck
    gid = str(ev['group_id'])
    l = watch_binds[gid] if gid in watch_binds else []
    changed = False
    async with lck:
        uid = ev['match'].group(1)
        if uid in l:
            l.remove(uid)
            watch_binds[gid] = l
            save_wanted_binds()
            changed = True
    user_name = await get_user_name(uid)
    if changed:
        msg = f'已取关 {user_name}' if user_name else '已取关'
    else:
        msg = f'{user_name} 未被关注' if user_name else '目标未被关注'
    await bot.finish(ev, msg, at_sender=True)
def check_key(d1: Dict, d2: Dict, key: str) -> bool:
    return key in d1 and key in d1

#@sv.scheduled_job('interval', minutes=1)
@sv.scheduled_job('cron', second=0)
async def on_wanted_schedule():
    global wanted_binds, watch_binds, lck
    if not await should_check():
        sv.logger.info(f'Skip wanted query')
        return

    bot = get_bot()

    wanted_notice = {}

    bind_cache = {}
    watch_cache = {}

    async with lck:
        bind_cache = deepcopy(wanted_binds)
        watch_cache = deepcopy(watch_binds)


    for gid in wanted_binds:
        wanted_list = bind_cache[gid]
        watch_list = watch_cache.get(gid, [])

        scan_list = list(wanted_list)
        scan_list.extend(watch_list)

        for id in scan_list:
            if id in wanted_notice:
                # 其他群已经通缉过了
                msg = wanted_notice[id]
                if msg != '__NOT_CHANGED__':
                    await bot.send_group_msg(
                        group_id = int(gid),
                        message = msg
                    )
                continue
            try:
                sv.logger.info(f'querying wanted {id} for group {gid}')
                res = await query(id)

                watch = id in watch_list

                # 无缓存信息，保存信息就行
                last = cache_db.get_user_info(id)
                cache_db.cache_user_info(id, res)
                if not last:
                    continue
                #if id not in wanted_cache:
                #    wanted_cache[id] = res
                #    continue
                #last = wanted_cache[id]
                #wanted_cache[id] = res

                # 如果最后上线时间和上次的上线时间相差超过三分钟就提醒
                if check_key(res, last, 'last_login_time') and (res['last_login_time'] - last['last_login_time']) > 60*3:
                    time_local = time.localtime(res['last_login_time'])
                    dt = time.strftime("%H:%M",time_local)
                    login_notice =  f'于{dt}上线'
                    wanted_info = '注意逮捕'
                else:
                    login_notice = ''
                    wanted_info = ''

                if check_key(res, last, 'user_name') and res['user_name'] != last['user_name']:
                    change_name_notice = f' 改名为 {res["user_name"]}(UID: {id}) '
                else:
                    change_name_notice = ''

                if res['arena_rank'] != last['arena_rank']:
                    rank_minus = res['arena_rank'] - last['arena_rank']                    
                    change_str = "下降" if rank_minus > 0 else "上升"
                    if rank_minus < 0:
                        # 排名上升，记录为一次进攻
                        cache_db.cache_user_jjc_challenge(id)
                    else:
                        # rank down, still send notice
                        watch = False
                    rank_minus = abs(rank_minus)
                    jjc_noice = f'\njjc：{last["arena_rank"]}->{res["arena_rank"]} {change_str}{rank_minus}名'
                else:
                    jjc_noice = ''

                if res['grand_arena_rank'] != last['grand_arena_rank']:
                    rank_minus = res['grand_arena_rank']-last['grand_arena_rank']
                    change_str = "下降" if rank_minus > 0 else "上升"
                    if rank_minus < 0:
                        # 排名上升，记录为一次进攻
                        cache_db.cache_user_pjjc_challenge(id)
                    else:
                        # rank down, still send notice
                        watch = False
                    rank_minus = abs(rank_minus)
                    pjjc_notice = f'\npjjc：{last["grand_arena_rank"]}->{res["grand_arena_rank"]} {change_str}{rank_minus}名'
                else:
                    pjjc_notice = ''

                if not watch and (login_notice or change_name_notice or jjc_noice or pjjc_notice):
                    last_user_name = last['user_dname'] if 'user_dname' in last else last['user_name'] 
                    msg = f"通缉犯 {last_user_name} " + login_notice + change_name_notice
                    msg += jjc_noice + pjjc_notice
                    if jjc_noice or pjjc_notice:
                        msg += "\n"
                    msg += wanted_info
                    wanted_notice[id] = msg
                    await bot.send_group_msg(group_id = int(gid),
                        message = msg
                    )
                else:
                    wanted_notice[id] = '__NOT_CHANGED__'
            except ApiException as e:
                sv.logger.info(f'对{id}的检查出错\n{format_exc()}')
                if e.code == 6:

                    async with lck:
                        wanted_binds[gid].remove(id)
                        save_wanted_binds()
                    sv.logger.info(f'已经自动删除错误的uid={id}')
            except:
                sv.logger.info(f'对{id}的检查出错\n{format_exc()}')


@sv.on_fullmatch(('通缉犯概要','lswts'))
async def send_arena_sub_status(bot,ev):
    global wanted_binds, lck

    async with lck:
        ids = wanted_binds.get(str(ev['group_id']), [])
        wids = watch_binds.get(str(ev['group_id']), [])
        if wids:
            ids = list(ids)
            ids.append('watch')
            ids.extend(wids)
        try:
            await send_summary(ids, cache_db, bot, ev)
        except ApiException as e:
            await bot.finish(ev, f'查询出错，{e}', at_sender=True)
