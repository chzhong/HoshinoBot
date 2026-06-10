#!/bin/bash
# 在 pcrbot 虚拟环境中安装 Python 包。
# 用法：docker exec -u pcrbot <container> /HoshinoBot/docker/pip-install.sh <pip 参数...>
set -euo pipefail

VENV="${HOME}/.venv"
if [ ! -x "${VENV}/bin/pip" ]; then
    echo "[ERROR] 未找到虚拟环境 ${VENV}" >&2
    exit 1
fi

if [ $# -eq 0 ]; then
    echo "用法: pip-install.sh <pip 参数...>" >&2
    echo "示例: pip-install.sh install redis" >&2
    echo "示例: pip-install.sh install -r hoshino/modules/pcrjjc2/requirements.txt" >&2
    exit 1
fi

exec "${VENV}/bin/pip" "$@"
