import ast
import json
import os
import sqlite3
import stat
import tempfile
from collections import namedtuple
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Catalog:
    names: dict = field(default_factory=dict)
    profiles: dict = field(default_factory=dict)
    playable: set = field(default_factory=set)
    version: int = 0
    source: str = ""


def character_id(value):
    if isinstance(value, bool) or not str(value).isascii() or not str(value).isdigit():
        raise ValueError("invalid character ID")
    result = int(value)
    if not 1000 <= result <= 9999:
        raise ValueError("invalid character ID")
    return result


def names_from(data):
    if not isinstance(data, dict):
        raise ValueError("invalid name list")
    result = {}
    for key, names in data.items():
        if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
            raise ValueError("invalid character names")
        names = list(dict.fromkeys(name for name in names if name.strip()))
        if names:
            result[character_id(key)] = names
    return result


def profiles_from(data):
    if not isinstance(data, dict):
        raise ValueError("invalid profile list")
    result = {}
    for key, profile in data.items():
        if not isinstance(profile, dict) or not all(
            isinstance(label, str) and isinstance(value, str) for label, value in profile.items()
        ):
            raise ValueError("invalid character profile")
        result[character_id(key)] = profile
    return result


def read_autopcr_data(path):
    blocks = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {"CHARA_NAME", "CHARA_NICKNAME", "CHARA_PROFILE"}:
                    blocks[target.id] = ast.literal_eval(node.value)
    names = names_from(blocks.get("CHARA_NAME", {}))
    for key, nickname in blocks.get("CHARA_NICKNAME", {}).items():
        if key in names and isinstance(nickname, str) and nickname.strip() and nickname not in names[key]:
            names[key].append(nickname)
    return Catalog(names, profiles_from(blocks.get("CHARA_PROFILE", {})), source="autopcr 静态资料")


def quote_identifier(value):
    return '"' + value.replace('"', '""') + '"'


def select_table(db, schema, table, fields):
    aliases = schema.get(table, {})
    for candidate in (table, aliases.get("table")):
        if not candidate:
            continue
        identifier = quote_identifier(candidate)
        columns = {row[1] for row in db.execute(f"PRAGMA table_info({identifier})")}
        mapping = [field if field in columns else aliases.get(field) for field in fields]
        if all(field in columns for field in mapping):
            names = ", ".join(map(quote_identifier, mapping))
            return db.execute(f"SELECT {names} FROM {identifier}").fetchall()
    raise ValueError(f"主数据库缺少可识别的 {table} 表或字段")


PROFILE_FIELDS = {
    "guild": "公会", "age": "年龄", "height": "身高", "weight": "体重",
    "blood_type": "血型", "race": "种族", "favorite": "喜好", "voice": "声优",
}
Profile = namedtuple("Profile", ("unit_id", "unit_name", "birth_month", "birth_day", *PROFILE_FIELDS))


def unit_to_character(unit_id):
    return character_id(unit_id // 100 if unit_id >= 100000 else unit_id)


def read_catalog(path, version, source):
    schema = json.loads(Path(__file__).with_name("schema.json").read_text(encoding="utf-8"))
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        playable_units = {row[0] for row in select_table(db, schema, "unlock_unit_condition", ("unit_id",))}
        unit_rows = select_table(db, schema, "unit_data", ("unit_id", "unit_name"))
        profiles = select_table(db, schema, "unit_profile", Profile._fields)
    result = Catalog(version=version, source=source)
    for unit_id, name in unit_rows:
        if unit_id in playable_units and isinstance(name, str) and name.strip():
            try:
                key = unit_to_character(unit_id)
            except (ValueError, TypeError):
                continue
            result.playable.add(key)
            result.names.setdefault(key, [])
            if name.strip() not in result.names[key]:
                result.names[key].append(name.strip())
    if not result.playable:
        raise ValueError("主数据库未提供可用角色")
    for values in profiles:
        row = Profile(*values)
        try:
            key = unit_to_character(row.unit_id)
        except (ValueError, TypeError):
            continue
        if key not in result.playable:
            continue
        profile = {label: str(value).strip() for field, label in PROFILE_FIELDS.items()
                   if (value := getattr(row, field)) is not None and str(value).strip()}
        if str(row.birth_month).isdigit() and str(row.birth_day).isdigit():
            month, day = int(row.birth_month), int(row.birth_day)
            if 1 <= month <= 12 and 1 <= day <= 31:
                profile["生日"] = f"{month}月{day}日"
        if profile:
            profile["名字"] = str(row.unit_name).strip() if row.unit_name else result.names[key][0]
            result.profiles.setdefault(key, profile)
    return result


def merge_catalog(current, *sources):
    names, profiles = dict(current.names), {key: dict(value) for key, value in current.profiles.items()}
    for source in sources:
        for key, aliases in source.names.items():
            names[key] = list(dict.fromkeys((*names.get(key, ()), *aliases)))
        for key, incoming in source.profiles.items():
            if key not in names:
                continue
            existing = profiles.setdefault(key, {})
            for label, value in incoming.items():
                if not existing.get(label) and value.strip():
                    existing[label] = value
            if existing:
                existing.setdefault("名字", names[key][0])
    return Catalog(names, profiles)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=4) + "\n").encode("utf-8")


def stage_bytes(path, data):
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as file:
        staged = Path(file.name)
        try:
            os.fchmod(file.fileno(), mode)
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        except BaseException:
            staged.unlink(missing_ok=True)
            raise
    return staged


def write_bytes(path, data):
    staged = stage_bytes(path, data)
    try:
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def load_files(directory):
    def load(filename, validate):
        path = directory / filename
        return validate(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else {}

    return Catalog(load("CHARA_NAME.json", names_from), load("CHARA_PROFILE.json", profiles_from))


def save_files(directory, before, after):
    if not after.names:
        raise ValueError("不写入空花名册")
    staged, replaced = {}, []
    try:
        for filename, old, new in (("CHARA_NAME.json", before.names, after.names),
                                   ("CHARA_PROFILE.json", before.profiles, after.profiles)):
            path = directory / filename
            if old != new or not path.exists():
                original = path.read_bytes() if path.exists() else None
                staged[path] = stage_bytes(path, json_bytes(new)), original
        for path, (temp, original) in staged.items():
            os.replace(temp, path)
            replaced.append((path, original))
    except OSError:
        for path, original in reversed(replaced):
            if original is None:
                path.unlink(missing_ok=True)
            else:
                write_bytes(path, original)
        raise
    finally:
        for temp, _ in staged.values():
            temp.unlink(missing_ok=True)
    return bool(replaced)
