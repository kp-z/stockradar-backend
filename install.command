#!/bin/bash
# StockRadar 安装助手 - 双击此文件即可完成安装

APP="/Applications/StockRadar.app"

echo "=============================="
echo "  StockRadar 安装助手"
echo "=============================="
echo ""

# 检查是否已安装
if [ ! -d "$APP" ]; then
    echo "未检测到 StockRadar.app，请先将应用拖入 Applications 文件夹，再双击此脚本。"
    echo ""
    read -p "按回车键退出..." _
    exit 1
fi

echo "正在解除系统安全限制..."
xattr -cr "$APP"

echo "完成！正在启动 StockRadar..."
open "$APP"
