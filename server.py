"""
StockRadar 引擎 - Railway 部署版
使用 mootdx 通达信数据接口获取真实行情
"""

import asyncio
import json
import time
import random
import websockets
from websockets.asyncio.server import Request, Response
from websockets.datastructures import Headers
import os
import sys
import shutil
import traceback
import requests
from datetime import datetime, timedelta
import sqlite3
import hashlib
import secrets

# ── Supabase 云同步（可选） ──
try:
    from supabase_sync import (
        init_supabase, is_available, set_sync_enabled,
        cloud_register, cloud_login, cloud_create_session,
        cloud_save_watchlist, cloud_get_watchlist,
        cloud_save_schemes, cloud_get_schemes,
        enqueue_sync, drain_sync_queue, merge_watchlists,
        cloud_login_verify, cloud_get_all_users_admin,
    )
    SUPABASE_LOADED = True
except ImportError:
    SUPABASE_LOADED = False


def _get_resource_dir():
    """PyInstaller 打包后的只读资源目录，开发时为项目根目录"""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def _get_data_dir():
    """可读写的数据目录，打包后放 ~/Library/Application Support/StockRadar/"""
    if getattr(sys, 'frozen', False):
        data_dir = os.path.expanduser('~/Library/Application Support/StockRadar')
        os.makedirs(data_dir, exist_ok=True)
        return data_dir
    return os.path.dirname(os.path.abspath(__file__))

# ── SQLite 用户数据库 ──
DB_FILE = os.path.join(_get_data_dir(), 'stockradar.db')

