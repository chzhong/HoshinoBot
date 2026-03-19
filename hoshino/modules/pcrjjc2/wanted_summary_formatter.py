"""
wanted_summary_formatter.py - 通缉犯概要格式化器

负责将 WantedSummaryRow 转换为表格渲染所需的格式。
"""

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Final, List, Optional, Protocol, Tuple, Union

from .schema import (
    NOTICE_LEVEL_ATTENTION,
    NOTICE_LEVEL_HIGH,
    NOTICE_LEVEL_HIGH_BEFORE_SETTLEMENT,
    NOTICE_LEVEL_HIGH_TODAY,
    NOTICE_LEVEL_NONE,
)
from .table_image import (
    Cell,
    Header,
    RGBTuple,
    Row,
    StyledText,
    image_to_cq,
    render_table,
)

# 颜色常量
_COLOR_RED_BRICK = (178, 34, 34)  # 红砖色（jjc 表头）
_COLOR_RED_BRICK_LIGHT = (220, 120, 120)  # 浅红砖色（同场背景）
_COLOR_DEEP_BLUE = (25, 25, 112)  # 深蓝色（pjjc 表头）
_COLOR_DEEP_BLUE_LIGHT = (135, 206, 250)  # 浅深蓝色（同场背景）
_COLOR_GRAY = (140, 140, 140)  # 灰色（不通报/佑树公会名）
_COLOR_DARK_GRAY = (96, 96, 96)  # 灰色（不通报/佑树公会名）
_COLOR_TEXT = (30, 30, 30)  # 默认文字色

# ============================================================================
# 字体宽度参数 (字体大小: 15px, NotoSansMonoCJKsc-VF + NotoEmoji-VariableFont)
# 如果更换字体，需要重新运行 test_char_width.py 测量并更新这些参数
# ============================================================================
_SPACE_WIDTH: Final = 8  # 空格宽度 (px)
_CHINESE_WIDTH: Final = 15  # 汉字宽度 (px)
_EMOJI_WIDTH: Final = 19  # Emoji宽度 (emoji字体, px)


# 静音emoji偏移量
# 当前面没有emoji时: "123次" + " 🔇"
# 需要让 "🔇" 与 "次" 对齐
# 计算: (3*8 + 15) - (39 + 8) = 39 - 47 = -8
# 但实际测量发现 -4 效果更好（可能是emoji渲染的边距）
_GRID_UNIT: Final = max(_CHINESE_WIDTH, _EMOJI_WIDTH)


def _calc_mute_params(w: int) -> Tuple[int, int]:
    if w == _GRID_UNIT:
        return (0, 0)
    else:
        return (1, _GRID_UNIT - (w + _SPACE_WIDTH))


# ============================================================================

MUTE_SIGN: Final = "🔇"
WARN_SIGN: Final = "⚠️"
MINE_SIGN: Final = "⛏️"
DOWN_SIGN: Final = "👇"
BATT_SIGN: Final = "🤺"

_BATTLE3: Final = WARN_SIGN
_BATTLE4: Final = BATT_SIGN
_BATTLE5: Final = WARN_SIGN + BATT_SIGN


class MockNow(Protocol):
    mock_now: Optional[datetime] = None


@dataclass
class WantedSummaryRow:
    """通缉犯概要表格的一行数据。"""

    index: int  # 1-based 编号（群通缉和个人通缉分别编号）
    uid: str
    user_name: str  # 昵称，缓存中无则为 uid
    avatar_unit_name: Optional[str]  # 头像的角色名
    clan_name: Optional[str]  # 公会名

    # 竞技场信息
    arena_group: Optional[int]  # 场号
    arena_rank: Optional[int]  # 排名
    arena_challenges: int  # 上升次数（从 Redis 读取）
    arena_on: bool  # 是否通报 jjc
    arena_mining: bool  # 是否挖矿中

    # 公主竞技场信息
    grand_arena_group: Optional[int]
    grand_arena_rank: Optional[int]
    grand_arena_challenges: int
    grand_arena_on: bool
    grand_arena_mining: bool

    # 上线时间
    last_login_time: int  # Unix 时间戳

    # 备注和通知级别
    note: str
    notice_level: int

    # 是否与命令发送者同场（用于背景色高亮）
    same_arena_group: bool
    same_grand_arena_group: bool
    arena_str: str  # "N场 M名" 或 "-"（兼容纯文本输出）
    grand_arena_str: str


