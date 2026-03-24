"""
snapshot_updater.py — 全市场每日收盘快照采集器

功能：
1. 获取全市场 A 股列表（~5000 只）
2. 批量获取最近 70 天 K 线数据（用于计算 MA60）
3. 计算预指标（MA5/10/20/60、布林带、极值、量比）
4. 写入本地 klines.db local_snapshots 表
5. 分批 upsert 到 Supabase daily_snapshots 表

使用方式：
  python snapshot_updater.py              # 采集今天的数据
  python snapshot_updater.py 2026-03-21   # 采集指定日期（用于补数据）

建议在收盘后 15:10 运行，或接入 server.py on_market_close() 自动触发。
"""

import sys
import os
import time
import logging
import statistics
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('snapshot_updater')

# 确保项目根目录在 sys.path 中
_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


# ── 数据获取 ──

def _fetch_stock_list():
    """获取全市场股票列表，优先从 klines.db，降级到在线获取。"""
    from klines_store import load_stocks, init_klines_db, save_stocks
    init_klines_db()
    stocks = load_stocks()
    if len(stocks) >= 3000:
        logger.info(f'从 klines.db 加载股票列表: {len(stocks)} 只')
        return stocks

    logger.info('klines.db 股票列表不足，从网络获取...')
    from feeds.stock_list import fetch_stock_list
    online = fetch_stock_list()
    if online:
        save_stocks(online)
        logger.info(f'网络获取股票列表: {len(online)} 只')
        return online

    if stocks:
        logger.warning(f'网络获取失败，使用已有 {len(stocks)} 只')
        return stocks
    return []


def _fetch_klines_for_stock(code, days=70):
    """获取单只股票的 K 线数据，返回 list[dict] 或 None。

    优先腾讯（HTTP 直连，无代理问题），然后 akshare（含成交额但走 HTTPS）。
    """
    from feeds.historical import fetch_tencent, fetch_akshare

    # 优先腾讯：HTTP 直连，不受代理干扰，速度快
    result = fetch_tencent(code, days)
    if result:
        return [{'date': k.date, 'open': k.open, 'high': k.high, 'low': k.low,
                 'close': k.close, 'volume': k.volume, 'amount': k.amount}
                for k in result]

    # 腾讯失败才尝试 akshare（HTTPS，可能被代理拦截）
    try:
        result = fetch_akshare(code, days)
        if result:
            return [{'date': k.date, 'open': k.open, 'high': k.high, 'low': k.low,
                     'close': k.close, 'volume': k.volume, 'amount': k.amount}
                    for k in result]
    except Exception:
        pass
    return None


# ── 指标计算 ──

def _calc_ma(closes, period):
    """计算移动均线，数据不足返回 None。"""
    if len(closes) < period:
        return None
    return round(sum(closes[-period:]) / period, 4)


def _calc_bollinger(closes, period=20):
    """计算布林带 (upper, mid, lower)，数据不足返回 (None, None, None)。"""
    if len(closes) < period:
        return None, None, None
    window = closes[-period:]
    mid = sum(window) / period
    std = statistics.pstdev(window)
    return (round(mid + 2 * std, 4), round(mid, 4), round(mid - 2 * std, 4))


