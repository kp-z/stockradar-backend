"""
Supabase 云端同步模块
使用 requests 直接调 Supabase REST API (PostgREST)，避免 SDK 版本冲突。
密码验证和用户管理均走 Supabase，本地 SQLite 只缓存当前用户的 session 和数据。
"""

import os
import hashlib
import json
import sqlite3
import logging
import requests
from datetime import datetime, timedelta

logger = logging.getLogger("supabase_sync")

# ── 加载 .env 文件 ──
def _load_dotenv():
    """手动加载 .env 文件，不依赖 python-dotenv 包。"""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if not os.path.exists(env_path):
        return
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            key, value = key.strip(), value.strip()
            if not os.environ.get(key):
                os.environ[key] = value

_load_dotenv()

# ── Supabase 配置 ──
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

_initialized = False
_sync_enabled = True
_headers = {}
_rest_url = ""


def init_supabase():
    """初始化 REST API 配置。返回 True 表示可用。"""
    global _initialized, _headers, _rest_url
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.info("Supabase 未配置 (缺少 SUPABASE_URL 或 SUPABASE_SERVICE_KEY)")
        return False
    try:
        _rest_url = f"{SUPABASE_URL}/rest/v1"
        _headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        # 测试连接
        r = requests.get(f"{_rest_url}/users?select=id&limit=1", headers=_headers, timeout=10)
        r.raise_for_status()
        _initialized = True
        logger.info("Supabase REST API 连接成功")
        return True
    except Exception as e:
        logger.warning(f"Supabase 初始化失败: {e}")
        _initialized = False
        return False


def is_available():
    """检查 Supabase 是否配置且同步已开启。"""
    return _initialized and _sync_enabled


def set_sync_enabled(enabled):
    """运行时切换同步开关。"""
    global _sync_enabled
    _sync_enabled = bool(enabled)
    logger.info(f"云同步已{'开启' if _sync_enabled else '关闭'}")


def _api(method, path, data=None, params=None):
    """统一 REST API 调用。"""
    url = f"{_rest_url}/{path}"
    r = requests.request(method, url, headers=_headers, json=data, params=params, timeout=15)
    r.raise_for_status()
    if r.text:
        return r.json()
    return []


# ── 用户操作 ──

def cloud_register(username, password_hash, salt):
    """在 Supabase 创建用户，返回云端 UUID 或 None。"""
    if not is_available():
        return None
    try:
        result = _api("POST", "users", {
            "username": username,
            "password_hash": password_hash,
            "salt": salt,
        })
        if result and len(result) > 0:
            uid = result[0]["id"]
            logger.info(f"云端用户创建成功: {username} -> {uid}")
            return uid
        return None
    except Exception as e:
        logger.warning(f"云端注册失败: {e}")
        return None


def cloud_login(username, password_hash):
    """在 Supabase 验证用户，返回用户字典或 None。"""
    if not is_available():
        return None
    try:
        result = _api("GET", "users", params={
            "select": "*",
            "username": f"eq.{username}",
            "password_hash": f"eq.{password_hash}",
        })
        if result:
            row = result[0]
            return {
                "cloud_id": row["id"],
                "username": row["username"],
                "is_admin": row.get("is_admin", False),
            }
        return None
    except Exception as e:
        logger.warning(f"云端登录验证失败: {e}")
        return None


def cloud_create_session(cloud_user_id, token, expires_at):
    """在 Supabase 存储 session。"""
    if not is_available():
        return
    try:
        # upsert: 用特殊 header
        headers = {**_headers, "Prefer": "resolution=merge-duplicates,return=representation"}
        requests.post(f"{_rest_url}/sessions", headers=headers, json={
            "token": token,
            "user_id": cloud_user_id,
            "expires_at": expires_at,
        }, timeout=15).raise_for_status()
    except Exception as e:
        logger.warning(f"云端 session 创建失败: {e}")


