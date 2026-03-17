"""
table_image.py - 通用图片表格生成模块

用法::

    from .table_image import render_table

    img_cqcode = render_table(
        headers=["编号", "昵称", "UID"],
        rows=[
            ["1", "用户A", "1012345678901"],
            ["2", "用户B", "1012345678902"],
        ]
    )

返回值为 CQ 码字符串，可直接发送。

支持富文本::

    from .table_image import Cell, StyledText, styled

    # 链式 builder
    rows = [[
        Cell(content=styled("100").color((200,50,50)).bold().done(), align="right"),
        "普通文字",
    ]]

    # StyledText 直接作为单元格内容
    rows = [[ StyledText("警告", bold=True, text_color=(200,50,50)), "内容" ]]

    # 多段拼接（列表）
    rows = [[
        Cell(content=[StyledText("▼", text_color=(220,50,50)), "10"], align="right"),
    ]]
"""

import base64
import os
from dataclasses import dataclass, field
from io import BytesIO
from typing import Final, List, Literal, Optional, Sequence, Tuple, Union

from PIL import Image, ImageDraw, ImageFont
from typing_extensions import TypeAlias

RGBTuple: TypeAlias = Tuple[int, int, int]

Color: TypeAlias = Union["RGB", RGBTuple]


@dataclass
class RGB:
    r: int
    g: int
    b: int

    def as_tuple(self) -> RGBTuple:
        return (self.r, self.g, self.b)


def _to_tuple(c: Color) -> RGBTuple:
    if isinstance(c, RGB):
        return c.as_tuple()
    return c


@dataclass
class StyledText:
    text: str
    font: Optional[str] = None  # 字体文件路径，None 则继承上下文
    size: Optional[float] = None  # 字号，None 则继承上下文
    text_color: Optional[Color] = None  # 前景色，None 则继承上下文
    bg_color: Optional[Color] = None  # 背景色，None 则继承上下文
    bold: Optional[bool] = None  # 粗体（需对应字体文件支持）
    italic: Optional[bool] = None  # 斜体（保留字段，暂未实现）
    underline: Optional[bool] = None  # 下划线
    linethrough: Optional[bool] = None  # 删除线
    dx: Optional[int] = None  # X轴偏移（像素），用于微调位置
    dy: Optional[int] = None  # Y轴偏移（像素），用于微调位置
    sub: Union["Text", Sequence["Text"], None] = None  # 下标
    sup: Union["Text", Sequence["Text"], None] = None  # 上标


class _StyledTextBuilder:
    """链式 builder，via styled(text)."""

    def __init__(self, text: str):
        self._st = StyledText(text=text)

    def color(self, c: Color) -> "_StyledTextBuilder":
        self._st.text_color = c
        return self

    def bg(self, c: Color) -> "_StyledTextBuilder":
        self._st.bg_color = c
        return self

    def bold(self, v: bool = True) -> "_StyledTextBuilder":
        self._st.bold = v
        return self

    def size(self, s: float) -> "_StyledTextBuilder":
        self._st.size = s
        return self

    def underline(self, v: bool = True) -> "_StyledTextBuilder":
        self._st.underline = v
        return self

    def done(self) -> StyledText:
        return self._st


def styled(text: str) -> _StyledTextBuilder:
    """构造 StyledText 的链式 builder。用 .done() 取得 StyledText。"""
    return _StyledTextBuilder(text)


Text: TypeAlias = Union[str, StyledText]
HorizontalAlign: TypeAlias = Literal["left", "center", "right", "start", "end"]
VerticalAlign: TypeAlias = Literal["baseline", "top", "middle", "bottom"]


@dataclass
class Cell:
    content: Union[Text, Sequence[Text]]
    align: Optional[HorizontalAlign] = None
    valign: Optional[VerticalAlign] = None
    colspan: Optional[int] = None
    rowspan: Optional[int] = None  # 保留字段，暂未实现
    text_color: Optional[Color] = None  # 文本颜色，None 则继承上下文
    bg_color: Optional[Color] = None  # 背景色，None 则继承上下文
    text_font: Optional[str] = None  # 字体文件路径，None 则继承上下文
    text_size: Optional[float] = None  # 字号，None 则继承上下文
    min_width: Optional[str] = None  # 最小宽度，如 "10em" 表示10个字符宽度


