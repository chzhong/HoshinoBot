#!/usr/bin/env python3
"""
install_deps.py — 依次安装框架和各插件的依赖。

用法：
    python3 install_deps.py [--dry-run] [--modules-only] [--strict]

支持格式：requirements.txt、requirement.txt、pyproject.toml（[project].dependencies）
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
MODULES_DIR = os.path.join(ROOT, "hoshino", "modules")


def parse_args():
    parser = argparse.ArgumentParser(description="安装 HoshinoBot 框架与插件依赖")
    parser.add_argument("--dry-run", action="store_true", help="只打印不执行 pip")
    parser.add_argument(
        "--modules-only",
        action="store_true",
        help="仅安装 hoshino/modules 下各插件依赖，跳过框架 requirements.txt",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="任一 pip 安装失败时以非零退出码结束（--modules-only 时默认启用）",
    )
    parser.add_argument(
        "--no-strict",
        action="store_true",
        help="即使安装失败也返回 0（覆盖 --modules-only 的默认 strict）",
    )
    return parser.parse_args()


def pip_install(req_file: str, dry_run: bool, strict: bool) -> bool:
    print(f"\n>>> pip install -r {os.path.relpath(req_file, ROOT)}")
    if dry_run:
        return True
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", req_file],
        check=False,
    )
    if result.returncode != 0:
        print(f"[WARN] 安装失败，退出码 {result.returncode}，继续下一个...")
        return not strict
    return True


def pip_install_toml(toml_file: str, dry_run: bool, strict: bool) -> bool:
    """从 pyproject.toml 的 [project].dependencies 安装。"""
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib  # fallback
        except ImportError:
            print(f"[SKIP] {toml_file}: 需要 tomllib/tomli 解析 toml，跳过")
            return True

    with open(toml_file, "rb") as f:
        data = tomllib.load(f)

    deps = data.get("project", {}).get("dependencies", [])
    if not deps:
        print(f"[SKIP] {toml_file}: 无 [project].dependencies")
        return True

    print(f"\n>>> pip install (from {os.path.relpath(toml_file, ROOT)})")
    for dep in deps:
        print(f"    {dep}")
    if dry_run:
        return True
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install"] + deps,
        check=False,
    )
    if result.returncode != 0:
        print(f"[WARN] 安装失败，退出码 {result.returncode}，继续下一个...")
        return not strict
    return True


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


def install_dir(label: str, directory: str, dry_run: bool, strict: bool) -> bool:
    found = find_req_file(directory)
    if not found:
        print(f"[SKIP] {label}: 无依赖文件")
        return True
    kind, path = found
    print(f"[{label}]")
    if kind == "req":
        return pip_install(path, dry_run, strict)
    return pip_install_toml(path, dry_run, strict)


def install_modules(dry_run: bool, strict: bool) -> bool:
    ok = True
    if not os.path.isdir(MODULES_DIR):
        print(f"[WARN] modules 目录不存在: {MODULES_DIR}")
        return ok

    modules = sorted(
        d for d in os.listdir(MODULES_DIR)
        if os.path.isdir(os.path.join(MODULES_DIR, d)) and not d.startswith("_")
    )

    for mod in modules:
        mod_dir = os.path.join(MODULES_DIR, mod)
        if not install_dir(f"插件 {mod}", mod_dir, dry_run, strict):
            ok = False

    return ok


def main():
    args = parse_args()
    strict = args.strict or (args.modules_only and not args.no_strict)

    if args.dry_run:
        print("=== DRY RUN 模式，只打印不执行 ===\n")

    ok = True

    if not args.modules_only:
        if not install_dir("框架 (hoshino)", ROOT, args.dry_run, strict):
            ok = False

    if not install_modules(args.dry_run, strict):
        ok = False

    print("\n=== 安装完成 ===")

    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