class WantedSummaryFormatter:
    """通缉犯概要格式化器。"""

    def __init__(self, now_hour: int = None):
        """
        :param now_hour: 当前小时（0-23），用于判断是否显示 ⚠️ 标志
        """
        self.now_hour = now_hour if now_hour is not None else time.localtime().tm_hour

    def format_headers(self) -> List[Union[str, Cell]]:
        """生成表头。"""
        return [
            Header(content="#", align="center", min_width="2em"),  # 编号列
            Header(content="昵称", align="center", min_width="20em"),
            Header(
                content="战斗竞技场",
                align="center",
                bg_color=_COLOR_RED_BRICK,
                text_color=(255, 255, 255),
                min_width="18em",  # " " + 场号(3+2) + 排名(5+2) + 次数/标志(3+2) + 标志(2) + " " ≈ 13em
            ),
            Header(
                content="公主竞技场",
                align="center",
                bg_color=_COLOR_DEEP_BLUE,
                text_color=(255, 255, 255),
                min_width="18em",
            ),
            Header(
                content="上线时间", align="center", min_width="13em"
            ),  # "03-16 10:20" + " ?"
            Header(content="UID", align="center", min_width="15em"),  # 13位数字
            Header(content="备注", align="left", min_width="24em"),
        ]

    def format_row(self, row: WantedSummaryRow) -> Row:
        """
        将 WantedSummaryRow 转换为表格行。

        :param row: 通缉犯数据行
        :return: 表格行（Cell 列表）
        """
        return [
            Cell(content=str(row.index), align="center"),  # 编号
            self._format_name_cell(row),
            self._format_arena_cell(row),
            self._format_grand_arena_cell(row),
            self._format_login_time_cell(row),
            Cell(content=row.uid, align="center"),
            self._format_note_cell(row),
        ]

    def _format_name_cell(self, row: WantedSummaryRow) -> Cell:
        """格式化昵称列。"""
        # 如果是佑树（默认名）且有公会名或头像，显示额外信息
        if row.user_name == "佑树" and (row.clan_name or row.avatar_unit_name):
            # 昵称 + 换行 + 工会名（50%字体，灰色）+ 换行 + 头像（50%字体，灰色）
            nickname = StyledText(text=row.user_name)

            if row.clan_name:
                nickname.sup = StyledText(
                    text=f" {row.clan_name}",
                    size=10,
                    text_color=_COLOR_DARK_GRAY,
                )

            if row.avatar_unit_name:
                nickname.sub = StyledText(
                    text=f" {row.avatar_unit_name}头",
                    size=10,
                    text_color=_COLOR_DARK_GRAY,
                )

            return Cell(content=nickname, align="left")

        # 默认：显示昵称，最多10个汉字宽度，超出截断加省略号
        name = row.user_name
        if len(name) > 10:
            name = name[:9] + "…"
        return Cell(content=name, align="left")

    def _format_arena_cell(self, row: WantedSummaryRow) -> Cell:
        bg_color = _COLOR_RED_BRICK_LIGHT if row.same_arena_group else None
        # 通缉等级为 0 或不通报时，使用灰色
        text_color = (
            _COLOR_GRAY
            if (row.notice_level == NOTICE_LEVEL_NONE or not row.arena_on)
            else _COLOR_TEXT
        )
        return self._format_rank_cell(
            row.arena_group,
            row.arena_rank,
            row.arena_mining,
            int(row.arena_challenges),
            row.arena_on,
            bg_color,
            text_color,
        )

    def _format_grand_arena_cell(self, row: WantedSummaryRow) -> Cell:
        """格式化公主竞技场列。"""
        # 背景色：同场时浅深蓝色
        bg_color = _COLOR_DEEP_BLUE_LIGHT if row.same_grand_arena_group else None
        # 通缉等级为 0 或不通报时，使用灰色
        text_color = (
            _COLOR_GRAY
            if (row.notice_level == NOTICE_LEVEL_NONE or not row.grand_arena_on)
            else _COLOR_TEXT
        )

        return self._format_rank_cell(
            row.grand_arena_group,
            row.grand_arena_rank,
            row.grand_arena_mining,
            int(row.grand_arena_challenges),
            row.grand_arena_on,
            bg_color,
            text_color,
        )

    def _format_rank_cell(
        self,
        group: int,
        rank: int,
        mining: bool,
        challenge_count: int,
        report_on: bool,
        bg_color: RGBTuple,
        text_color: RGBTuple,
    ) -> Cell:
        """
        格式化竞技场列。
        格式：场号(75%字体) 排名 上升次数|⛏️|👇 🔇
        使用左对齐+预估总宽度实现"居中"效果。
        """
        group_font_size = 11

        # 构建文本
        parts = []

        # 场号（75%字体，3位数字）
        if group > 0:
            parts.append(
                StyledText(
                    text=f"{group:3d}场",
                    size=group_font_size,
                    text_color=text_color,
                )
            )
        else:
            parts.append(
                StyledText(text="???场", size=group_font_size, text_color=text_color)
            )

        # 排名（5位数字）
        if rank > 0:
            parts.append(
                StyledText(
                    text=f"{rank:5d}名",
                    text_color=text_color,
                )
            )
        else:
            parts.append(StyledText(text="?????名", text_color=text_color))

        last_width = _CHINESE_WIDTH
        # 上升次数 / 标志
        # 使用配置的空格数和emoji，左对齐避免尾部emoji不确定问题
        if mining:
            # 挖矿：N个空格 + emoji
            parts.append("   ")
            parts.append(
                StyledText(text=MINE_SIGN, text_color=text_color, font="emoji.ttf")
            )
            last_width = _EMOJI_WIDTH
        elif rank > 100:
            # 跌出前100：N个空格 + emoji
            parts.append("   ")
            parts.append(
                StyledText(text=DOWN_SIGN, text_color=text_color, font="emoji.ttf")
            )
            last_width = _EMOJI_WIDTH
        elif challenge_count > 0:
            # 上升次数：XXX次
            parts.append(
                StyledText(text=f"{challenge_count:3d}次", text_color=text_color)
            )
        else:
            # 无变化：5个空格
            parts.append("     ")

        # 不通报标志（emoji字体）
        # 逻辑：
        # - 如果前面用了emoji，直接输出静音emoji（两个emoji放一起很自然）
        # - 如果前面没用emoji，会少4px，先输出1个空格（多8px），再把静音emoji向左偏移4px
        #   这样总偏移 = -4 + 8 = +4px，刚好对齐
        if not report_on:
            (spaces, mute_dx) = _calc_mute_params(last_width)
            if spaces:
                parts.append(" ")
            parts.append(
                StyledText(
                    text=MUTE_SIGN,
                    text_color=text_color,
                    font="emoji.ttf",
                    dx=mute_dx,
                )
            )

        # 使用左对齐，让内容自然排列
        return Cell(content=parts, align="left", bg_color=bg_color)

    def _format_login_time_cell(self, row: WantedSummaryRow) -> Cell:
        """格式化上线时间列。"""
        if row.last_login_time == 0:
            return Cell(content="-", align="center")

        # 计算距离现在的时间
        now = time.time()
        hours_ago = (now - row.last_login_time) / 3600

        # 转换为本地时间
        login_time = time.localtime(row.last_login_time)
        current_date = time.strftime("%m-%d", login_time)

        # 格式化时间
        # 第一行固定显示日期+时间，后续的行仅有自然日不同时才显示日期
        if row.index == 1:
            # 第一行：显示完整的日期+时间
            time_str = time.strftime("%m-%d %H:%M", login_time)
        else:
            # 后续行：只显示时间，除非日期不同
            if not hasattr(self, "_last_date") or self._last_date != current_date:
                # 日期不同，显示完整的日期+时间
                time_str = time.strftime("%m-%d %H:%M", login_time)
            else:
                # 日期相同，只显示时间
                time_str = time.strftime("      %H:%M", login_time)

        # 记录当前日期，供下一行使用
        self._last_date = current_date

        # 48小时以上未上线，添加 ? 标志
        if hours_ago > 48:
            content = [time_str, " ?"]
        else:
            content = time_str

        return Cell(content=content, align="center")

    def _format_note_cell(self, row: WantedSummaryRow) -> Cell:
        """格式化备注列。"""
        parts = []

        now_hour = self.now_hour
        if isinstance(mock_now := getattr(row, "mock_now", None), datetime):
            now_hour = mock_now.hour

        # 备注文字
        if row.note:
            parts.append(row.note)

        sign = ""

        # 通知级别标志
        if row.notice_level == NOTICE_LEVEL_NONE:
            sign = MUTE_SIGN
        elif row.notice_level == NOTICE_LEVEL_ATTENTION:
            # 14:00～14:59 期间显示 ⚠️
            if now_hour == 14:
                sign = WARN_SIGN
        elif row.notice_level == NOTICE_LEVEL_HIGH_BEFORE_SETTLEMENT:
            # 14:00～14:59 期间显示 ⚠️🤺
            if now_hour == 14:
                sign = _BATTLE3
        elif row.notice_level == NOTICE_LEVEL_HIGH_TODAY:
            # 次日05:00之前显示 ⚠️🤺🤺⚠️
            # 简化判断：假设当前是同一天
            sign = _BATTLE4
        elif row.notice_level == NOTICE_LEVEL_HIGH:
            sign = _BATTLE5

        if sign:
            parts.append(StyledText(text=sign, font="emoji.ttf"))

        return Cell(content=parts, align="left")


