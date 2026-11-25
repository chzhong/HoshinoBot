import asyncio
import json
import re
import sqlite3
from dataclasses import dataclass
from hashlib import md5
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .catalog import json_bytes, read_catalog, stage_bytes, write_bytes


MAINTENANCE = "https://l3-prod-all-gs-gzlj.bilibiligame.net/source_ini/get_maintenance_status?format=json"
DEFAULT_CDN = "https://l1-prod-patch-gzlj.bilibiligame.net/client_ob_771"
CATEGORY = "AssetBundles/Android"
MASTER = "a/masterdata_master.unity3d"
ROOT_MANIFEST = "manifest/manifest_assetmanifest"
MAINTENANCE_HEADERS = {
    # Public Android client metadata, as used by autopcr's anonymous request.
    "User-Agent": "Dalvik/2.1.0 (Linux, U, Android 5.1.1, PCRT00 Build/LMY48Z)",
    "X-Unity-Version": "2021.3.20f1c1", "APP-VER": "11.7.2", "BATTLE-LOGIC-VERSION": "4",
    "BUNDLE-VER": "", "DEVICE": "2", "DEVICE-NAME": "OPPO PCRT00", "EXCEL-VER": "1.0.0",
    "GRAPHICS-DEVICE-NAME": "Adreno (TM) 640", "IP-ADDRESS": "10.0.2.15", "KEYCHAIN": "",
    "LOCALE": "CN", "PLATFORM-OS-VERSION": "Android OS 5.1.1 / API-22 (LMY48Z/rel.se.infra.20200612.100533)",
    "REGION-CODE": "", "RES-VER": "10002200", "SHORT-UDID": "0", "CHANNEL-ID": "1",
    "DEVICE-ID": md5(b"hoshino-pcr-roster").hexdigest(), "PLATFORM": "2", "PLATFORM-ID": "2",
    "RES-KEY": "ab00a0a6dd915a052a2ef7fd649083e5",
}
ASSET_NAME = re.compile(r"(?:manifest/[\w.-]+|a/[\w.-]+)", re.ASCII)
RESOURCE_MANIFEST = re.compile(r"manifest/(?:masterdata|icon|unit|unit_icon)_assetmanifest(?:_s)?")
ICON_NAME = re.compile(r"a/unit_icon_unit_[0-9]+\.unity3d")
HASH = re.compile(r"(?:[0-9a-f]{16}|[0-9a-f]{32})", re.ASCII)
MAX_BUNDLE = 160 * 1024 * 1024


@dataclass(frozen=True)
class Release:
    version: int
    base: str = DEFAULT_CDN
    mirrors: tuple = ()


def safe_cdn(value):
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value if "://" in value else "https://" + value)
    if (parsed.scheme == "https" and re.fullmatch(r"l[1-9][0-9]*-prod-patch-gzlj\.bilibiligame\.net", parsed.netloc)
            and re.fullmatch(r"/client_ob_[0-9]+/?", parsed.path) and not parsed.query and not parsed.fragment):
        return f"https://{parsed.netloc}{parsed.path.rstrip('/')}"
    return None


def parse_release(raw):
    payload = json.loads(raw)["data"]
    version = str(payload.get("required_manifest_ver") or payload.get("manifest_ver") or "")
    if not re.fullmatch(r"[0-9]{8,18}", version):
        raise ValueError("维护接口未返回有效资源版本")
    sources = list(dict.fromkeys(base for resource in payload.get("resource") or [] if (base := safe_cdn(resource))))
    return Release(int(version), sources[0], tuple(sources[1:])) if sources else Release(int(version))


def fetch(url, *, data=None, headers=None, limit=MAX_BUNDLE):
    with urlopen(Request(url, data=data, headers=headers or {}), timeout=25) as response:
        result = response.read(limit + 1)
    if len(result) > limit:
        raise ValueError("下载资源超过大小限制")
    return result


def decode_bundle(data, texture=False):
    import UnityPy
    UnityPy.config.FALLBACK_UNITY_VERSION = "6000.0.58f2"
    for obj in UnityPy.load(data).objects:
        if obj.type.name == ("Texture2D" if texture else "TextAsset"):
            asset = obj.read()
            if texture:
                return asset.image
            value = asset.script if hasattr(asset, "script") else asset.m_Script
            return value.encode("utf-8", "surrogateescape") if isinstance(value, str) else bytes(value)
    raise ValueError("游戏资源不包含预期内容")


