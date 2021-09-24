import os.path
from typing import Union

import pytz
import json
import random
from datetime import date, datetime, timedelta
from hoshino import util
from hoshino import R
from hoshino.priv import check_priv, SUPERUSER
from hoshino.service import Service, priv

sv_help = '''
未成年解放提醒的说
'''.strip()

sv = Service(
    name='解封提醒',  # 功能名
    use_priv=priv.NORMAL,  # 使用权限
    manage_priv=priv.ADMIN,  # 管理权限
    visible=True,  # False隐藏
    enable_on_default=False,  # 是否默认启用
    bundle='订阅',  # 属于哪一类
    help_=sv_help  # 帮助文本
)


def atqq(qqid):
    return f'[CQ:at,qq={qqid}]'


def week_to_date(now: datetime, parsed: datetime) -> date:
    dow_now = now.isoweekday()
    dow_parsed = parsed.isoweekday()
    if dow_parsed < dow_now:
        dow_parsed += 7
    return now.date() + timedelta(days=dow_parsed - dow_now)


def prepend_years(now: datetime, parsed: datetime) -> date:
    return now.date().replace(month=parsed.month, day=parsed.day)


DATE_PATTERNS = [
    ('%m/%d', prepend_years), ('%m-%d', prepend_years),
    ('%y/%m%/%d', lambda n, p: p.date()), ('%y-%m-%d', lambda n, p: p.date()),
    ('%Y/%m%/%d', lambda n, p: p.date()), ('%Y-%m-%d', lambda n, p: p.date())
]


def parse_date(s: str, now: datetime = None) -> date:
    now = now if now else datetime.now()
    for pattern, converter in DATE_PATTERNS:
        try:
            parsed = datetime.strptime(s, pattern)
            return converter(now, parsed)
        except ValueError:
            continue
    raise ValueError('不支持的日期格式：' + s)


class SealConfig:

    def __init__(self, path='config.json'):
        self._load_config(path)

    def _load_config(self, path='config.json'):
        self.path = path
        if os.path.exists(path):
            with open(path, 'r') as fp:
                config = json.load()
        else:
            config = {}
        exceptions = config.get('exceptions', {})
        self.black_dates = exceptions.get('black_dates', [])
        self.free_dates = exceptions.get('free_dates', [])
        self.seals = config.get('seals', {})

    def reload_config(self, path='config.json'):
        self._load_config(path)

    def save_config(self):
        with open(self.path, 'w') as fp:
            config = {
                'exceptions': {
                    'black_dates': self.black_dates,
                    'free_dates': self.free_dates
                },
                'seals': self.seals
            }
            json.dump(config, fp)

    def add_seal(self, gid: str, qqid: str, delegate=None, delegate_days=None):
        group_config = self.seals.get(gid, {})
        if qqid in seal:
            seal_config = group_config[qqid]
        else:
            seal_config = {}
        if delegate:
            seal_config['delegate'] = delegate
            if delegate_days:
                seal_config['delegate_days'] = delegate_days
            elif 'delegate_days' in seal_config:
                del seal_config['delegate_days']
        elif 'delegate' in seal_config:
            del seal_config['delegate']
            if 'delegate_days' in seal_config:
                del seal_config['delegate_days']
        group_config[qqid] = seal_config
        self.seals[gid] = group_config
        self.save_config()
        if delegate and delegate_days:
            return f'{atqq(qqid)} ({atqq(qqid)} 于每周 {",".join(delegate_days)} 代理)'
        elif delegate:
            return f'{atqq(qqid)} ({atqq(qqid)} 代理)'
        else:
            return atqq(qqid)

    def remove_seal(self, gid: str, qqid: str):
        if gid not in self.seals:
            return
        group_config = self.seals[gid]
        if qqid not in group_config:
            return
        del group_config[qqid]
        if not group_config:
            del self.seals[gid]
        self.save_config()

    def add_black_date(self, s, now=None):
        black_date = parse_date(s, now).strftime('%Y-%m-%d')
        changed = False
        if black_date in self.free_dates:
            self.free_dates.remove(black_date)
            changed = True
        if black_date not in self.black_dates:
            self.black_dates.append(black_date)
            changed = True
        if changed:
            self.save_config()
        return changed

    def add_free_date(self, s, now=None):
        free_date = parse_date(s, now).strftime('%Y-%m-%d')
        changed = False
        if free_date not in self.free_dates:
            self.free_dates.append(free_date)
            changed = True
        if free_date in self.black_dates:
            self.black_dates.remove(free_date)
            changed = True
        if changed:
            self.save_config()
        return changed

    def clean_dates(self):
        today = date.today()
        self.free_dates[:] = filter(lambda d: datetime(d, '%Y-%m-%d').date() >= today, self.free_dates)
        self.black_dates[:] = filter(lambda d: datetime(d, '%Y-%m-%d').date() >= today, self.black_dates)

    def _at_sealed(self, dow: int, free_day, qqid, seal_config):
        if 'delegate' not in seal_config:
            return atqq(qqid)
        else:
            delegate = seal_config['delegate']
            delegate_days = seal_config.get('delegate_days', [])
            should_delegate = not free_day and dow in delegate_days
            if should_delegate:
                return f'{atqq(delegate)}(代 {atqq(qqid)})'
            else:
                return atqq(qqid)

    def get_ats(self, dow: int, free_day):
        ats = []
        for gid, group_config in self.seals:
            group_ats = []
            group_at_config = {'gid': gid, 'ats': group_ats}
            for qqid, seal_config in group_config:
                group_ats.append(self._at_sealed(dow, free_day, qqid, seal_config))
            group_at_config['ats'] = group_ats
            ats.append(group_at_config)
        return ats

    def is_relax_day(self, now: datetime = None):
        now = now if now else datetime.now()
        day = now.strftime('%Y-%m-%d')
        dow = now.isoweekday()
        if day in self.black_dates:
            return False, day, dow, None
        if day in self.free_dates:
            return True, day, dow, True
        return dow in (5, 6, 7), day, dow, False


