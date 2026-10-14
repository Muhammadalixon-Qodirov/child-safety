"""AI layer: Groq vision for screenshots, a policy-following safety model for text,
and a general model for parent advice and reports. Falls back to a keyword
classifier when no API key is configured, so the app still runs offline."""
import base64
import io
import json
import re
from pathlib import Path

import httpx
from PIL import Image

from . import config

POLICY = (Path(__file__).parent / "policy.md").read_text(encoding="utf-8")
CATEGORIES = ["SAFE", "GROOMING", "PII", "BULLYING", "SELF_HARM", "VIOLENCE", "ADULT", "GAMBLING", "SCAM"]
LAST_ERROR = {"message": ""}


def enabled():
    return bool(config.GROQ_API_KEY)


def _chat(model, messages, max_tokens=700, json_mode=False, reasoning=False):
    payload = {"model": model, "messages": messages, "temperature": 0.1, "max_completion_tokens": max_tokens}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if reasoning:
        payload["reasoning_effort"] = "low"
    headers = {"Authorization": f"Bearer {config.GROQ_API_KEY}"}
    for attempt in range(2):
        r = httpx.post(f"{config.GROQ_BASE_URL}/chat/completions", json=payload, headers=headers, timeout=45)
        if r.status_code == 400 and attempt == 0:
            # Some models reject json_mode / reasoning_effort; retry with a plain request.
            payload.pop("response_format", None)
            payload.pop("reasoning_effort", None)
            continue
        if r.status_code >= 400:
            LAST_ERROR["message"] = f"{model}: HTTP {r.status_code} {r.text[:300]}"
            r.raise_for_status()
        LAST_ERROR["message"] = ""
        return r.json()["choices"][0]["message"].get("content") or ""
    return ""


def _parse_json(text):
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise ValueError(f"no JSON in model output: {text[:200]!r}")
    return json.loads(match.group(0))


def _normalize(result, source):
    cat = str(result.get("category", "SAFE")).upper().replace("-", "_").replace(" ", "_")
    if cat not in CATEGORIES:
        cat = "SAFE"
    try:
        risk = int(float(result.get("risk", 0)))
    except (TypeError, ValueError):
        risk = 0
    risk = max(0, min(100, risk))
    if cat == "SAFE":
        risk = min(risk, 29)
    return {
        "category": cat, "risk": risk,
        "evidence": str(result.get("evidence", ""))[:300],
        "reason_parent": str(result.get("reason_parent", ""))[:600],
        "reason_child": str(result.get("reason_child", ""))[:600],
        "engine": source,
    }


# ---------------------------------------------------------------- keyword fallback
KEYWORDS = {
    "GROOMING": [
        r"don'?t tell (your )?(mom|mum|dad|parents|anyone)", r"our (little )?secret", r"keep (it|this) (a )?secret",
        r"send (me )?(a )?(pic|photo|selfie)", r"how old are you", r"meet (up|in person|irl)",
        r"i'?ll (buy|give) you", r"free robux.*(if|for) you", r"delete (this|our) chat",
        r"you'?re (so )?mature for your age", r"add me on (snap|telegram|whatsapp)",
        r"hech kimga aytma", r"ota-?onangga aytma", r"sir(imiz)? bo'?lsin", r"rasm(ingni)? (yubor|tashla)",
        r"никому не говори", r"родителям не говори", r"скинь (фото|фотку)", r"это наш секрет",
    ],
    "PII": [
        r"\b(my|ur|your) (home )?address\b", r"what school", r"which school", r"where do you live",
        r"\+?998[\s-]?\d{2}", r"\b\d{3}[\s-]\d{3}[\s-]\d{4}\b", r"my password", r"send (me )?your location",
        r"manzil(ing|im)", r"qaysi maktab", r"qayerda yashaysan", r"telefon raqam", r"\d+-maktab",
        r"где ты живешь", r"какая школа", r"мой адрес",
    ],
    "BULLYING": [
        r"\b(you'?re|ur) (so )?(stupid|ugly|fat|loser|worthless)", r"nobody likes you", r"kill yourself",
        r"everyone hates you", r"\bidiot\b", r"\bloser\b",
        r"ahmoq", r"tentak", r"seni hech kim yoqtirmaydi", r"xunuk",
        r"тупой", r"урод", r"тебя все ненавидят", r"лох",
    ],
    "SELF_HARM": [
        r"want to die", r"kill myself", r"end it all", r"hurt myself", r"cut myself", r"suicide",
        r"o'?lgim kelyapti", r"o'?zimni o'?ldir", r"хочу умереть", r"покончить с собой",
    ],
    "VIOLENCE": [r"how to make a (bomb|gun)", r"i'?ll (kill|stab|shoot) you", r"school shoot", r"gore"],
    "ADULT": [r"\bporn", r"\bnsfw\b", r"\bnudes?\b", r"\bxxx\b", r"\bsexy pics?\b"],
    "GAMBLING": [r"\bcasino\b", r"\bbetting\b", r"place (a|your) bet", r"1xbet", r"\bstake\.com", r"melbet", r"jackpot", r"stavka"],
    "SCAM": [r"free (robux|v-?bucks|skins?|nitro)", r"claim your (prize|reward)", r"verify your account",
             r"enter your password", r"you (have )?won", r"send (the )?code"],
}
BASE_RISK = {"GROOMING": 85, "SELF_HARM": 85, "ADULT": 85, "PII": 65, "BULLYING": 65,
             "VIOLENCE": 70, "GAMBLING": 75, "SCAM": 65}