@dataclass
class Header(Cell):
    min_width: Optional[str] = None  # 最小宽度，如 "10em" 表示10个字符宽度


CellLike: TypeAlias = Union[Text, Cell]
HeaderLike: TypeAlias = Union[Text, Cell, Header]

Row: TypeAlias = Sequence[CellLike]
Rows: TypeAlias = Sequence[Row]
Headers: TypeAlias = Sequence[HeaderLike]  # headers 默认粗体样式

_DIR: Final = os.path.dirname(__file__)
_FONT_PATH: Final = os.path.join(_DIR, "fonts", "mono.ttf")
_FALLBACK_FONTS: Final = [
    os.path.join(_DIR, "fonts", "NotoSansMonoCJKsc-VF.ttf"),
    os.path.join(_DIR, "fonts", "sarasa-mono-sc-regular.ttf"),
]

# ── 样式常量 ──────────────────────────────────────────────────
CELL_FONT_SIZE: Final = 15
HEADER_FONT_SIZE: Final = 15
_CELL_PAD_X: Final = 10  # 单元格左右内边距（像素）
_CELL_PAD_Y: Final = 6  # 单元格上下内边距（像素）
_BORDER: Final = 1  # 线宽

_COLOR_BG: Final = (255, 255, 255)
_COLOR_HEADER_BG: Final = (52, 73, 94)
_COLOR_HEADER_FG: Final = (255, 255, 255)
_COLOR_ROW_ODD: Final = (245, 245, 245)
_COLOR_ROW_EVEN: Final = (255, 255, 255)
_COLOR_BORDER: Final = (200, 200, 200)
_COLOR_TEXT: Final = (30, 30, 30)


@dataclass
class _CellLayout:
    """布局阶段计算出的单元格渲染参数。"""

    x: int
    y: int
    w: int  # 含 colspan 合并后的像素宽度
    h: int
    bg: RGBTuple
    align: HorizontalAlign
    valign: VerticalAlign
    # 规范化后的文字段：(text, bg_color, fg_color, font, underline)
    segments: List["_SegmentLayout"] = field(default_factory=list)
    is_header: bool = False


@dataclass
class _SegmentLayout:
    text: str  # 文本
    bg: Optional[RGBTuple]  # 背景色
    fg: RGBTuple  # 前景色
    font: ImageFont.FreeTypeFont  # 字体
    underline: bool = False  # 下划线
    linethrough: bool = False  # 删除线
    dx: int = 0  # X轴偏移（像素）
    dy: int = 0  # Y轴偏移（像素）
    sub: Optional["_SegmentLayout"] = None  # 下标
    sup: Optional["_SegmentLayout"] = None  # 上标


@dataclass
class TableRenderContext:
    """供外部扩展使用的渲染上下文（当前未在核心流程中传递，保留作扩展点）。"""

    draw: ImageDraw.ImageDraw
    image: Image.Image

    font: ImageFont.FreeTypeFont
    header_font: ImageFont.FreeTypeFont
    title_font: ImageFont.FreeTypeFont

    header_row: bool
    row_num: int
    col_num: int
    x: float
    y: float


def get_mono_font(size: Optional[int] = None) -> ImageFont.FreeTypeFont:
    return _load_font(size or CELL_FONT_SIZE)


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in [_FONT_PATH] + _FALLBACK_FONTS:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _text_font(
    font_path: str, font_size: Union[int, float, None]
) -> ImageFont.FreeTypeFont:
    try:
        font_path = (
            font_path
            if os.path.isabs(font_path)
            else os.path.join(_DIR, "fonts", font_path)
        )

        if not os.path.exists(font_path):
            print("****** Cannot load font at:", font_path)
            return None
        sz = int(font_size) if font_size else CELL_FONT_SIZE
        return ImageFont.truetype(font_path, sz)
    except Exception as ex:
        print("****** Load font failed:", font_path, ex)
        return None


