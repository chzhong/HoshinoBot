"""
pcrjjc2/__init__.py - 功能开关入口

USE_NEW_LOGIC = False  →  加载旧逻辑（legacy.py），行为与重构前完全一致
USE_NEW_LOGIC = True   →  加载新逻辑（service.py），自完成迁移和初始化
"""

from .flags import USE_NEW_LOGIC

if USE_NEW_LOGIC:
    from .service import sv  # noaq: F401
else:
    from .legacy import sv  # noqa: F401
