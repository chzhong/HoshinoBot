"""
test_char_width.py - 测试字符宽度对齐 + 字体渲染

测试等宽字体和 emoji 字体的字符宽度，输出配置参数。
用于更新 wanted_summary_formatter.py 中的字体宽度参数。

图片布局：
  左侧：对齐测试（原有部分，不变）
  右上：mono 字体渲染测试（英文、中文、所需 emoji、其它 emoji）
  右中：emoji 字体渲染测试

运行方式：
    cd /path/to/HoshinoBot
    python hoshino/modules/pcrjjc2/tests/test_char_width.py
"""

import os
from typing import Tuple

from PIL import Image, ImageDraw, ImageFont

_DIR = os.path.dirname(__file__)
_FONTS_DIR = os.path.join(_DIR, "../fonts")

MONO_FONT = "NotoSansMonoCJKsc-VF.ttf"
EMOJI_FONT = "NotoEmoji-VariableFont_wght.ttf"
FONT_SIZE = 15

# 所需 emoji（业务相关）
REQUIRED_EMOJIS = ["⛏️", "👇", "🔇", "⚠️", "🤺", "❓"]
# 其它常用 emoji
OTHER_EMOJIS = ["😀", "😂", "👍", "❤️", "🎉", "🔥", "✅", "❌"]

# 测试文本
ENGLISH_TEXT = "The quick brown fox jumps over the lazy dog. 0123456789"
CHINESE_TEXT = "竞技场排名监控通缉犯概要上线时间备注公会名"
PUNCTUATION_TEXT = "，。！？、：；「」【】（）…—～·"


def measure_and_output():
    """测量字符宽度并输出配置参数。"""

    mono_font_path = os.path.join(_FONTS_DIR, MONO_FONT)
    emoji_font_path = os.path.join(_FONTS_DIR, EMOJI_FONT)

    mono_font = ImageFont.truetype(mono_font_path, FONT_SIZE)
    emoji_font = ImageFont.truetype(emoji_font_path, FONT_SIZE)

    space_width = int(mono_font.getlength(" "))
    chinese_width = int(mono_font.getlength("次"))
    emoji_width = int(emoji_font.getlength("⛏️"))

    print("=" * 70)
    print("字体宽度测量结果")
    print("=" * 70)
    print(f"字体大小: {FONT_SIZE}px")
    print(f"等宽字体: {MONO_FONT}")
    print(f"Emoji字体: {EMOJI_FONT}")
    print()
    print(f"空格宽度 (' '):        {space_width:3d}px")
    print(f"汉字宽度 ('次'):       {chinese_width:3d}px")
    print(f"Emoji宽度 ('⛏️'):      {emoji_width:3d}px")
    print()

    grid_unit = max(chinese_width, emoji_width)
    print("=" * 70)
    print("对齐验证")
    print("=" * 70)
    print(f"GRID_UNIT = max({chinese_width}, {emoji_width}) = {grid_unit}px")
    print()

    three_digits_chinese = int(mono_font.getlength("123次"))
    print(f"'123次' 实际宽度: {three_digits_chinese}px")
    print()

    three_spaces = int(mono_font.getlength("   "))
    three_spaces_emoji = three_spaces + emoji_width
    print(
        f"'   ⛏️' 实际宽度: {three_spaces_emoji}px (3空格{three_spaces}px + emoji{emoji_width}px)"
    )
    print()

    mute_spaces = 1
    mute_dx = grid_unit - (chinese_width + space_width)
    print("静音emoji参数 (当前面是'次'时):")
    print(f"  空格数: {mute_spaces}")
    print(f"  偏移量 dx: {mute_dx:+d}px")
    print(
        f"  验证: '次' + ' ' + emoji(dx={mute_dx:+d}) = {chinese_width} + {space_width} + {emoji_width} + ({mute_dx:+d}) = {chinese_width + space_width + emoji_width + mute_dx}px"
    )
    print(f"  目标: GRID_UNIT = {grid_unit}px")
    print(
        f"  {'✓ 对齐正确' if chinese_width + space_width + emoji_width + mute_dx == grid_unit else '✗ 对齐错误'}"
    )
    print()

    print("=" * 70)
    print("配置参数 (复制到 wanted_summary_formatter.py)")
    print("=" * 70)
    print(f"_SPACE_WIDTH: Final = {space_width}  # 空格宽度 (px)")
    print(f"_CHINESE_WIDTH: Final = {chinese_width}  # 汉字宽度 (px)")
    print(f"_EMOJI_WIDTH: Final = {emoji_width}  # Emoji宽度 (emoji字体, px)")
    print()
    print("# 自动计算:")
    print(f"# _GRID_UNIT = max(_CHINESE_WIDTH, _EMOJI_WIDTH) = {grid_unit}")
    print(f"# 静音emoji参数 (当前面是'次'时): spaces={mute_spaces}, dx={mute_dx:+d}")
    print()

    return {
        "space_width": space_width,
        "chinese_width": chinese_width,
        "emoji_width": emoji_width,
        "grid_unit": grid_unit,
        "mute_spaces": mute_spaces,
        "mute_dx": mute_dx,
    }


