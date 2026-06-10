#!/bin/bash
# 重新扫描 modules 并安装插件 Python 依赖（无需重建镜像或 restart）。
# 用法：docker exec -u pcrbot <container> /HoshinoBot/docker/reinstall-module-deps.sh
set -euo pipefail

APP_ROOT="/HoshinoBot"
MARKER="${HOME}/.modules-deps-installed"

rm -f "$MARKER"

echo "正在安装插件依赖..."
if python "${APP_ROOT}/install_deps.py" --modules-only; then
    echo "插件依赖安装完成。"
    touch "$MARKER"
    exit 0
fi

echo "[WARN] 插件依赖安装存在错误，请检查上方日志并手动处理。" >&2
touch "$MARKER"
exit 1
