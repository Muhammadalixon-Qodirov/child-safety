"""Turns rules + zone + schedule + usage into concrete decisions for the agent."""
import time
from datetime import datetime

from . import db

MODES = {
    "home": {"label": "Home", "icon": "🏠", "apps": [], "sites": [],
             "about": "Normal rules and daily limits."},
    "strict": {"label": "Unknown network", "icon": "☕", "apps": ["game", "social"], "sites": ["social", "game"],
               "about": "Connected to a network your parent hasn't approved, so games and chat are paused."},
    "homework": {"label": "Homework", "icon": "📚", "apps": ["game", "social", "video"],
                 "sites": ["social", "game", "video"], "about": "Only study apps and the browser."},
    "focus": {"label": "Focus (your choice)", "icon": "🎯", "apps": ["game", "social", "video"],
              "sites": ["social", "game", "video"], "about": "You switched on focus mode. Nice!"},
    "school": {"label": "School time", "icon": "🏫", "apps": ["game", "social", "video"],
               "sites": ["social", "video", "game"], "about": "Learning apps only during lessons."},
    "downtime": {"label": "Bedtime", "icon": "🌙", "apps": ["game", "social", "video", "browser"],
                 "sites": ["social", "video", "game"], "about": "Time to rest. Emergency help still works."},
}
PRIORITY = {"home": 1, "strict": 2, "homework": 3, "focus": 3, "school": 4, "downtime": 5}
ALWAYS_BLOCKED_SITE_CATEGORIES = {"gambling", "adult"}
TRUST_LEVELS = [(0, "Seedling", "🌱", 0), (50, "Sprout", "🌿", 10), (100, "Tree", "🌳", 20)]

_last_logged = {}


def trust_level(points):
    level = TRUST_LEVELS[0]
    for lvl in TRUST_LEVELS:
        if points >= lvl[0]:
            level = lvl
    nxt = next((l for l in TRUST_LEVELS if l[0] > points), None)
    return {"name": level[1], "icon": level[2], "bonus_minutes": level[3], "points": points,
            "next_at": nxt[0] if nxt else None, "next_name": nxt[1] if nxt else None}


def _in_window(start, end, now):
    cur = now.strftime("%H:%M")
    if start <= end:
        return start <= cur < end
    return cur >= start or cur < end  # crosses midnight


def active_schedules(child_id, now=None):
    now = now or datetime.now()
    out = []
    for s in db.query("SELECT * FROM schedules WHERE child_id=? AND enabled=1", (child_id,)):
        # A window that crosses midnight belongs to the day it started on.
        day = now.weekday()
        if s["start"] > s["end"] and now.strftime("%H:%M") < s["end"]:
            day = (day - 1) % 7
        if str(day) in s["days"] and _in_window(s["start"], s["end"], now):
            out.append(s)
    return out


def resolve_mode(child, network, now=None):
    zones = db.query("SELECT * FROM zones WHERE child_id=?", (child["id"],))
    if not network:
        zone, base = {"name": "Offline", "mode": "home"}, "home"
    else:
        zone = next((z for z in zones if z["network"].lower() == network.lower()), None)
        if zone:
            base = zone["mode"]
        else:
            zone, base = {"name": "Unknown network", "mode": "strict"}, "strict"
    candidates = [(base, f"zone: {zone['name']}")]
    for s in active_schedules(child["id"], now):
        candidates.append((s["mode"], f"schedule: {s['name']}"))
    if child["focus_until"] > time.time():
        candidates.append(("focus", "focus mode"))
    mode, why = max(candidates, key=lambda c: PRIORITY.get(c[0], 0))
    return zone["name"], mode, why


def match_app(process_names, app):
    patterns = [p.strip().lower() for p in app["match"].split(",") if p.strip()]
    hits = []
    for proc in process_names:
        base = proc.lower().removesuffix(".exe")
        if any(base == p or base.startswith(p) for p in patterns):
            hits.append(proc)
    return hits


def app_usage(child_id):
    rows = db.query("SELECT app_id, seconds FROM usage WHERE child_id=? AND day=?", (child_id, db.today()))
    return {r["app_id"]: r["seconds"] for r in rows}


