from hoshino import Service
from hoshino.typing import CQEvent
import re
import asyncio
import datetime
from . import pjjcdata

sv_help = '''[贴r HH:MM] 在 HH:MM 贴第r名。冒号兼容如下任意符号 .:,。：， 和空格
[强贴r HH:MM] 强行贴第r名。用于修正错误贴和时间误差
[查贴] 查看已经贴的名次和出现的时间
[不可贴] 查询自己不可贴的名次
[我是第r] 指定自己当天的名次为r
[看不见人][可贴] 查询自己可见的名次。如果未指定自己的名次，则返回前10未被贴且自己可见的名次
[代贴r][代强贴r] 代其他人贴第r名。不会让自己对第r名不可见
[消贴r] 删除第r名的贴贴状态但不移除冷却，适用于放贴跑路
'''

sv = Service('贴贴助手', help_=sv_help)
db = pjjcdata.pjjcbot_database()

@sv.on_fullmatch('贴贴帮助', only_to_me=False)
async def send_jjchelp(bot, ev):
    self_ids = bot._wsr_api_clients.keys()
    for sid in self_ids:
        gl = await bot.get_group_list(self_id=sid)
        msg = f"本Bot目前服务群数目{len(gl)}"
    await bot.send(ev, f'{sv_help}\n{msg}')

async def _unlock_rank(bot, ev:CQEvent, *, restore_invisible=False):
    msg = ev.message.extract_plain_text().strip()
    try:
        rank = int(msg)
    except ValueError:
        return
    group_id = ev['group_id']
    db.del_lock_rank(rank, group_id)
    if restore_invisible:
        pass

    await bot.send(ev, f'已取消{rank}的贴贴状态 其他人接住')
    cur = datetime.datetime.now()
    await asyncio.sleep(90)
    if not db.is_exist_in_lock_rank(rank, group_id):
        rt = db.get_user_rank(rank, group_id)
        if rt:
            await bot.send(ev, f'[CQ:at,qq={rt}]已经一分半没有人接你了，赶紧换防吧')
        else:
            await bot.send(ev, f'第{rank}，已经一分半没有人接你了，赶紧换防吧')

@sv.on_prefix(('删贴','消贴'))
async def force_lock_rank(bot, ev:CQEvent):
    await _unlock_rank(bot, ev)

@sv.on_prefix(('误贴','错贴'))
async def force_lock_rank(bot, ev:CQEvent):
    await _unlock_rank(bot, ev, restore_invisible=True)

async def _lock_rank(bot, ev: CQEvent, *, force: bool=False, on_behalf=False):
    msg = ev.message.extract_plain_text().strip()
    res = re.match(r'(\d+)\s+(\d+)[\.\s:,：，。](\d+)', msg)
    if not res:
        return
    group_id = ev['group_id']
    user_id = ev['user_id']
    rank = int(res[1])
    min = int(res[2])
    sec = int(res[3])
    if not force and db.is_exist_in_lock_rank(rank, group_id):
        await bot.send(ev, f'第{rank}正在锁定中，无法被贴', at_sender=True)
        return
    if min < 0 or min > 59 or sec < 0 or sec > 59:
        await bot.send(ev, f'时间格式有误，不能大于59', at_sender=True)
        return
    cur = datetime.datetime.now()
    start = datetime.datetime(cur.year, cur.month, cur.day, cur.hour, min, sec)
    end = start + datetime.timedelta(minutes=3)
    checktime = start + datetime.timedelta(minutes=4.5)
    unlock_end = start + datetime.timedelta(minutes=10)
    if (cur - start) > datetime.timedelta(minutes=2) or (cur - start) < datetime.timedelta(minutes=-1):
        await bot.send(ev, f'贴的时间和当前时间不匹配', at_sender=True)
        return
    await bot.send(ev, f'已记录{rank}将在{end.minute}.{sec}出来')
    db.record_lock_action(rank, user_id, group_id, start)
    db.set_lock_rank(rank, group_id, end)
    if not on_behalf:
        db.add_invisible_rank_for_user(rank, group_id, user_id, unlock_end)
    await asyncio.sleep((end-cur).seconds-10)
    rt = db.get_lock_rank_by_rank(rank, group_id)
    if pjjcdata.str_to_time(rt) != end:
        return
    await bot.send(ev, f'第{rank}还剩10秒出来，准备接住')
    db.del_lock_rank(rank, group_id)

    cur = datetime.datetime.now()
    await asyncio.sleep((checktime-cur).seconds)
    if not db.is_exist_in_lock_rank(rank, group_id):
        rt = db.get_user_rank(rank, group_id)
        if rt:
            await bot.send(ev, f'[CQ:at,qq={rt}]已经一分半没有人接你了，赶紧换防吧')
        else:
            await bot.send(ev, f'第{rank}，已经一分半没有人接你了，赶紧换防吧')


