"""
game.py — the activities currently in play. Starts from the defaults in
content.py; anything saved from /admin/content is stored in the database and
replaces them (so edits survive redeploys and every server process sees them).
"""

import json
import uuid
from types import SimpleNamespace

import content
import db

PROOFS = ("name", "photo", "video", "either")
SETTINGS_KEY = "content"


def defaults():
    return {
        "event_name": content.EVENT_NAME,
        "square_points": content.BINGO_SQUARE_POINTS,
        "line_bonus": content.BINGO_LINE_BONUS,
        "free_square": content.FREE_SQUARE,
        "bingo_traits": list(content.BINGO_TRAITS),
        "challenges": [dict(a) for a in content.CHALLENGES],
        "performances": [dict(a) for a in content.PERFORMANCES],
    }


def raw():
    """The editable content as a plain dict (saved version, else defaults)."""
    row = db.query("SELECT value FROM mixer_settings WHERE key = ?", (SETTINGS_KEY,), one=True)
    if row:
        try:
            return {**defaults(), **json.loads(row["value"])}
        except ValueError:
            pass
    return defaults()


def build(data):
    """Turn the editable dict into what the app uses."""
    bingo = [{"id": f"b{i}", "title": t, "points": data["square_points"],
              "proof": "name", "detail": "Who is it?"}
             for i, t in enumerate(data["bingo_traits"])]
    bingo.insert(12, {"id": "free", "title": data["free_square"], "points": 0,
                      "proof": "none", "detail": ""})
    activities = {a["id"]: {**a, "kind": kind}
                  for kind, items in (("bingo", bingo), ("challenge", data["challenges"]),
                                      ("perform", data["performances"]))
                  for a in items if a["proof"] != "none"}
    return SimpleNamespace(
        EVENT_NAME=data["event_name"], BINGO=bingo, BINGO_LINE_BONUS=data["line_bonus"],
        CHALLENGES=data["challenges"], PERFORMANCES=data["performances"], ACTIVITIES=activities)


def current():
    return build(raw())


def _text(value, limit, what):
    text = " ".join(str(value or "").split())
    if not text:
        raise ValueError(f"{what} can't be empty.")
    if len(text) > limit:
        raise ValueError(f"{what} is too long (max {limit} characters).")
    return text


def _points(value, what):
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a whole number.")
    if not 0 <= n <= 100:
        raise ValueError(f"{what} must be between 0 and 100.")
    return n


def _activities(items, prefix, label):
    out, seen = [], set()
    for i, a in enumerate(items or []):
        what = f"{label} #{i + 1}"
        aid = str(a.get("id") or "")
        # Keep existing ids so submissions stay attached; mint one for new rows.
        if not aid.startswith(prefix) or aid in seen or len(aid) > 40:
            aid = f"{prefix}{uuid.uuid4().hex[:8]}"
        seen.add(aid)
        proof = a.get("proof")
        if proof not in PROOFS:
            raise ValueError(f"{what}: pick what proof it needs.")
        out.append({"id": aid, "title": _text(a.get("title"), 100, f"{what} title"),
                    "detail": " ".join(str(a.get("detail") or "").split())[:200],
                    "points": _points(a.get("points"), f"{what} points"), "proof": proof})
    return out


def save(data):
    """Validate an edited dict from the admin editor and store it.
    Raises ValueError with a message for the admin if something's off."""
    traits = data.get("bingo_traits") or []
    if len(traits) != 24:
        raise ValueError("Bingo needs exactly 24 squares (plus the free one).")
    clean = {
        "event_name": _text(data.get("event_name"), 60, "Event name"),
        "square_points": _points(data.get("square_points"), "Points per square"),
        "line_bonus": _points(data.get("line_bonus"), "Bingo line bonus"),
        "free_square": _text(data.get("free_square"), 60, "Free square"),
        "bingo_traits": [_text(t, 80, f"Bingo square {i + 1}") for i, t in enumerate(traits)],
        "challenges": _activities(data.get("challenges"), "c-", "Challenge"),
        "performances": _activities(data.get("performances"), "p-", "Performance"),
    }
    value = json.dumps(clean, ensure_ascii=False)
    if db.query("SELECT 1 FROM mixer_settings WHERE key = ?", (SETTINGS_KEY,), one=True):
        db.query("UPDATE mixer_settings SET value = ? WHERE key = ?", (value, SETTINGS_KEY))
    else:
        db.query("INSERT INTO mixer_settings (key, value) VALUES (?, ?)", (SETTINGS_KEY, value))


def reset():
    db.query("DELETE FROM mixer_settings WHERE key = ?", (SETTINGS_KEY,))