def _text_width(text: str, font: ImageFont.FreeTypeFont) -> int:
    """返回文本渲染宽度（兼容 Pillow 新旧 API）。"""
    try:
        return int(font.getlength(text))
    except AttributeError:
        return font.getsize(text)[0]


def _text_height(font: ImageFont.FreeTypeFont) -> int:
    """返回字体行高。"""
    try:
        ascent, descent = font.getmetrics()
        return ascent + descent
    except AttributeError:
        return font.getsize("Ag")[1]


def _normalize_segments(
    content: Union[Text, Sequence[Text]],
    default_bg: Optional[RGBTuple],
    default_fg: RGBTuple,
    default_font: ImageFont.FreeTypeFont,
) -> List[_SegmentLayout]:
    """
    将 content（str / StyledText / 列表）规范化为
    [(text, bg_color, fg_color, font, underline), ...] 列表。
    bg_color 为 None 表示使用单元格背景色。
    """
    if isinstance(content, (str, StyledText)):
        items: List[Text] = [content]
    else:
        items = list(content)

    result = []
    for item in items:
        if isinstance(item, str):
            result.append(_SegmentLayout(item, default_bg, default_fg, default_font))
        else:  # StyledText
            bg = _to_tuple(item.bg_color) if item.bg_color is not None else default_bg
            fg = (
                _to_tuple(item.text_color)
                if item.text_color is not None
                else default_fg
            )
            # 确定主文本字体和路径
            if item.font or item.size:
                try:
                    path = item.font or (
                        _FONT_PATH if os.path.exists(_FONT_PATH) else _FALLBACK_FONTS[0]
                    )
                    sz = int(item.size) if item.size else CELL_FONT_SIZE
                    f = _text_font(path, sz)
                except Exception:
                    f = default_font
                    path = (
                        _FONT_PATH if os.path.exists(_FONT_PATH) else _FALLBACK_FONTS[0]
                    )
            else:
                f = default_font
                path = _FONT_PATH if os.path.exists(_FONT_PATH) else _FALLBACK_FONTS[0]

            # 主文本的实际字体大小（用于计算上下标大小）
            main_font_size = int(item.size) if item.size else CELL_FONT_SIZE

            ul = bool(item.underline)
            dl = bool(item.linethrough)
            dx = item.dx or 0
            dy = item.dy or 0

            # 处理上下标
            sub_seg = None
            sup_seg = None
            if item.sub:
                # 下标：文本大小为主文本的50%，去除换行
                sub_size = main_font_size * 0.5
                if isinstance(item.sub, str):
                    sub_text = item.sub.replace("\n", "").replace("\r", "")
                    sub_fg_color = fg
                    sub_bg_color = bg
                elif isinstance(item.sub, StyledText):
                    sub_text = item.sub.text.replace("\n", "").replace("\r", "")
                    sub_fg_color = (
                        _to_tuple(item.sub.text_color) if item.sub.text_color else fg
                    )
                    sub_bg_color = (
                        _to_tuple(item.sub.bg_color) if item.sub.bg_color else bg
                    )
                    sub_size = item.sub.size if item.sub.size else sub_size
                else:
                    # Sequence[Text] - 暂不支持，取第一个
                    first = item.sub[0] if item.sub else ""
                    if isinstance(first, str):
                        sub_text = first.replace("\n", "").replace("\r", "")
                        sub_fg_color = fg
                        sub_bg_color = bg
                    else:
                        sub_text = first.text.replace("\n", "").replace("\r", "")
                        sub_fg_color = (
                            _to_tuple(first.text_color) if first.text_color else fg
                        )
                        sub_bg_color = (
                            _to_tuple(first.bg_color) if first.bg_color else bg
                        )
                        sub_size = first.size if first.size else sub_size

                sub_font = _text_font(path, sub_size) or f
                sub_seg = _SegmentLayout(sub_text, sub_bg_color, sub_fg_color, sub_font)

            if item.sup:
                # 上标：文本大小为主文本的50%，去除换行
                sup_size = main_font_size * 0.5
                if isinstance(item.sup, str):
                    sup_text = item.sup.replace("\n", "").replace("\r", "")
                    sup_fg_color = fg
                    sup_bg_color = bg
                elif isinstance(item.sup, StyledText):
                    sup_text = item.sup.text.replace("\n", "").replace("\r", "")
                    sup_fg_color = (
                        _to_tuple(item.sup.text_color) if item.sup.text_color else fg
                    )
                    sup_bg_color = (
                        _to_tuple(item.sup.bg_color) if item.sup.bg_color else bg
                    )
                    sup_size = item.sup.size if item.sup.size else sup_size
                else:
                    # Sequence[Text] - 暂不支持，取第一个
                    first = item.sup[0] if item.sup else ""
                    if isinstance(first, str):
                        sup_text = first.replace("\n", "").replace("\r", "")
                        sup_fg_color = fg
                        sup_bg_color = bg
                    else:
                        sup_text = first.text.replace("\n", "").replace("\r", "")
                        sup_fg_color = (
                            _to_tuple(first.text_color) if first.text_color else fg
                        )
                        sup_bg_color = (
                            _to_tuple(first.bg_color) if first.bg_color else bg
                        )
                        sup_size = item.size if item.size else sup_size

                sup_font = _text_font(path, sup_size) or f
                sup_seg = _SegmentLayout(sup_text, sup_bg_color, sup_fg_color, sup_font)

            result.append(
                _SegmentLayout(item.text, bg, fg, f, ul, dl, dx, dy, sub_seg, sup_seg)
            )
    return result


