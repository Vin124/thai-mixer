"""
sets.py — packs people can start a game from: the built-in ones in
presets.py, plus custom sets users make. A custom set is private to its owner
unless they switch on "public", which lists it for everyone.

Every read and write here takes the acting user's id and enforces who may
see or change what; views never check ownership themselves.
"""

import json
import uuid

import db
import game
import presets


def _meta(meta):
    """Validated title / emoji / description for a custom set."""
    title = " ".join(str(meta.get("title") or "").split())
    if not title:
        raise ValueError("Give your set a name.")
    if len(title) > 40:
        raise ValueError("Set name is too long (max 40 characters).")
    emoji = "".join(str(meta.get("emoji") or "").split())[:8] or "🎲"
    description = " ".join(str(meta.get("description") or "").split())[:140]
    return title, emoji, description


def _card(row, user_id):
    return {"id": row["id"], "title": row["title"], "emoji": row["emoji"],
            "description": row["description"], "builtin": False,
            "mine": row["owner_id"] == user_id, "public": bool(row["public"]),
            "owner": row.get("owner_name") or ""}


def builtin_cards():
    return [{"id": p["id"], "title": p["title"], "emoji": p["emoji"],
             "description": p["description"], "builtin": True, "mine": False,
             "public": True, "owner": ""} for p in presets.PACKS]


def library(user_id):
    """Everything this user can start a game from: built-ins, their own sets,
    then other people's public sets."""
    rows = db.query("""
        SELECT s.id, s.owner_id, s.title, s.emoji, s.description, s.public, u.name AS owner_name
        FROM mixer_sets s LEFT JOIN mixer_users u ON u.id = s.owner_id
        WHERE s.owner_id = ? OR s.public = 1
        ORDER BY CASE WHEN s.owner_id = ? THEN 0 ELSE 1 END, s.updated_at DESC""",
                    (user_id, user_id))
    return builtin_cards() + [_card(r, user_id) for r in rows]


def load(set_id, user_id):
    """(title, pack dict) for a set this user may use, else None."""
    preset = presets.get(set_id)
    if preset:
        return preset["title"], json.loads(json.dumps(preset["pack"]))  # a copy
    row = db.query("SELECT * FROM mixer_sets WHERE id = ? AND (owner_id = ? OR public = 1)",
                   (set_id, user_id), one=True)
    if row:
        return row["title"], json.loads(row["data"])
    return None


def get_own(set_id, user_id):
    """A custom set row (with its pack under "pack") if this user owns it, else None."""
    row = db.query("SELECT * FROM mixer_sets WHERE id = ? AND owner_id = ?",
                   (set_id, user_id), one=True)
    if row:
        row["pack"] = json.loads(row["data"])
        row["public"] = bool(row["public"])
    return row


def create(user_id, meta, pack, now):
    """Validate and store a new set. Returns its id. Raises ValueError."""
    title, emoji, description = _meta(meta)
    data = json.dumps(game.clean(pack), ensure_ascii=False)
    sid = str(uuid.uuid4())
    db.query("""INSERT INTO mixer_sets (id, owner_id, title, emoji, description, data, public,
                                        created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
             (sid, user_id, title, emoji, description, data,
              1 if meta.get("public") else 0, now, now))
    return sid


def update(set_id, user_id, meta, pack, now):
    """Save edits to a set this user owns. False if it isn't theirs.
    Raises ValueError for bad input."""
    if not get_own(set_id, user_id):
        return False
    title, emoji, description = _meta(meta)
    data = json.dumps(game.clean(pack), ensure_ascii=False)
    db.query("""UPDATE mixer_sets SET title = ?, emoji = ?, description = ?, data = ?, public = ?,
                                     updated_at = ?
                WHERE id = ? AND owner_id = ?""",
             (title, emoji, description, data, 1 if meta.get("public") else 0, now,
              set_id, user_id))
    return True


def delete(set_id, user_id):
    """Delete a set this user owns. Games already made from it keep their copy."""
    db.query("DELETE FROM mixer_sets WHERE id = ? AND owner_id = ?", (set_id, user_id))