def _compute_snapshot(code, name, klines, target_date):
    """从 K 线数据计算一行快照。返回 dict 或 None。"""
    if not klines or len(klines) < 2:
        return None

    # 找到 target_date 对应的 K 线
    today_k = None
    for k in reversed(klines):
        if k['date'] <= target_date:
            today_k = k
            break
    if not today_k:
        return None

    # 截取到 today_k 的位置
    idx = next((i for i, k in enumerate(klines) if k['date'] == today_k['date']), None)
    if idx is None or idx < 1:
        return None
    history = klines[:idx + 1]

    closes = [k['close'] for k in history]
    volumes = [k['volume'] for k in history]
    amounts = [k['amount'] for k in history]
    highs = [k['high'] for k in history]
    lows = [k['low'] for k in history]

    prev_close = closes[-2] if len(closes) >= 2 else closes[-1]
    change_pct = round((closes[-1] - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0

    boll_upper, boll_mid, boll_lower = _calc_bollinger(closes, 20)

    avg_vol_5 = sum(volumes[-6:-1]) / 5 if len(volumes) >= 6 else None
    vol_ratio_5 = round(volumes[-1] / avg_vol_5, 2) if avg_vol_5 and avg_vol_5 > 0 else None

    avg_amount_5 = round(sum(amounts[-6:-1]) / 5, 2) if len(amounts) >= 6 else None

    recent_20_highs = highs[-20:] if len(highs) >= 20 else highs
    recent_20_lows = lows[-20:] if len(lows) >= 20 else lows
    recent_60_highs = highs[-60:] if len(highs) >= 60 else highs
    recent_60_lows = lows[-60:] if len(lows) >= 60 else lows

    return {
        'code': code,
        'date': today_k['date'],
        'name': name,
        'close': today_k['close'],
        'change_pct': change_pct,
        'volume': today_k['volume'],
        'amount': today_k['amount'],
        'open': today_k['open'],
        'high': today_k['high'],
        'low': today_k['low'],
        'ma5': _calc_ma(closes, 5),
        'ma10': _calc_ma(closes, 10),
        'ma20': _calc_ma(closes, 20),
        'ma60': _calc_ma(closes, 60),
        'boll_upper': boll_upper,
        'boll_mid': boll_mid,
        'boll_lower': boll_lower,
        'high_20d': max(recent_20_highs) if recent_20_highs else None,
        'low_20d': min(recent_20_lows) if recent_20_lows else None,
        'high_60d': max(recent_60_highs) if recent_60_highs else None,
        'low_60d': min(recent_60_lows) if recent_60_lows else None,
        'vol_ratio_5': vol_ratio_5,
        'avg_amount_5': avg_amount_5,
    }


# ── 主流程 ──

def run_snapshot_update(target_date=None, max_workers=10):
    """执行全市场快照更新。

    Args:
        target_date: 目标日期字符串 (YYYY-MM-DD)，默认今天
        max_workers: 并发获取线程数
    """
    if target_date is None:
        target_date = date.today().isoformat()
    logger.info(f'=== 开始全市场快照更新 (目标日期: {target_date}) ===')

    # 1. 获取股票列表
    stocks = _fetch_stock_list()
    if not stocks:
        logger.error('无法获取股票列表，中止')
        return False
    logger.info(f'待处理: {len(stocks)} 只股票')

    # 2. 并发获取 K 线并计算快照
    snapshots = []
    failed = 0
    t0 = time.time()

    def _process_one(stock):
        code, name = stock['code'], stock['name']
        klines = _fetch_klines_for_stock(code, 70)
        if not klines:
            return None
        return _compute_snapshot(code, name, klines, target_date)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_process_one, s): s for s in stocks}
        done_count = 0
        for future in as_completed(futures):
            done_count += 1
            if done_count % 200 == 0:
                logger.info(f'进度: {done_count}/{len(stocks)}')
            try:
                snap = future.result()
                if snap:
                    snapshots.append(snap)
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                stock = futures[future]
                logger.debug(f'{stock["code"]} 处理异常: {e}')

    elapsed = time.time() - t0
    logger.info(f'K线获取完成: 成功 {len(snapshots)}, 失败 {failed}, 耗时 {elapsed:.1f}s')

    if not snapshots:
        logger.error('无有效快照数据，中止')
        return False

    # 3. 写入本地 klines.db
    try:
        from klines_store import save_snapshots, purge_old_snapshots
        saved = save_snapshots(snapshots)
        logger.info(f'本地快照写入: {saved} 行')
        purge_old_snapshots(7)
    except Exception as e:
        logger.warning(f'本地快照写入失败: {e}')

    # 4. 写入 Supabase
    try:
        from supabase_sync import (
            init_supabase, cloud_upsert_snapshots,
            cloud_set_snapshot_date, cloud_purge_old_snapshots,
        )
        if init_supabase():
            total = cloud_upsert_snapshots(snapshots)
            if total:
                cloud_set_snapshot_date(target_date)
                cloud_purge_old_snapshots(7)
                logger.info(f'Supabase 快照写入: {total} 行')
            else:
                logger.warning('Supabase 快照写入失败')
        else:
            logger.warning('Supabase 不可用，跳过云端写入')
    except Exception as e:
        logger.warning(f'Supabase 写入异常: {e}')

    logger.info(f'=== 快照更新完成: {len(snapshots)} 只股票 ===')
    return True


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else None
    run_snapshot_update(target_date=target)