def cloud_validate_session(token):
    """在 Supabase 检查 session 有效性，返回用户字典或 None。"""
    if not is_available():
        return None
    try:
        result = _api("GET", "sessions", params={
            "select": "user_id,expires_at",
            "token": f"eq.{token}",
        })
        if not result:
            return None
        session = result[0]
        expires = datetime.fromisoformat(session["expires_at"].replace("Z", "+00:00"))
        if expires < datetime.now(expires.tzinfo):
            return None
        user_result = _api("GET", "users", params={
            "select": "id,username,is_admin",
            "id": f"eq.{session['user_id']}",
        })
        if user_result:
            row = user_result[0]
            return {
                "cloud_id": row["id"],
                "username": row["username"],
                "is_admin": row.get("is_admin", False),
            }
        return None
    except Exception as e:
        logger.warning(f"云端 session 验证失败: {e}")
        return None


# ── 数据同步操作 ──

def cloud_save_watchlist(cloud_user_id, codes):
    """替换云端自选股（删除旧数据 + 批量插入）。"""
    if not is_available() or not cloud_user_id:
        return
    try:
        # 删除旧数据
        requests.delete(
            f"{_rest_url}/user_watchlists",
            headers=_headers,
            params={"user_id": f"eq.{cloud_user_id}"},
            timeout=15,
        ).raise_for_status()
        # 批量插入
        if codes:
            rows = [{"user_id": cloud_user_id, "stock_code": c} for c in codes]
            _api("POST", "user_watchlists", rows)
        logger.info(f"云端自选股已同步: {len(codes)} 只")
    except Exception as e:
        logger.warning(f"云端自选股保存失败: {e}")


def cloud_get_watchlist(cloud_user_id):
    """从 Supabase 获取自选股列表。"""
    if not is_available() or not cloud_user_id:
        return []
    try:
        result = _api("GET", "user_watchlists", params={
            "select": "stock_code",
            "user_id": f"eq.{cloud_user_id}",
            "order": "added_at",
        })
        return [r["stock_code"] for r in (result or [])]
    except Exception as e:
        logger.warning(f"云端自选股获取失败: {e}")
        return []


def cloud_save_schemes(cloud_user_id, schemes_json):
    """upsert 云端筛选方案。"""
    if not is_available() or not cloud_user_id:
        return
    try:
        data = json.loads(schemes_json) if isinstance(schemes_json, str) else schemes_json
        headers = {**_headers, "Prefer": "resolution=merge-duplicates,return=representation"}
        requests.post(f"{_rest_url}/user_schemes", headers=headers, json={
            "user_id": cloud_user_id,
            "schemes_json": data,
            "updated_at": datetime.now().isoformat(),
        }, timeout=15).raise_for_status()
        logger.info("云端筛选方案已同步")
    except Exception as e:
        logger.warning(f"云端筛选方案保存失败: {e}")


def cloud_get_schemes(cloud_user_id):
    """从 Supabase 获取筛选方案，返回 list 或 None。"""
    if not is_available() or not cloud_user_id:
        return None
    try:
        result = _api("GET", "user_schemes", params={
            "select": "schemes_json,updated_at",
            "user_id": f"eq.{cloud_user_id}",
        })
        if result:
            row = result[0]
            data = row["schemes_json"]
            if isinstance(data, str):
                return json.loads(data)
            return data
        return None
    except Exception as e:
        logger.warning(f"云端筛选方案获取失败: {e}")
        return None


# ── 离线同步队列 ──

def enqueue_sync(db_file, action, payload):
    """将失败的同步操作入队，稍后重试。"""
    try:
        conn = sqlite3.connect(db_file)
        conn.execute(
            "INSERT INTO sync_queue (action, payload_json) VALUES (?, ?)",
            (action, json.dumps(payload, ensure_ascii=False)),
        )
        conn.commit()
        conn.close()
        logger.info(f"同步操作已入队: {action}")
    except Exception as e:
        logger.warning(f"入队失败: {e}")