def extra_minutes(child_id):
    rows = db.query("SELECT app_id, minutes FROM extra_time WHERE child_id=? AND day=?", (child_id, db.today()))
    return {r["app_id"]: r["minutes"] for r in rows}


def time_left(child, app, usage=None, extra=None):
    if app["action"] != "limit" or not app["limit_minutes"]:
        return None
    usage = usage if usage is not None else app_usage(child["id"])
    extra = extra if extra is not None else extra_minutes(child["id"])
    bonus = trust_level(child["trust_points"])["bonus_minutes"]
    allowed = (app["limit_minutes"] + extra.get(app["id"], 0) + bonus) * 60
    return max(0, allowed - usage.get(app["id"], 0))


def blocked_sites(child_id, mode):
    cats = set(MODES[mode]["sites"]) | ALWAYS_BLOCKED_SITE_CATEGORIES
    out = []
    for s in db.query("SELECT * FROM sites WHERE child_id=?", (child_id,)):
        if s["action"] == "allow":
            continue
        if s["action"] == "block" or s["category"] in cats:
            out.append(s["domain"])
    for t in db.query("SELECT target FROM temp_blocks WHERE child_id=? AND kind='site' AND until>?",
                      (child_id, time.time())):
        out.append(t["target"])
    return sorted(set(out))


def _should_log(key, every=600):
    now = time.time()
    if now - _last_logged.get(key, 0) > every:
        _last_logged[key] = now
        return True
    return False


def decide(child, running, network, interval):
    """Core decision for one heartbeat. Returns (response, new_events)."""
    zone, mode, why = resolve_mode(child, network)
    apps = db.query("SELECT * FROM apps WHERE child_id=?", (child["id"],))
    usage, extra = app_usage(child["id"]), extra_minutes(child["id"])
    temp = {t["target"].lower() for t in db.query(
        "SELECT target FROM temp_blocks WHERE child_id=? AND kind='app' AND until>?", (child["id"], time.time()))}
    kill, messages, events, running_apps = [], [], [], []

    for app in apps:
        procs = match_app(running, app)
        if not procs:
            continue
        reason = None
        if app["action"] == "block":
            reason = f"{app['name']} is blocked by your parent."
            if app["category"] == "vpn":
                reason = "VPN and proxy apps are turned off on this device."
        elif app["category"] in MODES[mode]["apps"]:
            reason = f"{app['name']} is paused during {MODES[mode]['label']}."
        elif app["name"].lower() in temp:
            reason = f"{app['name']} was paused because something risky was spotted."
        else:
            left = time_left(child, app, usage, extra)
            if left is not None and left <= 0:
                reason = f"Your time for {app['name']} is up for today. You can ask for more."
            elif left is not None and left <= 300 and _should_log(("warn", app["id"]), 240):
                messages.append(f"⏳ {app['name']}: {max(1, left // 60)} min left today.")
        if reason:
            kill.extend(procs)
            messages.append(reason)
            if _should_log(("kill", app["id"], mode)):
                risk = 70 if app["category"] == "vpn" else 15
                events.append({"source": "tamper" if app["category"] == "vpn" else "app",
                               "category": "TAMPER" if app["category"] == "vpn" else "APP_RULE",
                               "risk": risk, "action_taken": "closed", "target": app["name"],
                               "title": f"{app['name']} closed", "reason_parent": reason,
                               "reason_child": reason})
        else:
            running_apps.append(app["name"])
            if app["action"] == "limit":
                db.execute("""INSERT INTO usage(child_id, day, app_id, seconds) VALUES (?,?,?,?)
                              ON CONFLICT(child_id, day, app_id) DO UPDATE SET seconds = seconds + excluded.seconds""",
                           (child["id"], db.today(), app["id"], int(interval)))

    response = {
        "zone": zone, "mode": mode, "mode_label": MODES[mode]["label"], "mode_icon": MODES[mode]["icon"],
        "mode_reason": why, "kill": sorted(set(kill)), "messages": messages,
        "block_sites": blocked_sites(child["id"], mode),
        "screen_interval": 10 if mode in ("strict",) else 15,
        "ai_consent": bool(child["ai_consent"]),
    }
    return response, events, running_apps
