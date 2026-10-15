"""
Smoke test for the custom set builder (/sets) and the shared pack editor,
against a throwaway SQLite file with Google sign-in faked. Run from the repo
root:

    .venv/Scripts/python tests/sets_smoke.py      (Windows)
    .venv/bin/python tests/sets_smoke.py          (macOS / Linux)

Prints one line per check and exits non-zero on the first failure.
"""

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DB_FILE = os.path.join(tempfile.mkdtemp(), "sets_smoke.db")
os.environ.update(DATABASE_URL="", SUPABASE_SERVICE_KEY="", SUPABASE_URL="https://proj.supabase.co",
                  SUPABASE_ANON_KEY="anon", ADMIN_EMAILS="boss@example.com", FLASK_SECRET_KEY="x")

import db  # noqa: E402
db.SQLITE_PATH = DB_FILE
import auth  # noqa: E402

USERS = {
    "a": {"id": "ua", "email": "a@example.com", "name": "Ann Maker"},
    "b": {"id": "ub", "email": "b@example.com", "name": "Bo Other"},
}
auth.exchange = lambda code, verifier: dict(USERS[code])

import app as A  # noqa: E402
import game  # noqa: E402
import presets  # noqa: E402
import sets  # noqa: E402

n = 0


def check(name, ok, detail=""):
    global n
    n += 1
    print(f"{'ok ' if ok else 'FAIL'} {n:2} {name}" + (f"  [{detail}]" if not ok and detail else ""))
    if not ok:
        sys.exit(1)


def client(who=None):
    t = A.app.test_client()
    if who:
        t.get("/login/google?next=/")
        r = t.get(f"/auth/callback?code={who}")
        assert r.status_code == 302, r.status_code
    return t


def mine(uid):
    return [s for s in sets.library(uid) if s["mine"]]


def form(pack, title="Ann's set", public=False, **extra):
    data = {"title": title, "emoji": "🦄", "description": "For testing", "data": json.dumps(pack)}
    if public:
        data["public"] = "1"
    data.update(extra)
    return data


base = json.loads(json.dumps(presets.get("entrepreneurs")["pack"]))

# 1
anon = client()
check("signed-out /sets and /sets/new ask for sign-in",
      "/login/google" in anon.get("/sets").location and "/login/google" in anon.get("/sets/new").location)

a, b = client("a"), client("b")
# 2
page = a.get("/sets")
check("/sets renders with the built-in packs", page.status_code == 200
      and all(p["title"].encode() in page.data for p in presets.PACKS) and b"No sets yet" in page.data)
# 3
page = a.get("/sets/new?from=entrepreneurs")
check("copying a built-in prefills its name and traits", page.status_code == 200
      and b'value="Copy of Entrepreneurs"' in page.data and b"Has pivoted a company" in page.data)
check("an unknown ?from= falls back to the first built-in pack",
      presets.PACKS[0]["pack"]["bingo_traits"][0].encode() in a.get("/sets/new?from=nope").data)

# 4
r = a.post("/sets/new", data=form(base))
sid = r.location.split("/sets/")[1].split("/")[0] if r.status_code == 302 else ""
row = sets.get_own(sid, "ua")
check("creating a set makes a private one owned by Ann and lands on its edit page",
      r.status_code == 302 and f"/sets/{sid}/edit" in r.location and row and not row["public"]
      and row["title"] == "Ann's set", r.status_code)
check("its edit page renders with the saved banner", b"Saved" in a.get(r.location).data)

# 5
before = len(mine("ua"))
r = a.post("/sets/new", data=form(dict(base, bingo_traits=base["bingo_traits"][:23])))
check("23 squares is refused and nothing is created",
      r.status_code == 400 and b"exactly 24 squares" in r.data and len(mine("ua")) == before)
check("the refused form keeps the user's edits", b"Ann&#39;s set" in r.data and b"Has pivoted a company" in r.data)

# 6
r = a.post("/sets/new", data={"title": "No data"})
check("a post without the pack JSON is refused, not a 500",
      r.status_code == 400 and "Couldn't read the form".encode() in r.data.replace(b"&#39;", b"'")
      and len(mine("ua")) == before)

# 7
saved = sets.get_own(sid, "ua")["pack"]
old_ids = [c["id"] for c in saved["challenges"]]
edit = json.loads(json.dumps(saved))
edit["challenges"][0]["title"] = "Renamed challenge"
edit["challenges"].append({"id": "", "title": "Brand new", "detail": "", "points": 2, "proof": "photo"})
r = a.post(f"/sets/{sid}/edit", data=form(edit))
new_ids = [c["id"] for c in sets.get_own(sid, "ua")["pack"]["challenges"]]
check("editing keeps existing challenge ids and mints one only for the new row",
      r.status_code == 302 and new_ids[:-1] == old_ids and new_ids[-1].startswith("c-")
      and new_ids[-1] not in old_ids, new_ids)