def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            last_login TEXT
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT DEFAULT (datetime('now')),
            expires_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_watchlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            stock_code TEXT NOT NULL,
            added_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, stock_code)
        );
        CREATE TABLE IF NOT EXISTS user_schemes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            schemes_json TEXT NOT NULL,
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id)
        );
    ''')
    # ── 云同步迁移 ──
    try:
        conn.execute("ALTER TABLE users ADD COLUMN cloud_user_id TEXT")
    except sqlite3.OperationalError:
        pass  # 列已存在
    conn.execute('''CREATE TABLE IF NOT EXISTS sync_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        retry_count INTEGER DEFAULT 0
    )''')
    cur = conn.execute("SELECT COUNT(*) FROM users WHERE is_admin=1")
    if cur.fetchone()[0] == 0:
        print("[DB] 无本地管理员，首次登录后将从 Supabase 同步")
    conn.commit()
    conn.close()

def _hash_password(password, salt):
    return hashlib.sha256((password + salt).encode()).hexdigest()

def create_user(username, password):
    if not (SUPABASE_LOADED and is_available()):
        return False, '服务不可用，无法注册（需要网络连接）'
    salt = secrets.token_hex(16)
    pw_hash = _hash_password(password, salt)
    try:
        cloud_uid = cloud_register(username, pw_hash, salt)
    except ValueError as e:
        return False, str(e)
    if cloud_uid is None:
        return False, '注册失败，请稍后重试'
    conn = sqlite3.connect(DB_FILE)
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, salt, cloud_user_id) VALUES (?, '', '', ?)",
            (username, cloud_uid),
        )
        conn.commit()
        return True, None
    except sqlite3.IntegrityError:
        return False, '用户名已存在'
    finally:
        conn.close()

def verify_user(username, password):
    if not (SUPABASE_LOADED and is_available()):
        return None
    cloud_user = cloud_login_verify(username, password)
    if not cloud_user:
        return None
    # 确保本地有该用户记录（用于 session 关联），同步 is_admin
    conn = sqlite3.connect(DB_FILE)
    row = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if not row:
        conn.execute(
            "INSERT INTO users (username, password_hash, salt, cloud_user_id, is_admin) VALUES (?, '', '', ?, ?)",
            (username, cloud_user['cloud_id'], 1 if cloud_user['is_admin'] else 0),
        )
        conn.commit()
        row = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    else:
        conn.execute(
            "UPDATE users SET cloud_user_id=?, is_admin=? WHERE username=?",
            (cloud_user['cloud_id'], 1 if cloud_user['is_admin'] else 0, username),
        )
        conn.commit()
    local_id = row[0]
    conn.close()
    return {'id': local_id, 'username': username, 'is_admin': cloud_user['is_admin'], 'cloud_user_id': cloud_user['cloud_id']}

def create_session(user_id):
    token = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(days=7)).isoformat()
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)", (token, user_id, expires))
    conn.execute("UPDATE users SET last_login=datetime('now') WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    return token

def get_user_by_token(token):
    conn = sqlite3.connect(DB_FILE)
    row = conn.execute("""
        SELECT u.id, u.username, u.is_admin, u.cloud_user_id FROM sessions s
        JOIN users u ON s.user_id = u.id
        WHERE s.token = ? AND s.expires_at > datetime('now')
    """, (token,)).fetchone()
    conn.close()
    if row:
        return {'id': row[0], 'username': row[1], 'is_admin': bool(row[2]), 'cloud_user_id': row[3]}
    return None

def save_user_watchlist(user_id, codes):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM user_watchlists WHERE user_id=?", (user_id,))
    for code in codes:
        conn.execute("INSERT OR IGNORE INTO user_watchlists (user_id, stock_code) VALUES (?, ?)", (user_id, code))
    conn.commit()
    conn.close()

def get_user_watchlist(user_id):
    conn = sqlite3.connect(DB_FILE)
    rows = conn.execute("SELECT stock_code FROM user_watchlists WHERE user_id=? ORDER BY added_at", (user_id,)).fetchall()
    conn.close()
    return [r[0] for r in rows]

def save_user_schemes(user_id, schemes_json):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""INSERT INTO user_schemes (user_id, schemes_json, updated_at) VALUES (?, ?, datetime('now'))
                    ON CONFLICT(user_id) DO UPDATE SET schemes_json=excluded.schemes_json, updated_at=datetime('now')""",
                 (user_id, schemes_json))
    conn.commit()
    conn.close()

def get_user_schemes(user_id):
    conn = sqlite3.connect(DB_FILE)
    row = conn.execute("SELECT schemes_json FROM user_schemes WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return json.loads(row[0]) if row else None

def get_all_users_admin():
    conn = sqlite3.connect(DB_FILE)
    users = conn.execute("SELECT id, username, is_admin, created_at, last_login FROM users ORDER BY id").fetchall()
    result = []
    for u in users:
        wl = get_user_watchlist(u[0])
        sc = get_user_schemes(u[0])
        result.append({
            'id': u[0], 'username': u[1], 'is_admin': bool(u[2]),
            'created_at': u[3], 'last_login': u[4],
            'watchlist': wl, 'schemes': sc
        })
    conn.close()
    return result

# mootdx 通达信数据接口
from mootdx.quotes import Quotes

# 可选：Ashare 备用数据源（新浪/腾讯双核心）
try:
    from ashare_adapter import fetch_klines_ashare, preload_all_klines_ashare, fetch_index_klines_ashare
    from ashare_adapter import is_available as ashare_available
    print(f"[Ashare] 适配层已加载, 可用={ashare_available()}")
except ImportError:
    def fetch_klines_ashare(code, days=150): return []
    def preload_all_klines_ashare(stocks, days=150): return {}
    def ashare_available(): return False

WS_PORT = int(os.environ.get('PORT', 31749))

# ── 运行时配置（可由前端 WS 实时更新） ──
APP_CONFIG = {
    'sector_source': 'kaipanla',   # 'kaipanla' | 'eastmoney'
    'kaipanla_user_id': '0',
    'kaipanla_token': '0',
    'ashare_enabled': True,        # 是否启用 Ashare 备用源
    'ashare_as_primary': False,    # True = Ashare 作为K线主力（替换TDX）
}

# ── 管理员自定义板块涨幅数据（非空时优先于 API） ──
ADMIN_CUSTOM_SECTORS = []

# ── 情绪数据缓存 ──
_sentiment_cache = {'data': None, 'ts': 0}
_SENTIMENT_TTL_OPEN = 60     # 开盘时60秒TTL
_SENTIMENT_TTL_CLOSED = 300  # 闭盘时300秒TTL

def get_sentiment_cached():
    """带缓存的情绪数据获取"""
    now = time.time()
    state = get_market_state()
    ttl = _SENTIMENT_TTL_OPEN if state in ('open', 'call') else _SENTIMENT_TTL_CLOSED
    if _sentiment_cache['data'] and (now - _sentiment_cache['ts']) < ttl:
        return _sentiment_cache['data']
    data = gen_sentiment_data()
    _sentiment_cache['data'] = data
    _sentiment_cache['ts'] = now
    return data

# ── 通达信连接 ──
tdx_client = None

def get_tdx():
    global tdx_client
    try:
        if tdx_client is None:
            tdx_client = Quotes.factory(market='std', bestip=False, timeout=5)
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

# ── K线缓存 {code: [kline_list]} ──
klines_cache = {}
KLINES_FILE = os.path.join(_get_data_dir(), 'klines_data.json')

# 打包环境首次启动时，从 bundle 资源复制初始缓存
if getattr(sys, 'frozen', False) and not os.path.exists(KLINES_FILE):
    _bundled = os.path.join(_get_resource_dir(), 'klines_data.json')
    if os.path.exists(_bundled):
        shutil.copy2(_bundled, KLINES_FILE)
_last_save_date = ''  # 上次收盘保存的日期 YYYY-MM-DD
_today_updated = False  # 今天是否已用实时行情更新过当天K线

def load_klines_from_file():
    """启动时从本地JSON文件加载K线数据（毫秒级）"""
    global klines_cache
    if os.path.exists(KLINES_FILE):
        try:
            with open(KLINES_FILE, 'r', encoding='utf-8') as f:
                klines_cache = json.load(f)
            total = sum(len(v) for v in klines_cache.values())
            print(f"[缓存] 从本地文件加载成功: {len(klines_cache)} 只股票, 共 {total} 条K线")
            return True
        except Exception as e:
            print(f"[缓存] 本地文件加载失败: {e}")
    return False

def save_klines_to_file():
    """将K线缓存保存到本地JSON文件"""
    try:
        with open(KLINES_FILE, 'w', encoding='utf-8') as f:
            json.dump(klines_cache, f, ensure_ascii=False)
        total = sum(len(v) for v in klines_cache.values())
        print(f"[缓存] 已保存到本地文件: {len(klines_cache)} 只股票, 共 {total} 条K线")
    except Exception as e:
        print(f"[缓存] 保存失败: {e}")

def preload_all_klines(days=150):
    """从通达信下载所有个股K线数据"""
    global klines_cache
    client = get_tdx()
    if not client:
        print("[预加载] 通达信未连接，跳过")
        _preload_ashare_fallback(days)
        return
    loaded = 0
    for code, name in STOCKS:
        try:
            df = client.bars(symbol=code, frequency=9, offset=days)
            if df is not None and not df.empty:
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
                klines_cache[code] = result
                loaded += 1
        except Exception as e:
            print(f"[预加载] {code} {name} 失败: {e}")
    print(f"[预加载] 完成，共加载 {loaded}/{len(STOCKS)} 只股票的 {days} 日K线")
    # 保存到文件
    save_klines_to_file()

    # Ashare fallback：TDX 未连接时用 Ashare 补充
def _preload_ashare_fallback(days=150):
    """TDX 不可用时用 Ashare 批量预加载K线"""
    if APP_CONFIG.get('ashare_enabled') and ashare_available():
        print("[预加载] 通达信不可用，切换 Ashare 备用源...")
        ashare_data = preload_all_klines_ashare(STOCKS, days)
        if ashare_data:
            klines_cache.update(ashare_data)
            save_klines_to_file()

def trim_klines_to_150():
    """修剪每只股票的K线数据，只保留最近150天"""
    for code in klines_cache:
        if len(klines_cache[code]) > 150:
            klines_cache[code] = klines_cache[code][-150:]

def update_today_kline_from_quotes(quotes):
    """用实时行情更新当天的K线数据（盘中每轮调用）"""
    if not quotes:
        return
    today_str = datetime.now().strftime('%Y-%m-%d')
    updated = 0
    for code, name in STOCKS:
        q = quotes.get(code)
        if not q or q['price'] <= 0:
            continue
        klines = klines_cache.get(code, [])
        if not klines:
            continue
        # 构造当天K线
        today_k = {
            'date': today_str,
            'open': q['open'] if q['open'] > 0 else q['price'],
            'close': q['price'],
            'high': q['high'] if q['high'] > 0 else q['price'],
            'low': q['low'] if q['low'] > 0 else q['price'],
            'volume': q['vol'],
            'amount': q['amount'] * 1e8,  # 转回原始单位
        }
        # 如果最后一条是今天的，替换；否则追加
        if klines and klines[-1]['date'] == today_str:
            klines[-1] = today_k
        else:
            klines.append(today_k)
        klines_cache[code] = klines
        updated += 1
    return updated

def on_market_close():
    """收盘时调用：修剪到150天并保存"""
    global _last_save_date, _today_updated
    today_str = datetime.now().strftime('%Y-%m-%d')
    if _last_save_date == today_str:
        return  # 今天已保存过
    trim_klines_to_150()
    save_klines_to_file()
    _last_save_date = today_str
    _today_updated = False
    print(f"[收盘] 已保存 {today_str} 完整数据，维护150天窗口")

def refresh_klines_cache_if_needed():
    """检查是否需要刷新缓存（仅在缓存为空时从通达信重新下载）"""
    if not klines_cache:
        print("[缓存] 缓存为空，从通达信下载...")
        preload_all_klines(150)

# ── 方案选股引擎 ──
def screen_stocks_by_schemes(schemes, quotes=None):
    """根据方案条件筛选股票，返回符合条件的 alerts 列表"""
    if not schemes:
        return []

    now = datetime.now()
    time_str = now.strftime('%H:%M:%S')
    results = []

    for code, name in STOCKS:
        klines = klines_cache.get(code, [])
        if not klines or len(klines) < 5:
            continue

        q = quotes.get(code) if quotes else None
        matched_schemes = []

        for scheme in schemes:
            if not scheme.get('enabled', False):
                continue
            conds = scheme.get('conditions', {})
            all_pass = False
            any_enabled = False

            for key, cond in conds.items():
                if not cond.get('enabled', False):
                    continue
                any_enabled = True
                if not check_condition(key, cond, code, klines, q):
                    break
            else:
                if any_enabled:
                    all_pass = True

            if all_pass:
                matched_schemes.append(scheme.get('name', '未命名'))

        if matched_schemes:
            last_k = klines[-1]
            prev_k = klines[-2] if len(klines) >= 2 else last_k
            price = q['price'] if q and q.get('price', 0) > 0 else last_k['close']
            change = q['change'] if q else round((last_k['close'] - prev_k['close']) / prev_k['close'] * 100, 2) if prev_k['close'] > 0 else 0
            amount = q['amount'] if q else round(last_k['amount'] / 1e8, 2)
            speed = q.get('speed', 0) if q else 0
            concepts = CONCEPT_MAP.get(code, [])

            results.append({
                'id': f"{code}-screen-{int(time.time()*1000)}-{random.randint(100,999)}",
                'code': code,
                'name': name,
                'type': 'volume',
                'label': '📊 方案选股',
                'price': price,
                'change': change,
                'speed': speed,
                'amount': amount,
                'time': time_str,
                'timestamp': int(time.time() * 1000),
                'reason': None,
                'concepts': concepts[:3],
                'matched_schemes': matched_schemes,
            })

    results.sort(key=lambda a: abs(a['change']), reverse=True)
    return results

def check_condition(key, cond, code, klines, q):
    """检查单个条件是否满足"""
    try:
        last_k = klines[-1]
        closes = [k['close'] for k in klines]
        highs = [k['high'] for k in klines]
        lows = [k['low'] for k in klines]
        amounts = [k['amount'] for k in klines]
        volumes = [k['volume'] for k in klines]
        price = q['price'] if q and q.get('price', 0) > 0 else last_k['close']

        if key == 'marketCap':
            cap_min = float(cond.get('min', 0))
            cap_max = float(cond.get('max', 9999))
            float_shares = _float_shares_cache.get(code, 0)
            if float_shares <= 0:
                return True  # 无流通股本数据时跳过此条件
            cap = price * float_shares / 1e8  # 流通市值（亿元）
            return cap_min <= cap <= cap_max

        elif key == 'limitUp':
            change = q['change'] if q else 0
            if not q and len(klines) >= 2:
                change = round((closes[-1] - closes[-2]) / closes[-2] * 100, 2) if closes[-2] > 0 else 0
            return change >= 9.8

        elif key == 'limitDown':
            change = q['change'] if q else 0
            if not q and len(klines) >= 2:
                change = round((closes[-1] - closes[-2]) / closes[-2] * 100, 2) if closes[-2] > 0 else 0
            return change <= -9.8

        elif key == 'amountHigh':
            days = int(cond.get('days', 5))
            if len(amounts) < days + 1:
                return False
            recent = amounts[-days-1:-1]
            return amounts[-1] > max(recent) if recent else False

        elif key == 'amountLow':
            days = int(cond.get('days', 5))
            if len(amounts) < days + 1:
                return False
            recent = amounts[-days-1:-1]
            return amounts[-1] < min(recent) if recent else False

        elif key == 'amountMultiple':
            multiple = float(cond.get('multiple', 2))
            if len(amounts) < 2:
                return False
            return amounts[-1] >= amounts[-2] * multiple if amounts[-2] > 0 else False

        elif key == 'volumeRatio':
            vr_min = float(cond.get('min', 2))
            if len(volumes) < 6:
                return False
            avg5 = sum(volumes[-6:-1]) / 5
            return volumes[-1] >= avg5 * vr_min if avg5 > 0 else False

        elif key == 'breakDayMA':
            period = int(cond.get('period', 5))
            if len(closes) < period + 1:
                return False
            ma = sum(closes[-period:]) / period
            prev_close = closes[-2]
            return prev_close < ma and price >= ma

        elif key == 'breakGolden':
            days = int(cond.get('days', 20))
            ratio = float(cond.get('ratio', 0.382))
            if len(klines) < days:
                return False
            recent = klines[-days:]
            high = max(k['high'] for k in recent)
            low = min(k['low'] for k in recent)
            golden_level = high - (high - low) * ratio
            return price >= golden_level and closes[-2] < golden_level if len(closes) >= 2 else False

        elif key == 'bollingerUp':
            rules = cond.get('rules', [])
            if not rules and 'band' in cond:
                rules = [{'band': cond.get('band', 'upper'), 'period': cond.get('period', '20d')}]
            if not rules:
                return False
            for rule in rules:
                band = rule.get('band', 'upper')
                period_str = rule.get('period', '20d')
                period = int(period_str.replace('d', '').replace('m', '')) if isinstance(period_str, str) else 20
                if len(closes) < period:
                    return False
                sma = sum(closes[-period:]) / period
                std = (sum((c - sma)**2 for c in closes[-period:]) / period) ** 0.5
                if band == 'upper':
                    level = sma + 2 * std
                elif band == 'middle':
                    level = sma
                else:
                    level = sma - 2 * std
                if not (len(closes) >= 2 and price >= level and closes[-2] < level):
                    return False
            return True

        elif key == 'bollingerDown':
            rules = cond.get('rules', [])
            if not rules and 'band' in cond:
                rules = [{'band': cond.get('band', 'lower'), 'period': cond.get('period', '20d')}]
            if not rules:
                return False
            for rule in rules:
                band = rule.get('band', 'lower')
                period_str = rule.get('period', '20d')
                period = int(period_str.replace('d', '').replace('m', '')) if isinstance(period_str, str) else 20
                if len(closes) < period:
                    return False
                sma = sum(closes[-period:]) / period
                std = (sum((c - sma)**2 for c in closes[-period:]) / period) ** 0.5
                if band == 'lower':
                    level = sma - 2 * std
                elif band == 'middle':
                    level = sma
                else:
                    level = sma + 2 * std
                if not (len(closes) >= 2 and price <= level and closes[-2] > level):
                    return False
            return True

        elif key == 'cupHandle':
            days = int(cond.get('days', 20))
            dayA = int(cond.get('dayA', 5))
            dayB = int(cond.get('dayB', 10))
            minPct = float(cond.get('minPct', 10))
            maxPct = float(cond.get('maxPct', 30))
            if len(klines) < max(days, dayA, dayB) + 1:
                return False
            high_n = max(k['high'] for k in klines[-days:])
            closeA = closes[-dayA] if dayA <= len(closes) else closes[0]
            closeB = closes[-dayB] if dayB <= len(closes) else closes[0]
            if closeB <= 0:
                return False
            pct = (closeA - closeB) / closeB * 100
            return price >= high_n and minPct <= pct <= maxPct

        elif key == 'priceCompare':
            rules = cond.get('rules', [])
            for rule in rules:
                dayL = int(rule.get('dayL', 1))
                dayR = int(rule.get('dayR', 2))
                fieldL = rule.get('fieldL', 'close')
                fieldR = rule.get('fieldR', 'close')
                op = rule.get('op', 'gt')
                multiplier = rule.get('multiplier', None)
                if dayL > len(klines) or dayR > len(klines):
                    return False
                valL = klines[-dayL].get(fieldL, 0)
                valR = klines[-dayR].get(fieldR, 0)
                if multiplier is not None and multiplier > 0:
                    valR = valR * float(multiplier)
                if op == 'gt' and not (valL > valR):
                    return False
                if op == 'lt' and not (valL < valR):
                    return False
            return True

        elif key == 'amountCompare':
            rules = cond.get('rules', [])
            for rule in rules:
                dayL = int(rule.get('dayL', 1))
                dayR = int(rule.get('dayR', 2))
                op = rule.get('op', 'gt')
                multiplier = rule.get('multiplier', None)
                if dayL > len(amounts) or dayR > len(amounts):
                    return False
                valL = amounts[-dayL]
                valR = amounts[-dayR]
                if multiplier is not None and multiplier > 0:
                    valR = valR * float(multiplier)
                if op == 'gt' and not (valL > valR):
                    return False
                if op == 'lt' and not (valL < valR):
                    return False
            return True

        elif key == 'bigOrder':
            # 需要逐笔成交数据判断大单，当前数据源不支持
            return False

        elif key == 'shortRise':
            seconds = int(cond.get('seconds', 60))
            percent = float(cond.get('percent', 3))
            history = price_history.get(code, [])
            if not history:
                return False
            now = time.time()
            cutoff = now - seconds
            # 找到 N 秒前的价格（最接近 cutoff 的记录）
            old_prices = [p for t, p in history if t <= cutoff]
            if not old_prices:
                return False
            old_price = old_prices[-1]  # cutoff 之前最近的价格
            if old_price <= 0:
                return False
            rise = (price - old_price) / old_price * 100
            return rise >= percent

        elif key == 'breakMinMA':
            minutes = int(cond.get('minutes', 5))
            history = price_history.get(code, [])
            if not history:
                return False
            now = time.time()
            cutoff = now - minutes * 60
            # 收集 N 分钟内的价格计算均价
            recent_prices = [p for t, p in history if t >= cutoff]
            if len(recent_prices) < 3:
                return False  # 数据不足
            ma = sum(recent_prices) / len(recent_prices)
            # 突破判断：之前在均线下方，现在突破
            prev_prices = recent_prices[:-1]
            prev_avg = sum(prev_prices) / len(prev_prices)
            return prev_avg < ma and price >= ma

    except Exception as e:
        print(f"[选股] 条件 {key} 检查失败: {e}")
        return False

    return True

# ── 价格历史滑动窗口（用于 shortRise / breakMinMA 条件）──
price_history = {}  # {code: [(timestamp, price), ...]}
_PRICE_HISTORY_MAX_AGE = 600  # 保留最近600秒

def record_price_history(quotes):
    """记录实时价格到滑动窗口"""
    now = time.time()
    cutoff = now - _PRICE_HISTORY_MAX_AGE
    for code, q in quotes.items():
        if q.get('price', 0) <= 0:
            continue
        if code not in price_history:
            price_history[code] = []
        price_history[code].append((now, q['price']))
        # 清理过期数据
        price_history[code] = [(t, p) for t, p in price_history[code] if t > cutoff]

# ── 流通市值缓存（通过 finance 接口获取流通股本）──
_float_shares_cache = {}  # {code: 流通股本(股)}
_float_shares_loaded = False

def load_float_shares():
    """从通达信 finance 接口加载流通股本数据"""
    global _float_shares_loaded
    client = get_tdx()
    if not client:
        return
    for code, name in STOCKS:
        try:
            df = client.finance(symbol=code)
            if df is not None and not df.empty:
                # finance 返回的字段中 liutongguben 为流通股本（股）
                row = df.iloc[-1] if len(df) > 1 else df.iloc[0]
                float_shares = float(row.get('liutongguben', 0))
                if float_shares > 0:
                    _float_shares_cache[code] = float_shares
        except Exception as e:
            pass
    _float_shares_loaded = True
    print(f"[财务] 加载流通股本: {len(_float_shares_cache)}/{len(STOCKS)} 只")

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
    """从通达信获取个股日K线，TDX 失败时 fallback 到 Ashare"""
    client = get_tdx()
    if not client:
        if APP_CONFIG.get('ashare_enabled') and ashare_available():
            return fetch_klines_ashare(code, days)
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
        if APP_CONFIG.get('ashare_enabled') and ashare_available():
            return fetch_klines_ashare(code, days)
        return []

def fetch_index_quotes():
    """获取沪深指数，TDX 优先，失败时 fallback 到东财"""
    client = get_tdx()
    if client:
        try:
            df = client.quotes([(1, '999999'), (0, '399001'), (1, '000300')])
            if df is not None and not df.empty:
                names = {'999999': '上证指数', '399001': '深证成指', '000300': '沪深300'}
                result = []
                for _, row in df.iterrows():
                    code = str(row.get('code', '')).zfill(6)
                    price = float(row.get('price', 0))
                    last_close = float(row.get('last_close', 0))
                    change = round((price - last_close) / last_close * 100, 2) if last_close > 0 else 0
                    result.append({'name': names.get(code, code), 'price': round(price, 2), 'change': change})
                return result
        except Exception as e:
            print(f"[TDX] 获取指数失败，尝试东财 fallback: {e}")

    # Fallback：东财指数接口（非交易时段也返回最新价）
    try:
        url = 'https://push2.eastmoney.com/api/qt/ulist.np/get'
        params = {
            'fltt': 2, 'invt': 2,
            'fields': 'f2,f3,f12,f14',
            'secids': '1.000001,0.399001,1.000300',
            'ut': 'fa5fd1943c7b386f172d6893dbfba10b',
        }
        resp = requests.get(url, params=params,
                            headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.eastmoney.com/'},
                            timeout=8)
        diff = resp.json().get('data', {}).get('diff', [])
        result = []
        for item in (diff or []):
            price = float(item.get('f2', 0))
            change = float(item.get('f3', 0))
            name = item.get('f14', '')
            if price > 0:
                result.append({'name': name, 'price': round(price, 2), 'change': round(change, 2)})
        if result:
            print(f"[东财] 指数 fallback 成功，获取 {len(result)} 条")
        return result
    except Exception as e:
        print(f"[东财] 指数 fallback 失败: {e}")
        return []

def fetch_sh_klines(days=20):
    """获取上证指数日K线，优先通达信，回退 Ashare"""
    # 尝试通达信
    client = get_tdx()
    if client:
        try:
            df = client.bars(symbol='999999', frequency=9, offset=days)
            if df is not None and not df.empty:
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
    # 回退 Ashare（上证指数 = sh000001）
    if ashare_available():
        try:
            klines = fetch_index_klines_ashare('sh000001', days)
            if klines:
                print(f"[Ashare] 上证指数K线获取成功: {len(klines)} 条")
                return klines
        except Exception as e:
            print(f"[Ashare] 获取上证K线失败: {e}")
    return []

def fetch_market_breadth():
    """从东方财富获取全市场涨跌统计（真实数据）"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'}

        # 查询沪深两市涨跌家数（上证+深证求和 = 全A股）
        url2 = 'https://push2.eastmoney.com/api/qt/ulist.np/get'
        params2 = {
            'fltt': 2, 'invt': 2,
            'fields': 'f1,f2,f3,f4,f6,f12,f14,f104,f105,f106',
            'secids': '1.000001,0.399001',  # 上证 + 深证
            '_': int(time.time() * 1000)
        }
        resp2 = requests.get(url2, params=params2, headers=headers, timeout=8)
        data2 = resp2.json()
        diff = data2.get('data', {}).get('diff', [])
        up, down, flat = 0, 0, 0
        for item in diff:
            up += int(item.get('f104', 0))
            down += int(item.get('f105', 0))
            flat += int(item.get('f106', 0))

        # 涨停跌停数量：东方财富涨停池API（主源），10jqka（备源）
        limit_up = 0
        limit_down = 0
        try:
            today = datetime.now().strftime('%Y%m%d')
            # 东方财富涨停池
            url_zt = 'https://push2ex.eastmoney.com/getTopicZTPool'
            params_zt = {
                'ut': '7eea3edcaed734bea9cbfc24409ed989',
                'dpt': 'wz.ztzt', 'Ession': 'CURRENT',
                'date': today, '_': int(time.time() * 1000)
            }
            resp_zt = requests.get(url_zt, headers=headers, timeout=5)
            zt_data = resp_zt.json()
            pool = (zt_data.get('data') or {}).get('pool', [])
            if pool:
                limit_up = len(pool)
            # 东方财富跌停池
            url_dt = 'https://push2ex.eastmoney.com/getTopicDTPool'
            params_dt = {
                'ut': '7eea3edcaed734bea9cbfc24409ed989',
                'dpt': 'wz.ztzt', 'Ession': 'CURRENT',
                'date': today, '_': int(time.time() * 1000)
            }
            resp_dt = requests.get(url_dt, headers=headers, timeout=5)
            dt_data = resp_dt.json()
            dt_pool = (dt_data.get('data') or {}).get('pool', [])
            if dt_pool:
                limit_down = len(dt_pool)
        except Exception as e:
            print(f"[情绪] 东财涨停池失败，尝试10jqka: {e}")
            try:
                url_ths = 'https://data.10jqka.com.cn/datacentre/limit_up/limiter_count.html'
                resp_ths = requests.get(url_ths, headers={
                    'User-Agent': 'Mozilla/5.0',
                    'Referer': 'https://data.10jqka.com.cn/'
                }, timeout=5)
                if resp_ths.status_code == 200:
                    ths_data = resp_ths.json()
                    limit_up = ths_data.get('data', {}).get('limit_up_count', 0)
                    limit_down = ths_data.get('data', {}).get('limit_down_count', 0)
            except Exception as e2:
                print(f"[情绪] 10jqka也失败: {e2}")

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
            'UserID': APP_CONFIG['kaipanla_user_id'],
            'Token':  APP_CONFIG['kaipanla_token'],
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

def fetch_eastmoney_sectors():
    """从东方财富获取概念板块涨跌排名（题材备用数据源）"""
    try:
        import time as _time
        url = 'https://push2.eastmoney.com/api/qt/clist/get'
        params = {
            'pn': 1, 'pz': 15, 'po': 1, 'np': 1, 'fltt': 2, 'invt': 2,
            'fid': 'f3',
            'fs': 'b:BK0717',
            'fields': 'f2,f3,f12,f14,f128',
            '_': int(_time.time() * 1000),
        }
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'}
        resp = requests.get(url, params=params, headers=headers, timeout=8)
        resp_json = resp.json()
        data = resp_json.get('data') or {}
        items = data.get('diff') or []
        if not items:
            print(f"[东财板块] 非交易时段或无数据（rc={resp_json.get('rc', '?')}）")
        sectors = []
        for item in (items or [])[:10]:
            name = item.get('f14', '')
            chg  = item.get('f3', 0)
            leader = item.get('f128', '')
            if name:
                sectors.append({
                    'name': name,
                    'change': round(float(chg), 2) if chg else 0,
                    'isLimitCount': False,
                    'leader': leader,
                })
        if sectors:
            print(f"[东财板块] 获取到 {len(sectors)} 个概念板块")
        return sectors
    except Exception as e:
        print(f"[东财板块] 获取失败: {e}")
        return []

def gen_sentiment_data():
    """生成情绪面板数据（真实数据源）"""
    sources = {'tdx': False, 'eastmoney': False, 'kaipanla': False, 'ashare': ashare_available()}

    indices = fetch_index_quotes()
    sh_klines = fetch_sh_klines(20)
    if indices:
        sources['tdx'] = True

    # 市场宽度：从东方财富获取全市场真实涨跌统计
    breadth = fetch_market_breadth()
    if breadth.get('up', 0) > 0 or breadth.get('down', 0) > 0:
        sources['eastmoney'] = True

    # 题材涨停排名：管理员自定义数据优先，否则按配置选数据源
    sector_source_label = '管理员配置'
    if ADMIN_CUSTOM_SECTORS:
        sectors = ADMIN_CUSTOM_SECTORS
    else:
        sector_source = APP_CONFIG.get('sector_source', 'kaipanla')
        if sector_source == 'eastmoney':
            sectors = fetch_eastmoney_sectors()
            if sectors:
                sources['eastmoney'] = True
            sector_source_label = '东方财富'
        else:
            sectors = fetch_kaipanla_sectors()
            if sectors:
                sources['kaipanla'] = True
            sector_source_label = '开盘啦'

    return {
        'indices': indices,
        'breadth': breadth,
        'sectors': sectors,
        'history': [],
        'sh_klines': sh_klines,
        'sources': sources,
        'updated_at': datetime.now().strftime('%H:%M:%S'),
        'index_source': 'TDX' if sources.get('tdx') else '东方财富',
        'breadth_source': '东方财富',
        'sector_source': sector_source_label,
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

def gen_stock_list_from_cache():
    """基于缓存K线数据生成股票列表（无需实时行情，用于非盘中展示）"""
    results = []
    now = datetime.now()
    time_str = now.strftime('%H:%M:%S')
    for code, name in STOCKS:
        klines = klines_cache.get(code, [])
        if not klines or len(klines) < 2:
            continue
        last_k = klines[-1]
        prev_k = klines[-2]
        price = last_k['close']
        change = round((last_k['close'] - prev_k['close']) / prev_k['close'] * 100, 2) if prev_k['close'] > 0 else 0
        amount = round(last_k['amount'] / 1e8, 2) if last_k['amount'] > 1e6 else round(last_k['amount'], 2)
        concepts = CONCEPT_MAP.get(code, [])

        # 判断标签
        label = '📊 个股'
        alert_type = 'volume'
        if change >= 9.8:
            label = '🔒 涨停'; alert_type = 'limit-up'
        elif change >= 5:
            label = '🚀 强势'; alert_type = 'rocket'
        elif change <= -9.8:
            label = '🔒 跌停'; alert_type = 'limit-down'
        elif change <= -5:
            label = '🏊 大跌'; alert_type = 'dive'

        results.append({
            'id': f"{code}-cache-{int(time.time()*1000)}-{random.randint(100,999)}",
            'code': code,
            'name': name,
            'type': alert_type,
            'label': label,
            'price': price,
            'change': change,
            'speed': 0,
            'amount': amount,
            'time': last_k.get('date', time_str),
            'timestamp': int(time.time() * 1000),
            'reason': None,
            'concepts': concepts[:3],
        })
    results.sort(key=lambda a: abs(a['change']), reverse=True)
    return results

async def ws_handler(websocket):
    clients.add(websocket)
    auth_user = None  # per-connection auth state
    print(f"[WS] +1 客户端 ({len(clients)})")
    try:
        # 发送初始数据：如果有缓存，立即推送股票列表
        init_alerts = all_alerts[:50]
        if not init_alerts and klines_cache:
            init_alerts = gen_stock_list_from_cache()
        # 获取上证指数K线（放线程池）
        sh_klines = await asyncio.to_thread(fetch_sh_klines, 60)
        await websocket.send(json.dumps({
            'type': 'init',
            'alerts': init_alerts,
            'market': get_market_state(),
            'sources': {'tdx': tdx_client is not None, 'klines_cache': len(klines_cache) > 0, 'ashare': ashare_available(), 'ashare_enabled': APP_CONFIG.get('ashare_enabled', False)},
            'stocks_all': [{'code': c, 'name': n} for c, n in STOCKS],
            'sh_klines': sh_klines
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
                    # 优先从缓存取，缓存没有再从通达信取（线程池）
                    klines = klines_cache.get(code, [])
                    if klines:
                        klines = klines[-days:]
                    else:
                        klines = await asyncio.to_thread(fetch_stock_klines, code, days)
                    await websocket.send(json.dumps({
                        'type': 'klines',
                        'data': klines
                    }))
                    print(f"[K线] {code} {days}日 → {len(klines)}条")
                elif data.get('action') == 'get_sentiment':
                    sentiment = await asyncio.to_thread(get_sentiment_cached)
                    await websocket.send(json.dumps({
                        'type': 'sentiment',
                        'data': sentiment
                    }))
                elif data.get('action') == 'check_watchlist':
                    codes = data.get('codes', [])
                    wl_schemes = data.get('schemes', [])
                    def _check_watchlist():
                        refresh_klines_cache_if_needed()
                        quotes = {}
                        if get_market_state() in ('open', 'call'):
                            quotes = fetch_realtime_quotes() or {}
                        results = []
                        for code in codes:
                            name = STOCK_NAMES.get(code, code)
                            klines = klines_cache.get(code, [])
                            if not klines or len(klines) < 5:
                                results.append({'code': code, 'name': name, 'matched_schemes': [], 'price': 0, 'change': 0})
                                continue
                            q = quotes.get(code)
                            matched = []
                            for scheme in wl_schemes:
                                if not scheme.get('enabled', False):
                                    continue
                                conds = scheme.get('conditions', {})
                                any_enabled = False
                                all_pass = False
                                for key, cond in conds.items():
                                    if not cond.get('enabled', False):
                                        continue
                                    any_enabled = True
                                    if not check_condition(key, cond, code, klines, q):
                                        break
                                else:
                                    if any_enabled:
                                        all_pass = True
                                if all_pass:
                                    matched.append(scheme.get('name', '未命名'))
                            last_k = klines[-1]
                            prev_k = klines[-2] if len(klines) >= 2 else last_k
                            price = q['price'] if q and q.get('price', 0) > 0 else last_k['close']
                            change = q['change'] if q else round((last_k['close'] - prev_k['close']) / prev_k['close'] * 100, 2) if prev_k['close'] > 0 else 0
                            results.append({'code': code, 'name': name, 'matched_schemes': matched, 'price': round(price, 2), 'change': round(change, 2)})
                        return results
                    wl_results = await asyncio.to_thread(_check_watchlist)
                    await websocket.send(json.dumps({'type': 'watchlist_results', 'results': wl_results}))
                    print(f"[自选] 检查 {len(codes)} 只自选股，{sum(1 for r in wl_results if r['matched_schemes'])} 只命中")
                elif data.get('action') == 'register':
                    username = (data.get('username') or '').strip()
                    password = data.get('password', '')
                    if not username or not password or len(password) < 4:
                        await websocket.send(json.dumps({'type': 'auth_result', 'success': False, 'error': '用户名和密码不能为空且密码至少4位'}))
                    else:
                        ok, err = await asyncio.to_thread(create_user, username, password)
                        if ok:
                            user = await asyncio.to_thread(verify_user, username, password)
                            token = await asyncio.to_thread(create_session, user['id'])
                            auth_user = user
                            if user.get('cloud_user_id'):
                                expires = (datetime.now() + timedelta(days=7)).isoformat()
                                asyncio.create_task(asyncio.to_thread(cloud_create_session, user['cloud_user_id'], token, expires))
                            await websocket.send(json.dumps({'type': 'auth_result', 'success': True, 'token': token, 'user': {'id': user['id'], 'username': user['username'], 'is_admin': user['is_admin']}}))
                            print(f"[Auth] 新用户注册: {username}")
                        else:
                            await websocket.send(json.dumps({'type': 'auth_result', 'success': False, 'error': err}))
                elif data.get('action') == 'login':
                    username = (data.get('username') or '').strip()
                    password = data.get('password', '')
                    user = await asyncio.to_thread(verify_user, username, password)
                    if user:
                        token = await asyncio.to_thread(create_session, user['id'])
                        auth_user = user
                        saved_wl = await asyncio.to_thread(get_user_watchlist, user['id'])
                        saved_sc = await asyncio.to_thread(get_user_schemes, user['id'])
                        # ── 云端数据合并 ──
                        if SUPABASE_LOADED and is_available() and user.get('cloud_user_id'):
                            try:
                                cloud_wl = await asyncio.to_thread(cloud_get_watchlist, user['cloud_user_id'])
                                cloud_sc = await asyncio.to_thread(cloud_get_schemes, user['cloud_user_id'])
                                if cloud_wl:
                                    saved_wl = merge_watchlists(saved_wl, cloud_wl)
                                if cloud_sc is not None:
                                    saved_sc = cloud_sc
                            except Exception as e:
                                print(f"[Supabase] 登录数据合并失败: {e}")
                        await websocket.send(json.dumps({
                            'type': 'auth_result', 'success': True, 'token': token,
                            'user': {'id': user['id'], 'username': user['username'], 'is_admin': user['is_admin']},
                            'saved_watchlist': saved_wl, 'saved_schemes': saved_sc
                        }))
                        print(f"[Auth] 用户登录: {username}")
                    else:
                        await websocket.send(json.dumps({'type': 'auth_result', 'success': False, 'error': '用户名或密码错误'}))
                elif data.get('action') == 'auth_token':
                    token = data.get('token', '')
                    user = await asyncio.to_thread(get_user_by_token, token)
                    if user:
                        auth_user = user
                        saved_wl = await asyncio.to_thread(get_user_watchlist, user['id'])
                        saved_sc = await asyncio.to_thread(get_user_schemes, user['id'])
                        # ── 云端数据合并 ──
                        if SUPABASE_LOADED and is_available() and user.get('cloud_user_id'):
                            try:
                                cloud_wl = await asyncio.to_thread(cloud_get_watchlist, user['cloud_user_id'])
                                cloud_sc = await asyncio.to_thread(cloud_get_schemes, user['cloud_user_id'])
                                if cloud_wl:
                                    saved_wl = merge_watchlists(saved_wl, cloud_wl)
                                if cloud_sc is not None:
                                    saved_sc = cloud_sc
                            except Exception as e:
                                print(f"[Supabase] token登录数据合并失败: {e}")
                        await websocket.send(json.dumps({
                            'type': 'auth_result', 'success': True,
                            'user': {'id': user['id'], 'username': user['username'], 'is_admin': user['is_admin']},
                            'saved_watchlist': saved_wl, 'saved_schemes': saved_sc
                        }))
                    else:
                        await websocket.send(json.dumps({'type': 'auth_result', 'success': False, 'error': 'token已过期'}))
                elif data.get('action') == 'sync_watchlist':
                    if auth_user:
                        codes = data.get('codes', [])
                        await asyncio.to_thread(save_user_watchlist, auth_user['id'], codes)
                        await websocket.send(json.dumps({'type': 'sync_ok', 'what': 'watchlist'}))
                        # ── 异步推送云端 ──
                        if SUPABASE_LOADED and is_available() and auth_user.get('cloud_user_id'):
                            asyncio.create_task(asyncio.to_thread(cloud_save_watchlist, auth_user['cloud_user_id'], codes))
                elif data.get('action') == 'sync_schemes':
                    if auth_user:
                        sc_data = data.get('schemes', [])
                        await asyncio.to_thread(save_user_schemes, auth_user['id'], json.dumps(sc_data))
                        await websocket.send(json.dumps({'type': 'sync_ok', 'what': 'schemes'}))
                        # ── 异步推送云端 ──
                        if SUPABASE_LOADED and is_available() and auth_user.get('cloud_user_id'):
                            asyncio.create_task(asyncio.to_thread(cloud_save_schemes, auth_user['cloud_user_id'], json.dumps(sc_data)))
                elif data.get('action') == 'admin_get_users':
                    if auth_user and auth_user.get('is_admin'):
                        users_data = await asyncio.to_thread(cloud_get_all_users_admin)
                        await websocket.send(json.dumps({'type': 'admin_users', 'users': users_data}))
                elif data.get('action') == 'admin_set_sectors':
                    global ADMIN_CUSTOM_SECTORS
                    if auth_user and auth_user.get('is_admin'):
                        ADMIN_CUSTOM_SECTORS = data.get('sectors', [])
                        # 清除情绪缓存使新数据立即生效
                        global _sentiment_cache
                        _sentiment_cache = {'data': None, 'ts': 0}
                        await websocket.send(json.dumps({'type': 'admin_sectors_ok', 'count': len(ADMIN_CUSTOM_SECTORS)}))
                        print(f"[Admin] 自定义板块数据已更新: {len(ADMIN_CUSTOM_SECTORS)} 条")
                elif data.get('action') == 'logout':
                    auth_user = None
                    await websocket.send(json.dumps({'type': 'auth_result', 'success': False, 'error': '已退出'}))
                elif data.get('action') == 'set_sync_mode':
                    enabled = bool(data.get('enabled', True))
                    if SUPABASE_LOADED:
                        set_sync_enabled(enabled)
                    await websocket.send(json.dumps({'type': 'sync_mode', 'enabled': enabled}))
                    print(f"[同步] 云同步已{'开启' if enabled else '关闭'}")
                elif data.get('action') == 'update_config':
                    cfg = data.get('config', {})
                    if isinstance(cfg, dict):
                        key_map = {
                            'sectorSource':   'sector_source',
                            'kaipanlaUserId': 'kaipanla_user_id',
                            'kaipanlaToken':  'kaipanla_token',
                            'ashareEnabled':  'ashare_enabled',
                            'ashareAsPrimary': 'ashare_as_primary',
                        }
                        for fe_key, be_key in key_map.items():
                            if fe_key in cfg:
                                APP_CONFIG[be_key] = str(cfg[fe_key])
                        uid_preview = APP_CONFIG['kaipanla_user_id']
                        print(f"[配置] 数据源={APP_CONFIG['sector_source']}, UserID={uid_preview[:4]}***")
                elif data.get('action') == 'update_schemes':
                    # 收到方案后立即执行选股（阻塞调用放线程池）
                    schemes = data.get('schemes', [])
                    def _do_screen():
                        refresh_klines_cache_if_needed()
                        # 非盘中跳过实时行情（无意义且慢），直接用空 quotes
                        quotes = {}
                        if get_market_state() in ('open', 'call'):
                            quotes = fetch_realtime_quotes() or {}
                        return screen_stocks_by_schemes(schemes, quotes)
                    screen_results = await asyncio.to_thread(_do_screen)
                    await websocket.send(json.dumps({
                        'type': 'screen_results',
                        'alerts': screen_results
                    }))
                    print(f"[选股] 方案选股完成，命中 {len(screen_results)} 只")
                elif data.get('action') == 'screen_stocks':
                    schemes = data.get('schemes', [])
                    def _do_screen2():
                        refresh_klines_cache_if_needed()
                        # 非盘中跳过实时行情（无意义且慢），直接用空 quotes
                        quotes = {}
                        if get_market_state() in ('open', 'call'):
                            quotes = fetch_realtime_quotes() or {}
                        return screen_stocks_by_schemes(schemes, quotes)
                    screen_results = await asyncio.to_thread(_do_screen2)
                    await websocket.send(json.dumps({
                        'type': 'screen_results',
                        'alerts': screen_results
                    }))
                    print(f"[选股] 手动选股完成，命中 {len(screen_results)} 只")
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
    """主扫描循环：每3秒获取行情并检测异动，同时实时更新当天K线"""
    global all_alerts
    print("[扫描] 启动实时扫描循环")

    # 启动时先连接通达信（放线程池，不阻塞事件循环）
    await asyncio.to_thread(get_tdx)

    # 加载流通股本数据（用于 marketCap 条件）
    await asyncio.to_thread(load_float_shares)

    _prev_state = ''
    _kline_update_count = 0
    _sentiment_broadcast_count = 0
    _last_queue_drain = time.time()

    while True:
        try:
            state = get_market_state()

            # ── 定期消费同步队列（每60秒）──
            if SUPABASE_LOADED and time.time() - _last_queue_drain > 60:
                asyncio.create_task(asyncio.to_thread(drain_sync_queue, DB_FILE))
                _last_queue_drain = time.time()

            # 盘中扫描
            if state in ('open', 'call'):
                quotes = await asyncio.to_thread(fetch_realtime_quotes)
                if quotes:
                    # ⓪ 记录价格历史（供 shortRise/breakMinMA 使用）
                    record_price_history(quotes)

                    # ① 检测异动
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

                    # ② 实时更新当天K线（每轮都更新内存中的当天数据）
                    updated = update_today_kline_from_quotes(quotes)
                    _kline_update_count += 1
                    if _kline_update_count % 100 == 0:  # 每300秒(5分钟)打印一次
                        print(f"[K线] 已实时更新 {updated} 只股票的当天K线 (第{_kline_update_count}轮)")

                    # ③ 每30秒广播情绪数据
                    _sentiment_broadcast_count += 1
                    if _sentiment_broadcast_count % 10 == 0:
                        try:
                            sentiment = await asyncio.to_thread(get_sentiment_cached)
                            await broadcast({'type': 'sentiment', 'data': sentiment})
                        except Exception as e:
                            print(f"[情绪] 广播失败: {e}")
                else:
                    print("[扫描] 未获取到行情数据")

            # 刚从盘中切换到收盘 → 保存数据
            elif _prev_state in ('open',) and state == 'closed':
                print("[扫描] 检测到收盘，保存K线数据...")
                await asyncio.to_thread(on_market_close)

            else:
                # 非盘中：每30秒检查一次状态
                await asyncio.sleep(27)

            _prev_state = state

        except Exception as e:
            print(f"[扫描] 错误: {e}")
            traceback.print_exc()

        await asyncio.sleep(3)

FRONTEND_DIR = os.path.join(_get_resource_dir(), 'frontend')

async def health_check(connection, request: Request):
    """处理 HTTP 请求：非 WebSocket 升级请求返回 HTTP 响应，WebSocket 请求放行"""
    # 是 WebSocket 升级请求，放行让 websockets 处理
    upgrade = request.headers.get("Upgrade", "").lower()
    if upgrade == "websocket":
        return None

    # 普通 HTTP 请求
    if request.path == "/health":
        return Response(200, "OK", Headers({"Content-Type": "text/plain"}), b"StockRadar OK\n")
    if request.path == "/" or request.path == "/index.html":
        index_path = os.path.join(FRONTEND_DIR, 'index.html')
        try:
            with open(index_path, 'rb') as f:
                content = f.read()
            return Response(200, "OK", Headers({"Content-Type": "text/html; charset=utf-8"}), content)
        except FileNotFoundError:
            return Response(404, "Not Found", Headers({"Content-Type": "text/plain"}), b"Frontend not found\n")
    # 其他路径（favicon 等）返回 404
    return Response(404, "Not Found", Headers({"Content-Type": "text/plain"}), b"Not found\n")

async def main():
    init_db()
    # ── 初始化 Supabase ──
    if SUPABASE_LOADED:
        supabase_ok = init_supabase()
        print(f"[Supabase] 初始化 {'成功' if supabase_ok else '跳过(未配置)'}")
    bind_host = "127.0.0.1" if getattr(sys, 'frozen', False) else "0.0.0.0"
    server = await websockets.serve(
        ws_handler, bind_host, WS_PORT,
        process_request=health_check,
        ping_interval=20,
        ping_timeout=20,
    )
    print(f"[StockRadar] ws://{bind_host}:{WS_PORT} (mootdx 真实行情)")

    # 启动时优先从本地JSON文件加载K线（毫秒级，不阻塞）
    print("[启动] 尝试从本地文件加载K线缓存...")
    loaded = load_klines_from_file()
    if loaded:
        print(f"[启动] 本地缓存已加载，{len(klines_cache)} 只股票可用")
    else:
        print("[启动] 本地无缓存，后台尝试从通达信下载...")

    # 后台尝试补充最新数据（全部放线程池，不阻塞WS服务和事件循环）
    async def background_update():
        await asyncio.sleep(3)  # 等3秒再尝试，让WS先稳定
        def _sync_update():
            try:
                if not klines_cache:
                    print("[补充] 缓存为空，尝试从通达信全量下载...")
                    preload_all_klines(150)
                    return
                client = get_tdx()
                if client:
                    updated_count = 0
                    for code, name in STOCKS:
                        try:
                            df = client.bars(symbol=code, frequency=9, offset=5)
                            if df is not None and not df.empty:
                                existing = klines_cache.get(code, [])
                                existing_dates = {k['date'] for k in existing}
                                for _, row in df.iterrows():
                                    dt = str(row.get('datetime', ''))[:10]
                                    if dt not in existing_dates:
                                        existing.append({
                                            'date': dt,
                                            'open': round(float(row.get('open', 0)), 2),
                                            'close': round(float(row.get('close', 0)), 2),
                                            'high': round(float(row.get('high', 0)), 2),
                                            'low': round(float(row.get('low', 0)), 2),
                                            'volume': float(row.get('vol', 0)),
                                            'amount': float(row.get('amount', 0)),
                                        })
                                existing.sort(key=lambda k: k['date'])
                                klines_cache[code] = existing[-150:]
                                updated_count += 1
                        except Exception as e:
                            pass
                    if updated_count:
                        print(f"[补充] 完成，补充了 {updated_count} 只股票的最新K线")
                        trim_klines_to_150()
                        save_klines_to_file()
                else:
                    print("[补充] 通达信不可用，尝试 Ashare 补充最新K线...")
                    if APP_CONFIG.get('ashare_enabled') and ashare_available():
                        ashare_data = preload_all_klines_ashare(STOCKS, 5)
                        for c, new_klines in ashare_data.items():
                            existing = klines_cache.get(c, [])
                            existing_dates = {k['date'] for k in existing}
                            for k in new_klines:
                                if k['date'] not in existing_dates:
                                    existing.append(k)
                            existing.sort(key=lambda k: k['date'])
                            klines_cache[c] = existing[-150:]
                        if ashare_data:
                            save_klines_to_file()
                            print(f"[补充] Ashare 补充了 {len(ashare_data)} 只股票的最新K线")
                    else:
                        print("[补充] 使用本地缓存数据")
            except Exception as e:
                print(f"[补充] 补充K线失败: {e}")
        await asyncio.to_thread(_sync_update)

    asyncio.create_task(background_update())
    await scan_loop()

if __name__ == '__main__':
    asyncio.run(main())