def _draw_font_sample(draw, mono_font, test_font, font_label, emojis, x, y, width):
    """在指定位置绘制字体样本（标签 + 英文 + 中文 + emoji 行）。"""
    line_h = FONT_SIZE + 6

    # 字体标签
    draw.text((x, y), font_label, font=mono_font, fill=(80, 80, 80))
    y += line_h

    # 英文 + 空格
    draw.text((x, y), ENGLISH_TEXT[:40], font=test_font, fill=(0, 0, 0))
    y += line_h

    # 中文 + 标点
    draw.text((x, y), CHINESE_TEXT, font=test_font, fill=(0, 0, 0))
    y += line_h

    draw.text((x, y), PUNCTUATION_TEXT, font=test_font, fill=(0, 0, 0))
    y += line_h

    # 所需 emoji 行
    draw.text((x, y), "所需: ", font=mono_font, fill=(100, 100, 100))
    ex = x + int(mono_font.getlength("所需: "))
    for emoji in REQUIRED_EMOJIS:
        try:
            draw.text((ex, y), emoji, font=test_font, fill=(0, 0, 0))
        except Exception:
            draw.text((ex, y), "?", font=mono_font, fill=(255, 0, 0))
        ex += FONT_SIZE * 2 + 4
    y += line_h

    # 其它 emoji 行
    draw.text((x, y), "其它: ", font=mono_font, fill=(100, 100, 100))
    ex = x + int(mono_font.getlength("其它: "))
    for emoji in OTHER_EMOJIS:
        try:
            draw.text((ex, y), emoji, font=test_font, fill=(0, 0, 0))
        except Exception:
            draw.text((ex, y), "?", font=mono_font, fill=(255, 0, 0))
        ex += FONT_SIZE * 2 + 4
    y += line_h + 4

    return y


def _draw_align_tests(draw: ImageDraw.ImageDraw, mono_font, emoji_font, params, x0, y0):
    """绘制对齐测试部分，返回结束 y 坐标。"""
    lh = FONT_SIZE + 8
    grid_unit = params["grid_unit"]
    dx = params["mute_dx"]
    x_start = x0 + 20
    y = y0

    draw.text(
        (x0, y),
        f"SPACE={params['space_width']}px  CHINESE={params['chinese_width']}px  EMOJI={params['emoji_width']}px  GRID={grid_unit}px",
        font=mono_font,
        fill=(100, 100, 100),
    )
    y += lh + 4

    # 网格参考线（先记录起始 y，绘制完内容后再画）
    grid_y_start = y
    grid_cols = 10

    grid_y_end = grid_y_start + lh * 9
    # 画网格线（覆盖整个内容区域）
    for i in range(grid_cols):
        gx = x_start + i * grid_unit
        _draw_dashed_line(
            draw,
            (gx, grid_y_start),
            (gx, grid_y_end),
            fill=(224, 224, 224),
            width=1,
            joint="miter",
        )

    # 1. 123次
    draw.text((x0, y), "1.", font=mono_font, fill=(0, 0, 0))
    draw.text((x_start, y), "123次", font=mono_font, fill=(0, 0, 0))
    w = int(mono_font.getlength("123次"))
    draw.text((x_start + w + 6, y), f"({w}px)", font=mono_font, fill=(160, 160, 160))
    y += lh

    # 2. 3空格+⛏️
    draw.text((x0, y), "2.", font=mono_font, fill=(0, 0, 0))
    draw.text((x_start, y), "   ", font=mono_font, fill=(0, 0, 0))
    w1 = int(mono_font.getlength("   "))
    draw.text((x_start + w1, y), "⛏️", font=emoji_font, fill=(0, 0, 0))
    w2 = int(emoji_font.getlength("⛏️"))
    draw.text(
        (x_start + w1 + w2 + 6, y),
        f"({w1 + w2}px)",
        font=mono_font,
        fill=(160, 160, 160),
    )
    y += lh

    # 3. 123次 🔇 (with dx offset)
    draw.text((x0, y), "3.", font=mono_font, fill=(0, 0, 0))
    draw.text((x_start, y), "123次", font=mono_font, fill=(0, 0, 0))
    w1 = int(mono_font.getlength("123次"))
    draw.text((x_start + w1, y), " ", font=mono_font, fill=(0, 0, 0))
    w2 = int(mono_font.getlength(" "))
    draw.text((x_start + w1 + w2 + dx, y), "🔇", font=emoji_font, fill=(0, 0, 0))
    draw.text(
        (x_start + w1 + w2 + 28, y), f"dx={dx:+d}px", font=mono_font, fill=(0, 140, 0)
    )
    y += lh

    # 4. ⛏️🔇 (no offset)
    draw.text((x0, y), "4.", font=mono_font, fill=(0, 0, 0))
    draw.text((x_start, y), "   ", font=mono_font, fill=(0, 0, 0))
    w1 = int(mono_font.getlength("   "))
    draw.text((x_start + w1, y), "⛏️", font=emoji_font, fill=(0, 0, 0))
    w2 = int(emoji_font.getlength("⛏️"))
    draw.text((x_start + w1 + w2, y), "🔇", font=emoji_font, fill=(0, 0, 0))
    draw.text(
        (x_start + w1 + w2 + 28, y), "no offset", font=mono_font, fill=(160, 160, 160)
    )
    y += lh + 4

    # Complete examples
    draw.text((x0, y), "Examples:", font=mono_font, fill=(0, 0, 0))
    y += lh
    for text_parts, label in [
        ([("123次", mono_font)], "Normal"),
        (
            [("123次", mono_font), (" ", mono_font), ("🔇", emoji_font, dx)],
            "Normal+mute",
        ),
        ([("   ", mono_font), ("⛏️", emoji_font), ("🔇", emoji_font)], "Mining+mute"),
        ([("   ", mono_font), ("👇", emoji_font), ("🔇", emoji_font)], "Down+mute"),
    ]:
        cx = x_start
        for part in text_parts:
            offset = part[2] if len(part) > 2 else 0
            draw.text((cx + offset, y), part[0], font=part[1], fill=(0, 0, 0))
            cx += int(part[1].getlength(part[0]))
        draw.text((x_start + 160, y), label, font=mono_font, fill=(128, 128, 128))
        y += lh

    return y


