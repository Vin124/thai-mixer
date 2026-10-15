"""
game.py — games and their activities. A game is one party: it gets a join
code, a host, and a copy of the pack (bingo + challenges + performances) it
was created from, which the host can edit at /g/<code>/admin/content without
touching the pack itself.

A "pack" is the editable dict: event_name, square_points, line_bonus,
free_square, bingo_traits (24), challenges, performances, roles.
"""

import json
import re
import secrets
import uuid
from types import SimpleNamespace

import content
import db

PROOFS = ("name", "photo", "video", "either")
# The game made from the original single-event data (Thai Club). Its players
# and submissions were assigned to it by db.init_db.
LEGACY_ID = "thai-club"
LEGACY_CODE = "THAI"
# No I/O/0/1: codes get read aloud and typed off a projector.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ"
CODE_RE = re.compile(r"[A-Z0-9]{4,8}")


def legacy_pack():
    """The original event's content: what was saved from the old /admin
    editor (mixer_settings), else content.py."""
    data = {
        "event_name": content.EVENT_NAME,
        "square_points": content.BINGO_SQUARE_POINTS,
        "line_bonus": content.BINGO_LINE_BONUS,
        "free_square": content.FREE_SQUARE,
        "bingo_traits": list(content.BINGO_TRAITS),
        "challenges": [dict(a) for a in content.CHALLENGES],
        "performances": [dict(a) for a in content.PERFORMANCES],
        "roles": [{"key": "phi", "label": "พี่", "hint": "upperclassman"},
                  {"key": "nong", "label": "น้อง", "hint": "new member"}],
    }
    row = db.query("SELECT value FROM mixer_settings WHERE key = 'content'", one=True)
    if row:
        try:
            data.update(json.loads(row["value"]))
        except ValueError:
            pass
    return data


def build(data):
    """Turn a pack dict into what the app uses."""
    bingo = [{"id": f"b{i}", "title": t, "points": data["square_points"],
              "proof": "name", "detail": "Who is it?"}
             for i, t in enumerate(data["bingo_traits"])]
    bingo.insert(12, {"id": "free", "title": data["free_square"], "points": 0,
                      "proof": "none", "detail": ""})
    activities = {a["id"]: {**a, "kind": kind}
                  for kind, items in (("bingo", bingo), ("challenge", data["challenges"]),
                                      ("perform", data["performances"]))
                  for a in items if a["proof"] != "none"}
    roles = data.get("roles") or []
    return SimpleNamespace(
        EVENT_NAME=data["event_name"], BINGO=bingo, BINGO_LINE_BONUS=data["line_bonus"],
        CHALLENGES=data["challenges"], PERFORMANCES=data["performances"], ACTIVITIES=activities,
        ROLES={r["key"]: r["label"] for r in roles}, ROLE_HINTS={r["key"]: r["hint"] for r in roles})


# ---------- validation ----------

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


def _roles(items):
    out, seen = [], set()
    if len(items or []) > 4:
        raise ValueError("At most 4 roles.")
    for i, r in enumerate(items or []):
        label = _text(r.get("label"), 20, f"Role #{i + 1}")
        key = str(r.get("key") or "")
        if not re.fullmatch(r"[a-z]{1,12}", key) or key in seen:
            key = f"r{uuid.uuid4().hex[:6]}".translate(str.maketrans("0123456789", "ghijklmnop"))
        seen.add(key)
        out.append({"key": key, "label": label,
                    "hint": " ".join(str(r.get("hint") or "").split())[:40]})
    return out


def clean(data):
    """A validated copy of an edited pack. Raises ValueError with a message
    for the person editing if something's off."""
    if not isinstance(data, dict):
        raise ValueError("Couldn't read the form — try again.")
    traits = data.get("bingo_traits") or []
    if not isinstance(traits, list) or len(traits) != 24:
        raise ValueError("Bingo needs exactly 24 squares (plus the free one).")
    return {
        "event_name": _text(data.get("event_name"), 60, "Event name"),
        "square_points": _points(data.get("square_points"), "Points per square"),
        "line_bonus": _points(data.get("line_bonus"), "Bingo line bonus"),
        "free_square": _text(data.get("free_square"), 60, "Free square"),
        "bingo_traits": [_text(t, 80, f"Bingo square {i + 1}") for i, t in enumerate(traits)],
        "challenges": _activities(data.get("challenges"), "c-", "Challenge"),
        "performances": _activities(data.get("performances"), "p-", "Performance"),
        "roles": _roles(data.get("roles")),
    }


# ---------- game rows ----------

def _row(game):
    if game:
        game["pack"] = json.loads(game["data"])
    return game


def by_code(code):
    code = (code or "").strip().upper()
    if not CODE_RE.fullmatch(code):
        return None
    return _row(db.query("SELECT * FROM mixer_games WHERE code = ?", (code,), one=True))


def create(title, host_id, pack, pack_id, now):
    """A new game from a (validated) pack. Returns the game row."""
    for _ in range(20):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        if not db.query("SELECT 1 FROM mixer_games WHERE code = ?", (code,), one=True):
            break
    else:
        raise RuntimeError("Couldn't find a free game code.")
    gid = str(uuid.uuid4())
    db.query("""INSERT INTO mixer_games (id, code, title, host_id, pack_id, data, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
             (gid, code, title, host_id, pack_id, json.dumps(clean(pack), ensure_ascii=False), now))
    return by_code(code)


def save_pack(game_id, data):
    """Validate and store the host's edits to this game's activities."""
    db.query("UPDATE mixer_games SET data = ? WHERE id = ?",
             (json.dumps(clean(data), ensure_ascii=False), game_id))


def for_user(user_id):
    """Games this user hosts or plays in, newest first."""
    return db.query("""
        SELECT gm.code, gm.title, gm.host_id = ? AS is_host,
               (SELECT COUNT(*) FROM mixer_players p2 WHERE p2.game_id = gm.id) AS players
        FROM mixer_games gm
        WHERE gm.host_id = ? OR EXISTS (SELECT 1 FROM mixer_players p
                                        WHERE p.game_id = gm.id AND p.user_id = ?)
        ORDER BY gm.created_at DESC""", (user_id, user_id, user_id))


def ensure_legacy(now):
    """Create the Thai Club game for the original event's data, once."""
    if not db.query("SELECT 1 FROM mixer_games WHERE id = ?", (LEGACY_ID,), one=True):
        pack = legacy_pack()
        db.query("""INSERT INTO mixer_games (id, code, title, host_id, pack_id, data, created_at)
                    VALUES (?, ?, ?, NULL, 'thai-club', ?, ?)""",
                 (LEGACY_ID, LEGACY_CODE, pack["event_name"],
                  json.dumps(pack, ensure_ascii=False), now))
