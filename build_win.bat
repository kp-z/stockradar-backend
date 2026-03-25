@echo off
REM StockRadar Windows 应用一键打包脚本
setlocal

echo === StockRadar Windows App Builder ===

REM 检查虚拟环境
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

REM 安装依赖
echo [1/4] 安装依赖...
pip install -r requirements.txt -q
pip install -r requirements-desktop-win.txt -q

REM 生成 ICO 图标
echo [2/4] 生成图标...
if not exist "assets\app_icon.ico" (
    python scripts\generate_ico.py
)

REM 清理旧构建
echo [3/4] 打包中...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM 执行打包
pyinstaller stockradar_win.spec --noconfirm

REM 验证
if exist "dist\StockRadar\StockRadar.exe" (
    echo [4/4] 打包成功!

    REM 创建 ZIP 发行包
    echo 正在创建 ZIP 发行包...
    powershell -Command "Compress-Archive -Path 'dist\StockRadar\*' -DestinationPath 'dist\StockRadar-Windows.zip' -Force"

    echo.
    echo === 构建完成 ===
    echo   EXE: dist\StockRadar\StockRadar.exe
    echo   ZIP: dist\StockRadar-Windows.zip
) else (
    echo [错误] 打包失败，请检查日志
    exit /b 1
)

endlocal
