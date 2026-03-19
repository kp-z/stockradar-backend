# StockRadar Backend

StockRadar 演示引擎后端服务，用于为前端提供 WebSocket 实时数据推送。

## 部署到 Railway

1. 在 Railway 创建新项目
2. 连接此 GitHub 仓库
3. Railway 会自动检测 Python 项目并部署
4. 获取部署后的 WebSocket URL（wss://your-app.railway.app）
5. 在前端配置中更新 WebSocket 地址

## 本地运行

```bash
pip install -r requirements.txt
python server.py
```

服务将在 ws://localhost:9876 启动