@sv.on_prefix(('强制贴','强贴'))
async def force_lock_rank(bot, ev:CQEvent):
    await _lock_rank(bot, ev, force=True)

@sv.on_prefix('代贴')
async def lock_rank(bot, ev:CQEvent):
    await _lock_rank(bot, ev, on_behalf=True)

@sv.on_prefix('代强贴')
async def lock_rank(bot, ev:CQEvent):
    await _lock_rank(bot, ev, force=True, on_behalf=True)

@sv.on_prefix('贴')
async def lock_rank(bot, ev:CQEvent):
    await _lock_rank(bot, ev)

@sv.on_fullmatch('查贴')
async def get_locked_ranks(bot, ev:CQEvent):
    group_id = ev['group_id']
    msg = ''
    rt = db.get_lock_rank(group_id)
    for k,v in rt.items():
        v = pjjcdata.str_to_time(v)
        msg+='%s %s.%s\n' % (k, v.minute, v.second)
    if msg == '':
        msg = '没有贴贴成员'
    await bot.send(ev, f'{msg}')


@sv.on_fullmatch(('不可贴列表', '不可贴'))
async def get_invisible_rank(bot, ev:CQEvent):
    group_id = ev['group_id']
    user_id = ev['user_id']
    rt = db.get_invisible_rank_for_user(group_id, user_id)
    if not rt:
        await bot.send(ev, '没有您无法锁定的名次', at_sender=True)
        return
    now = datetime.datetime.now()
    msg = '您当前无法锁定的名次为：\n'
    count = 0
    for i in range(0, len(rt), 2):
        v = pjjcdata.str_to_time(rt[i+1])
        if v > now:
            count += 1
            msg+='%s %s.%s\n' % (rt[i], v.minute, v.second)
    if count > 0:
        await bot.send(ev, f'{msg}', at_sender=True)
    else:
        await bot.send(ev, '没有您无法锁定的名次', at_sender=True)

@sv.on_fullmatch(('看不见人', '看不到人', '看不见人了', '看不到人了', '没人了', '可贴'))
async def get_visible_rank(bot, ev:CQEvent):
    group_id = ev['group_id']
    user_id = ev['user_id']
    visibles = db.get_visible_rank_for_user(group_id, user_id)
    if not visibles:
        msg = '当前您可见的名次似乎都已经被贴或者不可贴。请使用“查贴”或者“不可贴”确认情况。'
    else:
        msg = '当前您可见的名次为（实际情况请根据自己的名次判断）：\n' + ' '.join([str(k) for k in visibles])
    await bot.send(ev, f'{msg}', at_sender=True)

@sv.on_prefix('我是第')
async def set_my_rank(bot, ev:CQEvent):
    msg = ev.message.extract_plain_text().strip()
    group_id = ev['group_id']
    user_id = ev['user_id']
    if msg.isdigit():
        rank = int(msg)
        await bot.send(ev, f'已经录您为第{rank}', at_sender=True)
        db.set_user_rank(rank, group_id, user_id)
    else:
        await bot.send(ev, f'格式错误，数字要为阿拉伯数字哦', at_sender=True)


@sv.on_fullmatch('我的名次')
async def get_my_rank(bot, ev:CQEvent):
    msg = ev.message.extract_plain_text()
    group_id = ev['group_id']
    user_id = ev['user_id']
    rt = db.query_user_rank(group_id, user_id)
    if rt:
        await bot.send(ev, f'您是第{rt}', at_sender=True)
    else:
        await bot.send(ev, f'您还没有报过名次', at_sender=True)