# 8
two = dict(edit, challenges=sets.get_own(sid, "ua")["pack"]["challenges"],
           roles=[{"key": "", "label": "Maker", "hint": "makes things"},
                  {"key": "", "label": "Taker", "hint": ""}])
a.post(f"/sets/{sid}/edit", data=form(two))
roles1 = sets.get_own(sid, "ua")["pack"]["roles"]
a.post(f"/sets/{sid}/edit", data=form(dict(two, roles=roles1)))
roles2 = sets.get_own(sid, "ua")["pack"]["roles"]
page = a.get(f"/sets/{sid}/edit").data
check("2 roles round-trip with stable keys",
      [r["label"] for r in roles2] == ["Maker", "Taker"] and roles1 == roles2
      and all(f'data-key="{r["key"]}"'.encode() in page for r in roles2), roles2)
a.post(f"/sets/{sid}/edit", data=form(dict(two, roles=[])))
check("saving 0 roles stores []", sets.get_own(sid, "ua")["pack"]["roles"] == [])

# 9
snapshot = sets.get_own(sid, "ua")
check("Bo can't open Ann's set editor", b.get(f"/sets/{sid}/edit").status_code == 404)
r = b.post(f"/sets/{sid}/edit", data=form(base, title="Hacked"))
check("Bo can't save over Ann's set", r.status_code == 404 and sets.get_own(sid, "ua") == snapshot)
b.post(f"/sets/{sid}/delete")
check("Bo can't delete Ann's set", sets.get_own(sid, "ua") is not None)

# 10 + 12
xss = "<script>alert(1)</script>"
check("a private set isn't on Bo's /sets page", sid.encode() not in b.get("/sets").data)
a.post(f"/sets/{sid}/edit", data=form(sets.get_own(sid, "ua")["pack"], title=xss, public=True))
page = b.get("/sets").data
check("once public, it's on Bo's /sets page with Copy & edit", f"from={sid}".encode() in page)
check("its title is escaped for Bo", b"&lt;script&gt;alert(1)&lt;/script&gt;" in page and xss.encode() not in page)
copy = b.get(f"/sets/new?from={sid}")
check("Bo's Copy & edit prefills Ann's set", copy.status_code == 200
      and b"Copy of &lt;script&gt;" in copy.data and b"Renamed challenge" in copy.data)

# 11
a.post(f"/sets/{sid}/edit", data=form(dict(sets.get_own(sid, "ua")["pack"],
                                           roles=[{"key": "", "label": "Maker", "hint": ""}])))
r = a.post("/new", data={"pack": sid, "title": "Set night"})
check("Ann's set starts a game", r.status_code == 302 and "/admin" in r.location, r.status_code)
code = r.location.split("/g/")[1].split("/")[0]
g1 = game.by_code(code)
check("the game copies the set's pack", g1["pack_id"] == sid
      and g1["pack"]["challenges"][0]["title"] == "Renamed challenge")

# 13
page = a.get(f"/g/{code}/admin/content")
check("the per-game editor renders with a roles section",
      page.status_code == 200 and b'data-list="roles"' in page.data and b"Maker" in page.data)
gp = json.loads(json.dumps(g1["pack"]))
ids_before = [c["id"] for c in gp["challenges"]]
gp["challenges"][1]["title"] = "Changed in game"
gp["roles"].append({"key": "", "label": "Guest", "hint": "just here"})
r = a.post(f"/g/{code}/admin/content", data={"data": json.dumps(gp)})
after = game.by_code(code)["pack"]
check("a per-game edit keeps challenge ids and saves the new role",
      r.status_code == 200 and [c["id"] for c in after["challenges"]] == ids_before
      and after["challenges"][1]["title"] == "Changed in game"
      and [x["label"] for x in after["roles"]] == ["Maker", "Guest"]
      and after["roles"][0]["key"] == g1["pack"]["roles"][0]["key"], after["roles"])
check("the per-game edit didn't touch the set",
      sets.get_own(sid, "ua")["pack"]["challenges"][1]["title"] != "Changed in game")

# 14
b.post(f"/g/{code}", data={"name": "Bo", "role": after["roles"][0]["key"]})
a.post(f"/sets/{sid}/delete")
check("the owner can delete the set", sets.get_own(sid, "ua") is None and sid.encode() not in a.get("/sets").data)
check("its game keeps working for a joined player", b.get(f"/g/{code}/play").status_code == 200)
before = game.by_code(code)["pack"]
r = a.post(f"/g/{code}/admin/content/reset")
check("reset after the set is deleted says so and changes nothing",
      r.status_code == 409 and b"nothing to reset to" in r.data and game.by_code(code)["pack"] == before)

print(f"\nall {n} checks passed")