def drain_sync_queue(db_file):
    """消费离线同步队列，最多重试 5 次后丢弃。"""
    if not is_available():
        return
    try:
        conn = sqlite3.connect(db_file)
        rows = conn.execute(
            "SELECT id, action, payload_json, retry_count FROM sync_queue ORDER BY id LIMIT 20"
        ).fetchall()
        if not rows:
            conn.close()
            return

        processed = []
        for row_id, action, payload_json, retry_count in rows:
            payload = json.loads(payload_json)
            success = _process_queue_item(action, payload)
            if success:
                processed.append(row_id)
            elif retry_count >= 4:
                processed.append(row_id)
                logger.warning(f"同步队列项 {row_id} 超过重试次数，已丢弃")
            else:
                conn.execute(
                    "UPDATE sync_queue SET retry_count = retry_count + 1 WHERE id = ?",
                    (row_id,),
                )

        if processed:
            conn.execute(
                f"DELETE FROM sync_queue WHERE id IN ({','.join('?' * len(processed))})",
                processed,
            )
        conn.commit()
        conn.close()
        if processed:
            logger.info(f"同步队列已处理 {len(processed)} 项")
    except Exception as e:
        logger.warning(f"队列消费失败: {e}")


def _process_queue_item(action, payload):
    """处理单个队列项，返回是否成功。"""
    try:
        if action == "register":
            uid = cloud_register(
                payload["username"], payload["pw_hash"], payload["salt"]
            )
            return uid is not None
        elif action == "save_watchlist":
            cloud_save_watchlist(payload["cloud_user_id"], payload["codes"])
            return True
        elif action == "save_schemes":
            cloud_save_schemes(
                payload["cloud_user_id"], payload["schemes_json"]
            )
            return True
        elif action == "create_session":
            cloud_create_session(
                payload["cloud_user_id"], payload["token"], payload["expires_at"]
            )
            return True
        else:
            logger.warning(f"未知队列操作: {action}")
            return True
    except Exception as e:
        logger.warning(f"队列项处理失败 ({action}): {e}")
        return False


# ── 合并逻辑 ──

def merge_watchlists(local, cloud):
    """并集合并自选股，去重保序。"""
    seen = set()
    merged = []
    for code in local + cloud:
        if code not in seen:
            seen.add(code)
            merged.append(code)
    return merged


# ── 密码验证（Supabase 为主） ──

def cloud_login_verify(username, password):
    """从 Supabase 验证用户名+密码，返回用户信息或 None。"""
    if not is_available():
        return None
    try:
        result = _api("GET", "users", params={
            "select": "id,username,salt,password_hash,is_admin",
            "username": f"eq.{username}",
        })
        if not result:
            return None
        row = result[0]
        expected = hashlib.sha256((password + row['salt']).encode()).hexdigest()
        if expected != row['password_hash']:
            return None
        return {
            'cloud_id': row['id'],
            'username': row['username'],
            'is_admin': bool(row.get('is_admin', False)),
        }
    except Exception as e:
        logger.warning(f"云端密码验证失败: {e}")
        return None


# ── 管理员：获取所有用户数据 ──

def cloud_get_all_users_admin():
    """获取所有用户及其 watchlist/schemes（仅管理员调用）。"""
    if not is_available():
        return []
    try:
        users = _api("GET", "users", params={
            "select": "id,username,is_admin,created_at,last_login",
        })
        result = []
        for u in (users or []):
            uid = u['id']
            wl_rows = _api("GET", "user_watchlists", params={
                "select": "stock_code",
                "user_id": f"eq.{uid}",
                "order": "added_at",
            })
            sc_rows = _api("GET", "user_schemes", params={
                "select": "schemes_json",
                "user_id": f"eq.{uid}",
            })
            schemes = None
            if sc_rows:
                raw = sc_rows[0].get('schemes_json')
                schemes = raw if isinstance(raw, list) else (json.loads(raw) if raw else None)
            result.append({
                'id': uid,
                'username': u['username'],
                'is_admin': bool(u.get('is_admin')),
                'created_at': u.get('created_at'),
                'last_login': u.get('last_login'),
                'watchlist': [r['stock_code'] for r in (wl_rows or [])],
                'schemes': schemes,
            })
        return result
    except Exception as e:
        logger.warning(f"云端获取用户列表失败: {e}")
        return []
    return merged
