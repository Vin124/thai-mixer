"""
sets_views.py — pages for making your own sets (custom packs).
Placeholder until the set builder lands: lists the library only.
"""

from flask import render_template

from app import app, current_user, login_redirect
import sets


@app.route("/sets")
def sets_index():
    user = current_user()
    if not user:
        return login_redirect()
    return render_template("sets_index.html", library=sets.library(user["id"]))