def _draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    start: Tuple[int, int],
    end: Tuple[int, int],
    dash_length: int = 10,
    gap_length: int = 5,
    **kwargs,
):
    """手动绘制虚线"""
    x1, y1 = start
    x2, y2 = end
    length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
    dx, dy = (x2 - x1) / length, (y2 - y1) / length

    current = 0
    while current < length:
        seg_start = (x1 + dx * current, y1 + dy * current)
        seg_end = (
            x1 + dx * min(current + dash_length, length),
            y1 + dy * min(current + dash_length, length),
        )
        draw.line([seg_start, seg_end], **kwargs)
        current += dash_length + gap_length


def render_test_image(params):
    """渲染测试图片，验证对齐效果。动态计算尺寸。"""

    mono_font_path = os.path.join(_FONTS_DIR, MONO_FONT)
    emoji_font_path = os.path.join(_FONTS_DIR, EMOJI_FONT)

    mono_font = ImageFont.truetype(mono_font_path, FONT_SIZE)
    emoji_font = ImageFont.truetype(emoji_font_path, FONT_SIZE)

    # 估算右侧字体样本高度：每个样本 6 行 × (FONT_SIZE+6)
    sample_line_h = FONT_SIZE + 6
    sample_h = 6 * sample_line_h + 4  # 6行 + 小间距

    # 左侧：标题(1行) + 参数(1行) + 4个测试(各1行) + examples(5行) = 约11行
    left_h = 11 * (FONT_SIZE + 8) + 10

    # 右侧：mono样本 + 分隔 + emoji样本
    right_h = sample_h * 2 + 6

    PAD = 6
    left_w = 360
    right_w = 400
    img_width = left_w + right_w + PAD * 3
    img_height = max(left_h, right_h) + PAD + 24  # +24 for title

    img = Image.new("RGB", (img_width, img_height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # 标题
    y = PAD
    draw.text(
        (PAD, y),
        f"Character Width Test  (font size: {FONT_SIZE}px)",
        font=mono_font,
        fill=(0, 0, 0),
    )
    y += FONT_SIZE + 10

    # ── 左侧：对齐测试 ────────────────────────────────────────────────
    left_end_y = _draw_align_tests(draw, mono_font, emoji_font, params, PAD, y)

    # 垂直分隔线
    sep_x = left_w + PAD * 2
    draw.line(
        [(sep_x, y - 4), (sep_x, max(left_end_y, right_h + y))],
        fill=(180, 180, 180),
        width=1,
    )

    # ── 右上：mono 字体样本 ───────────────────────────────────────────
    rx = sep_x + PAD
    ry = y
    ry = _draw_font_sample(
        draw,
        mono_font,
        mono_font,
        f"[mono] {MONO_FONT}",
        REQUIRED_EMOJIS + OTHER_EMOJIS,
        rx,
        ry,
        right_w,
    )

    # 水平分隔线
    draw.line([(rx, ry), (img_width - PAD, ry)], fill=(200, 200, 200), width=1)
    ry += 4

    # ── 右中：emoji 字体样本 ──────────────────────────────────────────
    _draw_font_sample(
        draw,
        mono_font,
        emoji_font,
        f"[emoji] {EMOJI_FONT}",
        REQUIRED_EMOJIS + OTHER_EMOJIS,
        rx,
        ry,
        right_w,
    )

    output_path = os.path.join(_DIR, "_test_char_width.png")
    img.save(output_path)
    print(f"测试图片已保存到: {output_path}")
    print()

    return output_path


if __name__ == "__main__":
    params = measure_and_output()
    render_test_image(params)