_CONFIG: Union[SealConfig, None] = None


def load_config() -> SealConfig:
    global _CONFIG
    if not _CONFIG:
        _CONFIG = SealConfig()
    return _CONFIG


@sv.on_fullmatch(["帮助解封提醒"])
async def bangzhu(bot, ev):
    await bot.send(ev, sv_help, at_sender=True)


@sv.on_prefix(["封印"])
async def seal(bot, ev):
    gid = str(ev.group_id)
    sid = None
    delegate = None
    days = ev.message.extract_plain_text()
    delegate_days = None
    for m in ev.message:
        if m.type == 'at' and m.data['qq'] != 'all':
            if sid is None:
                sid = m.data['qq']
            elif delegate is None:
                delegate = m.data['qq']
        elif m.type == 'at' and m.data['qq'] == 'all':
            continue
    if delegate and days and days.strip():
        delegate_days = list(map(int, days.split(',')))
    if sid is None:
        await bot.send(ev, '请@需要封印的群员哦w')
        return
    config = load_config()
    config.add_seal(gid, sid, delegate, delegate_days)


@sv.on_prefix(["解封"])
async def unseal(bot, ev):
    gid = str(ev.group_id)
    ats = []
    sids = []
    for m in ev.message:
        if m.type == 'at' and m.data['qq'] != 'all':
            sids.append(m.data['qq'])
            ats.append(atqq(m.data['qq']))
    config = load_config()
    for sid in sids:
        config.remove_seal(gid, sid)
    await bot.send(ev, '已解封 ' + ' '.join(ats))


@sv.on_prefix(["强化结界"])
async def add_black(bot, ev):
    text = str(ev.message).strip()
    if not text:
        await bot.send(ev, "格式：强化结界 (年/)月/日", at_sender=True)
        return
    cfg = load_config()
    try:
        cfg.add_black_date(text)
    except ValueError as e:
        await bot.send(ev, str(e) + "\n格式：强化结界 (年/)月/日", at_sender=True)
        return


@sv.on_prefix(["削弱结界"])
async def add_free(bot, ev):
    text = str(ev.message).strip()
    if not text:
        await bot.send(ev, "格式：削弱结界 (年/)月/日", at_sender=True)
        return
    cfg = load_config()
    try:
        cfg.add_free_date(text)
    except ValueError as e:
        await bot.send(ev, str(e) + "\n格式：削弱结界 (年/)月/日", at_sender=True)
        return


def get_hour_call():
    """从HOUR_CALLS中挑出一组时报，每日更换，一日之内保持相同"""
    config = util.load_config(__file__)
    now = datetime.now(pytz.timezone('Asia/Shanghai'))
    hc_groups = config["HOUR_CALLS"]
    g = hc_groups[now.day % len(hc_groups)]
    return config[g]


@sv.scheduled_job('cron', hour='20')
async def hour_call():
    now = datetime.now(pytz.timezone('Asia/Shanghai'))
    if not now.hour == 20:
        return
    config = load_config()
    relax_day, _, dow, free_day = config.is_relax_day(now)
    if not relax_day:
        return
    ats = config.get_ats(dow, free_day)
    if not ats:
        return
    for group_at_config in ats:
        group_ats = group_at_config['ats']
        if not group_ats:
            continue
        gid = group_at_config['gid']
        await sv.bot.send_group_msg(int(gid), '封印已经解除，孩子们可以稍微放松一下了。' + ' '.join(group_ats)
        + str(R.img(f"children_release{random.randint(1, 4)}.jpg").cqcode))
