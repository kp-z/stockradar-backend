# klines_store.py — klines.db SQLite K 线存储
#
# 与 stockradar.db 分离，专门存储历史 K 线数据。
# 支持全市场（5000+ 只），WAL 模式保证多读安全。

import os
import sqlite3
import sys

_DB_PATH = None


def _get_db_path() -> str:
    global _DB_PATH
    if _DB_PATH:
        return _DB_PATH
    from platform_dirs import get_data_dir
    _DB_PATH = os.path.join(get_data_dir(), 'klines.db')
    return _DB_PATH


def init_klines_db():
    """初始化 klines.db 表结构（首次运行时调用）。"""
    conn = sqlite3.connect(_get_db_path())
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS klines (
            code   TEXT NOT NULL,
            date   TEXT NOT NULL,
            open   REAL,
            high   REAL,
            low    REAL,
            close  REAL,
            volume REAL,
            amount REAL,
            source TEXT DEFAULT 'akshare',
            PRIMARY KEY (code, date)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS stocks (
            code       TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            market     TEXT,
            updated_at TEXT
        )
    ''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_klines_code_date ON klines(code, date)')
    # 全市场每日收盘快照（本地缓存，与 Supabase daily_snapshots 同构）
    conn.execute('''
        CREATE TABLE IF NOT EXISTS local_snapshots (
            code        TEXT NOT NULL,
            date        TEXT NOT NULL,
            name        TEXT NOT NULL DEFAULT '',
            close       REAL NOT NULL,
            change_pct  REAL DEFAULT 0,
            volume      REAL DEFAULT 0,
            amount      REAL DEFAULT 0,
            open        REAL DEFAULT 0,
            high        REAL DEFAULT 0,
            low         REAL DEFAULT 0,
            ma5         REAL, ma10 REAL, ma20 REAL, ma60 REAL,
            boll_upper  REAL, boll_mid REAL, boll_lower REAL,
            high_20d    REAL, low_20d REAL, high_60d REAL, low_60d REAL,
            vol_ratio_5 REAL, avg_amount_5 REAL,
            PRIMARY KEY (code, date)
        )
    ''')
    conn.commit()
    conn.close()


def save_klines(code: str, klines: list) -> int:
    """批量 upsert K 线数据。klines 为 Kline dataclass 或 dict 列表。

    返回写入条数。
    """
    if not klines:
        return 0
    conn = sqlite3.connect(_get_db_path())
    rows = []
    for k in klines:
        if hasattr(k, 'date'):
            rows.append((code, k.date, k.open, k.high, k.low, k.close, k.volume, k.amount,
                         getattr(k, 'source', 'akshare')))
        else:
            rows.append((code, k['date'], k.get('open', 0), k.get('high', 0),
                         k.get('low', 0), k.get('close', k.get('price', 0)),
                         k.get('volume', k.get('vol', 0)), k.get('amount', 0), 'legacy'))
    conn.executemany(
        'INSERT OR REPLACE INTO klines(code,date,open,high,low,close,volume,amount,source)'
        ' VALUES(?,?,?,?,?,?,?,?,?)',
        rows,
    )
    conn.commit()
    conn.close()
    return len(rows)


def load_klines(code: str, days: int = 150) -> list[dict]:
    """从 klines.db 读取最近 days 条 K 线，返回 dict 列表（按日期升序）。"""
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        'SELECT date,open,high,low,close,volume,amount,source'
        ' FROM klines WHERE code=? ORDER BY date DESC LIMIT ?',
        (code, days),
    ).fetchall()
    conn.close()
    result = [dict(r) for r in reversed(rows)]
    return result


def get_latest_date(code: str) -> str | None:
    """返回 code 在 klines.db 中最新的日期字符串，无数据返回 None。"""
    conn = sqlite3.connect(_get_db_path())
    row = conn.execute(
        'SELECT MAX(date) FROM klines WHERE code=?', (code,)
    ).fetchone()
    conn.close()
    return row[0] if row and row[0] else None


def save_stocks(stock_list: list[dict]):
    """批量 upsert 股票列表。stock_list: [{code, name, market}]"""
    if not stock_list:
        return
    from datetime import date
    today = date.today().isoformat()
    conn = sqlite3.connect(_get_db_path())
    conn.executemany(
        'INSERT OR REPLACE INTO stocks(code,name,market,updated_at) VALUES(?,?,?,?)',
        [(s['code'], s['name'], s.get('market', ''), today) for s in stock_list],
    )
    conn.commit()
    conn.close()