def _segments_width(
    segments: List[_SegmentLayout],
) -> int:
    """
    计算 segments 的总宽度。
    支持多行文本：返回最宽行的宽度。
    支持上下标：上下标宽度取 max(sub_width, sup_width)。
    """
    max_width = 0
    current_line_width = 0

    for seg in segments:
        # 检查是否包含换行符
        lines = seg.text.split("\n")
        for i, line in enumerate(lines):
            if i > 0:
                # 遇到换行，记录当前行宽度，重置
                max_width = max(max_width, current_line_width)
                current_line_width = 0

            line_width = _text_width(line, seg.font)

            # 处理上下标
            if seg.sub or seg.sup:
                sub_width = _text_width(seg.sub.text, seg.sub.font) if seg.sub else 0
                sup_width = _text_width(seg.sup.text, seg.sup.font) if seg.sup else 0
                script_width = max(sub_width, sup_width)
                line_width += script_width

            current_line_width += line_width

    # 记录最后一行
    max_width = max(max_width, current_line_width)
    return max_width


def _segments_height(
    segments: List[_SegmentLayout],
) -> int:
    """
    计算 segments 的总高度。
    支持多行文本：累加所有行的高度。
    """
    if not segments:
        return 0

    total_height = 0
    max_line_height = 0

    for seg in segments:
        lines = seg.text.split("\n")
        font_h = _text_height(seg.font)

        for i, line in enumerate(lines):
            if i > 0:
                # 遇到换行，累加上一行高度
                total_height += max_line_height
                max_line_height = 0

            # 当前行高度
            line_height = font_h

            # 处理上下标（上下标会增加行高）
            if seg.sub or seg.sup:
                sub_h = _text_height(seg.sub.font) if seg.sub else 0
                sup_h = _text_height(seg.sup.font) if seg.sup else 0
                # 上下标各占基准字体高度的一半空间
                line_height += max(sub_h, sup_h) // 2

            max_line_height = max(max_line_height, line_height)

    # 累加最后一行
    total_height += max_line_height
    return total_height


def _cell_content_width(
    content: Union[Text, Sequence[Text]],
    default_fg: RGBTuple,
    default_font: ImageFont.FreeTypeFont,
) -> int:
    return _segments_width(_normalize_segments(content, None, default_fg, default_font))


def _font_ascent(font: ImageFont.FreeTypeFont) -> int:
    """返回字体的 ascent（基线到顶部的距离）。"""
    try:
        ascent, _ = font.getmetrics()
        return ascent
    except AttributeError:
        return font.getsize("Ag")[1]