class OfficialAssets:
    def __init__(self, cache, request=fetch):
        self.cache = cache
        self.request = request
        self._assets = {}

    async def current(self):
        # Same unauthenticated maintenance request as pcrdata; no SID or account.
        result = await asyncio.to_thread(self.request, MAINTENANCE, data=b'{"viewer_id":"0"}',
                                         headers=MAINTENANCE_HEADERS, limit=1024 * 1024)
        return parse_release(result)

    def cached_release(self, version):
        path = self.cache / f"assets-{version}.json"
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            base = safe_cdn(cached["base"])
            mirrors = tuple(url for value in cached.get("mirrors", []) if (url := safe_cdn(value)))
        except (OSError, ValueError, TypeError, KeyError):
            base, mirrors = None, ()
        return Release(version, base or DEFAULT_CDN, mirrors)

    async def get_asset(self, release, path, *, limit=MAX_BUNDLE):
        for base in (release.base, *release.mirrors):
            try:
                return await asyncio.to_thread(self.request, f"{base}/{path}", limit=limit)
            except OSError as error:
                last_error = error
        raise last_error

    async def manifest(self, release):
        if release in self._assets:
            return self._assets[release]
        cache_path = self.cache / f"assets-{release.version}.json"
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            assets = cached["assets"]
            if cached["base"] == release.base and MASTER in assets and all(
                ASSET_NAME.fullmatch(key) and HASH.fullmatch(value) for key, value in assets.items()
            ):
                self._assets[release] = assets
                return assets
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass

        prefix = f"Manifest/{CATEGORY}/{release.version}/"
        assets, pending, seen = {}, [ROOT_MANIFEST], {ROOT_MANIFEST}
        while pending:
            names, pending = pending[:8], pending[8:]
            docs = await asyncio.gather(*(self.get_asset(release, prefix + name, limit=32 * 1024 * 1024)
                                         for name in names))
            # Preserve manifest order: later *_s lists contain the actual pool
            # identifiers and must override the preliminary 32-char hashes.
            for doc in docs:
                for line in doc.decode("utf-8-sig").splitlines():
                    name, _, digest = line.strip().partition(",")
                    digest = digest.split(",", 1)[0].strip()
                    if not ASSET_NAME.fullmatch(name):
                        continue
                    if RESOURCE_MANIFEST.fullmatch(name) and name not in seen:
                        if len(seen) >= 512:
                            raise ValueError("资源清单数量异常")
                        seen.add(name)
                        pending.append(name)
                    elif (name == MASTER or ICON_NAME.fullmatch(name)) and HASH.fullmatch(digest):
                        assets[name] = digest
        if MASTER not in assets:
            raise ValueError("游戏资源清单缺少主数据库")
        self.cache.mkdir(parents=True, exist_ok=True)
        write_bytes(cache_path, json_bytes({"base": release.base, "mirrors": release.mirrors, "assets": assets}))
        self._assets[release] = assets
        return assets

    async def bundle(self, release, asset):
        digest = (await self.manifest(release))[asset]
        return await self.get_asset(release, f"pool/{CATEGORY}/{digest[:2]}/{digest}")

    def database(self, version):
        return self.cache / f"master-{version}.db"

    async def catalog(self, release):
        path = self.database(release.version)
        if path.exists():
            try:
                return await asyncio.to_thread(read_catalog, path, release.version, "官服主数据库")
            except (OSError, ValueError, TypeError, sqlite3.Error):
                pass
        raw = await self.bundle(release, MASTER)
        return await asyncio.to_thread(self._install_database, release.version, raw)

    def _install_database(self, version, raw):
        path = self.database(version)
        self.cache.mkdir(parents=True, exist_ok=True)
        staged = stage_bytes(path, decode_bundle(raw))
        try:
            catalog = read_catalog(staged, version, "官服主数据库")
            staged.replace(path)
        finally:
            staged.unlink(missing_ok=True)
        return catalog
