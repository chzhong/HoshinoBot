"""
pcrjjc2/__init__.py - 模块入口
"""

import os
import sys
import types


def _disable_module(name: str):
    """
    disable some module.

    hoshino will load all pyhton modules, so only disable modules we don't need

    :param name: local module name to disable
    """
    module_name = __name__ + "." + name
    _stub = types.ModuleType(module_name)
    sys.modules[module_name] = _stub
    print(f"Disabled {module_name}")


if not bool(os.environ.get("TEST")):
    # disable TEST modules unless we start tests
    _disable_module("tests")
