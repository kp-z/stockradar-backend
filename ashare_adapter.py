# ashare_adapter.py — Ashare 数据源适配层
# 将 Ashare 的 DataFrame 格式转换为 stockradar 内存K线格式
# 注意：所有函数均为同步阻塞，调用方必须在 asyncio.to_thread() 中使用

import sys
import os

# 从项目 lib/ 目录导入 Ashare
if getattr(sys, 'frozen', False):
    _base_dir = sys._MEIPASS
else:
    _base_dir = os.path.dirname(os.path.abspath(__file__))
_lib_dir = os.path.join(_base_dir, 'lib')
if os.path.isdir(_lib_dir) and _lib_dir not in sys.path:
    sys.path.insert(0, _lib_dir)

try:
    from Ashare import get_price
    _ASHARE_AVAILABLE = True
except ImportError:
    _ASHARE_AVAILABLE = False


def to_ashare_code(code: str) -> str:
    """将 stockradar 代码格式转换为 Ashare 格式
    600519 -> sh600519，000001 -> sz000001
    规则：以 6/9/5 开头的为上交所，其余为深交所
    """
    if code.startswith('6') or code.startswith('9') or code.startswith('5'):
        return 'sh' + code
    return 'sz' + code


def df_to_kline_list(df) -> list:
    """将 Ashare 返回的 DataFrame 转换为 stockradar 内存K线格式

    注：Ashare 无 amount（成交额）字段，置 0。
    依赖 amount 的选股条件（amountHigh/amountLow/amountMultiple/amountCompare）
    在使用 Ashare 数据时将永不满足，这是可接受的降级行为。
    """
    result = []
    for ts, row in df.iterrows():
        result.append({
            'date':   ts.strftime('%Y-%m-%d'),
            'open':   round(float(row['open']),  2),
            'close':  round(float(row['close']), 2),
            'high':   round(float(row['high']),  2),
            'low':    round(float(row['low']),   2),
            'volume': float(row['volume']),
            'amount': 0.0,
        })
    return result


def fetch_klines_ashare(code: str, days: int = 150) -> list:
    """用 Ashare 获取单只股票日线数据，失败返回空列表"""
    if not _ASHARE_AVAILABLE:
        return []
    try:
        df = get_price(to_ashare_code(code), count=days, frequency='1d')
        if df is None or df.empty:
            return []
        return df_to_kline_list(df)
    except Exception as e:
        print(f"[Ashare] {code} 获取失败: {e}")
        return []


def df_to_kline_list_with_time(df) -> list:
    """将分钟K线 DataFrame 转换为带完整时间戳的 kline list"""
    result = []
    for ts, row in df.iterrows():
        result.append({
            'date':   ts.strftime('%Y-%m-%d %H:%M'),
            'open':   round(float(row['open']),  2),
            'close':  round(float(row['close']), 2),
            'high':   round(float(row['high']),  2),
            'low':    round(float(row['low']),   2),
            'volume': float(row['volume']),
            'amount': 0.0,
        })
    return result


def fetch_klines_60min_ashare(code: str, count: int = 100) -> list:
    """用 Ashare 获取单只股票60分钟K线（新浪→腾讯降级），失败返回空列表"""
    if not _ASHARE_AVAILABLE:
        return []
    try:
        df = get_price(to_ashare_code(code), count=count, frequency='60m')
        if df is None or df.empty:
            return []
        return df_to_kline_list_with_time(df)
    except Exception as e:
        print(f"[Ashare] {code} 60min获取失败: {e}")
        return []


def fetch_index_klines_ashare(symbol: str, days: int = 60) -> list:
    """获取指数K线，symbol 为 Ashare 格式如 sh000001（上证指数）。
    Ashare 不可用时直接调新浪财经 API 回退。"""
    if _ASHARE_AVAILABLE:
        try:
            df = get_price(symbol, count=days, frequency='1d')
            if df is not None and not df.empty:
                return df_to_kline_list(df)
        except Exception as e:
            print(f"[Ashare] 指数 {symbol} 获取失败: {e}")
    # 回退：直接用新浪财经 API
    return _fetch_index_klines_sina(symbol, days)


def _fetch_index_klines_sina(symbol: str, days: int = 60) -> list:
    """通过新浪财经 API 获取指数日K线数据"""
    import requests
    try:
        url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        params = {
            'symbol': symbol,
            'scale': 240,  # 日线
            'ma': 'no',
            'datalen': days,
        }
        r = requests.get(url, params=params, timeout=10,
                         headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.sina.com.cn'})
        if r.status_code != 200:
            return []
        data = r.json()
        result = []
        for item in data:
            result.append({
                'date': item.get('day', '')[:10],
                'open': round(float(item.get('open', 0)), 2),
                'close': round(float(item.get('close', 0)), 2),
                'high': round(float(item.get('high', 0)), 2),
                'low': round(float(item.get('low', 0)), 2),
                'volume': float(item.get('volume', 0)),
                'amount': 0.0,
            })
        if result:
            print(f"[Sina] 指数 {symbol} K线获取成功: {len(result)} 条")
        return result
    except Exception as e:
        print(f"[Sina] 指数 {symbol} 获取失败: {e}")
        return []


def preload_all_klines_ashare(stocks: list, days: int = 150) -> dict:
    """批量获取所有股票K线，返回 {code: kline_list}
    stocks 格式：[(code, name), ...]
    """
    if not _ASHARE_AVAILABLE:
        print("[Ashare] 库未安装，跳过批量预加载")
        return {}
    result = {}
    for code, name in stocks:
        klines = fetch_klines_ashare(code, days)
        if klines:
            result[code] = klines
        else:
            print(f"[Ashare] {code} {name} 获取失败")
    print(f"[Ashare] 预加载完成：{len(result)}/{len(stocks)} 只股票")
    return result


def is_available() -> bool:
    return _ASHARE_AVAILABLE
