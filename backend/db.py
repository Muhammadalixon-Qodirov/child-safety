"""SQLite storage. One small file, no ORM, safe to share across threads."""
import json
import sqlite3
import threading
import time
from datetime import datetime

from .config import DATA_DIR

DB_PATH = DATA_DIR / "guardian.db"
_lock = threading.RLock()
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.execute("PRAGMA journal_mode=WAL")

SCHEMA = """
CREATE TABLE IF NOT EXISTS children (
    id INTEGER PRIMARY KEY, name TEXT, age_group TEXT DEFAULT '10-13',
    trust_points INTEGER DEFAULT 40, last_seen REAL DEFAULT 0,
    network TEXT DEFAULT '', zone TEXT DEFAULT '', mode TEXT DEFAULT 'home',
    online INTEGER DEFAULT 0, offline_alerted INTEGER DEFAULT 0,
    auto_block INTEGER DEFAULT 1, ai_consent INTEGER DEFAULT 1,
    focus_until REAL DEFAULT 0, telegram_chat_id TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS apps (
    id INTEGER PRIMARY KEY, child_id INTEGER, name TEXT, match TEXT,
    category TEXT, action TEXT DEFAULT 'allow', limit_minutes INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sites (
    id INTEGER PRIMARY KEY, child_id INTEGER, domain TEXT, category TEXT, action TEXT DEFAULT 'block'
);
CREATE TABLE IF NOT EXISTS zones (
    id INTEGER PRIMARY KEY, child_id INTEGER, name TEXT, network TEXT, mode TEXT
);
CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY, child_id INTEGER, name TEXT, mode TEXT,
    start TEXT, end TEXT, days TEXT DEFAULT '0123456', enabled INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS usage (
    child_id INTEGER, day TEXT, app_id INTEGER, seconds INTEGER DEFAULT 0,
    PRIMARY KEY (child_id, day, app_id)
);
CREATE TABLE IF NOT EXISTS extra_time (
    child_id INTEGER, day TEXT, app_id INTEGER, minutes INTEGER DEFAULT 0,
    PRIMARY KEY (child_id, day, app_id)
);
CREATE TABLE IF NOT EXISTS temp_blocks (
    id INTEGER PRIMARY KEY, child_id INTEGER, kind TEXT, target TEXT, until REAL, reason TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY, child_id INTEGER, ts REAL, source TEXT, category TEXT,
    risk INTEGER, action_taken TEXT, target TEXT, title TEXT,
    reason_parent TEXT, reason_child TEXT, shot TEXT, shot_blur TEXT,
    status TEXT DEFAULT 'new', meta TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY, child_id INTEGER, ts REAL, kind TEXT, target TEXT,
    minutes INTEGER DEFAULT 0, reason TEXT, status TEXT DEFAULT 'pending', decided_ts REAL
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
"""


def query(sql, params=()):
    with _lock:
        return [dict(r) for r in _conn.execute(sql, params).fetchall()]


def one(sql, params=()):
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql, params=()):
    with _lock:
        cur = _conn.execute(sql, params)
        _conn.commit()
        return cur.lastrowid


def kv_get(key, default=None):
    row = one("SELECT value FROM kv WHERE key=?", (key,))
    return json.loads(row["value"]) if row else default


def kv_set(key, value):
    execute("INSERT OR REPLACE INTO kv(key, value) VALUES (?, ?)", (key, json.dumps(value)))


def today():
    return datetime.now().strftime("%Y-%m-%d")


def seed():
    if one("SELECT id FROM children LIMIT 1"):
        return
    cid = execute("INSERT INTO children(name, age_group) VALUES ('Sam', '10-13')")
    apps = [
        ("Roblox", "roblox", "game", "limit", 60),
        ("Minecraft", "minecraft", "game", "limit", 60),
        ("Steam", "steam", "game", "limit", 30),
        ("Discord", "discord", "social", "limit", 45),
        ("Telegram", "telegram", "social", "allow", 0),
        ("VLC Player", "vlc", "video", "limit", 30),
        ("Chrome", "chrome,chromium", "browser", "allow", 0),
        ("Firefox", "firefox", "browser", "allow", 0),
        ("LibreOffice", "soffice,libreoffice", "education", "allow", 0),
        ("VS Code", "code", "education", "allow", 0),
        ("VPN / proxy tools",
         "openvpn,wireguard,wg-quick,protonvpn,nordvpn,psiphon,windscribe,hotspotshield,tor",
         "vpn", "block", 0),
    ]
    for name, match, cat, action, limit in apps:
        execute("INSERT INTO apps(child_id, name, match, category, action, limit_minutes) VALUES (?,?,?,?,?,?)",
                (cid, name, match, cat, action, limit))
    sites = [
        ("1xbet.com", "gambling"), ("stake.com", "gambling"), ("melbet.com", "gambling"),
        ("tiktok.com", "social"), ("instagram.com", "social"), ("discord.com", "social"),
        ("youtube.com", "video"), ("twitch.tv", "video"),
        ("roblox.com", "game"), ("poki.com", "game"),
    ]
    for domain, cat in sites:
        # Gambling is always blocked; the others are blocked only by modes (school, bedtime...).
        action = "block" if cat == "gambling" else "mode"
        execute("INSERT INTO sites(child_id, domain, category, action) VALUES (?,?,?,?)", (cid, domain, cat, action))
    for name, network, mode in [("Home", "Home_WiFi", "home"), ("School", "School_WiFi", "school")]:
        execute("INSERT INTO zones(child_id, name, network, mode) VALUES (?,?,?,?)", (cid, name, network, mode))
    for name, mode, start, end, days in [
        ("School time", "school", "08:00", "13:00", "01234"),
        ("Homework", "homework", "16:00", "18:00", "01234"),
        ("Bedtime", "downtime", "22:00", "07:00", "0123456"),
    ]:
        execute("INSERT INTO schedules(child_id, name, mode, start, end, days) VALUES (?,?,?,?,?,?)",
                (cid, name, mode, start, end, days))


def init():
    with _lock:
        _conn.executescript(SCHEMA)
        _conn.commit()
    seed()


def purge_old(retention_days):
    """Privacy: drop events, screenshots and usage older than the retention window."""
    import os
    cutoff = time.time() - retention_days * 86400
    for ev in query("SELECT shot, shot_blur FROM events WHERE ts < ?", (cutoff,)):
        for path in (ev["shot"], ev["shot_blur"]):
            if path and os.path.exists(path):
                os.remove(path)
    execute("DELETE FROM events WHERE ts < ?", (cutoff,))
    cutoff_day = datetime.fromtimestamp(cutoff).strftime("%Y-%m-%d")
    execute("DELETE FROM usage WHERE day < ?", (cutoff_day,))
    execute("DELETE FROM temp_blocks WHERE until < ?", (time.time(),))
