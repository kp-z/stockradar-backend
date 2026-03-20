"""
StockRadar 引擎 - Railway 部署版
使用 mootdx 通达信数据接口获取真实行情
"""

import asyncio
import json
import time
import random
import websockets
import os
import traceback
import requests
from datetime import datetime

# mootdx 通达信数据接口
from mootdx.quotes import Quotes

WS_PORT = int(os.environ.get('PORT', 8080))

# ── 通达信连接 ──
tdx_client = None

def get_tdx():
    global tdx_client
    try:
        if tdx_client is None:
            tdx_client = Quotes.factory(market='std', bestip=True, timeout=10)
            print("[TDX] 通达信连接成功")
        return tdx_client
    except Exception as e:
        print(f"[TDX] 连接失败: {e}")
        tdx_client = None
        return None

def reconnect_tdx():
    global tdx_client
    tdx_client = None
    return get_tdx()

# ── 股票池 ──
STOCKS = [
    ('000001','平安银行'),('600519','贵州茅台'),('300750','宁德时代'),
    ('688256','寒武纪'),('002230','科大讯飞'),('300308','中际旭创'),
    ('601360','三六零'),('300418','昆仑万维'),('002261','拓维信息'),
    ('300339','润和软件'),('000977','浪潮信息'),('688111','金山办公'),
    ('688041','海光信息'),('300364','中文在线'),('300624','万兴科技'),
    ('600570','恒生电子'),('002371','北方华创'),('688981','中芯国际'),
    ('300059','东方财富'),('601012','隆基绿能'),('002475','立讯精密'),
    ('300760','迈瑞医疗'),('600036','招商银行'),('601318','中国平安'),
    ('002594','比亚迪'),('300274','阳光电源'),('688012','中微公司'),
    ('300033','同花顺'),('300496','中科创达'),('002049','紫光国微'),
    ('688036','传音控股'),('603986','兆易创新'),('300782','卓胜微'),
    ('002415','海康威视'),('300124','汇川技术'),('688169','石头科技'),
    ('300474','景嘉微'),('002241','歌尔股份'),('300661','圣邦股份'),
]

CONCEPT_MAP = {
    '000001':['银行','金融科技'],'600519':['白酒','消费'],'300750':['锂电池','新能源车','储能'],
    '688256':['AI芯片','人工智能','国产替代'],'002230':['人工智能','AI应用'],
    '300308':['光模块','CPO','算力'],'601360':['网络安全','AI大模型'],
    '300418':['AI大模型','AIGC'],'002261':['算力','华为概念','鸿蒙'],
    '300339':['鸿蒙','华为概念'],'000977':['服务器','算力','国产替代'],
    '688111':['AI办公','信创'],'688041':['AI芯片','国产替代'],
    '300364':['AI内容','AIGC'],'300624':['AIGC','AI应用'],
    '600570':['金融科技','数据要素'],'002371':['半导体设备','国产替代'],
    '688981':['芯片','国产替代'],'300059':['券商','金融科技'],
    '601012':['光伏','新能源'],'002475':['苹果产业链','消费电子','MR'],
    '300760':['医疗器械','创新药'],'600036':['银行','金融科技'],
    '601318':['保险','金融科技'],'002594':['新能源车','锂电池','智能驾驶'],
    '300274':['光伏','储能'],'688012':['半导体设备','国产替代'],
    '300033':['金融科技','AI应用'],'300496':['智能驾驶','鸿蒙'],
    '002049':['芯片','军工电子'],'688036':['消费电子','手机'],
    '603986':['存储芯片','国产替代'],'300782':['射频芯片','5G'],
    '002415':['安防','人工智能'],'300124':['工业自动化','机器人'],
    '688169':['扫地机器人','智能家居'],'300474':['GPU','国产替代','军工电子'],
    '002241':['MR','苹果产业链'],'300661':['模拟芯片','芯片'],
}

STOCK_NAMES = {code: name for code, name in STOCKS}

def code_to_market(code):
    """0=深圳 1=上海"""
    return 1 if code.startswith('6') or code.startswith('9') else 0

# ── 上一次快照 ──
last_snapshot = {}

def fetch_realtime_quotes():
    """从通达信获取实时行情快照"""
    client = get_tdx()
    if not client:
        return None
    try:
        # 构建查询列表：[(market, code), ...]
        stock_list = [(code_to_market(code), code) for code, _ in STOCKS]
        df = client.quotes(stock_list)
        if df is None or df.empty:
            return None
        result = {}
        for _, row in df.iterrows():
            code = str(row.get('code', '')).zfill(6)
            price = float(row.get('price', 0))
            last_close = float(row.get('last_close', 0))
            if last_close > 0 and price > 0:
                change = round((price - last_close) / last_close * 100, 2)
            else:
                change = 0
            vol = float(row.get('vol', 0))
            amount = float(row.get('amount', 0))
            result[code] = {
                'price': price,
                'last_close': last_close,
                'change': change,
                'vol': vol,
                'amount': round(amount / 1e8, 2),  # 转为亿
                'open': float(row.get('open', 0)),
                'high': float(row.get('high', 0)),
                'low': float(row.get('low', 0)),
            }
        return result
    except Exception as e:
        print(f"[TDX] 获取行情失败: {e}")
        reconnect_tdx()
        return None

