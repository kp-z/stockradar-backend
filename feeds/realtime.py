# feeds/realtime.py — 实时行情多源 Feed
#
# 优先级：TDX > 新浪 HTTP > 腾讯 HTTP
# 所有函数同步阻塞，调用方须放在 asyncio.to_thread() 中。

import requests
import time
from dataclasses import dataclass


@dataclass
class Quote:
    code: str
    price: float
    last_close: float
    change: float       # 涨跌幅 %
    open: float
    high: float
    low: float
    vol: float          # 成交量（手）
    amount: float       # 成交额（亿元）


def _to_sina_code(code: str) -> str:
    """600519 → sh600519，000001 → sz000001"""
    if code.startswith('6') or code.startswith('9') or code.startswith('5'):
        return 'sh' + code
    return 'sz' + code


def fetch_sina(codes: list[str]) -> dict[str, Quote] | None:
    """从新浪行情 API 批量获取实时行情。

    返回 {code: Quote}，失败返回 None。
    每次最多传 100 只（新浪限制），调用方可分批。
    """
    if not codes:
        return {}
    try:
        sina_codes = ','.join(_to_sina_code(c) for c in codes)
        url = f'http://hq.sinajs.cn/list={sina_codes}'
        headers = {
            'Referer': 'https://finance.sina.com.cn/',
            'User-Agent': 'Mozilla/5.0',
        }
        resp = requests.get(url, headers=headers, timeout=5)
        resp.encoding = 'gbk'
        result: dict[str, Quote] = {}
        for line in resp.text.splitlines():
            if '="' not in line or line.endswith('="";'):
                continue
            # var hq_str_sh600519="name,open,last_close,price,high,low,...,vol,amount,..."
            raw_code = line.split('"')[0].split('_')[-1]  # sh600519
            code = raw_code[2:]                            # 600519
            fields = line.split('"')[1].split(',')
            if len(fields) < 10:
                continue
            try:
                price      = float(fields[3]) if fields[3] else 0.0
                last_close = float(fields[2]) if fields[2] else 0.0
                open_      = float(fields[1]) if fields[1] else 0.0
                high       = float(fields[4]) if fields[4] else 0.0
                low        = float(fields[5]) if fields[5] else 0.0
                vol        = float(fields[8]) if fields[8] else 0.0
                amount_raw = float(fields[9]) if fields[9] else 0.0
            except (ValueError, IndexError):
                continue
            if price <= 0:
                continue
            change = round((price - last_close) / last_close * 100, 2) if last_close > 0 else 0.0
            result[code] = Quote(
                code=code,
                price=price,
                last_close=last_close,
                change=change,
                open=open_,
                high=high,
                low=low,
                vol=vol,
                amount=round(amount_raw / 1e8, 2),  # 元 → 亿
            )
        return result if result else None
    except Exception as e:
        print(f'[新浪行情] 获取失败: {e}')
        return None


def fetch_tencent(codes: list[str]) -> dict[str, Quote] | None:
    """从腾讯行情 API 批量获取实时行情（新浪失败时的备用）。

    返回 {code: Quote}，失败返回 None。
    """
    if not codes:
        return {}
    try:
        tencent_codes = ','.join(_to_sina_code(c) for c in codes)  # 同样用 sh/sz 前缀
        url = f'http://qt.gtimg.cn/q={tencent_codes}'
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=5)
        resp.encoding = 'gbk'
        result: dict[str, Quote] = {}
        for line in resp.text.splitlines():
            if '="' not in line or '~' not in line:
                continue
            # v_sh600519="1~贵州茅台~600519~price~last_close~open~vol~...~amount~..."
            raw_code = line.split('="')[0].split('_')[-1]  # sh600519
            code = raw_code[2:]                             # 600519
            fields = line.split('"')[1].split('~')
            if len(fields) < 37:
                continue
            try:
                price      = float(fields[3])  if fields[3]  else 0.0
                last_close = float(fields[4])  if fields[4]  else 0.0
                open_      = float(fields[5])  if fields[5]  else 0.0
                vol        = float(fields[6])  if fields[6]  else 0.0  # 手
                high       = float(fields[33]) if fields[33] else 0.0
                low        = float(fields[34]) if fields[34] else 0.0
                amount_raw = float(fields[37]) if fields[37] else 0.0  # 万元
            except (ValueError, IndexError):
                continue
            if price <= 0:
                continue
            change = round((price - last_close) / last_close * 100, 2) if last_close > 0 else 0.0
            result[code] = Quote(
                code=code,
                price=price,
                last_close=last_close,
                change=change,
                open=open_,
                high=high,
                low=low,
                vol=vol,
                amount=round(amount_raw / 1e4, 2),  # 万元 → 亿
            )
        return result if result else None
    except Exception as e:
        print(f'[腾讯行情] 获取失败: {e}')
        return None


def fetch_realtime(codes: list[str], batch_size: int = 100) -> dict[str, Quote] | None:
    """统一入口：新浪优先，失败自动 fallback 腾讯。

    支持超过 100 只的分批请求。
    返回 {code: Quote} 或 None（两个源都失败）。
    """
    result: dict[str, Quote] = {}
    failed_codes: list[str] = []

    # 分批请求新浪
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        data = fetch_sina(batch)
        if data:
            result.update(data)
            # 找出新浪没返回的股票（价格为 0 或不在结果里）
            for c in batch:
                if c not in data:
                    failed_codes.append(c)
        else:
            failed_codes.extend(batch)

    # 新浪失败的股票走腾讯
    if failed_codes:
        for i in range(0, len(failed_codes), batch_size):
            batch = failed_codes[i:i + batch_size]
            data = fetch_tencent(batch)
            if data:
                result.update(data)

    return result if result else None