def _render_segments(
    draw: ImageDraw.ImageDraw,
    segments: List[_SegmentLayout],
    x: int,
    y: int,
) -> None:
    """
    从 (x, y) 起依次绘制各段文字。
    - 支持多行文本（\\n 换行）
    - 支持上下标（sub/sup）
    - 同行各 segment 按基线对齐
    """
    # 先按行分组：将 segments 拆分为行列表，每行是 [(seg, line_text), ...]
    # 同时计算每行的基线高度（行内最大 ascent）
    lines: List[List[tuple]] = [[]]  # 每行是 [(seg, line_text), ...]

    for seg in segments:
        parts = seg.text.split("\n")
        for i, part in enumerate(parts):
            if i > 0:
                lines.append([])
            lines[-1].append((seg, part))

    cy = y  # 当前行的顶部 y

    for line_items in lines:
        if not line_items:
            # 空行：用第一个 segment 的字体高度推进
            if segments:
                cy += _text_height(segments[0].font)
            continue

        # 计算本行的基线位置（相对于行顶部）
        # 基线 = max(ascent) across all segments in this line
        max_ascent = 0
        for seg, _ in line_items:
            asc = _font_ascent(seg.font)
            max_ascent = max(max_ascent, asc)
            # 上标会把基线往下推（需要为上标留出空间）
            if seg.sup:
                sup_h = _text_height(seg.sup.font)
                # 上标顶部对齐到基准字体顶部，所以不额外增加 ascent
                # 但如果上标比基准字体高，需要额外空间
                pass

        baseline = cy + max_ascent  # 绝对基线 y 坐标

        # 渲染本行
        cx = x
        x_sub = cx  # 下标当前 x
        x_sup = cx  # 上标当前 x

        for seg, line_text in line_items:
            tw = _text_width(line_text, seg.font)
            th = _text_height(seg.font)
            asc = _font_ascent(seg.font)

            # 按基线对齐：text_y = baseline - ascent
            text_y = baseline - asc + seg.dy
            rx = cx + seg.dx

            # 绘制段级背景
            if seg.bg is not None:
                draw.rectangle(
                    [cx, baseline - asc, cx + tw, baseline - asc + th], fill=seg.bg
                )

            # 绘制文字
            if line_text:
                draw.text((rx, text_y), line_text, font=seg.font, fill=seg.fg)

            # 绘制下划线
            if seg.underline and line_text:
                ul_y = baseline - asc + th - 1
                draw.line([(rx, ul_y), (rx + tw, ul_y)], fill=seg.fg, width=1)

            # 绘制删除线
            if seg.linethrough and line_text:
                lt_y = baseline - asc + th // 2
                draw.line([(rx, lt_y), (rx + tw, lt_y)], fill=seg.fg, width=1)

            # 渲染上标（sup）
            if seg.sup:
                sup = seg.sup
                sup_text = sup.text
                sup_tw = _text_width(sup_text, sup.font)
                sup_asc = _font_ascent(sup.font)
                sup_th = _text_height(sup.font)
                # 上标的基线在主文本 ascent 的约 1/2 处
                sup_baseline = baseline - asc // 2
                sup_y = sup_baseline - sup_asc
                sup_x = cx + tw  # 上标紧跟主文字
                if sup.bg:
                    draw.rectangle(
                        [sup_x, sup_y, sup_x + sup_tw, sup_y + sup_th], fill=sup.bg
                    )
                draw.text((sup_x, sup_y), sup_text, font=sup.font, fill=sup.fg)
                x_sup = sup_x + sup_tw

            # 渲染下标（sub）
            if seg.sub:
                sub = seg.sub
                sub_text = sub.text
                sub_tw = _text_width(sub_text, sub.font)
                sub_asc = _font_ascent(sub.font)
                sub_th = _text_height(sub.font)
                # 下标的基线在主文本基线下方约 1/6 主文本高度
                sub_baseline = baseline + th // 6
                sub_y = sub_baseline - sub_asc
                sub_x = cx + tw  # 下标紧跟主文字
                if sub.bg:
                    draw.rectangle(
                        [sub_x, sub_y, sub_x + sub_tw, sub_y + sub_th], fill=sub.bg
                    )
                draw.text((sub_x, sub_y), sub_text, font=sub.font, fill=sub.fg)
                x_sub = sub_x + sub_tw

            # 推进 x：如果有上下标，x 取 max(x_sub, x_sup)
            if seg.sub or seg.sup:
                cx = max(x_sub, x_sup)
            else:
                cx += tw

        # 计算本行高度（含上下标）
        line_h = 0
        for seg, _ in line_items:
            h = _text_height(seg.font)
            if seg.sub:
                h += _text_height(seg.sub.font) // 2
            if seg.sup:
                pass  # 上标在基线上方，不增加行高
            line_h = max(line_h, h)

        cy += line_h