def detect_alerts(quotes):
    """检测异动：涨跌幅大、速度快的股票"""
    global last_snapshot
    alerts = []
    now = datetime.now()
    time_str = now.strftime('%H:%M:%S')

    for code, name in STOCKS:
        q = quotes.get(code)
        if not q or q['price'] <= 0:
            continue

        change = q['change']
        price = q['price']
        amount = q['amount']

        # 计算速度（与上次快照比较）
        speed = 0
        if code in last_snapshot:
            old = last_snapshot[code]
            old_change = old.get('change', 0)
            speed = round(abs(change - old_change), 2)

        # 异动条件：涨跌幅 > 3% 或 速度 > 1%/轮
        is_alert = False
        alert_type = 'volume'
        label = '📊 放量异动'

        if change >= 9.8:
            is_alert = True; alert_type = 'limit-up'; label = '🔒 涨停'
        elif change >= 7:
            is_alert = True; alert_type = 'rocket'; label = '🚀 快速拉升'
        elif change >= 3.5:
            is_alert = True; alert_type = 'rocket'; label = '🚀 强势上涨'
        elif change <= -9.8:
            is_alert = True; alert_type = 'limit-down'; label = '🔒 跌停'
        elif change <= -5:
            is_alert = True; alert_type = 'dive'; label = '🏊 大幅下跌'
        elif change <= -3:
            is_alert = True; alert_type = 'dive'; label = '🏊 快速下跌'
        elif speed >= 1.5:
            is_alert = True; alert_type = 'volume'; label = '⚡ 急速异动'
        elif amount >= 10 and abs(change) >= 2:
            is_alert = True; alert_type = 'volume'; label = '💰 放量异动'

        if is_alert:
            concepts = CONCEPT_MAP.get(code, [])
            alerts.append({
                'id': f"{code}-{int(time.time()*1000)}-{random.randint(100,999)}",
                'code': code,
                'name': name,
                'type': alert_type,
                'label': label,
                'price': price,
                'change': change,
                'speed': speed,
                'amount': amount,
                'time': time_str,
                'timestamp': int(time.time() * 1000),
                'reason': None,
                'concepts': concepts[:3],
            })

    last_snapshot = {code: quotes[code] for code in quotes}
    # 按涨跌幅绝对值排序
    alerts.sort(key=lambda a: abs(a['change']), reverse=True)
    return alerts

def fetch_stock_klines(code, days=60):
    """从通达信获取个股日K线"""
    client = get_tdx()
    if not client:
        return []
    try:
        market = code_to_market(code)
        df = client.bars(symbol=code, frequency=9, offset=days)  # 9=日线
        if df is None or df.empty:
            return []
        result = []
        for _, row in df.iterrows():
            dt = str(row.get('datetime', ''))[:10]
            result.append({
                'date': dt,
                'open': round(float(row.get('open', 0)), 2),
                'close': round(float(row.get('close', 0)), 2),
                'high': round(float(row.get('high', 0)), 2),
                'low': round(float(row.get('low', 0)), 2),
                'volume': float(row.get('vol', 0)),
                'amount': float(row.get('amount', 0)),
            })
        return result
    except Exception as e:
        print(f"[TDX] 获取K线 {code} 失败: {e}")
        reconnect_tdx()
        return []

def fetch_index_quotes():
    """获取沪深指数"""
    client = get_tdx()
    if not client:
        return []
    try:
        # 上证指数(1.999999), 深证成指(0.399001), 沪深300(1.000300)
        df = client.quotes([(1, '999999'), (0, '399001'), (1, '000300')])
        if df is None or df.empty:
            return []
        names = {'999999': '上证指数', '399001': '深证成指', '000300': '沪深300'}
        result = []
        for _, row in df.iterrows():
            code = str(row.get('code', '')).zfill(6)
            price = float(row.get('price', 0))
            last_close = float(row.get('last_close', 0))
            change = round((price - last_close) / last_close * 100, 2) if last_close > 0 else 0
            result.append({
                'name': names.get(code, code),
                'price': round(price, 2),
                'change': change,
            })
        return result
    except Exception as e:
        print(f"[TDX] 获取指数失败: {e}")
        return []

