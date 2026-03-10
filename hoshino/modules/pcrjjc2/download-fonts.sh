#!/bin/bash

set -e

FONTS_DIR="fonts"
mkdir -p "$FONTS_DIR"
pushd "$FONTS_DIR"

echo "=== 下载开源字体 ==="

# Ubuntu Mono
echo "下载 Ubuntu Mono..."
curl -L "https://gitee.com/zhch186/fonts/raw/master/ubuntu.ttf" \
     -o "ubuntu.ttf"

# Noto Sans Mono CJK SC VF
echo "下载 Noto Sans Mono CJK SC VF..."
curl -L "https://gitee.com/zhch186/fonts/raw/master/NotoSansMonoCJKsc-VF.ttf" \
     -o "NotoSansMonoCJKsc-VF.ttf"

echo "=== 创建符号链接 ==="
ln -sf "NotoSansMonoCJKsc-VF.ttf" "mono.ttf"

echo "=== 完成 ==="
ls -lh
popd