def load_stocks() -> list[dict]:
    """返回所有股票列表，按 code 排序。"""
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    rows = conn.execute('SELECT code,name,market,updated_at FROM stocks ORDER BY code').fetchall()
    conn.close()
    return [dict(r) for r in rows]


def load_all_codes() -> list[str]:
    """返回 klines.db 中所有有K线数据的股票代码列表。"""
    conn = sqlite3.connect(_get_db_path())
    rows = conn.execute('SELECT DISTINCT code FROM klines ORDER BY code').fetchall()
    conn.close()
    return [r[0] for r in rows]


def purge_old_klines(keep_days: int = 300):
    """删除每只股票超过 keep_days 天的老数据。"""
    from datetime import date, timedelta
    cutoff = (date.today() - timedelta(days=keep_days)).isoformat()
    conn = sqlite3.connect(_get_db_path())
    conn.execute('DELETE FROM klines WHERE date < ?', (cutoff,))
    deleted = conn.total_changes
    conn.commit()
    conn.close()
    if deleted:
        print(f'[klines.db] 已清除 {deleted} 条超期数据（>{keep_days}天）')


def db_stats() -> dict:
    """返回数据库统计信息。"""
    conn = sqlite3.connect(_get_db_path())
    klines_count = conn.execute('SELECT COUNT(*) FROM klines').fetchone()[0]
    stocks_count = conn.execute('SELECT COUNT(*) FROM stocks').fetchone()[0]
    codes_count = conn.execute('SELECT COUNT(DISTINCT code) FROM klines').fetchone()[0]
    conn.close()
    return {
        'klines': klines_count,
        'stocks': stocks_count,
        'codes_with_data': codes_count,
        'db_path': _get_db_path(),
    }


# ── 本地快照缓存 ──

_SNAPSHOT_FIELDS = (
    'code', 'date', 'name', 'close', 'change_pct', 'volume', 'amount',
    'open', 'high', 'low', 'ma5', 'ma10', 'ma20', 'ma60',
    'boll_upper', 'boll_mid', 'boll_lower',
    'high_20d', 'low_20d', 'high_60d', 'low_60d',
    'vol_ratio_5', 'avg_amount_5',
)


def save_snapshots(snapshots: list[dict]) -> int:
    """批量 upsert 快照到本地 local_snapshots 表。返回写入条数。"""
    if not snapshots:
        return 0
    conn = sqlite3.connect(_get_db_path())
    placeholders = ','.join('?' * len(_SNAPSHOT_FIELDS))
    cols = ','.join(_SNAPSHOT_FIELDS)
    rows = []
    for s in snapshots:
        rows.append(tuple(s.get(f, 0) for f in _SNAPSHOT_FIELDS))
    conn.executemany(
        f'INSERT OR REPLACE INTO local_snapshots({cols}) VALUES({placeholders})',
        rows,
    )
    conn.commit()
    conn.close()
    return len(rows)


def load_snapshots(target_date: str = None) -> list[dict]:
    """加载指定日期（默认最新）的全部快照，返回 dict 列表。"""
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    if target_date:
        rows = conn.execute(
            'SELECT * FROM local_snapshots WHERE date=? ORDER BY code',
            (target_date,),
        ).fetchall()
    else:
        # 找最新日期
        latest = conn.execute(
            'SELECT MAX(date) FROM local_snapshots'
        ).fetchone()[0]
        if not latest:
            conn.close()
            return []
        rows = conn.execute(
            'SELECT * FROM local_snapshots WHERE date=? ORDER BY code',
            (latest,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_snapshot_date() -> str | None:
    """返回本地快照的最新日期，无数据返回 None。"""
    conn = sqlite3.connect(_get_db_path())
    row = conn.execute('SELECT MAX(date) FROM local_snapshots').fetchone()
    conn.close()
    return row[0] if row and row[0] else None


def purge_old_snapshots(keep_days: int = 7):
    """清理超过 keep_days 天的旧快照。"""
    from datetime import date, timedelta
    cutoff = (date.today() - timedelta(days=keep_days)).isoformat()
    conn = sqlite3.connect(_get_db_path())
    conn.execute('DELETE FROM local_snapshots WHERE date < ?', (cutoff,))
    deleted = conn.total_changes
    conn.commit()
    conn.close()
    if deleted:
        print(f'[klines.db] 已清除 {deleted} 条旧快照（>{keep_days}天）')
