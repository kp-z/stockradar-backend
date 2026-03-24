# feeds/stock_list.py — 全市场股票列表数据源
#
# Fallback 链：新浪批量探测 → akshare（全量 → 分拆上交所+深交所）
# 结果写入 klines.db stocks 表，支持按代码/名称搜索。
# 同步阻塞，调用方须放在 asyncio.to_thread() 中。

import time
import requests

_SINA_URL = 'http://hq.sinajs.cn/list='
_HEADERS = {'Referer': 'https://finance.sina.com.cn/', 'User-Agent': 'Mozilla/5.0'}
_BATCH_SIZE = 100


# ── 内部：新浪批量探测 ──

def _scan_batch(sina_codes: list[str]) -> list[dict]:
    """查询一批代码，返回有效股票 [{code, name, market}]"""
    try:
        url = _SINA_URL + ','.join(sina_codes)
        resp = requests.get(url, headers=_HEADERS, timeout=8)
        resp.encoding = 'gbk'
        result = []
        for line in resp.text.splitlines():
            if '=\"' not in line or line.endswith('=\"\";'):
                continue
            raw_code = line.split('\"')[0].split('_')[-1]   # sh600519
            fields = line.split('\"')[1].split(',')
            name = fields[0] if fields else ''
            code = raw_code[2:]   # 600519
            market = 'SH' if raw_code.startswith('sh') else 'SZ'
            if name and len(code) == 6:
                result.append({'code': code, 'name': name, 'market': market})
        return result
    except Exception as e:
        print(f'[股票列表] 批量查询失败: {e}')
        return []


def _fetch_via_sina_scan() -> list[dict] | None:
    """主源：通过新浪实时行情接口遍历代码段探测全 A 股。

    HTTP 无 SSL，约 1-2 分钟完成，返回 5000+ 只。
    """
    all_stocks: list[dict] = []
    seen: set[str] = set()

    # (起始int, 结束int, sh/sz前缀)
    ranges = [
        (600000, 606000, 'sh'),   # 沪主板
        (688000, 690000, 'sh'),   # 科创板
        (1,      3000,   'sz'),   # 深主板+中小板（000001-002999）
        (300000, 302000, 'sz'),   # 创业板
    ]

    for start, end, prefix in ranges:
        batch: list[str] = []
        for num in range(start, end):
            code = str(num).zfill(6)
            batch.append(f'{prefix}{code}')
            if len(batch) >= _BATCH_SIZE:
                for s in _scan_batch(batch):
                    if s['code'] not in seen:
                        seen.add(s['code'])
                        all_stocks.append(s)
                batch = []
                time.sleep(0.05)
        if batch:
            for s in _scan_batch(batch):
                if s['code'] not in seen:
                    seen.add(s['code'])
                    all_stocks.append(s)

    if all_stocks:
        all_stocks.sort(key=lambda x: x['code'])
        print(f'[股票列表] 新浪扫描完成：{len(all_stocks)} 只')
        return all_stocks
    return None


# ── 内部：akshare fallback ──

def _fetch_via_akshare() -> list[dict] | None:
    """Fallback：通过 akshare 获取全 A 股列表。

    尝试顺序：
    1. stock_info_a_code_name()  — 全市场一次性（最快，依赖深交所 HTTPS）
    2. 分拆：stock_info_sh_name_code() + stock_info_sz_name_code()
       — 任意一路成功即返回部分数据（上交所最稳定）
    """
    try:
        import akshare as ak
    except ImportError:
        print('[股票列表] akshare 未安装，跳过')
        return None

    all_stocks: list[dict] = []
    seen: set[str] = set()

    # 尝试全市场接口
    try:
        df = ak.stock_info_a_code_name()
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                code = str(row.get('code', '')).zfill(6)
                name = str(row.get('name', '')).strip()
                if code and name and len(code) == 6:
                    market = 'SH' if code.startswith(('6', '9', '5')) else 'SZ'
                    if code not in seen:
                        seen.add(code)
                        all_stocks.append({'code': code, 'name': name, 'market': market})
            if all_stocks:
                all_stocks.sort(key=lambda x: x['code'])
                print(f'[股票列表] akshare 全市场接口成功：{len(all_stocks)} 只')
                return all_stocks
    except Exception as e:
        print(f'[股票列表] akshare 全市场接口失败: {e}')

    # 分拆拉取：上交所
    try:
        df_sh = ak.stock_info_sh_name_code()
        if df_sh is not None and not df_sh.empty:
            for _, row in df_sh.iterrows():
                code = str(row.get('证券代码', '')).zfill(6)
                name = str(row.get('证券简称', '')).strip()
                if code and name and len(code) == 6 and code not in seen:
                    seen.add(code)
                    all_stocks.append({'code': code, 'name': name, 'market': 'SH'})
            print(f'[股票列表] akshare 上交所成功：{len([s for s in all_stocks if s["market"]=="SH"])} 只')
    except Exception as e:
        print(f'[股票列表] akshare 上交所接口失败: {e}')

    # 分拆拉取：深交所
    try:
        df_sz = ak.stock_info_sz_name_code(symbol='A股列表')
        if df_sz is not None and not df_sz.empty:
            # 深交所字段：A股代码、A股简称
            for _, row in df_sz.iterrows():
                code = str(row.get('A股代码', '')).zfill(6)
                name = str(row.get('A股简称', '')).strip()
                if code and name and len(code) == 6 and code not in seen:
                    seen.add(code)
                    all_stocks.append({'code': code, 'name': name, 'market': 'SZ'})
            print(f'[股票列表] akshare 深交所成功：{len([s for s in all_stocks if s["market"]=="SZ"])} 只')
    except Exception as e:
        print(f'[股票列表] akshare 深交所接口失败: {e}')

    if all_stocks:
        all_stocks.sort(key=lambda x: x['code'])
        print(f'[股票列表] akshare fallback 合计：{len(all_stocks)} 只')
        return all_stocks
    return None


# ── 公开接口 ──

def fetch_stock_list() -> list[dict] | None:
    """获取全 A 股列表，多源 fallback。

    Fallback 链：
    1. 新浪批量探测（HTTP，无 SSL，速度慢但稳定）
    2. akshare 全市场 → 分拆上交所+深交所

    返回 [{'code': '600519', 'name': '贵州茅台', 'market': 'SH'}]
    全部失败返回 None。
    """
    result = _fetch_via_sina_scan()
    if result:
        return result

    print('[股票列表] 新浪扫描失败，尝试 akshare fallback')
    result = _fetch_via_akshare()
    if result:
        return result

    print('[股票列表] 所有数据源均失败')
    return None


def build_search_index(stock_list: list[dict]) -> list[dict]:
    """构建内存搜索索引（去重排序）。"""
    seen: set[str] = set()
    result: list[dict] = []
    for s in stock_list:
        code = s['code']
        if code not in seen:
            seen.add(code)
            result.append(s)
    result.sort(key=lambda x: x['code'])
    return result


def search_stocks(query: str, index: list[dict], limit: int = 20) -> list[dict]:
    """在搜索索引中模糊查找股票。

    - 纯数字：按代码前缀匹配
    - 汉字/字母：按名称包含匹配
    返回最多 limit 条。
    """
    if not query:
        return []
    q = query.strip()
    results: list[dict] = []
    if q.isdigit():
        for s in index:
            if s['code'].startswith(q):
                results.append(s)
                if len(results) >= limit:
                    break
    else:
        q_lower = q.lower()
        for s in index:
            if q_lower in s['name'].lower():
                results.append(s)
                if len(results) >= limit:
                    break
    return results
