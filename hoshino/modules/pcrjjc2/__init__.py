"""
pcrjjc2/__init__.py - 功能开关入口

USE_NEW_LOGIC = False  →  加载旧逻辑（legacy.py），行为与重构前完全一致
USE_NEW_LOGIC = True   →  加载新逻辑（service.py），自完成迁移和初始化
"""

import os
import sys
import types

from .flags import USE_NEW_LOGIC

def _disable_module(name: str):
    module_name = __name__ + "." + name
    _stub = types.ModuleType(module_name)
    sys.modules[module_name] = _stub
    print(f"Disabled {module_name}")

if not bool(os.environ.get("TEST")):
    _disable_module("test_utils")
    _disable_module("test_arena_service")

if USE_NEW_LOGIC:
    _disable_module("legacy")
    from .service import sv  # noaq: F401
else:
    _disable_module("service")
    from .legacy import sv  # noqa: F401
