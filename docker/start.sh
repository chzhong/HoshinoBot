#!/bin/bash
set -euo pipefail

APP_ROOT="/HoshinoBot"
VENV="${HOME}/.venv"
STAMP="${HOME}/.venv-build-stamp"
MARKER="${HOME}/.modules-deps-installed"
BASE_REQ="/opt/hoshinobot-base/requirements.txt"
FRAMEWORK_REQ="${APP_ROOT}/requirements.txt"

banner() {
    echo "========================================"
    echo "  $1"
    echo "========================================"
}

current_build_id() {
    local py_ver os_id os_ver
    py_ver="$(python3 -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}")')"
    if [ -f /etc/os-release ]; then
        # shellcheck source=/dev/null
        . /etc/os-release
        os_id="${ID:-unknown}"
        os_ver="${VERSION_ID:-unknown}"
    else
        os_id="unknown"
        os_ver="unknown"
    fi
    echo "${py_ver}-${os_id}-${os_ver}"
}

write_build_stamp() {
    current_build_id > "$STAMP"
}

rebuild_framework_venv() {
    echo "[INFO] 重建虚拟环境 ${VENV} ..."
    rm -rf "$VENV"
    python3 -m venv "$VENV"
    local req_file="$FRAMEWORK_REQ"
    if [ ! -f "$req_file" ]; then
        req_file="$BASE_REQ"
    fi
    if [ ! -f "$req_file" ]; then
        echo "[WARN] 未找到 requirements.txt，跳过框架依赖安装"
    else
        "$VENV/bin/pip" install --no-cache-dir -r "$req_file"
    fi
    write_build_stamp
    rm -f "$MARKER"
}

ensure_venv() {
    if [ ! -d "$VENV" ]; then
        echo "[INFO] 虚拟环境不存在，正在创建..."
        rebuild_framework_venv
        return
    fi

    local expected current
    expected="$(current_build_id)"
    if [ -f "$STAMP" ]; then
        current="$(cat "$STAMP")"
    else
        current=""
    fi

    if [ "$expected" != "$current" ]; then
        echo "[WARN] 虚拟环境与当前 OS/Python 不匹配（stamp=${current:-无}, expected=${expected}）"
        rebuild_framework_venv
    fi
}

install_module_deps() {
    if [ -f "$MARKER" ]; then
        return
    fi

    if [ "${SKIP_MODULE_DEPS:-}" = "1" ]; then
        echo "[INFO] SKIP_MODULE_DEPS=1：跳过插件依赖自动安装。"
        echo "  稍后执行：docker exec -u pcrbot <name> ${APP_ROOT}/docker/reinstall-module-deps.sh"
        touch "$MARKER"
        return
    fi

    echo "首次启动：扫描 hoshino/modules 安装插件依赖..."
    if python "${APP_ROOT}/install_deps.py" --modules-only; then
        echo "插件依赖安装完成。"
    else
        echo "[WARN] 插件依赖安装存在错误，请登录容器手动处理："
        echo "  docker exec -u pcrbot -it <name> bash"
        echo "  如需系统库：docker exec -u root <name> ${APP_ROOT}/docker/apt-install.sh <pkg>"
        echo "  重装插件依赖：docker exec -u pcrbot <name> ${APP_ROOT}/docker/reinstall-module-deps.sh"
    fi
    touch "$MARKER"
}

on_exit() {
    local code=$?
    banner "HoshinoBot 已退出 (code=${code})"
}

banner "HoshinoBot 启动准备"

ensure_venv
install_module_deps

banner "HoshinoBot 正在运行"

trap on_exit EXIT
cd "$APP_ROOT"
"${VENV}/bin/python" run.py
