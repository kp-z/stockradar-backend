"""
StockRadar 演示引擎 - Railway 部署版
"""

import asyncio
import json
import time
import random
import websockets
import os

# Railway 会提供 PORT 环境变量
WS_PORT = int(os.environ.get('PORT', 9876))

STOCKS = [
    ('000001', '平安银行', ['银行','金融科技','数字货币']),
    ('600519', '贵州茅台', ['白酒','消费','大盘蓝筹']),
    ('300750', '宁德时代', ['锂电池','新能源车','储能']),
    ('688256', '寒武纪', ['AI芯片','人工智能','国产替代']),
    ('002230', '科大讯飞', ['人工智能','AI应用','教育信息化']),
    ('300308', '中际旭创', ['光模块','CPO','算力']),
    ('601360', '三六零', ['网络安全','AI大模型','数据要素']),
    ('300418', '昆仑万维', ['AI大模型','AIGC','游戏']),
    ('002261', '拓维信息', ['算力','华为概念','鸿蒙']),
    ('300339', '润和软件', ['鸿蒙','华为概念','金融科技']),
    ('000977', '浪潮信息', ['服务器','算力','国产替代']),
    ('688111', '金山办公', ['AI办公','信创','SaaS']),
    ('688041', '海光信息', ['AI芯片','国产替代','信创']),
    ('300364', '中文在线', ['AI内容','AIGC','数字版权']),
    ('300624', '万兴科技', ['AIGC','AI应用','SaaS']),
    ('600570', '恒生电子', ['金融科技','金融IT','数据要素']),
    ('002371', '北方华创', ['半导体设备','国产替代','芯片']),
    ('688981', '中芯国际', ['芯片','国产替代','半导体设备']),
    ('300059', '东方财富', ['券商','金融科技','互联网金融']),
    ('601012', '隆基绿能', ['光伏','新能源','HJT']),
    ('002475', '立讯精密', ['苹果产业链','消费电子','MR']),
    ('300760', '迈瑞医疗', ['医疗器械','创新药','大盘蓝筹']),
    ('600036', '招商银行', ['银行','金融科技','大盘蓝筹']),
    ('601318', '中国平安', ['保险','金融科技','大盘蓝筹']),
    ('002594', '比亚迪', ['新能源车','锂电池','智能驾驶']),
    ('300274', '阳光电源', ['光伏','储能','新能源']),
    ('688012', '中微公司', ['半导体设备','国产替代','芯片']),
    ('300033', '同花顺', ['金融科技','AI应用','券商']),
    ('300496', '中科创达', ['智能驾驶','鸿蒙','AI应用']),
    ('002049', '紫光国微', ['芯片','国产替代','军工电子']),
    ('688036', '传音控股', ['消费电子','非洲概念','手机']),
    ('603986', '兆易创新', ['存储芯片','国产替代','芯片']),
    ('300782', '卓胜微', ['射频芯片','消费电子','5G']),
    ('002415', '海康威视', ['安防','人工智能','智慧城市']),
    ('300124', '汇川技术', ['工业自动化','机器人','新能源车']),
    ('688169', '石头科技', ['扫地机器人','消费电子','智能家居']),
    ('300474', '景嘉微', ['GPU','国产替代','军工电子']),
    ('002241', '歌尔股份', ['MR','苹果产业链','消费电子']),
    ('300661', '圣邦股份', ['模拟芯片','芯片','国产替代']),
]

ALERT_TEMPLATES = [
    {'type':'rocket','label':'🚀 火箭发射','cr':(3.5,9.8),'sr':(3.0,8.0)},
    {'type':'dive','label':'🏊 高台跳水','cr':(-8.0,-1.5),'sr':(-7.0,-3.0)},
    {'type':'volume','label':'📊 放量突破','cr':(2.0,7.0),'sr':(1.0,4.0)},
    {'type':'limit-up','label':'🔒 接近涨停','cr':(9.0,9.8),'sr':(2.0,6.0)},
    {'type':'limit-up','label':'🔒 涨停','cr':(9.95,10.02),'sr':(0.5,3.0)},
    {'type':'limit-down','label':'🔒 跌停','cr':(-10.02,-9.95),'sr':(-3.0,-0.5)},
    {'type':'volume','label':'💰 超大单 12350手','cr':(1.0,6.0),'sr':(0.5,3.0)},
    {'type':'volume','label':'💰 超大单 9800手','cr':(0.5,4.0),'sr':(0.3,2.0)},
    {'type':'reversal','label':'🔄 V型反转','cr':(-1.0,3.0),'sr':(2.0,5.0)},
]