def _render_cell_layout(
    draw: ImageDraw.ImageDraw,
    layout: _CellLayout,
) -> None:
    """绘制单个单元格（背景 + 对齐后的文字段）。"""
    x, y, w, h = layout.x, layout.y, layout.w, layout.h

    draw.rectangle([x, y, x + w, y + h], fill=layout.bg)

    if not layout.segments:
        return

    seg_w = _segments_width(layout.segments)
    seg_h = _segments_height(layout.segments)

    # 垂直对齐（默认为 baseline，即顶部对齐）
    if layout.valign == "middle":
        text_y = y + (h - seg_h) // 2
    elif layout.valign == "bottom":
        text_y = y + h - seg_h - _CELL_PAD_Y
    else:  # baseline / top
        text_y = y + _CELL_PAD_Y

    # 水平对齐
    if layout.align in ("right", "end"):
        text_x = x + w - seg_w - _CELL_PAD_X
    elif layout.align == "center":
        text_x = x + (w - seg_w) // 2
    else:  # left / start
        text_x = x + _CELL_PAD_X

    _render_segments(draw, layout.segments, text_x, text_y)


def _render_row_layouts(
    draw: ImageDraw.ImageDraw,
    cells: List[_CellLayout],
    row_h: int,
    total_w: int,
) -> None:
    """绘制一行所有单元格及行底分隔线、右侧竖线。"""
    for layout in cells:
        _render_cell_layout(draw, layout)
        draw.line(
            [layout.x + layout.w, layout.y, layout.x + layout.w, layout.y + layout.h],
            fill=_COLOR_BORDER,
            width=_BORDER,
        )
    if cells:
        row_y = cells[0].y
        draw.line(
            [0, row_y + row_h, total_w, row_y + row_h],
            fill=_COLOR_BORDER,
            width=_BORDER,
        )


def _parse_cell(
    raw: CellLike,
) -> Tuple[
    Union[Text, Sequence[Text]],
    Optional[HorizontalAlign],
    Optional[VerticalAlign],
    int,
    Optional[RGBTuple],
    Optional[RGBTuple],
    Optional[str],
    Optional[float],
    Optional[str],
]:
    """
    解析 CellLike，返回 (content, align, valign, colspan, cell_bg, cell_fg, cell_font, cell_size, min_width)。
    """
    if isinstance(raw, Cell):
        colspan = raw.colspan if raw.colspan and raw.colspan > 1 else 1
        cell_bg = _to_tuple(raw.bg_color) if raw.bg_color is not None else None
        cell_fg = _to_tuple(raw.text_color) if raw.text_color is not None else None
        cell_font = raw.text_font
        cell_size = raw.text_size
        min_width = raw.min_width
        return (
            raw.content,
            raw.align,
            raw.valign,
            colspan,
            cell_bg,
            cell_fg,
            cell_font,
            cell_size,
            min_width,
        )
    elif isinstance(raw, StyledText):
        # StyledText 直接作为 content，没有 cell-level 属性
        return raw, None, None, 1, None, None, None, None, None
    else:
        # 普通字符串
        return raw, None, None, 1, None, None, None, None, None


