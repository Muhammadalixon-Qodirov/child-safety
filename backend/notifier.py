"""Telegram bot: pushes alerts with inline buttons and receives the parent's decisions."""
import json
import threading
import time

import httpx

from . import config, db

API = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"
ICONS = {"GROOMING": "🚨", "SELF_HARM": "🆘", "ADULT": "⛔", "PII": "🔐", "BULLYING": "💬", "VIOLENCE": "⚠️",
         "GAMBLING": "🎰", "SCAM": "🎣", "TAMPER": "🛠️", "SOS": "🆘", "OFFLINE": "📴", "APP_RULE": "⏱️"}
_handlers = {}


def enabled():
    return bool(config.TELEGRAM_BOT_TOKEN)


def chat_id():
    return db.kv_get("telegram_chat_id")


def _dashboard_link():
    return f"{config.PUBLIC_URL}/parent"


def _keyboard(rows):
    return json.dumps({"inline_keyboard": rows})


def _send(method, data, files=None):
    if not enabled() or not chat_id():
        return None
    data = {"chat_id": chat_id(), **data}
    try:
        r = httpx.post(f"{API}/{method}", data=data, files=files, timeout=20)
        return r.json()
    except Exception as exc:  # noqa: BLE001
        print(f"[telegram] {method} failed: {exc}")
        return None


def send_text(text):
    _send("sendMessage", {"text": text, "parse_mode": "HTML"})


def send_alert(event):
    icon = ICONS.get(event["category"], "⚠️")
    caption = (f"{icon} <b>{event['title']}</b>\n"
               f"Category: <b>{event['category']}</b> · Risk <b>{event['risk']}/100</b>\n"
               f"Action: {event['action_taken']}\n\n{event['reason_parent']}\n\n"
               f"Dashboard: {_dashboard_link()}")
    buttons = [[{"text": "⛔ Keep blocked", "callback_data": f"block:{event['id']}"},
                {"text": "✅ It's OK", "callback_data": f"ok:{event['id']}"}]]
    if event.get("target"):
        buttons.append([{"text": "💬 How do I talk about this?", "callback_data": f"advice:{event['id']}"}])
    markup = _keyboard(buttons)
    if event.get("shot_blur"):
        with open(event["shot_blur"], "rb") as fh:
            _send("sendPhoto", {"caption": caption[:1000], "parse_mode": "HTML", "reply_markup": markup},
                  files={"photo": fh})
    else:
        _send("sendMessage", {"text": caption, "parse_mode": "HTML", "reply_markup": markup})


def send_request(req, child_name):
    what = {"more_time": f"+{req['minutes']} min for {req['target']}",
            "unblock_app": f"open {req['target']}", "unblock_site": f"visit {req['target']}"}.get(req["kind"], req["target"])
    text = f"🙋 <b>{child_name} asks:</b> {what}\nReason: <i>{req['reason'] or '—'}</i>"
    markup = _keyboard([[{"text": "✅ Approve", "callback_data": f"approve:{req['id']}"},
                         {"text": "❌ Deny", "callback_data": f"deny:{req['id']}"}]])
    _send("sendMessage", {"text": text, "parse_mode": "HTML", "reply_markup": markup})


def on(action, fn):
    _handlers[action] = fn


def _poll():
    offset = db.kv_get("telegram_offset", 0)
    while True:
        try:
            r = httpx.get(f"{API}/getUpdates", params={"offset": offset, "timeout": 25}, timeout=35).json()
            for upd in r.get("result", []):
                offset = upd["update_id"] + 1
                db.kv_set("telegram_offset", offset)
                _handle(upd)
        except Exception as exc:  # noqa: BLE001
            print(f"[telegram] poll error: {exc}")
            time.sleep(5)


def _handle(upd):
    msg = upd.get("message")
    if msg and msg.get("text", "").startswith("/start"):
        db.kv_set("telegram_chat_id", msg["chat"]["id"])
        send_text("🛡️ <b>Guardian connected.</b>\nYou'll get alerts here only when something looks risky, "
                  "plus requests from your child. Nothing else.")
        return
    cb = upd.get("callback_query")
    if not cb:
        return
    action, _, ident = cb.get("data", "").partition(":")
    reply = "Done"
    if action in _handlers:
        try:
            reply = _handlers[action](int(ident)) or reply
        except Exception as exc:  # noqa: BLE001
            reply = f"Error: {exc}"
    httpx.post(f"{API}/answerCallbackQuery", data={"callback_query_id": cb["id"], "text": reply[:190]}, timeout=10)
    if action == "advice":
        send_text(reply)
    elif cb.get("message"):
        httpx.post(f"{API}/editMessageReplyMarkup", timeout=10, data={
            "chat_id": cb["message"]["chat"]["id"], "message_id": cb["message"]["message_id"],
            "reply_markup": _keyboard([[{"text": f"✔ {reply}", "callback_data": "noop:0"}]])})


def start():
    if enabled():
        threading.Thread(target=_poll, daemon=True).start()
        print("[telegram] bot polling started — send /start to your bot to link this dashboard")
