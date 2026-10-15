"""
Smoke test for the whole app against a throwaway SQLite file, with Google
sign-in faked. Run from the repo root:

    .venv/Scripts/python tests/smoke.py      (Windows)
    .venv/bin/python tests/smoke.py          (macOS / Linux)

Prints one line per check and exits non-zero on the first failure.
"""

import os
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DB_FILE = os.path.join(tempfile.mkdtemp(), "smoke.db")
os.environ.update(DATABASE_URL="", SUPABASE_SERVICE_KEY="", SUPABASE_URL="https://proj.supabase.co",
                  SUPABASE_ANON_KEY="anon", ADMIN_EMAILS="boss@example.com", FLASK_SECRET_KEY="x")

# The schema from before games existed, with one legacy player + photo + vote.
c = sqlite3.connect(DB_FILE)
c.executescript("""
CREATE TABLE mixer_players (id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE,
                            role TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE mixer_submissions (id TEXT PRIMARY KEY, player_id TEXT NOT NULL REFERENCES mixer_players(id) ON DELETE CASCADE,
  activity_id TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', media_key TEXT, media_type TEXT, status TEXT NOT NULL,
  created_at TEXT NOT NULL, reviewed_at TEXT, UNIQUE (player_id, activity_id));
CREATE TABLE mixer_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO mixer_players VALUES ('old1', 'Old Timer', 'old timer', 'phi', '2026-10-01');
INSERT INTO mixer_players VALUES ('old2', 'Second', 'second', 'nong', '2026-10-01');
INSERT INTO mixer_submissions VALUES ('olds', 'old1', 'c-wai-selfie', '', 'k.jpg', 'image', 'approved', 't', '2026-10-01');
""")
c.commit()
c.close()

import db  # noqa: E402
db.SQLITE_PATH = DB_FILE
import auth  # noqa: E402

USERS = {
    "a": {"id": "ua", "email": "a@example.com", "name": "Ann Host"},
    "b": {"id": "ub", "email": "b@example.com", "name": "Bo Guest"},
    "c": {"id": "uc", "email": "c@example.com", "name": "Cy Other"},
    "boss": {"id": "uboss", "email": "boss@example.com", "name": "Boss"},
}
auth.exchange = lambda code, verifier: dict(USERS[code])

import app as A  # noqa: E402
import game  # noqa: E402
import sets  # noqa: E402

n = 0


def check(name, ok, detail=""):
    global n
    n += 1
    print(f"{'ok ' if ok else 'FAIL'} {n:2} {name}" + (f"  [{detail}]" if not ok and detail else ""))
    if not ok:
        sys.exit(1)


def client(who=None, next_path="/"):
    t = A.app.test_client()
    if who:
        t.get(f"/login/google?next={next_path}")
        r = t.get(f"/auth/callback?code={who}")
        assert r.status_code == 302, r.status_code
    return t


# --- legacy data ---
legacy = db.query("SELECT id, game_id, user_id FROM mixer_players ORDER BY id")
check("legacy players moved into the Thai Club game, untouched otherwise",
      [(p["id"], p["game_id"], p["user_id"]) for p in legacy] ==
      [("old1", "thai-club", None), ("old2", "thai-club", None)], legacy)
check("legacy game exists with code THAI", game.by_code("thai")["id"] == game.LEGACY_ID)
lg = A.app.test_client()
with lg.session_transaction() as s:
    s["player_id"] = "old1"
check("legacy name-only session still plays", lg.get("/g/THAI/play").status_code == 200)
check("legacy /api/me scores the old photo", lg.get("/g/THAI/api/me").json["points"] == 3)
check("old /play link redirects into the Thai Club game",
      A.app.test_client().get("/play").location.endswith("/g/THAI/play"))

# --- homepage, sign-in ---
anon = A.app.test_client()
check("homepage renders signed out", anon.get("/").status_code == 200)
check("/new asks for sign-in", "/login/google" in anon.get("/new").location)
check("callback without a started sign-in is refused", anon.get("/auth/callback?code=a").status_code == 400)
evil = A.app.test_client()
evil.get("/login/google?next=//evil.example")
check("sign-in never redirects off-site", evil.get("/auth/callback?code=a").location == "/")

a = client("a")
check("signed-in homepage renders", a.get("/").status_code == 200 and b"Ann Host" in a.get("/").data)
check("new-game page lists the packs", b"Entrepreneurs" in a.get("/new").data)
r = a.post("/new", data={"pack": "entrepreneurs", "title": "Founders night"})
check("creating a game lands on its host page", r.status_code == 302 and "/admin" in r.location, r.location)
code1 = r.location.split("/g/")[1].split("/")[0]
g1 = game.by_code(code1)
check("game uses the chosen pack and title",
      g1["title"] == "Founders night" and g1["pack"]["roles"] and g1["host_id"] == "ua")
check("host page renders with the code", code1.encode() in a.get(f"/g/{code1}/admin").data)
check("nonexistent pack is refused", a.post("/new", data={"pack": "nope"}).status_code == 400)

# --- joining ---
check("join by code is case-insensitive", A.app.test_client().get(f"/join?code={code1.lower()}").location.endswith(f"/g/{code1}"))
check("unknown code shows an error", A.app.test_client().get("/join?code=ZZZZZZ").status_code == 404)
check("signed-out join page offers Google", b"/login/google" in anon.get(f"/g/{code1}").data)
b = client("b", f"/g/{code1}")
page = b.get(f"/g/{code1}")
check("join form shows the pack's roles and prefilled name", b"founder" in page.data and b'value="Bo Guest"' in page.data)
check("role is required when the pack has roles",
      b.post(f"/g/{code1}", data={"name": "Bo"}).status_code == 400)