def render_wanted_summary(
    group_rows: List[WantedSummaryRow],
    personal_rows: List[WantedSummaryRow],
    now_hour: int = None,
):
    """
    渲染通缉犯概要为图片对象。

    :param group_rows: 群通缉行列表
    :param personal_rows: 个人通缉行列表
    :param now_hour: 当前小时（用于判断标志显示）
    :return: PIL Image 对象
    """

    formatter = WantedSummaryFormatter(now_hour=now_hour)

    # 构建表格数据
    headers = formatter.format_headers()
    rows = []

    # 群通缉部分
    if group_rows:
        # 添加分组标题行（跨7列，因为添加了编号列）
        rows.append(
            [Cell(content=f"群通缉（{len(group_rows)}人）", colspan=7, align="center")]
        )
        # 添加数据行
        for row in group_rows:
            rows.append(formatter.format_row(row))

    # 个人通缉部分
    if personal_rows:
        # 添加分组标题行（跨7列，因为添加了编号列）
        rows.append(
            [
                Cell(
                    content=f"个人通缉（{len(personal_rows)}人）",
                    colspan=7,
                    align="center",
                )
            ]
        )
        # 添加数据行
        for row in personal_rows:
            rows.append(formatter.format_row(row))

    # 渲染表格（使用 min_rows 参数确保至少有5行数据）
    return render_table(headers=headers, rows=rows, min_rows=5)


def render_wanted_summary_as_cq(
    group_rows: List[WantedSummaryRow],
    personal_rows: List[WantedSummaryRow],
    now_hour: int = None,
) -> str:
    """
    渲染通缉犯概要为 CQ 码图片。

    :param group_rows: 群通缉行列表
    :param personal_rows: 个人通缉行列表
    :param now_hour: 当前小时（用于判断标志显示）
    :return: CQ 码字符串
    """

    if not group_rows and not personal_rows:
        return "暂无通缉犯"

    img = render_wanted_summary(group_rows, personal_rows, now_hour)

    # 转换为 CQ 码
    return image_to_cq(img)
