import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN))

from core.catalog import Profile, quote_identifier as quote, read_catalog
from core.icons import IconDownloader, asset_name, ensure_placeholder, icon_name, install_icon_compat, valid_png
from core.official import CATEGORY, DEFAULT_CDN, MASTER, ROOT_MANIFEST, OfficialAssets, Release, parse_release
from core.service import AutopcrFiles, RosterService


VERSION = 202611251200


def master_fixture(path, *, hashed=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.loads((PLUGIN / "core/schema.json").read_text(encoding="utf-8")) if hashed else {}
    tables = [
        ("unit_data", ("unit_id", "unit_name"), [(100101, "官服名"), (100201, "新角色"), (900001, "NPC")]),
        ("unlock_unit_condition", ("unit_id",), [(100101,), (100201,)]),
        ("unit_profile", Profile._fields, [Profile(100201, "新角色", "1", "2", "公会", "15", "150", "45",
                                                    "A", "人族", "阅读", "声优")]),
    ]
    db = sqlite3.connect(path)
    try:
        for name, fields, rows in tables:
            aliases = encoded.get(name, {})
            table = quote(aliases.get("table", name))
            columns = ",".join(quote(aliases.get(field, field)) for field in fields)
            db.execute(f"CREATE TABLE {table} ({columns})")
            db.executemany(f"INSERT INTO {table} VALUES ({','.join('?' for _ in fields)})", rows)
        db.commit()
    finally:
        db.close()


class FilesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.autopcr = AutopcrFiles(self.root / "autopcr", self.root / "cache")
        self.assets = SimpleNamespace(current=AsyncMock(return_value=Release(VERSION)),
                                      catalog=AsyncMock(), cached_release=Release)
        self.destination = self.root / "live"
        self.destination.mkdir()
        self.names = self.destination / "CHARA_NAME.json"
        self.names.write_text('{"1001":["我的名字","自用别名"]}', encoding="utf-8")
        self.profiles = self.destination / "CHARA_PROFILE.json"
        self.profiles.write_text('{"1001":{"名字":"自定义档案","手工字段":"保留"}}', encoding="utf-8")
        self.service = RosterService(self.destination, self.root / "state", self.autopcr, self.assets)

    def add_static(self):
        source = self.autopcr.root / "autopcr/util/pcr_data.py"
        source.parent.mkdir(parents=True)
        source.write_text('CHARA_NAME = {1001: ["已有角色"], 1002: ["旧静态名"]}\n'
                          'CHARA_NICKNAME = {1001: "花名"}\n'
                          'CHARA_PROFILE = {1002: {"名字": "新角色", "额外字段": "保留"}}\n'
                          'raise RuntimeError("must not execute autopcr code")\n', encoding="utf-8")

    async def test_autopcr_first_and_no_rewrite_on_repeat(self):
        self.add_static()
        master_fixture(self.autopcr.cache / "db" / f"{VERSION}.db")
        _, data, changed = await self.service.sync()
        self.assertTrue(changed)
        self.assertEqual(data.names[1001], ["我的名字", "自用别名", "官服名", "已有角色", "花名"])
        self.assertEqual(data.names[1002][0], "新角色")
        self.assertEqual(data.profiles[1001]["手工字段"], "保留")
        self.assertEqual(data.profiles[1002]["生日"], "1月2日")
        self.assertNotIn(9000, data.names)
        before = self.names.stat().st_mtime_ns, self.profiles.stat().st_mtime_ns
        _, _, changed = await self.service.sync()
        self.assertFalse(changed)
        self.assertEqual(before, (self.names.stat().st_mtime_ns, self.profiles.stat().st_mtime_ns))
        self.assets.catalog.assert_not_awaited()

    async def test_autopcr_absent_or_stale_uses_official_and_reads_hashed_fields(self):
        official = self.root / "official.db"
        master_fixture(official, hashed=True)
        self.assets.catalog.return_value = read_catalog(official, VERSION, "官服")
        self.assertEqual((await self.service.select()).data.source, "官服")
        master_fixture(self.autopcr.cache / "db" / f"{VERSION - 1}.db")
        selected, data, _ = await self.service.sync()
        self.assertEqual(selected.data.source, "官服")
        self.assertEqual(data.profiles[1002]["声优"], "声优")

    async def test_offline_prefers_existing_autopcr_cache(self):
        master_fixture(self.autopcr.cache / "db" / f"{VERSION - 1}.db")
        self.assets.current.side_effect = TimeoutError
        selected = await self.service.select()
        self.assertEqual(selected.data.version, VERSION - 1)
        self.assertIn("无法确认官服版本", selected.note)

    async def test_official_failure_leaves_existing_files(self):
        before = self.names.read_bytes(), self.profiles.read_bytes()
        self.assets.catalog.side_effect = TimeoutError
        with self.assertRaises(RuntimeError):
            await self.service.sync()
        self.assertEqual(before, (self.names.read_bytes(), self.profiles.read_bytes()))

    async def test_write_failure_restores_first_file(self):
        master_fixture(self.autopcr.cache / "db" / f"{VERSION}.db")
        before = self.names.read_bytes(), self.profiles.read_bytes()
        real_replace = os.replace

        def replace(src, dst):
            if dst == self.profiles:
                raise PermissionError
            real_replace(src, dst)

        with patch("core.catalog.os.replace", side_effect=replace), self.assertRaises(PermissionError):
            await self.service.sync()
        self.assertEqual(before, (self.names.read_bytes(), self.profiles.read_bytes()))

    async def test_official_manifest_fixture_and_cache(self):
        release = Release(VERSION)
        prefix = f"{DEFAULT_CDN}/Manifest/{CATEGORY}/{VERSION}/"
        child = "manifest/masterdata_assetmanifest"
        digest = "a" * 32
        pool_digest = "b" * 16
        raw = json.dumps({"data": {"required_manifest_ver": str(VERSION),
                                   "resource": ["example.com/client_ob_771/"]}}).encode()
        self.assertEqual(parse_release(raw), release)
        request = Mock(side_effect=lambda url, **_: {
            prefix + ROOT_MANIFEST: (f"{child},{digest},every,123\n{child}_s,{digest},every,123\n"
                                     f"manifest/unused_assetmanifest,{digest},every,1\n").encode(),
            prefix + child: f"{MASTER},{digest},every,123\n{asset_name(1002, 3)},{digest},every,123\n".encode(),
            prefix + child + "_s": f"{MASTER},{pool_digest},tutorial2,123,\n".encode(),
        }[url])
        cache = self.root / "state"
        manifest = await OfficialAssets(cache, request).manifest(release)
        self.assertEqual(set(manifest), {MASTER, asset_name(1002, 3)})
        self.assertEqual(manifest[MASTER], pool_digest)
        request.reset_mock()
        self.assertEqual(await OfficialAssets(cache, request).manifest(release), manifest)
        request.assert_not_called()


@unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow required for PNG tests")
class IconsTest(unittest.IsolatedAsyncioTestCase):
    async def test_download_reuse_corrupt_png_retry_and_web_object(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target, cache = root / "res", root / "autopcr"
            target.mkdir()
            (cache / "image").mkdir(parents=True)
            valid = target / icon_name(1001, 3)
            Image.new("RGB", (3, 3), (1, 2, 3)).save(valid)
            original = valid.read_bytes()
            (target / icon_name(1001, 6)).write_bytes(b"broken")
            Image.new("RGB", (3, 3)).save(cache / "image/unit_icon_unit_100111.png")
            asset = asset_name(1001, 6)
            assets = SimpleNamespace(manifest=AsyncMock(return_value={asset: "hash"}), bundle=AsyncMock())
            downloader = IconDownloader(target, cache, assets)
            with patch("core.icons.decode_bundle", side_effect=ValueError):
                counts, _, _ = await downloader.download({1001}, Release(VERSION))
            self.assertEqual((counts["已存在"], counts["已下载"], counts["失败"]), (1, 1, 1))
            self.assertEqual(valid.read_bytes(), original)
            assets.manifest.return_value = {}
            counts, _, _ = await downloader.download({1001}, Release(VERSION))
            self.assertEqual((counts["已存在"], counts["无对应资源"]), (2, 1))

            @dataclass
            class Chara:
                id: int
                star: int = 3
                icon = "old interface"

            resource = SimpleNamespace(img=lambda _, name: SimpleNamespace(path=str(target / name)))
            self.assertTrue(install_icon_compat(SimpleNamespace(Chara=Chara), resource))
            self.assertFalse(install_icon_compat(SimpleNamespace(Chara=Chara), resource))
            self.assertEqual((await Chara(1001).get_icon(6)).path, str(valid))
            self.assertEqual(Chara(1001).icon, "old interface")
            self.assertTrue(valid_png(Path((await Chara(9999).get_icon(3)).path)))


class RuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_refresh_preserves_direct_imports_and_permissions(self):
        name = "_roster_entrypoint_test"
        spec = importlib.util.spec_from_file_location(name, PLUGIN / "__init__.py")
        plugin = importlib.util.module_from_spec(spec)
        chara = ModuleType("hoshino.modules.priconne.chara")
        chara.Chara = type("Chara", (), {})
        chara.roster = SimpleNamespace(_roster={})
        data = ModuleType("hoshino.modules.priconne._pcr_data")
        names = data.CHARA_NAME = {1001: ["旧角色"]}
        profiles = data.CHARA_PROFILE = {}
        decorator = lambda *args, **kw: (lambda f: f)
        hoshino = ModuleType("hoshino")
        hoshino.Service = lambda *args, **kw: SimpleNamespace(logger=Mock(), on_fullmatch=decorator,
                                                              scheduled_job=decorator)
        hoshino.R = SimpleNamespace()
        hoshino.util = SimpleNamespace(normalize_str=str.lower)
        hoshino.priv = SimpleNamespace(SUPERUSER=999, check_priv=lambda ev, _: ev.allowed)
        nonebot = ModuleType("nonebot")
        nonebot.on_startup = lambda f: f
        with patch.dict(sys.modules, {name: plugin, "hoshino": hoshino, "nonebot": nonebot,
                                      chara.__name__: chara, data.__name__: data}):
            spec.loader.exec_module(plugin)
            plugin.refresh_runtime(SimpleNamespace(names={1002: ["NEW"]}, profiles={1002: {"名字": "NEW"}}))
            self.assertIs(names, data.CHARA_NAME)
            self.assertIs(profiles, data.CHARA_PROFILE)
            self.assertEqual(chara.roster._roster["new"], 1002)
            self.assertEqual(names, {1002: ["NEW"]})
            bot = SimpleNamespace(send=AsyncMock())
            await plugin.sync_command(bot, SimpleNamespace(allowed=False))
            await plugin.icon_command(bot, SimpleNamespace(allowed=False))
            bot.send.assert_not_awaited()
