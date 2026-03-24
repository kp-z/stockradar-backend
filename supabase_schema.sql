-- ============================================
-- StockRadar Supabase Schema
-- 在 Supabase SQL Editor 中执行此文件
-- ============================================

-- 用户表
CREATE TABLE users (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    is_admin BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_login TIMESTAMPTZ
);

-- 会话表（支持跨设备登录）
CREATE TABLE sessions (
    token TEXT PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

-- 自选股表
CREATE TABLE user_watchlists (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stock_code TEXT NOT NULL,
    added_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, stock_code)
);

-- 筛选方案表
CREATE TABLE user_schemes (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    schemes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id)
);

-- 同步元数据
CREATE TABLE sync_metadata (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    last_sync_at TIMESTAMPTZ DEFAULT NOW(),
    device_id TEXT
);

-- 策略模板表（管理员发布，所有用户可读取）
CREATE TABLE IF NOT EXISTS scheme_templates (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    name TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    conditions_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 全市场每日收盘快照（Layer 1 — 三层筛选架构）
CREATE TABLE IF NOT EXISTS daily_snapshots (
    code        TEXT NOT NULL,
    date        DATE NOT NULL,
    name        TEXT NOT NULL DEFAULT '',
    close       REAL NOT NULL,
    change_pct  REAL DEFAULT 0,
    volume      REAL DEFAULT 0,
    amount      REAL DEFAULT 0,
    open        REAL DEFAULT 0,
    high        REAL DEFAULT 0,
    low         REAL DEFAULT 0,
    ma5         REAL,
    ma10        REAL,
    ma20        REAL,
    ma60        REAL,
    boll_upper  REAL,
    boll_mid    REAL,
    boll_lower  REAL,
    high_20d    REAL,
    low_20d     REAL,
    high_60d    REAL,
    low_60d     REAL,
    vol_ratio_5 REAL,
    avg_amount_5 REAL,
    PRIMARY KEY (code, date)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_date ON daily_snapshots(date);

-- 快照元数据（记录最后更新时间等）
CREATE TABLE IF NOT EXISTS snapshot_metadata (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 启用行级安全（使用 service_role key 时自动绕过）
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_watchlists ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_schemes ENABLE ROW LEVEL SECURITY;
ALTER TABLE sync_metadata ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE snapshot_metadata ENABLE ROW LEVEL SECURITY;