def fetch_sh_klines(days=20):
    """获取上证指数日K线"""
    client = get_tdx()
    if not client:
        return []
    try:
        df = client.bars(symbol='999999', frequency=9, offset=days)
        if df is None or df.empty:
            return []
        result = []
        for _, row in df.iterrows():
            result.append({
                'open': round(float(row.get('open', 0)), 2),
                'close': round(float(row.get('close', 0)), 2),
                'high': round(float(row.get('high', 0)), 2),
                'low': round(float(row.get('low', 0)), 2),
            })
        return result
    except Exception as e:
        print(f"[TDX] 获取上证K线失败: {e}")
        return []

def fetch_market_breadth():
    """从东方财富获取全市场涨跌统计（真实数据）"""
    try:
        # 东方财富全市场涨跌统计API
        url = 'https://push2.eastmoney.com/api/qt/clist/get'
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'}
        # 获取全部A股（沪深）
        params = {
            'pn': 1, 'pz': 1, 'po': 1, 'np': 1, 'fltt': 2, 'invt': 2,
            'fid': 'f3', 'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',
            'fields': 'f2,f3,f4,f12,f14,f104,f105,f106',
            '_': int(time.time() * 1000)
        }
        resp = requests.get(url, params=params, headers=headers, timeout=8)
        data = resp.json()
        total = data.get('data', {}).get('total', 0)

        # f104=上涨家数, f105=下跌家数, f106=平盘家数 在汇总数据中
        # 但这个接口不直接给汇总，我们用另一个接口
        url2 = 'https://push2.eastmoney.com/api/qt/ulist.np/get'
        params2 = {
            'fltt': 2, 'invt': 2,
            'fields': 'f1,f2,f3,f4,f6,f12,f14,f104,f105,f106',
            'secids': '1.000001',  # 上证指数包含涨跌家数
            '_': int(time.time() * 1000)
        }
        resp2 = requests.get(url2, params=params2, headers=headers, timeout=8)
        data2 = resp2.json()
        diff = data2.get('data', {}).get('diff', [])
        if diff:
            item = diff[0]
            up = int(item.get('f104', 0))
            down = int(item.get('f105', 0))
            flat = int(item.get('f106', 0))
        else:
            up, down, flat = 0, 0, 0

        # 涨停跌停数量：用东方财富涨停板接口
        limit_up = 0
        limit_down = 0
        try:
            # 涨停
            url_lu = 'https://push2.eastmoney.com/api/qt/clist/get'
            params_lu = {
                'pn': 1, 'pz': 1, 'po': 1, 'np': 1, 'fltt': 2, 'invt': 2,
                'fid': 'f3', 'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',
                'fields': 'f2,f3,f12',
                'fid': 'f3', 'po': 0,
                'f3': '>=9.8',
                '_': int(time.time() * 1000)
            }
            # 更简单的方式：直接从同花顺获取涨停数
            url_zt = 'https://data.10jqka.com.cn/datacentre/limit_up/limiter_count.html'
            resp_zt = requests.get(url_zt, headers={
                'User-Agent': 'Mozilla/5.0',
                'Referer': 'https://data.10jqka.com.cn/'
            }, timeout=5)
            if resp_zt.status_code == 200:
                zt_data = resp_zt.json()
                limit_up = zt_data.get('data', {}).get('limit_up_count', 0)
                limit_down = zt_data.get('data', {}).get('limit_down_count', 0)
        except Exception as e:
            print(f"[情绪] 获取涨停数失败: {e}")

        total_count = up + down + flat or 1
        return {
            'up': up, 'down': down, 'flat': flat,
            'total': total_count,
            'ratio': round(up / total_count * 100, 1),
            'limit_up': limit_up,
            'limit_down': limit_down,
        }
    except Exception as e:
        print(f"[情绪] 获取市场宽度失败: {e}")
        return {'up': 0, 'down': 0, 'flat': 0, 'total': 1, 'ratio': 0, 'limit_up': 0, 'limit_down': 0}

def fetch_kaipanla_sectors():
    """从开盘啦获取题材涨停排名"""
    try:
        # 开盘啦涨停题材排名API
        url = 'https://pchq.kaipanla.com/w1/api/index.php'
        params = {
            'c': 'PCArrangeData',
            'a': 'StrengthRank',
            'st': 'ZTStock',
            'ot': 'desc',
            'UserID': '0',
            'Token': '0',
            'PhoneOSNew': '1',
            'DeviceID': 'web',
            'VerSion': '5.8.0.2',
        }
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://www.kaipanla.com/',
        }
        resp = requests.get(url, params=params, headers=headers, timeout=8)
        data = resp.json()
        items = data.get('list', data.get('data', []))
        sectors = []
        for item in items[:10]:
            name = item.get('GnName', item.get('Name', item.get('gn_name', '')))
            zt_count = item.get('ZTStock', item.get('zt_count', item.get('LimitUpNum', 0)))
            leader = item.get('LeadStock', item.get('lead_stock', ''))
            if name:
                sectors.append({
                    'name': name,
                    'change': int(zt_count) if zt_count else 0,
                    'isLimitCount': True,
                    'leader': leader,
                })
        if sectors:
            print(f"[开盘啦] 获取到 {len(sectors)} 个题材")
        return sectors
    except Exception as e:
        print(f"[开盘啦] 获取题材排名失败: {e}")
        traceback.print_exc()
        return []