def render_table(
    headers: Headers,
    rows: Rows,
    min_col_width: int = 40,
    title: str = "",
) -> Image.Image:
    """
    将表格渲染为 PIL Image 对象。

    :param headers:       列标题列表（支持 str / StyledText / Cell）
    :param rows:          数据行列表（每行元素支持 str / StyledText / Cell）
    :param min_col_width: 每列最小宽度（像素）
    :param title:         可选的图片标题（显示在表格上方）
    :return:              PIL Image 对象
    """
    font = _load_font(CELL_FONT_SIZE)
    header_font = _load_font(HEADER_FONT_SIZE)
    title_font = _load_font(HEADER_FONT_SIZE + 2) if title else None

    n_cols = len(headers)

    # ── 计算各列宽度 ──────────────────────────────────────────
    col_widths = [min_col_width] * n_cols
    col_aligns: List[HorizontalAlign] = ["left"] * n_cols

    def _measure(raw: CellLike, col_idx: int, f: ImageFont.FreeTypeFont) -> None:
        content, _, _, colspan, _, _, _, _, _ = _parse_cell(raw)
        if colspan > 1:
            return  # 合并列不参与单列宽度计算
        w = _cell_content_width(content, _COLOR_TEXT, f) + _CELL_PAD_X * 2
        col_widths[col_idx] = max(col_widths[col_idx], w)

    # 首先应用 header 中的 min_width
    for ci, h in enumerate(headers):
        parsed = _parse_cell(h)
        col_aligns[ci] = parsed[1]
        min_width_str = parsed[8]  # min_width 是第9个元素
        if min_width_str and min_width_str.endswith("em"):
            # 解析 "10em" -> 10 个字符宽度
            try:
                em_count = float(min_width_str[:-2])
                # 一个拉丁字符的宽度（使用 'M' 作为参考）
                char_width = _text_width("M", header_font)
                min_w = int(em_count * char_width) + _CELL_PAD_X * 2
                col_widths[ci] = max(col_widths[ci], min_w)
            except ValueError:
                pass  # 忽略无效的 min_width

    for ci, h in enumerate(headers):
        _measure(h, ci, header_font)
    for row in rows:
        for ci, cell in enumerate(row):
            if ci < n_cols:
                _measure(cell, ci, font)

    # ── 计算每行的实际高度（支持多行文本）──────────────────
    # 表头行高度
    header_height = CELL_FONT_SIZE + _CELL_PAD_Y * 2 + _BORDER
    for ci, raw in enumerate(headers):
        content, _, _, _, _, cell_fg, cell_font, cell_size, _ = _parse_cell(raw)
        default_fg = cell_fg if cell_fg is not None else _COLOR_HEADER_FG
        if cell_font is not None:
            default_font = _text_font(cell_font, cell_size) or header_font
        elif cell_size is not None:
            default_font = _load_font(int(cell_size))
        else:
            default_font = header_font
        segs = _normalize_segments(content, None, default_fg, default_font)
        seg_h = _segments_height(segs)
        header_height = max(header_height, seg_h + _CELL_PAD_Y * 2 + _BORDER)

    # 数据行高度列表
    row_heights = []
    for row in rows:
        row_h = CELL_FONT_SIZE + _CELL_PAD_Y * 2 + _BORDER
        for ci in range(n_cols):
            raw = row[ci] if ci < len(row) else ""
            content, _, _, _, _, cell_fg, cell_font, cell_size, _ = _parse_cell(raw)
            default_fg = cell_fg if cell_fg is not None else _COLOR_TEXT
            if cell_font is not None:
                default_font = _text_font(cell_font, cell_size) or font
            elif cell_size is not None:
                default_font = _load_font(int(cell_size))
            else:
                default_font = font
            segs = _normalize_segments(content, None, default_fg, default_font)
            seg_h = _segments_height(segs)
            row_h = max(row_h, seg_h + _CELL_PAD_Y * 2 + _BORDER)
        row_heights.append(row_h)

    total_width = sum(col_widths) + _BORDER
    title_height = (header_height + 4) if title else 0
    total_height = title_height + header_height + sum(row_heights) + _BORDER

    img = Image.new("RGB", (total_width, total_height), _COLOR_BG)
    draw = ImageDraw.Draw(img)

    y = 0

    # ── 可选标题 ─────────────────────────────────────────────
    if title:
        draw.rectangle([0, 0, total_width, title_height], fill=_COLOR_HEADER_BG)
        draw.text(
            (_CELL_PAD_X, _CELL_PAD_Y), title, font=title_font, fill=_COLOR_HEADER_FG
        )
        y = title_height

    # ── 表头行 ───────────────────────────────────────────────
    header_layouts: List[_CellLayout] = []
    x = 0
    for ci, raw in enumerate(headers):
        (
            content,
            align,
            valign,
            colspan,
            cell_bg,
            cell_fg,
            cell_font,
            cell_size,
            _,
        ) = _parse_cell(raw)
        w = sum(col_widths[ci : ci + colspan])

        # 使用 Cell 级别属性作为默认值
        default_fg = cell_fg if cell_fg is not None else _COLOR_HEADER_FG
        if cell_font is not None:
            default_font = _text_font(cell_font, cell_size) or header_font
        elif cell_size is not None:
            default_font = _load_font(int(cell_size))
        else:
            default_font = header_font

        segs = _normalize_segments(content, cell_bg, default_fg, default_font)
        header_layouts.append(
            _CellLayout(
                x=x,
                y=y,
                w=w,
                h=header_height,
                bg=cell_bg if cell_bg is not None else _COLOR_HEADER_BG,
                align=align or "left",
                valign=valign or "middle",
                segments=segs,
                is_header=True,
            )
        )
        x += w
    _render_row_layouts(draw, header_layouts, header_height, total_width)
    y += header_height

    # ── 数据行 ───────────────────────────────────────────────
    for ri, row in enumerate(rows):
        row_bg = _COLOR_ROW_ODD if ri % 2 == 0 else _COLOR_ROW_EVEN
        row_h = row_heights[ri]
        cell_layouts: List[_CellLayout] = []
        x = 0
        for ci in range(n_cols):
            raw = row[ci] if ci < len(row) else ""
            (
                content,
                align,
                valign,
                colspan,
                cell_bg,
                cell_fg,
                cell_font,
                cell_size,
                _,
            ) = _parse_cell(raw)
            w = sum(col_widths[ci : ci + colspan])
            align = align if align else col_aligns[ci]

            # 使用 Cell 级别属性作为默认值
            default_fg = cell_fg if cell_fg is not None else _COLOR_TEXT
            if cell_font is not None:
                default_font = _text_font(cell_font, cell_size) or font
            elif cell_size is not None:
                default_font = _load_font(int(cell_size))
            else:
                default_font = font

            segs = _normalize_segments(content, None, default_fg, default_font)
            cell_layouts.append(
                _CellLayout(
                    x=x,
                    y=y,
                    w=w,
                    h=row_h,
                    bg=cell_bg if cell_bg is not None else row_bg,
                    align=align or "left",
                    valign=valign or "middle",
                    segments=segs,
                    is_header=False,
                )
            )
            x += w
        _render_row_layouts(draw, cell_layouts, row_h, total_width)
        y += row_h

    # ── 外框 ─────────────────────────────────────────────────
    draw.rectangle(
        [0, 0, total_width - 1, total_height - 1], outline=_COLOR_BORDER, width=_BORDER
    )

    return img


def image_to_cq(img: Image.Image) -> str:
    """
    把 Image 转换为 CQ 码。
    """
    bio = BytesIO()
    img.save(bio, format="PNG")
    b64 = base64.b64encode(bio.getvalue()).decode()
    return f"[CQ:image,file=base64://{b64}]"


def render_table_as_cq(
    headers: Headers,
    rows: Rows,
    min_col_width: int = 40,
    title: str = "",
) -> str:
    """渲染表格并返回 CQ 码字符串（用于 QQ 消息发送）。"""
    img = render_table(headers, rows, min_col_width=min_col_width, title=title)
    return image_to_cq(img)


def render_table_as_file(
    headers: Headers,
    rows: Rows,
    path: str,
    min_col_width: int = 40,
    title: str = "",
) -> None:
    """渲染表格并保存为本地文件（用于测试和调试）。"""
    img = render_table(headers, rows, min_col_width=min_col_width, title=title)
    img.save(path)
