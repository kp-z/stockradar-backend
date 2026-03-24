#!/bin/bash
# StockRadar 本地开发启动脚本
# 用法: ./dev.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 激活虚拟环境（如果存在）
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

echo "=== StockRadar Dev ==="

# 杀掉旧的 server.py 进程
OLD_PIDS=$(pgrep -f "python.*server\.py" 2>/dev/null)
if [ -n "$OLD_PIDS" ]; then
    echo "[0/2] 停止旧进程 (PID: $OLD_PIDS)..."
    kill $OLD_PIDS 2>/dev/null
    sleep 0.5
fi

# 启动后端
echo "[1/1] 启动后端..."
python server.py &
SERVER_PID=$!

# 等待就绪
sleep 1

echo "后端 PID: $SERVER_PID"
echo "前端地址: http://localhost:31749/index.html"
echo "按 Ctrl+C 停止"

# 捕获退出信号，同时杀掉后端
trap "echo ''; echo '停止服务...'; kill $SERVER_PID 2>/dev/null; exit 0" INT TERM

# 等待后端进程
wait $SERVER_PID