NEWS_POOL = [
    '工信部发布人工智能产业发展新规划',
    '机构研报上调目标价至历史新高',
    '公司公告拟10转5派3元',
    '获北向资金连续5日净买入',
    '子公司与英伟达达成战略合作',
    '一季度业绩预增120%-150%',
    '大股东增持500万股',
    '纳入MSCI中国指数成分股',
    '获得国产替代大额订单',
    '央行降准0.5个百分点释放1.2万亿',
    '新能源车补贴延续至年底',
    '人形机器人量产进程加速',
    '低空经济政策密集落地',
    '华为发布新一代昇腾芯片',
    '苹果MR头显销量超预期',
    None, None, None, None,
]

def gen_alert(offset):
    code, name, concepts = random.choice(STOCKS)
    tmpl = random.choice(ALERT_TEMPLATES)
    change = round(random.uniform(*tmpl['cr']), 2)
    speed = round(random.uniform(*tmpl['sr']), 2)
    amount = round(random.uniform(0.5, 45.0), 2)
    minutes = offset // 60
    seconds = offset % 60
    h = 9 + (30 + minutes) // 60
    m = (30 + minutes) % 60
    time_str = f"{h:02d}:{m:02d}:{seconds:02d}"
    reason = random.choice(NEWS_POOL)
    n = random.randint(1, min(3, len(concepts)))
    tags = concepts[:n]

    return {
        'id': f"{code}-{int(time.time()*1000)}-{random.randint(100,999)}",
        'code': code,
        'name': name,
        'type': tmpl['type'],
        'label': tmpl['label'],
        'price': round(random.uniform(5, 300), 2),
        'change': change,
        'speed': speed,
        'amount': amount,
        'time': time_str,
        'timestamp': int(time.time() * 1000),
        'reason': reason,
        'concepts': tags,
    }

# 预生成演示数据
demo_alerts = []
t = 0
while t < 1800:
    demo_alerts.append(gen_alert(t))
    t += random.randint(3, 25)
demo_alerts.reverse()
print(f"[演示] 生成 {len(demo_alerts)} 条模拟异动")

clients = set()
feed_index = 0

async def ws_handler(websocket):
    clients.add(websocket)
    print(f"[WS] +1 客户端 ({len(clients)})")
    try:
        await websocket.send(json.dumps({
            'type': 'init',
            'alerts': demo_alerts[:20],
            'market': 'open'
        }))
        async for msg in websocket:
            data = json.loads(msg)
            if data.get('action') == 'refresh':
                await websocket.send(json.dumps({
                    'type': 'init', 'alerts': demo_alerts[:50], 'market': 'open'
                }))
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        clients.discard(websocket)
        print(f"[WS] -1 客户端 ({len(clients)})")

async def broadcast(data):
    if not clients: return
    msg = json.dumps(data)
    await asyncio.gather(*[ws.send(msg) for ws in clients.copy()], return_exceptions=True)

async def feed_loop():
    global feed_index
    feed_index = 20
    while True:
        await asyncio.sleep(random.uniform(2, 5))
        if feed_index < len(demo_alerts):
            alert = demo_alerts[feed_index]
            feed_index += 1
        else:
            alert = gen_alert(random.randint(0, 1800))
        from datetime import datetime
        now = datetime.now()
        alert['time'] = now.strftime('%H:%M:%S')
        alert['timestamp'] = int(time.time() * 1000)
        await broadcast({'type': 'alerts', 'items': [alert]})
        print(f"[推送] {alert['name']} {alert['label']} {'+' if alert['change']>=0 else ''}{alert['change']}%")

async def main():
    # 监听所有接口，Railway 需要
    server = await websockets.serve(ws_handler, "0.0.0.0", WS_PORT)
    print(f"[StockRadar 演示引擎] ws://0.0.0.0:{WS_PORT}")
    await feed_loop()

if __name__ == '__main__':
    asyncio.run(main())