def gen_sentiment_data():
    """生成情绪面板数据（真实数据源）"""
    indices = fetch_index_quotes()
    sh_klines = fetch_sh_klines(20)

    # 市场宽度：从东方财富获取全市场真实涨跌统计
    breadth = fetch_market_breadth()

    # 题材涨停排名：从开盘啦获取
    sectors = fetch_kaipanla_sectors()

    return {
        'indices': indices,
        'breadth': breadth,
        'sectors': sectors,
        'history': [],
        'sh_klines': sh_klines,
    }

def get_market_state():
    """判断市场状态"""
    now = datetime.now()
    h, m = now.hour, now.minute
    t = h * 100 + m
    weekday = now.weekday()
    if weekday >= 5:
        return 'closed'
    if t < 915:
        return 'pre'
    if 915 <= t < 930:
        return 'call'
    if 930 <= t < 1130:
        return 'open'
    if 1130 <= t < 1300:
        return 'lunch'
    if 1300 <= t < 1500:
        return 'open'
    return 'closed'

# ── WebSocket ──
clients = set()
all_alerts = []  # 累积的异动

async def ws_handler(websocket):
    clients.add(websocket)
    print(f"[WS] +1 客户端 ({len(clients)})")
    try:
        # 发送初始数据
        await websocket.send(json.dumps({
            'type': 'init',
            'alerts': all_alerts[:50],
            'market': get_market_state()
        }))
        async for msg in websocket:
            try:
                data = json.loads(msg)
                if data.get('action') == 'refresh':
                    await websocket.send(json.dumps({
                        'type': 'init',
                        'alerts': all_alerts[:50],
                        'market': get_market_state()
                    }))
                elif data.get('action') == 'get_klines':
                    code = data.get('code', '')
                    days = min(int(data.get('days', 60)), 150)
                    klines = fetch_stock_klines(code, days)
                    await websocket.send(json.dumps({
                        'type': 'klines',
                        'data': klines
                    }))
                    print(f"[K线] {code} {days}日 → {len(klines)}条")
                elif data.get('action') == 'get_sentiment':
                    sentiment = gen_sentiment_data()
                    await websocket.send(json.dumps({
                        'type': 'sentiment',
                        'data': sentiment
                    }))
                elif data.get('action') == 'update_schemes':
                    pass
            except Exception as e:
                print(f"[WS] 消息处理错误: {e}")
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        clients.discard(websocket)
        print(f"[WS] -1 客户端 ({len(clients)})")

async def broadcast(data):
    if not clients:
        return
    msg = json.dumps(data)
    await asyncio.gather(*[ws.send(msg) for ws in clients.copy()], return_exceptions=True)

async def scan_loop():
    """主扫描循环：每3秒获取行情并检测异动"""
    global all_alerts
    print("[扫描] 启动实时扫描循环")

    # 启动时先连接通达信
    get_tdx()

    while True:
        try:
            state = get_market_state()

            # 盘中才扫描
            if state in ('open', 'call'):
                quotes = fetch_realtime_quotes()
                if quotes:
                    new_alerts = detect_alerts(quotes)
                    if new_alerts:
                        all_alerts = new_alerts + all_alerts
                        all_alerts = all_alerts[:200]
                        await broadcast({
                            'type': 'alerts',
                            'items': new_alerts
                        })
                        for a in new_alerts[:3]:
                            print(f"[异动] {a['name']} {a['label']} {'+' if a['change']>=0 else ''}{a['change']}%")
                else:
                    print("[扫描] 未获取到行情数据")
            else:
                # 非盘中：每30秒检查一次状态
                await asyncio.sleep(27)

        except Exception as e:
            print(f"[扫描] 错误: {e}")
            traceback.print_exc()

        await asyncio.sleep(3)

async def main():
    server = await websockets.serve(ws_handler, "0.0.0.0", WS_PORT)
    print(f"[StockRadar] ws://0.0.0.0:{WS_PORT} (mootdx 真实行情)")
    await scan_loop()

if __name__ == '__main__':
    asyncio.run(main())
