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
from typing import List, Literal, Optional, Sequence, Tuple, Union

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
    font: Optional[str] = None          # 字体文件路径，None 则继承上下文
    size: Optional[float] = None        # 字号，None 则继承上下文
    text_color: Optional[Color] = None  # 前景色，None 则继承上下文
    bg_color: Optional[Color] = None    # 背景色，None 则继承上下文
    bold: Optional[bool] = None         # 粗体（需对应字体文件支持）
    italic: Optional[bool] = None       # 斜体（保留字段，暂未实现）
    underline: Optional[bool] = None    # 下划线


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
VerticalAlign: TypeAlias = Literal["top", "middle", "bottom"]

# 向后兼容旧拼写
HoritontalAlign: TypeAlias = HorizontalAlign


@dataclass
class Cell:
    content: Union[Text, Sequence[Text]]
    align: Optional[HorizontalAlign] = None
    valign: Optional[VerticalAlign] = None
    colspan: Optional[int] = None
    rowspan: Optional[int] = None   # 保留字段，暂未实现


CellLike: TypeAlias = Union[Text, Cell]

Row: TypeAlias = Sequence[CellLike]
Rows: TypeAlias = Sequence[Row]
Headers: TypeAlias = Row  # headers 默认粗体样式

_DIR = os.path.dirname(__file__)
_FONT_PATH = os.path.join(_DIR, "fonts", "mono.ttf")
_FALLBACK_FONTS = [
    os.path.join(_DIR, "fonts", "NotoSansMonoCJKsc-VF.ttf"),
    os.path.join(_DIR, "fonts", "sarasa-mono-sc-regular.ttf"),
]

# ── 样式常量 ──────────────────────────────────────────────────
_FONT_SIZE = 15
_HEADER_FONT_SIZE = 15
_CELL_PAD_X = 10  # 单元格左右内边距（像素）
_CELL_PAD_Y = 6   # 单元格上下内边距（像素）
_BORDER = 1       # 线宽

_COLOR_BG = (255, 255, 255)
_COLOR_HEADER_BG = (52, 73, 94)
_COLOR_HEADER_FG = (255, 255, 255)
_COLOR_ROW_ODD = (245, 245, 245)
_COLOR_ROW_EVEN = (255, 255, 255)
_COLOR_BORDER = (200, 200, 200)
_COLOR_TEXT = (30, 30, 30)


@dataclass
class _CellLayout:
    """布局阶段计算出的单元格渲染参数。"""
    x: int
    y: int
    w: int                  # 含 colspan 合并后的像素宽度
    h: int
    bg: RGBTuple
    align: HorizontalAlign
    valign: VerticalAlign
    # 规范化后的文字段：(text, fg_color, font, underline)
    segments: List[Tuple[str, RGBTuple, ImageFont.FreeTypeFont, bool]] = field(
        default_factory=list
    )
    is_header: bool = False


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


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in [_FONT_PATH] + _FALLBACK_FONTS:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


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
    default_fg: RGBTuple,
    default_font: ImageFont.FreeTypeFont,
) -> List[Tuple[str, RGBTuple, ImageFont.FreeTypeFont, bool]]:
    """
    将 content（str / StyledText / 列表）规范化为
    [(text, fg_color, font, underline), ...] 列表。
    """
    if isinstance(content, (str, StyledText)):
        items: List[Text] = [content]
    else:
        items = list(content)

    result = []
    for item in items:
        if isinstance(item, str):
            result.append((item, default_fg, default_font, False))
        else:  # StyledText
            fg = _to_tuple(item.text_color) if item.text_color is not None else default_fg
            if item.font or item.size:
                try:
                    path = item.font or (
                        _FONT_PATH if os.path.exists(_FONT_PATH) else _FALLBACK_FONTS[0]
                    )
                    sz = int(item.size) if item.size else _FONT_SIZE
                    f = ImageFont.truetype(path, sz)
                except Exception:
                    f = default_font
            else:
                f = default_font
            ul = bool(item.underline)
            result.append((item.text, fg, f, ul))
    return result


