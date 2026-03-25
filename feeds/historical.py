# feeds/historical.py — 历史 K 线多源 Feed
#
# 优先级：akshare(东财 stock_zh_a_hist, 含amount) > 腾讯直连 > Ashare
# 所有函数同步阻塞，调用方须放在 asyncio.to_thread() 中。

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class Kline:
    date: str       # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: float   # 成交量（股）
    amount: float   # 成交额（元），部分源可能为 0
    source: str = 'akshare'


def _sina_prefix(code: str) -> str:
    return ('sh' if code.startswith(('6', '9', '5')) else 'sz') + code


def fetch_akshare(code: str, days: int = 150) -> list[Kline] | None:
    """用 akshare stock_zh_a_hist（东财源）获取日 K 线，含完整成交额字段。

    返回 list[Kline]（按日期升序），失败返回 None。
    """
    try:
        import akshare as ak
        start = (date.today() - timedelta(days=days + 60)).strftime('%Y%m%d')
        end = date.today().strftime('%Y%m%d')
        df = ak.stock_zh_a_hist(
            symbol=code,
            period='daily',
            start_date=start,
            end_date=end,
            adjust='qfq',
        )
        if df is None or df.empty:
            return None
        result = []
        for _, row in df.iterrows():
            try:
                result.append(Kline(
                    date=str(row['日期'])[:10],
                    open=float(row['开盘']),
                    high=float(row['最高']),
                    low=float(row['最低']),
                    close=float(row['收盘']),
                    volume=float(row['成交量']) * 100,   # 手 → 股
                    amount=float(row['成交额']),
                    source='akshare',
                ))
            except (KeyError, ValueError):
                continue
        return result[-days:] if result else None
    except Exception as e:
        print(f'[akshare历史K线] {code} 获取失败: {e}')
        return None


def fetch_tencent(code: str, days: int = 150) -> list[Kline] | None:
    """直接调腾讯历史K线接口（无成交额，amount=0）。

    返回 list[Kline]，失败返回 None。
    """
    try:
        import requests
        symbol = _sina_prefix(code)
        start = (date.today() - timedelta(days=days + 60)).strftime('%Y-%m-%d')
        end = date.today().strftime('%Y-%m-%d')
        url = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
        params = {'param': f'{symbol},day,{start},{end},{days + 60},qfq'}
        resp = requests.get(url, params=params, headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
        data = resp.json()
        raw = (data.get('data') or {}).get(symbol, {})
        day_data = raw.get('qfqday') or raw.get('day') or []
        if not day_data:
            return None
        result = []
        for item in day_data:
            try:
                # [date, open, close, high, low, vol]
                result.append(Kline(
                    date=str(item[0])[:10],
                    open=float(item[1]),
                    high=float(item[3]),
                    low=float(item[4]),
                    close=float(item[2]),
                    volume=float(item[5]) * 100,  # 手 → 股
                    amount=0.0,
                    source='tencent',
                ))
            except (IndexError, ValueError):
                continue
        return result[-days:] if result else None
    except Exception as e:
        print(f'[腾讯历史K线] {code} 获取失败: {e}')
        return None


def fetch_ashare(code: str, days: int = 150) -> list[Kline] | None:
    """用本地 Ashare 库获取日 K 线（备用，无成交额）。

    返回 list[Kline]，amount 字段为 0，失败返回 None。
    """
    try:
        import sys
        import os
        lib_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'lib')
        if lib_path not in sys.path:
            sys.path.insert(0, lib_path)
        from Ashare import get_price
        df = get_price(code, frequency='1d', count=days)
        if df is None or df.empty:
            return None
        result = []
        for idx, row in df.iterrows():
            try:
                result.append(Kline(
                    date=str(idx)[:10],
                    open=float(row.get('open', 0)),
                    high=float(row.get('high', 0)),
                    low=float(row.get('low', 0)),
                    close=float(row.get('close', 0)),
                    volume=float(row.get('volume', 0)),
                    amount=0.0,
                    source='ashare',
                ))
            except (KeyError, ValueError):
                continue
        return result if result else None
    except Exception as e:
        print(f'[Ashare历史K线] {code} 获取失败: {e}')
        return None


def fetch_historical(code: str, days: int = 150) -> list[Kline] | None:
    """统一入口：腾讯 → akshare → Ashare。

    腾讯接口当前最稳定；akshare 作为含 amount 字段的备选；Ashare 本地库兜底。
    返回 list[Kline] 或 None（全部源失败）。
    """
    result = fetch_tencent(code, days)
    if result:
        return result
    print(f'[历史K线] {code} 腾讯失败，尝试 akshare')
    result = fetch_akshare(code, days)
    if result:
        return result
    print(f'[历史K线] {code} akshare 失败，尝试 Ashare 备用')
    return fetch_ashare(code, days)
