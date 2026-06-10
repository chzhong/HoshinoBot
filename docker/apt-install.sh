#!/bin/bash
# 以 root 安装系统包（pcrbot 无 sudo）。
# 用法：docker exec -u root <container> /HoshinoBot/docker/apt-install.sh <包名...>
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "[ERROR] 请使用 root 执行：docker exec -u root <container> $0 <包名...>" >&2
    exit 1
fi

if [ $# -eq 0 ]; then
    echo "用法: apt-install.sh <包名...>" >&2
    echo "示例: apt-install.sh libssl-dev" >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends "$@"
rm -rf /var/lib/apt/lists/*

echo "[INFO] 系统包已安装。若 Python 包编译失败，请重试："
echo "  docker exec -u pcrbot <container> /HoshinoBot/docker/pip-install.sh install --force-reinstall <pkg>"