def _segments_width(
    segments: List[Tuple[str, RGBTuple, ImageFont.FreeTypeFont, bool]],
) -> int:
    return sum(_text_width(t, f) for t, _, f, _ in segments)


def _cell_content_width(
    content: Union[Text, Sequence[Text]],
    default_fg: RGBTuple,
    default_font: ImageFont.FreeTypeFont,
) -> int:
    return _segments_width(_normalize_segments(content, default_fg, default_font))


def _render_text(
    ctx: TableRenderContext,
    row: Row,
    cell: Cell,
    text: Text,
) -> None:
    """
    在 ctx 当前坐标绘制单段文字（供外部扩展调用）。
    核心流程通过 _render_cell 直接使用 _CellLayout，此方法保留作扩展点。
    """
    segs = _normalize_segments(text, _COLOR_TEXT, ctx.font)
    _render_segments(ctx.draw, segs, int(ctx.x), int(ctx.y))


def _render_segments(
    draw: ImageDraw.ImageDraw,
    segments: List[Tuple[str, RGBTuple, ImageFont.FreeTypeFont, bool]],
    x: int,
    y: int,
) -> None:
    """从 (x, y) 起依次绘制各段文字，支持下划线。"""
    cx = x
    for text, fg, font, underline in segments:
        draw.text((cx, y), text, font=font, fill=fg)
        if underline:
            tw = _text_width(text, font)
            th = _text_height(font)
            draw.line([(cx, y + th - 1), (cx + tw, y + th - 1)], fill=fg, width=1)
        cx += _text_width(text, font)


def _render_cell(
    ctx: TableRenderContext,
    row: Row,
    cell: CellLike,
) -> None:
    """
    在 ctx 当前坐标绘制单元格（供外部扩展调用）。
    核心流程通过 _render_cell_layout 直接使用 _CellLayout。
    """
    pass  # 核心流程使用 _render_cell_layout，此方法保留作扩展点


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
    font_h = _text_height(layout.segments[0][2])

    # 垂直对齐
    if layout.valign == "middle":
        text_y = y + (h - font_h) // 2
    elif layout.valign == "bottom":
        text_y = y + h - font_h - _CELL_PAD_Y
    else:  # top
        text_y = y + _CELL_PAD_Y

    # 水平对齐
    if layout.align in ("right", "end"):
        text_x = x + w - seg_w - _CELL_PAD_X
    elif layout.align == "center":
        text_x = x + (w - seg_w) // 2
    else:  # left / start
        text_x = x + _CELL_PAD_X

    _render_segments(draw, layout.segments, text_x, text_y)


def _render_row(
    ctx: TableRenderContext,
    row: Row,
) -> None:
    """
    绘制一行（供外部扩展调用）。
    核心流程通过 _render_row_layouts 直接使用 _CellLayout 列表。
    """
    pass  # 核心流程使用 _render_row_layouts，此方法保留作扩展点


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
            [layout.x + layout.w, layout.y,
             layout.x + layout.w, layout.y + layout.h],
            fill=_COLOR_BORDER, width=_BORDER,
        )
    if cells:
        row_y = cells[0].y
        draw.line(
            [0, row_y + row_h, total_w, row_y + row_h],
            fill=_COLOR_BORDER, width=_BORDER,
        )


