"""Guardian backend: agent API, parent + child dashboards, AI pipeline, Telegram."""
import json
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import ai_engine, config, db, imaging, notifier, policy

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Guardian")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
CHILD_ID = 1
VICTIM_CATEGORIES = {"GROOMING", "PII", "BULLYING", "SELF_HARM", "VIOLENCE", "ADULT", "SCAM"}


def child():
    return db.one("SELECT * FROM children WHERE id=?", (CHILD_ID,))


def ts_h(ts):
    return datetime.fromtimestamp(ts).strftime("%a %H:%M")


# ------------------------------------------------------------------ events
def add_event(ev, notify=True):
    ev = {"source": "screen", "category": "SAFE", "risk": 0, "action_taken": "", "target": "", "title": "",
          "reason_parent": "", "reason_child": "", "shot": None, "shot_blur": None, "meta": {}, **ev}
    ev["id"] = db.execute(
        """INSERT INTO events(child_id, ts, source, category, risk, action_taken, target, title, reason_parent,
           reason_child, shot, shot_blur, meta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (CHILD_ID, time.time(), ev["source"], ev["category"], ev["risk"], ev["action_taken"], ev["target"],
         ev["title"], ev["reason_parent"], ev["reason_child"], ev["shot"], ev["shot_blur"], json.dumps(ev["meta"])))
    if notify and ev["risk"] >= 60:
        threading.Thread(target=notifier.send_alert, args=(ev,), daemon=True).start()
    return ev


def find_app(name):
    name = (name or "").lower()
    for a in db.query("SELECT * FROM apps WHERE child_id=?", (CHILD_ID,)):
        pats = [a["name"].lower()] + [p.strip() for p in a["match"].lower().split(",") if p.strip()]
        if any(p and p in name for p in pats):
            return a
    return None


def looks_like_domain(s):
    s = (s or "").strip().lower()
    return "." in s and " " not in s and len(s) < 80


def process_screen(image_bytes, ocr_text, app_name, origin="agent", source_hint=""):
    """The heart of Guardian: screenshot -> AI -> decide -> store (privacy-aware) -> act -> notify."""
    c = child()
    if not c["ai_consent"]:
        return {"risk": 0, "category": "SAFE", "skipped": "AI review disabled by parent"}
    ctx = {"age_group": c["age_group"], "app": app_name, "source": source_hint}
    res = ai_engine.analyze_screen(image_bytes, ocr_text, ctx)
    out = {"risk": res["risk"], "category": res["category"], "engine": res["engine"], "block": None,
           "message_child": None}
    if res["risk"] < 30:
        return out  # Safe: screenshot is discarded, nothing is stored.

    source = res.get("source") or app_name
    target_app = find_app(app_name) or find_app(source)
    block = None
    if res["risk"] >= 80 and c["auto_block"]:
        if looks_like_domain(source) and not target_app or (target_app and target_app["category"] == "browser"):
            domain = source.lower().removeprefix("https://").removeprefix("http://").split("/")[0] \
                if looks_like_domain(source) else ""
            if domain:
                block = {"kind": "site", "target": domain}
        if not block and target_app and target_app["category"] != "browser":
            block = {"kind": "app", "target": target_app["name"]}
    if block:
        db.execute("INSERT INTO temp_blocks(child_id, kind, target, until, reason) VALUES (?,?,?,?,?)",
                   (CHILD_ID, block["kind"], block["target"], time.time() + 2 * 3600, res["category"]))
        action = f"paused {block['target']} for 2h"
    elif res["risk"] >= 60:
        action = "parent alerted"
    else:
        action = "noted for weekly digest"

    shot = blur = None
    if res["risk"] >= 60 and res["category"] != "ADULT":
        shot, blur = imaging.save_with_blur(image_bytes)

    ev = add_event({
        "source": origin, "category": res["category"], "risk": res["risk"], "action_taken": action,
        "target": block["target"] if block else (target_app["name"] if target_app else source),
        "title": f"{res['category'].replace('_', ' ').title()} on {source or app_name or 'screen'}",
        "reason_parent": res["reason_parent"], "reason_child": res["reason_child"],
        "shot": shot, "shot_blur": blur,
        "meta": {"evidence": res.get("evidence", ""), "engine": res["engine"], "app": app_name,
                 "text": "" if res["category"] == "ADULT" else res.get("text", "")[:500]},
    })
    out.update(block=block, message_child=res["reason_child"], event_id=ev["id"])
    return out


# ------------------------------------------------------------------ agent API
def check_agent(key):
    if key != config.AGENT_KEY:
        raise HTTPException(401, "bad agent key")


@app.post("/api/agent/heartbeat")
async def heartbeat(request: Request, x_agent_key: str = Header("")):
    check_agent(x_agent_key)
    body = await request.json()
    c = child()
    now = time.time()
    interval = min(max(now - c["last_seen"], 0), 10) if c["last_seen"] else 0
    resp, events, running_apps = policy.decide(c, body.get("running", []), body.get("network", ""), interval)
    was_offline = not c["online"] and c["offline_alerted"]
    db.execute("""UPDATE children SET last_seen=?, online=1, offline_alerted=0, network=?, zone=?, mode=?
                  WHERE id=?""", (now, body.get("network", ""), resp["zone"], resp["mode"], CHILD_ID))
    db.kv_set("agent_info", {"hostname": body.get("hostname"), "platform": body.get("platform"),
                             "running": running_apps, "site_blocking": body.get("site_blocking")})
    for ev in events:
        add_event(ev, notify=ev["risk"] >= 60)
        if ev["category"] == "TAMPER":
            db.execute("UPDATE children SET trust_points=MAX(0, trust_points-5) WHERE id=?", (CHILD_ID,))
    if was_offline:
        threading.Thread(target=notifier.send_text, args=("✅ Guardian is back online.",), daemon=True).start()
    _award_trust(c, now)
    return resp


def _award_trust(c, now):
    last = db.kv_get("trust_tick", 0)
    if now - last > 600:  # +1 point for every 10 calm minutes online
        db.kv_set("trust_tick", now)
        if last:
            db.execute("UPDATE children SET trust_points=trust_points+1 WHERE id=?", (CHILD_ID,))
    focus_end = db.kv_get("focus_award", 0)
    if focus_end and now > focus_end:
        db.kv_set("focus_award", 0)
        db.execute("UPDATE children SET trust_points=trust_points+5 WHERE id=?", (CHILD_ID,))


@app.post("/api/agent/analyze")
async def agent_analyze(image: UploadFile = File(...), ocr_text: str = Form(""), app_name: str = Form(""),
                        x_agent_key: str = Header("")):
    check_agent(x_agent_key)
    data = await image.read()
    return process_screen(data, ocr_text, app_name)


# ------------------------------------------------------------------ parent API
def safety_weather(events):
    worst = max((e["risk"] for e in events), default=0)
    if worst >= 80:
        return {"icon": "⛈️", "label": "Needs attention", "level": "red"}
    if worst >= 60:
        return {"icon": "⛅", "label": "Some alerts", "level": "amber"}
    return {"icon": "☀️", "label": "All calm", "level": "green"}


def usage_today():
    c = child()
    usage, extra = policy.app_usage(CHILD_ID), policy.extra_minutes(CHILD_ID)
    rows = []
    for a in db.query("SELECT * FROM apps WHERE child_id=? ORDER BY category, name", (CHILD_ID,)):
        left = policy.time_left(c, a, usage, extra)
        rows.append({**a, "seconds": usage.get(a["id"], 0), "seconds_left": left,
                     "extra": extra.get(a["id"], 0)})
    return rows


@app.get("/api/state")
def state():
    c = child()
    since = time.time() - 86400
    events = db.query("SELECT * FROM events WHERE child_id=? AND ts>? AND risk>=30", (CHILD_ID, since))
    zone, mode, why = policy.resolve_mode(c, c["network"]) if c["online"] else (c["zone"] or "—", c["mode"], "")
    return {
        "child": c, "online": bool(c["online"]), "last_seen": c["last_seen"],
        "zone": zone, "mode": mode, "mode_reason": why, "mode_info": policy.MODES[mode],
        "weather": safety_weather(events), "alerts_today": sum(1 for e in events if e["risk"] >= 60),
        "usage": usage_today(), "trust": policy.trust_level(c["trust_points"]),
        "pending_requests": len(db.query("SELECT id FROM requests WHERE status='pending'")),
        "ai": {"enabled": ai_engine.enabled(), "vision_model": config.GROQ_VISION_MODEL,
               "safety_model": config.GROQ_SAFETY_MODEL, "last_error": ai_engine.LAST_ERROR["message"]},
        "telegram": {"enabled": notifier.enabled(), "linked": bool(notifier.chat_id())},
        "agent": db.kv_get("agent_info", {}),
        "blocked_sites": policy.blocked_sites(CHILD_ID, mode),
        "temp_blocks": db.query("SELECT * FROM temp_blocks WHERE until>?", (time.time(),)),
        "modes": policy.MODES,
    }


@app.get("/api/events")
def events(limit: int = 50, min_risk: int = 0):
    rows = db.query("SELECT * FROM events WHERE child_id=? AND risk>=? ORDER BY ts DESC LIMIT ?",
                    (CHILD_ID, min_risk, limit))
    for r in rows:
        r["meta"] = json.loads(r["meta"] or "{}")
        r["ts_h"] = ts_h(r["ts"])
        r["has_shot"] = bool(r["shot"])
        r.pop("shot"), r.pop("shot_blur")
    return rows


@app.get("/api/shots/{event_id}")
def shot(event_id: int, original: int = 0):
    ev = db.one("SELECT shot, shot_blur FROM events WHERE id=?", (event_id,))
    path = ev and (ev["shot"] if original else ev["shot_blur"])
    if not path or not os.path.exists(path):
        raise HTTPException(404)
    return FileResponse(path)


def decide_event(event_id, decision):
    ev = db.one("SELECT * FROM events WHERE id=?", (event_id,))
    if not ev:
        return "Not found"
    if decision == "ok":
        db.execute("DELETE FROM temp_blocks WHERE target=?", (ev["target"],))
        db.execute("UPDATE events SET status='allowed' WHERE id=?", (event_id,))
        return "Marked OK, block lifted"
    if ev["target"]:
        kind = "site" if looks_like_domain(ev["target"]) else "app"
        db.execute("INSERT INTO temp_blocks(child_id, kind, target, until, reason) VALUES (?,?,?,?,?)",
                   (CHILD_ID, kind, ev["target"], time.time() + 24 * 3600, "parent"))
    db.execute("UPDATE events SET status='blocked' WHERE id=?", (event_id,))
    return "Blocked for 24h"


@app.post("/api/events/{event_id}/decision")
async def event_decision(event_id: int, request: Request):
    body = await request.json()
    return {"result": decide_event(event_id, body.get("decision"))}


@app.get("/api/events/{event_id}/advice")
def event_advice(event_id: int):
    ev = db.one("SELECT * FROM events WHERE id=?", (event_id,))
    if not ev:
        raise HTTPException(404)
    return {"advice": ai_engine.conversation_advice(ev, child()["age_group"])}


@app.get("/api/report")
def report():
    since = time.time() - 7 * 86400
    evs = db.query("SELECT * FROM events WHERE child_id=? AND ts>? AND risk>=30 ORDER BY ts DESC", (CHILD_ID, since))
    for e in evs:
        e["ts_h"] = ts_h(e["ts"])
    rows = db.query("""SELECT a.name, SUM(u.seconds) AS seconds FROM usage u JOIN apps a ON a.id=u.app_id
                       WHERE u.child_id=? GROUP BY a.name""", (CHILD_ID,))
    return {"report": ai_engine.weekly_report(child(), evs, rows)}


@app.get("/api/usage/week")
def usage_week():
    days = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
    rows = db.query("""SELECT u.day, a.category, SUM(u.seconds) AS seconds FROM usage u JOIN apps a ON a.id=u.app_id
                       WHERE u.child_id=? AND u.day>=? GROUP BY u.day, a.category""", (CHILD_ID, days[0]))
    return {"days": days, "rows": rows}


CRUD = {
    "apps": ["name", "match", "category", "action", "limit_minutes"],
    "sites": ["domain", "category", "action"],
    "zones": ["name", "network", "mode"],
    "schedules": ["name", "mode", "start", "end", "days", "enabled"],
    "temp_blocks": [],  # list + delete only
}


@app.get("/api/{table}")
def list_rows(table: str):
    if table not in CRUD:
        raise HTTPException(404)
    return db.query(f"SELECT * FROM {table} WHERE child_id=? ORDER BY id", (CHILD_ID,))


@app.post("/api/{table}")
async def create_row(table: str, request: Request):
    if table not in CRUD:
        raise HTTPException(404)
    body = await request.json()
    fields = [f for f in CRUD[table] if f in body]
    rid = db.execute(f"INSERT INTO {table}(child_id, {', '.join(fields)}) VALUES (?, {', '.join('?' * len(fields))})",
                     (CHILD_ID, *[body[f] for f in fields]))
    return {"id": rid}


@app.put("/api/{table}/{row_id}")
async def update_row(table: str, row_id: int, request: Request):
    if table not in CRUD:
        raise HTTPException(404)
    body = await request.json()
    fields = [f for f in CRUD[table] if f in body]
    if fields:
        db.execute(f"UPDATE {table} SET {', '.join(f + '=?' for f in fields)} WHERE id=? AND child_id=?",
                   (*[body[f] for f in fields], row_id, CHILD_ID))
    return {"ok": True}


@app.delete("/api/{table}/{row_id}")
def delete_row(table: str, row_id: int):
    if table not in CRUD:
        raise HTTPException(404)
    db.execute(f"DELETE FROM {table} WHERE id=? AND child_id=?", (row_id, CHILD_ID))
    return {"ok": True}


@app.put("/api/child")
async def update_child(request: Request):
    body = await request.json()
    fields = [f for f in ("name", "age_group", "auto_block", "ai_consent") if f in body]
    if fields:
        db.execute(f"UPDATE children SET {', '.join(f + '=?' for f in fields)} WHERE id=?",
                   (*[body[f] for f in fields], CHILD_ID))
    return {"ok": True}


def decide_request(req_id, approve):
    req = db.one("SELECT * FROM requests WHERE id=?", (req_id,))
    if not req or req["status"] != "pending":
        return "Already handled"
    db.execute("UPDATE requests SET status=?, decided_ts=? WHERE id=?",
               ("approved" if approve else "denied", time.time(), req_id))
    if approve:
        if req["kind"] == "more_time":
            app_row = find_app(req["target"])
            if app_row:
                db.execute("""INSERT INTO extra_time(child_id, day, app_id, minutes) VALUES (?,?,?,?)
                              ON CONFLICT(child_id, day, app_id) DO UPDATE SET minutes = minutes + excluded.minutes""",
                           (CHILD_ID, db.today(), app_row["id"], req["minutes"]))
        elif req["kind"] == "unblock_site":
            db.execute("DELETE FROM temp_blocks WHERE target=?", (req["target"],))
            db.execute("INSERT INTO sites(child_id, domain, category, action) VALUES (?,?,?,?)",
                       (CHILD_ID, req["target"], "other", "allow"))
        elif req["kind"] == "unblock_app":
            db.execute("DELETE FROM temp_blocks WHERE target=?", (req["target"],))
            db.execute("""INSERT INTO extra_time(child_id, day, app_id, minutes)
                          SELECT ?, ?, id, 30 FROM apps WHERE name=? ON CONFLICT DO NOTHING""",
                       (CHILD_ID, db.today(), req["target"]))
    return "Approved ✅" if approve else "Denied"


@app.get("/api/requests")
def list_requests():
    rows = db.query("SELECT * FROM requests WHERE child_id=? ORDER BY ts DESC LIMIT 30", (CHILD_ID,))
    for r in rows:
        r["ts_h"] = ts_h(r["ts"])
    return rows


@app.post("/api/requests/{req_id}/decide")
async def request_decide(req_id: int, request: Request):
    body = await request.json()
    return {"result": decide_request(req_id, bool(body.get("approve")))}


@app.post("/api/demo/{scenario}")
def demo(scenario: str):
    if scenario not in imaging.DEMO_SCENARIOS:
        raise HTTPException(404)
    img, text, sc = imaging.render_demo(scenario)
    return process_screen(img, text, sc["app"], origin="demo", source_hint=sc.get("domain", ""))


# ------------------------------------------------------------------ child API
@app.get("/api/child/state")
def child_state():
    c = child()
    zone, mode, why = policy.resolve_mode(c, c["network"])
    limits = [{"name": u["name"], "category": u["category"], "seconds_left": u["seconds_left"],
               "limit_minutes": u["limit_minutes"] + u["extra"]}
              for u in usage_today() if u["seconds_left"] is not None]
    recent = db.query("""SELECT id, ts, category, risk, title, reason_child, action_taken FROM events
                         WHERE child_id=? AND (risk>=30 OR category='APP_RULE') ORDER BY ts DESC LIMIT 8""", (CHILD_ID,))
    for r in recent:
        r["ts_h"] = ts_h(r["ts"])
    return {
        "name": c["name"], "zone": zone, "mode": mode, "mode_reason": why, "mode_info": policy.MODES[mode],
        "trust": policy.trust_level(c["trust_points"]), "limits": limits, "recent": recent,
        "focus_until": c["focus_until"], "online": bool(c["online"]),
        "ai_consent": bool(c["ai_consent"]),
        "requests": db.query("SELECT * FROM requests WHERE child_id=? ORDER BY ts DESC LIMIT 6", (CHILD_ID,)),
        "blockable": [a["name"] for a in db.query("SELECT name FROM apps WHERE child_id=? AND category!='vpn'",
                                                  (CHILD_ID,))],
    }


@app.post("/api/child/request")
async def child_request(request: Request):
    body = await request.json()
    rid = db.execute("INSERT INTO requests(child_id, ts, kind, target, minutes, reason) VALUES (?,?,?,?,?,?)",
                     (CHILD_ID, time.time(), body.get("kind", "more_time"), body.get("target", ""),
                      int(body.get("minutes") or 0), body.get("reason", "")[:300]))
    req = db.one("SELECT * FROM requests WHERE id=?", (rid,))
    threading.Thread(target=notifier.send_request, args=(req, child()["name"]), daemon=True).start()
    return {"id": rid}


@app.post("/api/child/focus")
async def child_focus(request: Request):
    minutes = int((await request.json()).get("minutes", 30))
    until = time.time() + minutes * 60
    db.execute("UPDATE children SET focus_until=? WHERE id=?", (until, CHILD_ID))
    db.kv_set("focus_award", until)
    return {"focus_until": until}


@app.post("/api/child/sos")
async def child_sos(request: Request):
    body = await request.json()
    ev = add_event({"source": "sos", "category": "SOS", "risk": 95, "action_taken": "parent alerted",
                    "title": f"{child()['name']} pressed SOS",
                    "reason_parent": body.get("message") or "Your child asked for help. Please reach out now.",
                    "reason_child": "Your parent has been notified. Help is on the way."})
    return {"ok": True, "event_id": ev["id"]}


# Safe Typing: checks text the child is about to send, BEFORE it leaves the device.
# It does not store keystrokes. Only a flagged phrase is kept, and only so the child
# (and, for the most serious risks, the parent) can see why a warning appeared.
_typing_hits = {}  # per-category throttle so a parent isn't alerted on every keystroke


def _safe_typing_parent_alert(category, snippet):
    import time as _t
    now = _t.time()
    if now - _typing_hits.get(category, 0) < 120:
        return
    _typing_hits[category] = now
    titles = {"PII": "Child was about to share personal info while typing",
              "GROOMING": "Risky conversation detected while your child was typing",
              "SELF_HARM": "Your child typed something that may signal distress"}
    add_event({"source": "typing", "category": category, "risk": 70, "action_taken": "child warned before sending",
               "title": titles.get(category, "Risky text while typing"),
               "reason_parent": f"Guardian warned your child before they sent a message. Topic: {category}.",
               "reason_child": "Guardian gave you a heads-up before you sent that message.",
               "meta": {"evidence": snippet[:120]}})


@app.post("/api/child/type-check")
async def type_check(request: Request):
    """Called as the child types. Returns a gentle warning, nothing is stored unless risky."""
    text = (await request.json()).get("text", "")
    if len(text) < 8:
        return {"risk": 0}
    c = child()
    res = ai_engine.classify_text(text, {"age_group": c["age_group"], "app": "typing"})
    if res["risk"] < 40 or res["category"] == "SAFE":
        return {"risk": res["risk"]}
    # Only the three categories where a pre-send nudge helps the child directly.
    if res["category"] not in ("PII", "GROOMING", "SELF_HARM", "BULLYING"):
        return {"risk": res["risk"], "category": res["category"]}
    if res["category"] in ("PII", "GROOMING", "SELF_HARM") and res["risk"] >= 60:
        threading.Thread(target=_safe_typing_parent_alert,
                         args=(res["category"], res.get("evidence") or text), daemon=True).start()
    return {"risk": res["risk"], "category": res["category"], "warn": res["reason_child"]}


# ------------------------------------------------------------------ pages + background
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/parent")
def parent_page():
    return FileResponse(STATIC / "parent.html")


@app.get("/child")
def child_page():
    return FileResponse(STATIC / "child.html")


def _watchdog():
    last_purge = 0
    while True:
        time.sleep(5)
        c = child()
        if c["online"] and time.time() - c["last_seen"] > config.OFFLINE_AFTER_SEC:
            db.execute("UPDATE children SET online=0, offline_alerted=1 WHERE id=?", (CHILD_ID,))
            db.execute("UPDATE children SET trust_points=MAX(0, trust_points-5) WHERE id=?", (CHILD_ID,))
            add_event({"source": "tamper", "category": "TAMPER", "risk": 65, "action_taken": "parent alerted",
                       "title": "Guardian agent stopped",
                       "reason_parent": "The protection agent stopped reporting. It may have been closed, "
                                        "the computer turned off, or the network dropped.",
                       "reason_child": "Guardian stopped running, so your parent was told."})
        if time.time() - last_purge > 3600:
            db.purge_old(config.RETENTION_DAYS)
            last_purge = time.time()


@app.on_event("startup")
def startup():
    db.init()
    notifier.on("block", lambda i: decide_event(i, "block"))
    notifier.on("ok", lambda i: decide_event(i, "ok"))
    notifier.on("approve", lambda i: decide_request(i, True))
    notifier.on("deny", lambda i: decide_request(i, False))
    notifier.on("advice", lambda i: event_advice(i)["advice"])
    notifier.on("noop", lambda i: "Already handled")
    notifier.start()
    threading.Thread(target=_watchdog, daemon=True).start()
    print(f"[guardian] AI: {'Groq' if ai_engine.enabled() else 'offline keyword mode (set GROQ_API_KEY)'}")
