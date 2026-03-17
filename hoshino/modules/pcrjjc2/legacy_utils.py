import os
import string
import base64
import time
from io import BytesIO
from typing import Tuple, Dict

from PIL import Image, ImageFont, ImageDraw
from pillowdrawtable.drawtable import Drawtable
#from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot import MessageSegment

FILE_PATH = os.path.dirname(__file__)
FONTS_PATH = os.path.join(FILE_PATH, 'fonts')
FONTS = os.path.join(FONTS_PATH, 'msyh.ttf')
MONO_FONT = os.path.join(FONTS_PATH, 'mono.ttf')


def text_2_pic(text: string, weight: int = 120, height: int = 160, bg_color: Tuple = (255, 255, 255),
               text_color: string = "#000000", font_size: int = 14, text_offset: Tuple = (4, 4)):
    im = Image.new("RGB", (weight, height), bg_color)
    dr = ImageDraw.Draw(im)
    font = ImageFont.truetype(MONO_FONT, font_size)
    dr.text(text_offset, text, font=font, fill=text_color)
    bio = BytesIO()
    im.save(bio, format='PNG')
    base64_str = 'base64://' + base64.b64encode(bio.getvalue()).decode()
    return f"[CQ:image,file={base64_str}]"


def table_2_pic(lines, width, height):
    text_font = ImageFont.truetype(MONO_FONT, 14)
    header_font = ImageFont.truetype(MONO_FONT, 16)
    im = Image.new("RGB", (width, height), (255, 255, 255))
    dr = ImageDraw.Draw(im)
    table = Drawtable(data=lines, x=10, xend=20+width, y=5,
            font=text_font, line_spacer=5, margin_text=4, drawsheet=dr, 
            image_width=width, image_height=height, frame=True, 
            grid=True, columngrid=False, rowgrid=False, header=True, 
            text_color='black', header_color='black', headerfont=header_font
            )
    table.draw_table()
    bio = BytesIO()
    im.save(bio, format='PNG')
    base64_str = 'base64://' + base64.b64encode(bio.getvalue()).decode()
    return f"[CQ:image,file={base64_str}]"


def cycle_num(n: int) -> str:
    if n <= 0 or n > 20:
        return str(n)
    if 1 <= n <= 20:
        # ① (\u2460) ~ ⑳ (\u2473)
        return chr(0x2460 + n - 1)


class WantedSummary(object):

    def summary_header(self):
        raise NotImplemented

    def watch_header(self):
        raise NotImplemented

    def no_info_item(self, uid, seq):
        raise NotImplemented

    def wanted_item(self, uid, wanted_info, seq):
        raise NotImplemented

    def summarize_partial(self, parts, **kwargs):
        return '\n'.join(parts).strip()

    async def send_partial(self, data, bot, ev):
        await bot.send_group_msg(group_id=ev['group_id'], message=data)

    def __init__(self):
        pass

    async def process(self, wanted_ids, wanted_db, bot, ev, batch_size: int = None):
        msg = self.summary_header()
        seq = 0
        n = len(wanted_ids)
        print(f'Processing {n} wanted summary...\n')
        watch = False
        for uid in wanted_ids:
            if 'watch' == uid:
                watch = True
                continue
            seq += 1
            res = wanted_db.get_user_info(uid)
            if not res:
                msg.append(self.no_info_item(uid, seq))
            else:
                res['watch'] = watch
                msg.append(self.wanted_item(uid, res, seq))
            if batch_size and seq % batch_size == 0:
                print('Send partial...')
                data = self.summarize_partial(msg, offset=seq-len(msg), limit=batch_size, total=n)
                msg = []
                await self.send_partial(data, bot, ev)
        if msg:
            print('Sending last part...')
            data = self.summarize_partial(msg, offset=seq-len(msg), limit=batch_size, total=n)
            await self.send_partial(data, bot, ev)


class GroupForwardSummary(WantedSummary):

    @staticmethod
    def _new_forward_msg_item(content, uin='413209404', name='贴贴助手', seq=0):
        return {
            'type': 'node',
            'data': {
                'name': name,
                'uin': uin,
                'content': [MessageSegment.text(content)]
            }
        }

    def summary_header(self):
        return [self._new_forward_msg_item('本群关注人员状态：')]

    def watch_header(self):
        return [self._new_forward_msg_item('本群小号状态：')]

    def no_info_item(self, uid, seq):
        raise self._new_text_msg_item('状态未更新', name=f'目标犯: (UID: {uid}) ')

    def wanted_item(self, uid, wanted_info, seq):
        return self._new_forward_msg_item(
            f'''上线: {time.strftime("%m-%d %H:%M:%S", time.localtime(wanted_info['last_login_time']))} 
战斗{cycle_num(wanted_info['arena_group'])}：{wanted_info['arena_rank']} 上升{wanted_info['arena_challenge']}次
公主{cycle_num(wanted_info['grand_arena_group'])}：{wanted_info['grand_arena_rank']} 上升{wanted_info['grand_arena_challenge']}次''',
            name=f"> {wanted_info['user_dname']} ({uid}) <",
            uin=uid,
            seq=seq)

    async def process(self, wanted_ids, wanted_db, bot, ev, batch_size: None = None):
        await WantedSummary.process(self, wanted_ids, wanted_db, bot, ev, batch_size=None)

    def summarize_partial(self, parts, **kwargs):
        return parts

    async def send_partial(self, data, bot, ev):
        #res_id = await bot.call_action("send_forward_msg", messages=data)
        #await bot.send_group_msg(group_id=ev['group_id'], messages=MessageSegment.forward(res_id))
        await bot.send_group_forward_msg(group_id=ev['group_id'], messages=data)