def _parse_cell(
    raw: CellLike,
) -> Tuple[Union[Text, Sequence[Text]], Optional[HorizontalAlign], Optional[VerticalAlign], int, Optional[RGBTuple]]:
    """
    解析 CellLike，返回 (content, align, valign, colspan, override_bg)。
    """
    if isinstance(raw, Cell):
        colspan = raw.colspan if raw.colspan and raw.colspan > 1 else 1
        # 若 content 本身是单个 StyledText 且有 bg_color，将其提取为单元格背景
        bg = None
        if isinstance(raw.content, StyledText) and raw.content.bg_color is not None:
            bg = _to_tuple(raw.content.bg_color)
        return raw.content, raw.align, raw.valign, colspan, bg
    elif isinstance(raw, StyledText):
        bg = _to_tuple(raw.bg_color) if raw.bg_color is not None else None
        return raw, None, None, 1, bg
    else:
        return raw, None, None, 1, None


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
    font = _load_font(_FONT_SIZE)
    header_font = _load_font(_HEADER_FONT_SIZE)
    title_font = _load_font(_HEADER_FONT_SIZE + 2) if title else None

    n_cols = len(headers)

    # ── 计算各列宽度 ──────────────────────────────────────────
    col_widths = [min_col_width] * n_cols

    def _measure(raw: CellLike, col_idx: int, f: ImageFont.FreeTypeFont) -> None:
        content, _, _, colspan, _ = _parse_cell(raw)
        if colspan > 1:
            return  # 合并列不参与单列宽度计算
        w = _cell_content_width(content, _COLOR_TEXT, f) + _CELL_PAD_X * 2
        col_widths[col_idx] = max(col_widths[col_idx], w)

    for ci, h in enumerate(headers):
        _measure(h, ci, header_font)
    for row in rows:
        for ci, cell in enumerate(row):
            if ci < n_cols:
                _measure(cell, ci, font)

    row_height = _FONT_SIZE + _CELL_PAD_Y * 2 + _BORDER
    total_width = sum(col_widths) + _BORDER
    title_height = (row_height + 4) if title else 0
    total_height = title_height + row_height + len(rows) * row_height + _BORDER

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
        content, align, valign, colspan, _ = _parse_cell(raw)
        w = sum(col_widths[ci: ci + colspan])
        segs = _normalize_segments(content, _COLOR_HEADER_FG, header_font)
        header_layouts.append(_CellLayout(
            x=x, y=y, w=w, h=row_height,
            bg=_COLOR_HEADER_BG,
            align=align or "left",
            valign=valign or "middle",
            segments=segs,
            is_header=True,
        ))
        x += w
    _render_row_layouts(draw, header_layouts, row_height, total_width)
    y += row_height

    # ── 数据行 ───────────────────────────────────────────────
    for ri, row in enumerate(rows):
        row_bg = _COLOR_ROW_ODD if ri % 2 == 0 else _COLOR_ROW_EVEN
        cell_layouts: List[_CellLayout] = []
        x = 0
        for ci in range(n_cols):
            raw = row[ci] if ci < len(row) else ""
            content, align, valign, colspan, override_bg = _parse_cell(raw)
            w = sum(col_widths[ci: ci + colspan])
            segs = _normalize_segments(content, _COLOR_TEXT, font)
            cell_layouts.append(_CellLayout(
                x=x, y=y, w=w, h=row_height,
                bg=override_bg if override_bg is not None else row_bg,
                align=align or "left",
                valign=valign or "middle",
                segments=segs,
                is_header=False,
            ))
            x += w
        _render_row_layouts(draw, cell_layouts, row_height, total_width)
        y += row_height

    # ── 外框 ─────────────────────────────────────────────────
    draw.rectangle(
        [0, 0, total_width - 1, total_height - 1], outline=_COLOR_BORDER, width=_BORDER
    )

    return img


def render_table_as_cq(
    headers: Headers,
    rows: Rows,
    min_col_width: int = 40,
    title: str = "",
) -> str:
    """渲染表格并返回 CQ 码字符串（用于 QQ 消息发送）。"""
    img = render_table(headers, rows, min_col_width=min_col_width, title=title)
    bio = BytesIO()
    img.save(bio, format="PNG")
    b64 = base64.b64encode(bio.getvalue()).decode()
    return f"[CQ:image,file=base64://{b64}]"


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
