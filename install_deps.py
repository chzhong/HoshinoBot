#!/usr/bin/env python3
"""
install_deps.py — 依次安装框架和各插件的依赖。

用法：
    python3 install_deps.py [--dry-run]

支持格式：requirements.txt、requirement.txt、pyproject.toml（[project].dependencies）
"""
import os
import subprocess
import sys
import glob

ROOT = os.path.dirname(os.path.abspath(__file__))
MODULES_DIR = os.path.join(ROOT, "hoshino", "modules")

DRY_RUN = "--dry-run" in sys.argv


def pip_install(req_file: str):
    print(f"\n>>> pip install -r {os.path.relpath(req_file, ROOT)}")
    if DRY_RUN:
        return
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", req_file],
        check=False,
    )
    if result.returncode != 0:
        print(f"[WARN] 安装失败，退出码 {result.returncode}，继续下一个...")


def pip_install_toml(toml_file: str):
    """从 pyproject.toml 的 [project].dependencies 安装。"""
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib  # fallback
        except ImportError:
            print(f"[SKIP] {toml_file}: 需要 tomllib/tomli 解析 toml，跳过")
            return

    with open(toml_file, "rb") as f:
        data = tomllib.load(f)

    deps = data.get("project", {}).get("dependencies", [])
    if not deps:
        print(f"[SKIP] {toml_file}: 无 [project].dependencies")
        return

    print(f"\n>>> pip install (from {os.path.relpath(toml_file, ROOT)})")
    for dep in deps:
        print(f"    {dep}")
    if DRY_RUN:
        return
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install"] + deps,
        check=False,
    )
    if result.returncode != 0:
        print(f"[WARN] 安装失败，退出码 {result.returncode}，继续下一个...")


def find_req_file(directory: str):
    """按优先级查找依赖文件：requirements.txt > requirement.txt > pyproject.toml"""
    for name in ("requirements.txt", "requirement.txt"):
        path = os.path.join(directory, name)
        if os.path.exists(path):
            return ("req", path)
    path = os.path.join(directory, "pyproject.toml")
    if os.path.exists(path):
        return ("toml", path)
    return None


def install_dir(label: str, directory: str):
    found = find_req_file(directory)
    if not found:
        print(f"[SKIP] {label}: 无依赖文件")
        return
    kind, path = found
    print(f"[{label}]")
    if kind == "req":
        pip_install(path)
    else:
        pip_install_toml(path)


def main():
    if DRY_RUN:
        print("=== DRY RUN 模式，只打印不执行 ===\n")

    # 1. 框架
    install_dir("框架 (hoshino)", ROOT)

    # 2. 各插件
    if not os.path.isdir(MODULES_DIR):
        print(f"[WARN] modules 目录不存在: {MODULES_DIR}")
        return

    modules = sorted(
        d for d in os.listdir(MODULES_DIR)
        if os.path.isdir(os.path.join(MODULES_DIR, d)) and not d.startswith("_")
    )

    for mod in modules:
        mod_dir = os.path.join(MODULES_DIR, mod)
        install_dir(f"插件 {mod}", mod_dir)

    print("\n=== 安装完成 ===")


if __name__ == "__main__":
    main()
