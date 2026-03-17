#!/bin/bash

set -e

# ==================== 配置区域 ====================
export TEST=1
DEBUG_SCRIPT=false

# 模块目录（相对于项目根目录的路径）
MODULE_DIR="hoshino/modules/pcrjjc2"
TEST_DIR="${MODULE_DIR}/tests"

# ==================== 工具函数 ====================
# 将文件系统路径转换为 Python 模块名（/ 转 .）
path_to_module() {
    local path="$1"
    # 移除前导和尾随的 /
    path="${path#/}"
    path="${path%/}"
    # 将 / 转换为 .
    echo "$path" | tr '/' '.'
}

# 获取项目根目录
# 脚本位于 MODULE_DIR 下，需要向上推导
get_project_root() {
    # 脚本所在目录（绝对路径）
    local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    
    # 计算 MODULE_DIR 的层级深度（/ 的数量）
    local depth=$(echo "$MODULE_DIR" | tr -cd '/' | wc -c)
    
    # 从脚本目录向上回退 depth+1 层
    # 例如：script 在 root/modules/plugin1，MODULE_DIR 有 2 个 /，需要回退 3 层到项目根目录
    local root="$script_dir"
    for ((i=0; i<=depth; i++)); do
        root="$(dirname "$root")"
    done
    
    # 验证推导是否正确
    if [[ -d "${root}/${MODULE_DIR}" ]]; then
        echo "$root"
    else
        # fallback: 尝试从 script_dir 向上找 MODULE_DIR
        local temp_root="$script_dir"
        for ((i=0; i<10; i++)); do
            if [[ -d "${temp_root}/${MODULE_DIR}" ]]; then
                echo "$temp_root"
                return
            fi
            temp_root="$(dirname "$temp_root")"
        done
        # 最终 fallback: 脚本目录的父目录
        echo "$(dirname "$script_dir")"
    fi
}

# ==================== 主逻辑 ====================
# 获取项目根目录
PROJECT_ROOT="$(get_project_root)"

# 转换路径为 Python 模块名
MODULE="$(path_to_module "$MODULE_DIR")"
TEST_MODULE="$(path_to_module "$TEST_DIR")"

# 检测当前位置
current_dir="$(pwd)"
current_location="unknown"

if [[ "$current_dir" == "$PROJECT_ROOT/$MODULE_DIR" ]]; then
    current_location="MODULE_DIR"
elif [[ "$current_dir" == "$PROJECT_ROOT/$TEST_DIR" ]]; then
    current_location="TEST_DIR"
elif [[ "$current_dir" == "$PROJECT_ROOT" ]]; then
    current_location="PROJECT_ROOT"
else
    current_location="OTHER"
fi

if [[ "true" == "$DEBUG_SCRIPT" ]]; then 
    echo "当前位置：$current_location ($current_dir)"
    echo "项目根目录：$PROJECT_ROOT"
    echo "测试模块：$TEST_MODULE"
fi

# 进入项目根目录（确保 Python 模块导入路径正确）
pushd "$PROJECT_ROOT"  > /dev/null

# 处理测试模块名称（$1 可能带 .py 也可能不带）
test_name="$1"
if [[ -z "$test_name" ]]; then
    echo "错误：请指定测试模块名称"
    echo "用法：$0 <test_module> [args...]"
    exit 1
fi

# 移除 .py 后缀（如果存在）
test_name="${test_name%.py}"

# 剩余参数
shift
remaining_args="$@"

# 构建完整的 Python 模块路径
full_module="${TEST_MODULE}.${test_name}"

# 日志文件路径（使用绝对路径）
log_file="${PROJECT_ROOT}/${TEST_DIR}/${test_name}.log"

echo "运行：python -m $full_module $remaining_args"
echo "日志：$log_file"
echo "========================================="

# 运行测试并输出日志
python -m "$full_module" $remaining_args 2>&1 | tee "$log_file"

exit_code=${PIPESTATUS[0]}

popd > /dev/null
echo "========================================="
if [[ "true" == "$DEBUG_SCRIPT" ]]; then
    echo "测试完成，退出码：$exit_code"
    echo "日志已保存到：$log_file"
else
    echo ""
fi

exit $exit_code