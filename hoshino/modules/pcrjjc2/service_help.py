"""
service_help.py - pcrjjc2 帮助图片生成模块

职责：
  - 生成结构化的帮助图片（利用 table_image）
  - 缓存帮助图片，避免每次启动都重新生成
  - 提供 sv_help 变量供 service.py 使用
"""

import base64
import os
from io import BytesIO
from os.path import dirname, exists, join

# 帮助图片路径
_HELP_IMAGE_PATH_CN = join(dirname(__file__), "help_image_cn.png")

# 环境变量：GEN_HELP=1 强制重新生成帮助图片
_FORCE_GEN = os.environ.get("GEN_HELP") == "1"


def _generate_help_image_cn() -> bytes:
    """
    生成中文帮助图片（PNG 格式）。

    Returns:
        bytes: PNG 图片的二进制数据
    """
    # 延迟导入，避免启动时加载 PIL
    from PIL import Image, ImageDraw

    from .table_image import Cell, Header, Headers, Rows, get_mono_font, render_table

    # ── 基本信息和订阅说明文本 ──────────────────────────────
    title_text = "竞技场推送 - 帮助"

    basic_info = """本模块提供 PCR 竞技场排名监控和通缉功能。

【订阅相关命令】
竞技场绑定 <uid>        追加绑定（最多8个），默认双场推送
竞技场查询              查询本群绑定的 uid 实时排名
详细查询 [uid]          查询本群第一个uid（或指定uid）的详细信息
订阅状态查询            列出所有绑定的编号/uid/通知群/开关状态
删除竞技场订阅 <N>      按编号删除
启用竞技场订阅 [N]      启用 jjc 推送，不填N则操作全部
停止竞技场订阅 [N]      停止 jjc 推送，不填N则操作全部
启用公主竞技场订阅 [N]  启用 pjjc 推送，不填N则操作全部
停止公主竞技场订阅 [N]  停止 pjjc 推送，不填N则操作全部
转移竞技场订阅 <N>      将第N个订阅的通知群改为当前群

注：<参数> 表示必填，[参数] 表示可选
"""

    # ── 通缉相关命令（三列表格）──────────────────────────
    wanted_headers: Headers = [
        Header(content="群通缉命令", min_width="14em"),
        Header(content="功能", align="center", min_width="10em"),
        Header(content="个人通缉命令", min_width="14em"),
    ]
    wanted_rows: Rows = [
        # 基本操作
        [
            "群?通缉 <uid> [备注]",
            "添加通缉/标记",
            "标记 <uid> [备注]",
        ],
        [
            Cell(
                content="""每个群最多通缉30人，每个人多通缉8人。
备注用于标识通缉对象，显示在通缉概要和通报消息中。
例如：通缉 1012345678901 仇人
通报时显示：佑树 (仇人) 或 用户名 (仇人)""",
                colspan=3,
            )
        ],
        [
            "群?逮捕 <uid|idx>",
            "删除通缉/标记",
            "取消标记 <uid|idx>",
        ],
        # 查询
        [
            "群通缉犯概要 / lsgwts",
            "查看通缉列表",
            "我的通缉 / lspwts",
        ],
        [
            "通缉犯概要 / lswts",
            "查看全部（群+个人）",
            "",
        ],
        # 级别设置
        [
            "群?通缉级别 <uid|idx> <N>",
            "设置通缉级别（0-5）",
            "个人通缉级别 <uid|idx> <N>",
        ],
        [
            Cell(
                content="""【通缉级别说明】
0 = 不通知
1 = 按间隔通知（默认）
2 = 每分钟一报（结算后回1）
3 = 每分钟一报（次日5点后回1）
4 = 今日高频（次日5点后回1）
5 = 永久高频""",
                colspan=3,
            )
        ],
        [
            # 快捷级别
            "群?缓和通缉犯 <uid|idx>",
            "级别→1（缓和）",
            "个人缓和通缉犯 <uid|idx>",
        ],
        [
            "群?注意通缉犯 <uid|idx>",
            "级别→2（注意）",
            "个人注意通缉犯 <uid|idx>",
        ],
        [
            "群?关照通缉犯 <uid|idx>",
            "级别→3（结算前高频）",
            "个人关照通缉犯 <uid|idx>",
        ],
        [
            "群?今日关照通缉犯 <uid|idx>",
            "级别→4（今日高频）",
            "个人今日关照通缉犯 <uid|idx>",
        ],
        [
            "群?重点关照通缉犯 <uid|idx>",
            "级别→5（永久高频）",
            "个人重点关照通缉犯 <uid|idx>",
        ],
        # 通报开关
        [
            "群?开启通报jjc <uid|idx>",
            "开启 jjc 通报",
            "个人开启通报jjc <uid|idx>",
        ],
        [
            "群?关闭通报jjc <uid|idx>",
            "关闭 jjc 通报",
            "个人关闭通报jjc <uid|idx>",
        ],
        [
            "群?开启通报pjjc <uid|idx>",
            "开启 pjjc 通报",
            "个人开启通报pjjc <uid|idx>",
        ],
        [
            "群?关闭通报pjjc <uid|idx>",
            "关闭 pjjc 通报",
            "个人关闭通报pjjc <uid|idx>",
        ],
        # 备注
        [
            "群?设置备注 <uid|idx> <备注>",
            "设置备注",
            "个人设置备注 <uid|idx> <备注>",
        ],
        [
            "群?清空备注 <uid|idx>",
            "清空备注",
            "个人清空备注 <uid|idx>",
        ],
    ]

    # ── 生成图片 ──────────────────────────────────────────
    # 渲染通缉表格
    wanted_img = render_table(
        headers=wanted_headers,
        rows=wanted_rows,
        title="通缉相关命令",
        min_col_width=60,
    )

    # 计算文本区域尺寸
    title_font = get_mono_font(24)
    text_font = get_mono_font(14)

    # 创建临时图片来测量文本尺寸
    temp_img = Image.new("RGB", (1, 1))
    temp_draw = ImageDraw.Draw(temp_img)

    # 测量标题
    title_bbox = temp_draw.textbbox((0, 0), title_text, font=title_font)
    title_height = title_bbox[3] - title_bbox[1]

    # 测量基本信息文本
    basic_bbox = temp_draw.textbbox((0, 0), basic_info, font=text_font)
    basic_height = basic_bbox[3] - basic_bbox[1]

    # 计算总尺寸
    padding = 20
    total_width = max(wanted_img.width, 800)
    total_height = (
        padding
        + title_height
        + padding  # 标题
        + basic_height
        + padding  # 基本信息
        + padding  # 级别说明
        + wanted_img.height
        + padding  # 通缉表格
    )

    # 创建最终图片
    final_img = Image.new("RGB", (total_width, total_height), (255, 255, 255))
    draw = ImageDraw.Draw(final_img)

    # 绘制标题（居中）
    title_width = title_bbox[2] - title_bbox[0]
    title_x = (total_width - title_width) // 2
    y_offset = padding
    draw.text((title_x, y_offset), title_text, fill=(0, 0, 0), font=title_font)
    y_offset += title_height + padding

    # 绘制基本信息
    draw.text((padding, y_offset), basic_info, fill=(0, 0, 0), font=text_font)
    y_offset += basic_height + padding

    # 粘贴通缉表格
    final_img.paste(wanted_img, (0, y_offset))

    # 转换为 PNG 字节
    buf = BytesIO()
    final_img.save(buf, format="PNG")
    return buf.getvalue()


def _load_help_image_cn() -> str:
    """
    加载中文帮助图片并转换为 CQ 码。

    Returns:
        str: CQ 码字符串
    """
    # 检查是否需要生成
    if _FORCE_GEN or not exists(_HELP_IMAGE_PATH_CN):
        # 生成帮助图片
        img_data = _generate_help_image_cn()
        # 保存到文件
        with open(_HELP_IMAGE_PATH_CN, "wb") as f:
            f.write(img_data)
    else:
        # 读取已有的帮助图片
        with open(_HELP_IMAGE_PATH_CN, "rb") as f:
            img_data = f.read()

    # 转换为 base64 CQ 码
    b64 = base64.b64encode(img_data).decode()
    return f"[CQ:image,file=base64://{b64}]"


# ── 模块级变量 ──────────────────────────────────────────
# 在模块导入时生成/加载中文帮助图片
sv_help = _load_help_image_cn()