TEMPLATES = {
    "GROOMING": ("Someone is asking your child to keep secrets or share photos — a common grooming pattern.",
                 "When someone online asks you to keep a secret or send photos, that's a warning sign. You did nothing wrong — tell a trusted adult."),
    "PII": ("Personal details (address, school or phone) were shared or requested in a chat.",
            "Your address, school and phone number are like keys to your real life. Keep them private online."),
    "BULLYING": ("Hurtful or insulting messages appeared in a conversation.",
                 "Nobody deserves mean messages. You can block, screenshot and tell an adult you trust."),
    "SELF_HARM": ("Content suggests your child may be struggling emotionally or is seeing self-harm content.",
                  "It sounds like things might feel heavy right now. You're not alone — please talk to someone you trust."),
    "VIOLENCE": ("Violent or threatening content appeared on screen.",
                 "This content can be upsetting. It's okay to step away and talk about it."),
    "ADULT": ("Adult content was detected. No screenshot was stored.",
              "This page isn't meant for kids, so it was closed. You're not in trouble."),
    "GAMBLING": ("A gambling or betting site was opened.",
                 "Betting sites are designed to make you lose money. They're not allowed here."),
    "SCAM": ("A likely scam (free game currency, password or code request) appeared.",
             "\"Free Robux\" and code requests are almost always scams. Never share passwords or codes."),
}


def heuristic(text, ctx=None):
    text_l = (text or "").lower()
    best = {"category": "SAFE", "risk": 5, "evidence": ""}
    for cat, patterns in KEYWORDS.items():
        hits = [m.group(0) for p in patterns for m in [re.search(p, text_l)] if m]
        if hits:
            risk = min(100, BASE_RISK[cat] + 5 * (len(hits) - 1))
            if ctx and ctx.get("age_group") == "6-9":
                risk = min(100, risk + 10)
            if risk > best["risk"]:
                best = {"category": cat, "risk": risk, "evidence": ", ".join(hits[:3])}
    if best["category"] != "SAFE":
        best["reason_parent"], best["reason_child"] = TEMPLATES[best["category"]]
    return _normalize(best, "keywords")


def prefilter(text):
    """Cheap on-device style check used to decide whether a screenshot deserves AI review."""
    return heuristic(text)["risk"] >= 30


# ---------------------------------------------------------------- public API
def classify_text(text, ctx=None):
    ctx = ctx or {}
    if not text or not text.strip():
        return _normalize({"category": "SAFE", "risk": 0}, "empty")
    if not enabled():
        return heuristic(text, ctx)
    user = (f"Child age group: {ctx.get('age_group', '10-13')}. App/site: {ctx.get('app', 'unknown')}.\n"
            f"Content to review:\n<<<\n{text[:6000]}\n>>>")
    messages = [{"role": "system", "content": POLICY}, {"role": "user", "content": user}]
    for model in (config.GROQ_SAFETY_MODEL, config.GROQ_TEXT_MODEL):
        try:
            return _normalize(_parse_json(_chat(model, messages, json_mode=True, reasoning=True)), model)
        except Exception as exc:  # noqa: BLE001 - fall through to the next model
            LAST_ERROR["message"] = f"{model}: {exc}"
    return heuristic(text, ctx)


def _image_to_data_url(image_bytes, max_side=1280):
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


VISION_PROMPT = """Look at this screenshot from a child's computer.
1. Transcribe the important visible text (chat messages, page titles, search terms), max 800 characters.
2. Name the app or website shown (domain if visible).
3. Classify it with the child-safety policy below.

Return only JSON:
{"text": "...", "source": "app or domain", "category": "...", "risk": 0, "evidence": "...",
 "reason_parent": "...", "reason_child": "..."}

POLICY:
""" + POLICY


def vision_available():
    return bool(config.GEMINI_API_KEY) or bool(config.GROQ_VISION_MODEL)


