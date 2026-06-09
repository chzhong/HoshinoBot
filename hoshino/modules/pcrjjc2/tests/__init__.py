"""pcrjjc2 tests - 测试运行时禁用非测试模块"""

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
    # 获取当前模块所在的目录
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # 遍历当前目录下的所有 .py 文件
    for filename in os.listdir(current_dir):
        # 只处理 .py 文件
        if not filename.endswith(".py"):
            continue
        # 排除 __init__.py
        if filename == "__init__.py":
            continue
        module_name = os.path.splitext(filename)[0]

        _disable_module(module_name)