class PlainMessageSummary(WantedSummary):

    @staticmethod
    def _new_text_msg_item(content, uin='', name='', seq=0):
        if name:
            return f'{name}\n{content}'
        else:
            return content

    async def process(self, wanted_ids, wanted_db, bot, ev, batch_size: int = 2):
        await WantedSummary.process(self, wanted_ids, wanted_db, bot, ev, batch_size)

    def summary_header(self):
        return ['本群关注人员状态：']

    def summary_header(self):
        return ['本群小号状态：']

    def no_info_item(self, uid, seq):
        raise self._new_text_msg_item('状态未更新', name=f'目标犯: (UID: {uid}) ')

    def wanted_item(self, uid, wanted_info, seq):
        return self._new_text_msg_item(
            f'''上线: {time.strftime("%m-%d %H:%M:%S", time.localtime(wanted_info['last_login_time']))} 
战斗{cycle_num(wanted_info['arena_group'])}：{wanted_info['arena_rank']} 上升{wanted_info['arena_challenge']}次
公主{cycle_num(wanted_info['grand_arena_group'])}：{wanted_info['grand_arena_rank']} 上升{wanted_info['grand_arena_challenge']}次''',
            name=f"> {wanted_info['user_dname']} ({uid}) <",
            uin=uid,
            seq=seq)


class ImageSummary(PlainMessageSummary):

    async def process(self, wanted_ids, wanted_db, bot, ev, batch_size: int = 10):
        await PlainMessageSummary.process(self, wanted_ids, wanted_db, bot, ev, batch_size)

    def summarize_partial(self, parts, **kwargs):
        text = '\n'.join(parts).strip()
        n = text.count('\n')
        return text_2_pic(text, 400, (n + 2)*30, font_size=16, text_offset=(4, 4))


class TableImageSummary(WantedSummary):

    HEADER = (
        "目标",
        # gg场 xyz名 n次 #
        "   战斗竞技场   ",
        "   公主竞技场   ",
        # MM-dd HH:mm:ss #
        "    上线时间     ",
        # 0123456789abc #
        "      UID      ",
        " 备注"
    )

    @staticmethod
    def get_remark(res):
        dname = TableImageSummary.dname_to_remark(res)
        watch = res.get('watch', False)
        if watch:
            return '关注号 ' + dname
        else:
            return dname

    @staticmethod
    def dname_to_remark(res):
        if res['user_name'] != '佑树':
            return ''
        dname = res['user_dname']
        if not dname:
            return ''
        return dname[2:].strip()


    @staticmethod
    def format_wanted_status(uid, res: Dict):
        target = res['user_name']
        arena_info = ' {0:>2}场 {1:>3}名 {2:>2}次 ' \
            .format(res['arena_group'], res['arena_rank'], res['arena_challenge'])
        grand_arena_info = ' {0:>2}场 {1:>3}名 {2:>2}次 ' \
            .format(res['grand_arena_group'], res['grand_arena_rank'], res['grand_arena_challenge'])
        login_time = time.strftime(" %m-%d %H:%M:%S ", time.localtime(res['last_login_time']))
        remark = TableImageSummary.get_remark(res)
        return target, arena_info, grand_arena_info, login_time, f" {uid} ", remark


    @staticmethod
    def wanted_to_table(lines, **kwargs):
        offset = kwargs.get('offset', None)
        limit = kwargs.get('limit', None)
        total = kwargs.get('total', None)
        if offset is not None and limit is not None and total is not None:
            if total <= limit:
                title = '目标 ({0:>2})'.format(total)
            else:
                title = '目标 ({0:>2}-{1:>2}/{2:>2})'.format(offset+1, min(offset+limit, total), total)
            header = list(TableImageSummary.HEADER)
            header[0] = title
        else:
            header = TableImageSummary.HEADER
        lines = list(lines)
        lines.insert(0, header)
        n = len(lines)
        return table_2_pic(lines, 840, n * 23)

    @staticmethod
    def wanted_to_image(lines):
        lines = list(lines)
        lines.insert(0, TableImageSummary.HEADER)
        text = '\n'.join(lines).strip()
        n = text.count('\n')
        return text_2_pic(text, 780, 8 + (n + 2) * 22, font_size=16, text_offset=(4, 4))

    async def process(self, wanted_ids, wanted_db, bot, ev, batch_size: int = 30):
        await WantedSummary.process(self, wanted_ids, wanted_db, bot, ev, batch_size)

    def summary_header(self):
        return []

    def summary_header(self):
        return []

    def no_info_item(self, uid, seq):
        return f'({uid})', '?', '?', '?', f" {uid} ", '状态未更新'

    def wanted_item(self, uid, wanted_info, seq):
        return self.format_wanted_status(uid, wanted_info)

    def summarize_partial(self, parts, **kwargs):
        return self.wanted_to_table(parts, **kwargs)


async def send_summary(wanted_ids, wanted_db, bot, ev):
    processor = SummaryProcessor()
    await processor.process(wanted_ids, wanted_db, bot, ev)


#SummaryProcessor = ImageSummary
#SummaryProcessor = GroupForwardSummary
SummaryProcessor = TableImageSummary