r = b.post(f"/g/{code1}", data={"name": "Bo", "role": "founder"})
check("joining goes to play", r.location.endswith(f"/g/{code1}/play"))
check("play page renders with this game's API base", f'"/g/{code1}"'.encode() in b.get(f"/g/{code1}/play").data)
check("rejoining skips the form", b.get(f"/g/{code1}").location.endswith("/play"))
check("joined game shows on the homepage", code1.encode() in b.get("/").data)
dup = client("c")
check("names are unique within a game",
      dup.post(f"/g/{code1}", data={"name": "bo", "role": "curious"}).status_code == 400)

# --- host-only ---
check("a guest can't open host controls", b.get(f"/g/{code1}/admin").status_code == 403)
check("a guest can't reset a game", b.post(f"/g/{code1}/admin/reset", data={"what": "everything", "confirm": "RESET"}).status_code == 403)
check("Ann isn't host of the Thai Club game", a.get("/g/THAI/admin").status_code == 403)
boss = client("boss")
check("ADMIN_EMAILS can run the Thai Club game", boss.get("/g/THAI/admin").status_code == 200)
check("ADMIN_EMAILS can run anyone's game", boss.get(f"/g/{code1}/admin").status_code == 200)

# --- isolation between games ---
c2 = client("c")
code2 = c2.post("/new", data={"pack": "house-party"}).location.split("/g/")[1].split("/")[0]
check("a second game gets its own code", code2 != code1)
c2.post(f"/g/{code2}", data={"name": "Bo"})  # same name, different game
check("the same name can be used in another game", c2.get(f"/g/{code2}").location.endswith("/play"))
check("a player's photo from game 1 can't be voted on from game 2",
      c2.post(f"/g/{code2}/api/vote", data={"submission_id": "olds", "value": 1}).status_code == 404)
c2.post(f"/g/{code2}/admin/review", data={"id": "olds", "action": "reject"})
check("game 2's host can't reject game 1's (legacy) photo",
      db.query("SELECT status FROM mixer_submissions WHERE id = 'olds'", one=True)["status"] == "approved")
c2.post(f"/g/{code2}/admin/player/old1/delete")
check("game 2's host can't delete game 1's player",
      db.query("SELECT 1 FROM mixer_players WHERE id = 'old1'", one=True) is not None)
check("leaderboards are per game",
      [x["name"] for x in c2.get(f"/g/{code2}/api/screen").json["leaderboard"]] == ["Bo"])
c2.post(f"/g/{code2}/admin/reset", data={"what": "everything", "confirm": "RESET"})
check("resetting game 2 leaves the others alone",
      len(db.query("SELECT 1 FROM mixer_players WHERE game_id = ?", (g1["id"],))) == 1
      and len(db.query("SELECT 1 FROM mixer_players WHERE game_id = 'thai-club'")) == 2)

# --- playing + voting inside a game ---
sub_ok = b.post(f"/g/{code1}/api/submit", data={"activity_id": "b0", "note": "Someone"})
check("submitting a bingo square works", sub_ok.status_code == 200 and b.get(f"/g/{code1}/api/me").json["points"] >= 1)
check("photos feed works", b.get(f"/g/{code1}/api/photos?order=top").status_code == 200)

# --- host edits this game's activities ---
pack = dict(g1["pack"])
pack["free_square"] = "Changed"
r = a.post(f"/g/{code1}/admin/content", data={"data": __import__("json").dumps(pack)})
check("host can edit this game's activities", r.status_code == 200 and game.by_code(code1)["pack"]["free_square"] == "Changed")
no_roles = {k: v for k, v in pack.items() if k != "roles"}
a.post(f"/g/{code1}/admin/content", data={"data": __import__("json").dumps(no_roles)})
check("an edit without a roles section keeps the roles", game.by_code(code1)["pack"]["roles"] == g1["pack"]["roles"])
bad = dict(pack, bingo_traits=pack["bingo_traits"][:23])
check("bad edits are refused", a.post(f"/g/{code1}/admin/content", data={"data": __import__("json").dumps(bad)}).status_code == 400)
check("guest can't edit activities", b.post(f"/g/{code1}/admin/content", data={"data": "{}"}).status_code == 403)
a.post(f"/g/{code1}/admin/content/reset")
check("reset brings back the pack's content", game.by_code(code1)["pack"]["free_square"] != "Changed")

# --- custom sets ---
base = game.clean(__import__("presets").get("house-party")["pack"])
sid = sets.create("ua", {"title": "Ann's set", "emoji": "🦄"}, base, A.now())
check("private set is usable by its owner", sets.load(sid, "ua") is not None)
check("private set is hidden from others", sets.load(sid, "ub") is None
      and sid not in [x["id"] for x in sets.library("ub")])
check("only the owner can edit", sets.update(sid, "ub", {"title": "Hacked"}, base, A.now()) is False)
sets.update(sid, "ua", {"title": "Ann's set", "public": True}, base, A.now())
check("public set is listed for everyone", sid in [x["id"] for x in sets.library("ub")])
sets.delete(sid, "ub")
check("only the owner can delete", sets.get_own(sid, "ua") is not None)
r = b.post("/new", data={"pack": sid})
check("a public set can start a game", r.status_code == 302)
check("sets page renders", a.get("/sets").status_code == 200)

# --- sign out ---
b.post("/logout")
check("signing out ends play access", b.get(f"/g/{code1}/play").location.endswith(f"/g/{code1}"))

print(f"\nall {n} checks passed")
