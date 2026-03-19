import os
from typing import Final, Optional

PROJ_DIR: Final = os.path.dirname(__file__)
CACHE_DIR: Final = os.path.join(PROJ_DIR, "cache")
APP_VERSION_FILE: Final = os.path.join(CACHE_DIR, "app_version.txt")
MANIFEST_VERSION_FILE: Final = os.path.join(CACHE_DIR, "manifest_version.txt")


DEFAULT_VERSION: Final = "11.4.0"


def _load_version_text(path: str) -> Optional[str]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as fp:
            line = fp.readline().strip()
            return line
    except Exception:
        return None


def _save_version_text(path: str, version: str):
    try:
        with open(path, "w") as fp:
            fp.write(version)
        return True
    except Exception:
        return False


def save_app_version(version: str):
    global APP_VERSION
    APP_VERSION = version
    return _save_version_text(APP_VERSION_FILE, version)


def save_manifest_version(version: str):
    global MANIFEST_VERSION
    MANIFEST_VERSION = version
    return _save_version_text(MANIFEST_VERSION_FILE, version)


APP_VERSION = _load_version_text(APP_VERSION_FILE) or DEFAULT_VERSION
MANIFEST_VERSION = _load_version_text(MANIFEST_VERSION_FILE)
