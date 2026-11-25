import asyncio
from collections import Counter
from io import BytesIO
from pathlib import Path

from .catalog import character_id, write_bytes
from .official import decode_bundle


STARS = (1, 3, 6)
UNKNOWN = 1000


def icon_number(char_id, star):
    return character_id(char_id) * 100 + star * 10 + 1


def icon_name(char_id, star):
    return f"icon_unit_{icon_number(char_id, star)}.png"


def asset_name(char_id, star):
    return f"a/unit_icon_unit_{icon_number(char_id, star)}.unity3d"


def image_bytes(image):
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def valid_png(path):
    from PIL import Image
    try:
        with Image.open(path) as image:
            if image.format != "PNG":
                return False
            image.verify()
            return True
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return False


def ensure_placeholder(path):
    from PIL import Image
    if not valid_png(path):
        write_bytes(path, image_bytes(Image.new("RGB", (64, 64), (95, 101, 111))))


class IconDownloader:
    def __init__(self, target, autopcr_cache, assets, concurrency=4):
        self.target = target
        self.autopcr_cache = autopcr_cache
        self.assets = assets
        self.concurrency = concurrency

    async def download(self, ids, release):
        await asyncio.to_thread(self.target.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(ensure_placeholder, self.target / icon_name(UNKNOWN, 3))
        manifest_task, manifest_error = None, ""

        async def get_manifest():
            nonlocal manifest_error
            try:
                return await self.assets.manifest(release)
            except Exception as error:
                manifest_error = type(error).__name__

        async def one(key, star):
            nonlocal manifest_task
            target = self.target / icon_name(key, star)
            if await asyncio.to_thread(valid_png, target):
                return "已存在"
            local = self.autopcr_cache / "image" / f"unit_icon_unit_{icon_number(key, star)}.png"
            if await asyncio.to_thread(valid_png, local):
                await asyncio.to_thread(write_bytes, target, await asyncio.to_thread(local.read_bytes))
                return "已下载"
            if not release:
                return "失败"
            if manifest_task is None:
                manifest_task = asyncio.create_task(get_manifest())
            assets = await manifest_task
            if assets is None:
                return "失败"
            asset = asset_name(key, star)
            if asset not in assets:
                return "无对应资源"
            raw = await self.assets.bundle(release, asset)
            def install():
                with decode_bundle(raw, texture=True) as image:
                    write_bytes(target, image_bytes(image))
            await asyncio.to_thread(install)
            return "已下载"

        work = iter((key, star) for key in sorted(ids - {UNKNOWN}) for star in STARS)
        counts, failed = Counter(), []

        async def worker():
            for key, star in work:
                try:
                    result = await one(key, star)
                except Exception:
                    result = "失败"
                counts[result] += 1
                if result == "失败":
                    failed.append(f"{key}/{star}星")

        await asyncio.gather(*(worker() for _ in range(self.concurrency)))
        return counts, failed, manifest_error


def install_icon_compat(chara, resource):
    if hasattr(chara.Chara, "get_icon"):
        return False

    async def get_icon(self, star=None):
        rarity = star if star is not None else self.star
        rarity = 6 if rarity >= 6 else 1 if 0 < rarity < 3 else 3
        for candidate in dict.fromkeys((rarity, 3, 1, 6)):
            icon = resource.img("priconne/unit", icon_name(self.id, candidate))
            if await asyncio.to_thread(valid_png, Path(icon.path).expanduser()):
                return icon
        return resource.img("priconne/unit", icon_name(UNKNOWN, 3))

    chara.Chara.get_icon = get_icon
    return True
