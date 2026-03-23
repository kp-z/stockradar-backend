#!/bin/bash
# StockRadar Mac 应用一键打包脚本
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== StockRadar Mac App Builder ==="

# 检查虚拟环境
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# 安装依赖
echo "[1/3] 安装依赖..."
pip install -r requirements.txt -q
pip install -r requirements-desktop.txt -q

# 清理旧构建
echo "[2/3] 打包中..."
rm -rf build dist

# 执行打包
pyinstaller stockradar.spec --noconfirm

# 验证
if [ -d "dist/StockRadar.app" ]; then
    echo "[3/4] 打包成功!"
    du -sh dist/StockRadar.app

    # 制作 DMG 安装镜像（含 Applications 快捷方式）
    echo "[4/4] 制作 DMG 安装镜像..."
    rm -f dist/StockRadar.dmg
    rm -rf dist/dmg_staging
    mkdir -p dist/dmg_staging
    cp -r dist/StockRadar.app dist/dmg_staging/
    cp install.command dist/dmg_staging/
    ln -s /Applications dist/dmg_staging/Applications
    hdiutil create -volname "StockRadar" \
        -srcfolder dist/dmg_staging \
        -ov -format UDZO \
        dist/StockRadar.dmg
    rm -rf dist/dmg_staging

    echo ""
    echo "=== 构建完成 ==="
    echo "  DMG: dist/StockRadar.dmg"
    du -sh dist/StockRadar.dmg
    echo ""
    echo "  安装方式: 双击 DMG → 拖入 Applications → 双击「install.command」完成安装"
else
    echo "[错误] 打包失败，请检查日志"
    exit 1
fi
