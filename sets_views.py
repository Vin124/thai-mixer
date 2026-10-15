"""
sets_views.py — pages for making your own sets (custom packs): list, create,
edit, delete. Who may see or change a set is decided in sets.py; these views
only pass the signed-in user's id along.
"""

import json

from flask import abort, redirect, render_template, request, url_for

from app import app, current_user, login_redirect, now
import presets
import sets

BAD_FORM = "Couldn't read the form — try again."


def _submitted():
    """(meta, pack) from the editor form. pack is None if the hidden JSON
    field is missing or garbled (e.g. the page's script didn't run)."""
    meta = {k: request.form.get(k, "") for k in ("title", "emoji", "description")}
    meta["public"] = bool(request.form.get("public"))
    try:
        pack = json.loads(request.form.get("data", ""))
    except ValueError:
        pack = None
    return meta, (pack if isinstance(pack, dict) else None)


def _starter(user_id):
    """The pack a new set starts from when there's nothing to copy: a full
    card is easier to rewrite than 24 empty squares."""
    return sets.load(presets.PACKS[0]["id"], user_id)[1]


def _editor(set_id, meta, pack, error=None, saved=False, note=None):
    return render_template("set_edit.html", set_id=set_id, meta=meta, data=pack,
                           error=error, saved=saved, note=note), (400 if error else 200)


@app.route("/sets")
def sets_index():
    user = current_user()
    if not user:
        return login_redirect()
    library = sets.library(user["id"])
    return render_template("sets_index.html",
                           mine=[s for s in library if s["mine"]],
                           others=[s for s in library if not s["mine"]])


@app.route("/sets/new", methods=["GET", "POST"])
def sets_new():
    user = current_user()
    if not user:
        return login_redirect()
    if request.method == "POST":
        meta, pack = _submitted()
        if pack is None:
            return _editor(None, meta, _starter(user["id"]), error=BAD_FORM)
        try:
            set_id = sets.create(user["id"], meta, pack, now())
        except ValueError as e:
            return _editor(None, meta, {**_starter(user["id"]), **pack}, error=str(e))
        return redirect(url_for("sets_edit", set_id=set_id, saved=1))

    src = request.args.get("from")
    found = sets.load(src, user["id"]) if src else None
    if found:
        card = next((c for c in sets.library(user["id"]) if c["id"] == src), {})
        meta = {"title": f"Copy of {found[0]}"[:40], "emoji": card.get("emoji", ""),
                "description": card.get("description", ""), "public": False}
        return _editor(None, meta, found[1],
                       note=f"A copy of “{found[0]}” — change anything, it won't touch the original.")
    meta = {"title": "", "emoji": "", "description": "", "public": False}
    return _editor(None, meta, _starter(user["id"]),
                   note=f"We've filled this in with the {presets.PACKS[0]['title']} pack so you "
                        "can see how it works — replace the squares and activities with your own.")


@app.route("/sets/<set_id>/edit", methods=["GET", "POST"])
def sets_edit(set_id):
    user = current_user()
    if not user:
        return login_redirect()
    row = sets.get_own(set_id, user["id"])
    if not row:
        abort(404)
    if request.method == "POST":
        meta, pack = _submitted()
        if pack is None:
            return _editor(set_id, meta, row["pack"], error=BAD_FORM)
        try:
            if not sets.update(set_id, user["id"], meta, pack, now()):
                abort(404)
        except ValueError as e:
            return _editor(set_id, meta, {**row["pack"], **pack}, error=str(e))  # keep their edits
        return redirect(url_for("sets_edit", set_id=set_id, saved=1))
    meta = {k: row[k] for k in ("title", "emoji", "description", "public")}
    return _editor(set_id, meta, row["pack"], saved=bool(request.args.get("saved")))


@app.post("/sets/<set_id>/delete")
def sets_delete(set_id):
    """Games already made from the set keep their own copy of it."""
    user = current_user()
    if not user:
        return login_redirect()
    sets.delete(set_id, user["id"])
    return redirect(url_for("sets_index"))