def _gemini_vision(image_bytes, ctx):
    """Reads a screenshot with the Gemini API. Raises on any failure so the caller can fall back."""
    import base64
    b64 = base64.b64encode(image_bytes).decode()
    payload = {
        "contents": [{"parts": [
            {"text": VISION_PROMPT + f"\nChild age group: {ctx.get('age_group', '10-13')}."},
            {"inline_data": {"mime_type": "image/png", "data": b64}},
        ]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "maxOutputTokens": 900},
    }
    url = f"{config.GEMINI_BASE_URL}/models/{config.GEMINI_VISION_MODEL}:generateContent?key={config.GEMINI_API_KEY}"
    r = httpx.post(url, json=payload, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code} {r.text[:150]}")
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    return _parse_json(text)


def analyze_screen(image_bytes, ocr_text="", ctx=None):
    """Returns a classification plus the text and source the model saw on screen."""
    ctx = ctx or {}
    if not enabled() and not config.GEMINI_API_KEY:
        result = heuristic(ocr_text, ctx)
        result.update(text=ocr_text[:800], source=ctx.get("source") or ctx.get("app", ""))
        return result
    seen_text, source, vision = ocr_text, "", None
    try:
        if config.GEMINI_API_KEY:
            raw = _gemini_vision(image_bytes, ctx)
            vision = _normalize(raw, config.GEMINI_VISION_MODEL)
        elif config.GROQ_VISION_MODEL:
            content = [
                {"type": "text", "text": VISION_PROMPT + f"\nChild age group: {ctx.get('age_group', '10-13')}."},
                {"type": "image_url", "image_url": {"url": _image_to_data_url(image_bytes)}},
            ]
            raw = _parse_json(_chat(config.GROQ_VISION_MODEL, [{"role": "user", "content": content}],
                                    max_tokens=900, json_mode=True))
            vision = _normalize(raw, config.GROQ_VISION_MODEL)
        else:
            raise RuntimeError("no vision model configured")
        seen_text = (raw.get("text") or "") + ("\n" + ocr_text if ocr_text else "")
        source = str(raw.get("source", ""))[:120]
    except Exception as exc:  # noqa: BLE001
        LAST_ERROR["message"] = f"vision: {exc}"
    # Second opinion from the policy-following safety model on the extracted text.
    text_result = classify_text(seen_text, ctx) if seen_text.strip() else None
    candidates = [r for r in (vision, text_result) if r]
    result = max(candidates, key=lambda r: r["risk"]) if candidates else heuristic(ocr_text, ctx)
    if vision and text_result:
        result = dict(result, engine=f"{vision['engine']} + {text_result['engine']}")
    result.update(text=seen_text[:800], source=source or ctx.get("source") or ctx.get("app", ""))
    return result


def _fallback_advice(event):
    return ("1. Start calm: \"I'm not angry, I just want to make sure you're okay.\"\n"
            "2. Ask open questions: \"What happened? How did it make you feel?\"\n"
            "3. Make clear they're not in trouble for telling you.\n"
            "4. Agree on a next step together (block, report, or just keep talking).\n"
            f"Topic: {event.get('category', '')} — {event.get('reason_parent', '')}")


def conversation_advice(event, age_group):
    if not enabled():
        return _fallback_advice(event)
    prompt = (f"A parent got this alert from a child-safety app. Child age group: {age_group}.\n"
              f"Category: {event['category']}, risk {event['risk']}/100.\n"
              f"What the AI saw: {event.get('reason_parent', '')}\n\n"
              "Write short, warm, practical advice (max 120 words) on how the parent can talk to the child "
              "about it without shaming or scaring them: an opening sentence they can say word for word, "
              "2-3 questions to ask, and one concrete next step. Use plain language and a numbered list.")
    try:
        return _chat(config.GROQ_TEXT_MODEL, [{"role": "user", "content": prompt}], max_tokens=1200, reasoning=True)
    except Exception:  # noqa: BLE001
        return _fallback_advice(event)


def weekly_report(child, events, usage_rows):
    summary = {
        "child_age_group": child["age_group"],
        "alerts": [{"category": e["category"], "risk": e["risk"], "when": e["ts_h"]} for e in events[:40]],
        "screen_time_minutes": {u["name"]: round(u["seconds"] / 60) for u in usage_rows},
    }
    if not enabled():
        cats = {}
        for e in events:
            cats[e["category"]] = cats.get(e["category"], 0) + 1
        top = ", ".join(f"{k}: {v}" for k, v in sorted(cats.items(), key=lambda x: -x[1])) or "no alerts"
        return (f"This week: {len(events)} events ({top}). "
                "Tip: pick one calm moment to ask your child what they enjoyed online this week.")
    prompt = ("You write a weekly digest for a parent from a child-safety app. Be calm, short (max 130 words), "
              "privacy-respecting (no surveillance tone). Include: overall picture, any pattern worth attention "
              "(time of day, category), one positive thing, and one suggested conversation starter.\n"
              f"Data: {json.dumps(summary)}")
    try:
        return _chat(config.GROQ_TEXT_MODEL, [{"role": "user", "content": prompt}], max_tokens=1200, reasoning=True)
    except Exception:  # noqa: BLE001
        return "Report unavailable right now."
