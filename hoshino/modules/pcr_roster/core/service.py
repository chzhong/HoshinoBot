import asyncio
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .catalog import Catalog, load_files, merge_catalog, read_autopcr_data, read_catalog, save_files
from .official import OfficialAssets, Release


def optional_path(env, default):
    return Path(os.environ[env]).expanduser() if os.environ.get(env) else default


@dataclass(frozen=True)
class AutopcrFiles:
    root: Path
    cache: Path

    @classmethod
    def discover(cls):
        root = optional_path("PCR_ROSTER_AUTOPCR_ROOT", Path(__file__).resolve().parents[2] / "autopcr")
        default_cache = root.parent / "cache" if (root / "util/pcr_data.py").is_file() else root / "cache"
        return cls(root, optional_path("PCR_ROSTER_AUTOPCR_CACHE", default_cache))

    def static_catalog(self):
        for path in (self.root / "autopcr/util/pcr_data.py", self.root / "util/pcr_data.py"):
            if path.is_file():
                return read_autopcr_data(path)
        return Catalog()


def cached_catalog(directory, pattern, prefix, source):
    candidates = [(int(version), path) for path in directory.glob(pattern)
                  if (version := path.stem.removeprefix(prefix)).isascii() and version.isdigit()]
    for version, path in sorted(candidates, reverse=True):
        try:
            return read_catalog(path, version, source)
        except (OSError, TypeError, ValueError, sqlite3.Error):
            continue
    return Catalog()


@dataclass
class Selection:
    data: Catalog
    aliases: Catalog
    release: Release | None
    note: str = ""


class RosterService:
    def __init__(self, directory, state, autopcr=None, assets=None):
        self.directory = directory
        self.state = state
        self.autopcr = autopcr or AutopcrFiles.discover()
        self.assets = assets or OfficialAssets(state)

    async def select(self):
        def read_local():
            try:
                static = self.autopcr.static_catalog()
            except (OSError, ValueError, TypeError, SyntaxError):
                static = Catalog()
            return (static, cached_catalog(self.autopcr.cache / "db", "*.db", "", "autopcr 主数据库"),
                    cached_catalog(self.state, "master-*.db", "master-", "官服主数据库缓存"))

        static, autopcr, official_cache = await asyncio.to_thread(read_local)
        release, note = None, ""
        try:
            release = await self.assets.current()
        except Exception as error:
            note = f"无法确认官服版本（{type(error).__name__}）"

        if release and autopcr.version >= release.version:
            selected = autopcr
        elif release and official_cache.version >= release.version:
            selected = official_cache
        elif release:
            try:
                selected = await self.assets.catalog(release)
            except Exception as error:
                note = f"官服更新失败（{type(error).__name__}），使用可用缓存"
                selected = max((autopcr, official_cache), key=lambda data: data.version)
        else:
            selected = max((autopcr, official_cache), key=lambda data: data.version)

        if not selected.names:
            if not static.names:
                raise RuntimeError(note or "没有可用的角色数据")
            return Selection(static, Catalog(), release, note or "主数据库不可用，仅使用 autopcr 静态资料")
        if (not release or selected.version != release.version) and selected.version:
            release = self.assets.cached_release(selected.version)
        return Selection(selected, static, release, note)

    async def sync(self):
        selected = await self.select()

        def update():
            before = load_files(self.directory)
            after = merge_catalog(before, selected.data, selected.aliases)
            changed = save_files(self.directory, before, after)
            return after, changed

        after, changed = await asyncio.to_thread(update)
        return selected, after, changed
