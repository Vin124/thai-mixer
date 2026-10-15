"""
app.py — the mixer web app. Guests scan the QR, type a name, and play:
bingo (find someone who…), team-up challenges and performances, with
photo/video proof. Admins approve media before it hits the projector.

Pages:
  /         join (or straight to /play if already joined)
  /play     the player's phone view (incl. photo voting + winner)
  /screen   projector: live photo/video feed + leaderboard
  /admin    review queue (Google sign-in, emails listed in ADMIN_EMAILS)
  /qr       printable QR code that points at this site
"""

import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
load_dotenv()

from flask import (Flask, abort, g, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)
from werkzeug.middleware.proxy_fix import ProxyFix

import auth
import game
import db
import storage

MAX_UPLOAD_MB = 50  # Supabase's free tier caps each file at 50 MB
MAX_VIDEO_SECONDS = 30


def _secret_key():
    """FLASK_SECRET_KEY if set, else a random key saved next to the app so
    logins survive restarts. Never a fixed default: anyone who knew it could
    forge an admin login."""
    if os.environ.get("FLASK_SECRET_KEY"):
        return os.environ["FLASK_SECRET_KEY"]
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".secret_key")
    try:
        with open(path) as f:
            return f.read().strip()
    except FileNotFoundError:
        key = secrets.token_hex(32)
        with open(path, "w") as f:
            f.write(key)
        return key


app = Flask(__name__)
# Hosts put a proxy in front of the app; this makes request.host_url (used
# for the QR code) the real public https address.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.secret_key = _secret_key()
app.config.update(
    MAX_CONTENT_LENGTH=MAX_UPLOAD_MB * 1024 * 1024,
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    # Only send the cookie when the session changes. Otherwise a player-page
    # poll that was in flight during an admin login answers with the old
    # cookie and logs the admin straight back out.
    SESSION_REFRESH_EACH_REQUEST=False,
    SESSION_COOKIE_SAMESITE="Lax",
    # https-only cookies once hosted; plain http is fine on your own computer.
    SESSION_COOKIE_SECURE=(os.environ.get("COOKIE_SECURE") or ("1" if db.USE_PG else "0")) == "1",
)

# Google accounts allowed into /admin, comma-separated.
ADMIN_EMAILS = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}

ROLES = {"phi": "พี่", "nong": "น้อง"}
ROLE_HINTS = {"phi": "upperclassman", "nong": "new member"}
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/heic", "image/heif"}
VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm"}
EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif",
              "image/heic": "heic", "image/heif": "heif", "video/mp4": "mp4",
              "video/quicktime": "mov", "video/webm": "webm"}

db.init_db()
storage.init_storage(MAX_UPLOAD_MB * 1024 * 1024, EXTENSIONS)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def current_player():
    pid = session.get("player_id")
    if not pid:
        return None
    return db.query("SELECT * FROM mixer_players WHERE id = ?", (pid,), one=True)


def is_admin():
    return session.get("admin") is True


def cfg():
    """The current activities (admin edits or content.py defaults), loaded
    once per request."""
    if "game" not in g:
        g.game = game.current()
    return g.game


# ---------- scoring ----------

BINGO_LINES = ([[r * 5 + c for c in range(5)] for r in range(5)] +
               [[r * 5 + c for r in range(5)] for c in range(5)] +
               [[i * 6 for i in range(5)], [(i + 1) * 4 for i in range(5)]])


def score(done_ids):
    """Points for a set of completed (non-rejected) activity ids."""
    points = sum(cfg().ACTIVITIES[a]["points"] for a in done_ids if a in cfg().ACTIVITIES)
    done_squares = {i for i, sq in enumerate(cfg().BINGO)
                    if sq["id"] == "free" or sq["id"] in done_ids}
    lines = sum(1 for line in BINGO_LINES if all(i in done_squares for i in line))
    return points + lines * cfg().BINGO_LINE_BONUS, lines


def leaderboard(limit=None):
    players = db.query("SELECT id, name, role FROM mixer_players")
    rows = db.query("SELECT player_id, activity_id FROM mixer_submissions WHERE status <> 'rejected'")
    done = {}
    for r in rows:
        done.setdefault(r["player_id"], set()).add(r["activity_id"])
    board = []
    for p in players:
        pts, lines = score(done.get(p["id"], set()))
        board.append({"name": p["name"], "role": ROLES.get(p["role"], ""),
                      "points": pts, "lines": lines, "id": p["id"]})
    board.sort(key=lambda b: (-b["points"], b["name"].lower()))
    return board[:limit] if limit else board


# ---------- player pages ----------

def render_join(error=None, status=200, name=None, role=None):
    """The join page: a Google button, or, once signed in for the first
    time, the name + พี่/น้อง form."""
    pending = session.get("google")
    if name is None and pending:
        name = pending["name"]
    return render_template("join.html", event=cfg().EVENT_NAME, roles=ROLES, hints=ROLE_HINTS,
                           error=error, pending=pending, sign_in=auth.ENABLED,
                           name=name, role=role), status


def admin_login_page(error=None, status=200):
    return render_template("admin_login.html", error=error,
                           configured=bool(ADMIN_EMAILS and auth.ENABLED)), status


@app.route("/")
def join_page():
    if current_player():
        return redirect(url_for("play"))
    return render_join()


@app.route("/login/google")
def login_google():
    """Start Google sign-in. ?for=admin signs in to /admin instead of the game."""
    target = "admin" if request.args.get("for") == "admin" else "play"
    if not auth.ENABLED:
        msg = "Google sign-in isn't set up on this server."
        return admin_login_page(msg, 503) if target == "admin" else render_join(msg, 503)
    verifier = auth.new_verifier()
    session["oauth"] = {"verifier": verifier, "for": target}
    return redirect(auth.authorize_url(url_for("auth_callback", _external=True), verifier))


@app.route("/auth/callback")
def auth_callback():
    """Google -> Supabase -> here with ?code=. Admins go to /admin, known
    players straight to /play, first-timers to the join form."""
    flow = session.pop("oauth", None)
    target = flow["for"] if flow else "play"

    def failed(msg):
        return admin_login_page(msg, 400) if target == "admin" else render_join(msg, 400)

    code = request.args.get("code")
    if not flow or not code:
        return failed(request.args.get("error_description") or "Sign-in didn't finish — try again.")
    try:
        user = auth.exchange(code, flow["verifier"])
    except auth.AuthError as e:
        return failed(str(e))

    if target == "admin":
        if user["email"] not in ADMIN_EMAILS:
            return failed(f"{user['email']} isn't on the admin list.")
        session["admin"] = True
        return redirect(url_for("admin"))

    session.permanent = True
    player = db.query("SELECT id FROM mixer_players WHERE auth_user_id = ?", (user["id"],), one=True)
    if player:
        session.pop("google", None)
        session["player_id"] = player["id"]
        return redirect(url_for("play"))
    session["google"] = {"id": user["id"], "name": user["name"]}
    return redirect(url_for("join_page"))


@app.post("/join")
def join():
    pending = session.get("google")
    if not pending:
        return redirect(url_for("join_page"))
    # Signed in twice in two tabs: the first one already made the player.
    player = db.query("SELECT id FROM mixer_players WHERE auth_user_id = ?", (pending["id"],), one=True)
    if player:
        session.pop("google")
        session["player_id"] = player["id"]
        return redirect(url_for("play"))
    name = " ".join(request.form.get("name", "").split())[:40]
    role = request.form.get("role", "")
    if not name:
        error = "Type your name so people can find you."
    elif role not in ROLES:
        error = "Pick one: พี่ or น้อง."
    elif db.query("SELECT 1 FROM mixer_players WHERE name_key = ?", (name.lower(),), one=True):
        error = f"Someone already joined as “{name}”. Add your last initial or nickname."
    else:
        error = None
    if error:
        return render_join(error, 400, name=name, role=role)

    pid = str(uuid.uuid4())
    db.query("""INSERT INTO mixer_players (id, name, name_key, role, created_at, auth_user_id)
                VALUES (?, ?, ?, ?, ?, ?)""",
             (pid, name, name.lower(), role, now(), pending["id"]))
    session.pop("google")
    session.permanent = True
    session["player_id"] = pid
    return redirect(url_for("play"))


@app.post("/leave")
def leave():
    session.pop("player_id", None)
    return redirect(url_for("join_page"))


@app.route("/play")
def play():
    player = current_player()
    if not player:
        return redirect(url_for("join_page"))
    return render_template(
        "play.html", event=cfg().EVENT_NAME, player=player,
        role_label=ROLES.get(player["role"], ""),
        game=game_payload())


def game_payload():
    """Activities as the phone page needs them (re-sent with every /api/me
    poll so admin edits show up without a reload)."""
    return {"event": cfg().EVENT_NAME, "bingo": cfg().BINGO, "challenges": cfg().CHALLENGES,
            "performances": cfg().PERFORMANCES, "lineBonus": cfg().BINGO_LINE_BONUS,
            "maxUploadMb": MAX_UPLOAD_MB, "maxVideoSeconds": MAX_VIDEO_SECONDS,
            "directUpload": storage.USE_SUPABASE}


@app.route("/api/me")
def api_me():
    player = current_player()
    if not player:
        return jsonify(error="not_joined"), 401
    subs = db.query("SELECT * FROM mixer_submissions WHERE player_id = ?", (player["id"],))
    pts, lines = score({s["activity_id"] for s in subs if s["status"] != "rejected"})
    board = leaderboard()
    rank = next((i + 1 for i, b in enumerate(board) if b["id"] == player["id"]), None)
    return jsonify(
        game=game_payload(), points=pts, lines=lines, rank=rank, players=len(board),
        submissions={s["activity_id"]: {"status": s["status"], "note": s["note"],
                                        "mediaUrl": storage.url(s["media_key"]),
                                        "mediaType": s["media_type"]} for s in subs})


def media_kind(ctype, proof):
    """("image" | "video", None) if this file type fits the activity, else (None, error)."""
    kind = "image" if ctype in IMAGE_TYPES else "video" if ctype in VIDEO_TYPES else None
    if kind is None:
        return None, "That file type isn't supported — use a normal photo or video."
    if proof == "photo" and kind != "image":
        return None, "This one needs a photo."
    if proof == "video" and kind != "video":
        return None, "This one needs a video."
    return kind, None


@app.post("/api/upload-url")
def api_upload_url():
    """Step 1 of a direct upload: the phone gets a one-time Supabase URL,
    PUTs the file there, then calls /api/submit with the key."""
    player = current_player()
    if not player:
        return jsonify(error="Your session expired — rejoin from the QR code."), 401
    if not storage.USE_SUPABASE:
        return jsonify(error="Direct uploads aren't set up."), 400
    activity = cfg().ACTIVITIES.get(request.form.get("activity_id", ""))
    if not activity:
        return jsonify(error="That activity doesn't exist anymore."), 400
    ctype = request.form.get("content_type", "").lower()
    _, error = media_kind(ctype, activity["proof"])
    if error:
        return jsonify(error=error), 400
    if request.form.get("size", type=int, default=0) > MAX_UPLOAD_MB * 1024 * 1024:
        return too_large(None)
    # Keys start with the player's id so /api/submit can check the file is theirs.
    key = f"{player['id']}/{uuid.uuid4()}.{EXTENSIONS[ctype]}"
    return jsonify(key=key, url=storage.signed_upload_url(key))


@app.post("/api/submit")
def api_submit():
    player = current_player()
    if not player:
        return jsonify(error="Your session expired — rejoin from the QR code."), 401
    activity = cfg().ACTIVITIES.get(request.form.get("activity_id", ""))
    if not activity:
        return jsonify(error="That activity doesn't exist anymore."), 400

    existing = db.query("SELECT * FROM mixer_submissions WHERE player_id = ? AND activity_id = ?",
                        (player["id"], activity["id"]), one=True)

    note = " ".join(request.form.get("note", "").split())[:80]
    upload = request.files.get("media")
    uploaded_key = request.form.get("media_key", "")
    proof = activity["proof"]
    if proof == "name" and not note:
        return jsonify(error="Type the name of the person you found."), 400
    if proof in ("photo", "video", "either") and not (upload or uploaded_key):
        return jsonify(error="Add a photo or video as proof."), 400

    media_key = media_type = None
    if uploaded_key:
        # Already sent straight to Supabase via /api/upload-url.
        owner, _, filename = uploaded_key.partition("/")
        ctype = next((t for t, ext in EXTENSIONS.items()
                      if filename.endswith(f".{ext}")), "")
        media_type, error = media_kind(ctype, proof)
        if owner != player["id"] or "/" in filename or error:
            return jsonify(error=error or "That upload isn't yours — try again."), 400
        if not storage.exists(uploaded_key):
            return jsonify(error="The upload didn't finish — try again."), 400
        media_key = uploaded_key
    elif upload:
        ctype = (upload.mimetype or "").lower()
        media_type, error = media_kind(ctype, proof)
        if error:
            return jsonify(error=error), 400
        data = upload.read()
        if not data:
            return jsonify(error="The file was empty — try again."), 400
        media_key = f"{uuid.uuid4()}.{EXTENSIONS[ctype]}"
        storage.save(media_key, data, ctype)

    # No approval step: media goes straight to the projector. Admins can
    # still hide or reject it from /admin.
    # reviewed_at orders the projector feed, newest first.
    status = "approved" if media_key else "done"
    reviewed_at = now() if media_key else None
    if existing:
        if existing["media_key"] and existing["media_key"] != media_key:
            storage.delete(existing["media_key"])
            # Votes were for the old photo.
            db.query("DELETE FROM mixer_votes WHERE submission_id = ?", (existing["id"],))
        db.query("""UPDATE mixer_submissions SET note = ?, media_key = ?, media_type = ?,
                    status = ?, created_at = ?, reviewed_at = ? WHERE id = ?""",
                 (note, media_key, media_type, status, now(), reviewed_at, existing["id"]))
    else:
        db.query("""INSERT INTO mixer_submissions
                    (id, player_id, activity_id, note, media_key, media_type, status,
                     created_at, reviewed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                 (str(uuid.uuid4()), player["id"], activity["id"], note,
                  media_key, media_type, status, now(), reviewed_at))
    return jsonify(ok=True, status=status)


@app.post("/api/undo")
def api_undo():
    player = current_player()
    if not player:
        return jsonify(error="not_joined"), 401
    activity_id = request.form.get("activity_id", "")
    sub = db.query("SELECT * FROM mixer_submissions WHERE player_id = ? AND activity_id = ?",
                   (player["id"], activity_id), one=True)
    if sub:
        if sub["media_key"]:
            storage.delete(sub["media_key"])
        db.query("DELETE FROM mixer_submissions WHERE id = ?", (sub["id"],))
    return jsonify(ok=True)


# ---------- photo voting ----------

def photo_feed(viewer_id, order):
    """Every photo/video on the projector with its vote totals and the
    viewer's own vote. order: 'new' (newest first) or 'top' (best score
    first; ties go to whoever posted first)."""
    order_by = ("score DESC, up DESC, s.reviewed_at ASC" if order == "top"
                else "s.reviewed_at DESC")
    rows = db.query(f"""
        SELECT s.id, s.player_id, s.activity_id, s.note, s.media_key, s.media_type, p.name,
               COALESCE(SUM(v.value), 0) AS score,
               COALESCE(SUM(CASE WHEN v.value = 1 THEN 1 ELSE 0 END), 0) AS up,
               COALESCE(SUM(CASE WHEN v.value = -1 THEN 1 ELSE 0 END), 0) AS down,
               MAX(CASE WHEN v.player_id = ? THEN v.value END) AS my_vote
        FROM mixer_submissions s
        JOIN mixer_players p ON p.id = s.player_id
        LEFT JOIN mixer_votes v ON v.submission_id = s.id
        WHERE s.status = 'approved' AND s.media_key IS NOT NULL
        GROUP BY s.id, p.id
        ORDER BY {order_by}""", (viewer_id,))
    return [{"id": r["id"], "name": r["name"], "note": r["note"],
             "title": cfg().ACTIVITIES.get(r["activity_id"], {}).get("title", ""),
             "url": storage.url(r["media_key"]), "type": r["media_type"],
             "score": int(r["score"]), "up": int(r["up"]), "down": int(r["down"]),
             "myVote": r["my_vote"] or 0, "mine": r["player_id"] == viewer_id} for r in rows]


@app.route("/api/photos")
def api_photos():
    player = current_player()
    if not player:
        return jsonify(error="not_joined"), 401
    order = "top" if request.args.get("order") == "top" else "new"
    return jsonify(photos=photo_feed(player["id"], order))


@app.post("/api/vote")
def api_vote():
    """value 1 = up, -1 = down, 0 = take my vote back."""
    player = current_player()
    if not player:
        return jsonify(error="Your session expired — rejoin from the QR code."), 401
    value = request.form.get("value", type=int)
    if value not in (-1, 0, 1):
        return jsonify(error="Bad vote."), 400
    sub = db.query("""SELECT id, player_id FROM mixer_submissions
                      WHERE id = ? AND status = 'approved' AND media_key IS NOT NULL""",
                   (request.form.get("submission_id", ""),), one=True)
    if not sub:
        return jsonify(error="That photo isn't up anymore."), 404
    if sub["player_id"] == player["id"]:
        return jsonify(error="You can't vote on your own photo."), 400
    if value == 0:
        db.query("DELETE FROM mixer_votes WHERE submission_id = ? AND player_id = ?",
                 (sub["id"], player["id"]))
    else:
        db.query("""INSERT INTO mixer_votes (submission_id, player_id, value, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT (submission_id, player_id)
                    DO UPDATE SET value = excluded.value, created_at = excluded.created_at""",
                 (sub["id"], player["id"], value, now()))
    return jsonify(ok=True)


@app.errorhandler(413)
def too_large(_):
    return jsonify(error=f"That file is over {MAX_UPLOAD_MB} MB — record a shorter clip."), 413


# ---------- projector ----------

@app.route("/screen")
def screen():
    return render_template("screen.html", event=cfg().EVENT_NAME)


@app.route("/api/screen")
def api_screen():
    feed = db.query("""
        SELECT s.id, s.activity_id, s.note, s.media_key, s.media_type, s.reviewed_at, p.name
        FROM mixer_submissions s JOIN mixer_players p ON p.id = s.player_id
        WHERE s.status = 'approved' AND s.media_key IS NOT NULL
        ORDER BY s.reviewed_at DESC LIMIT 24""")
    return jsonify(
        feed=[{"id": f["id"], "name": f["name"], "note": f["note"],
               "title": cfg().ACTIVITIES.get(f["activity_id"], {}).get("title", ""),
               "url": storage.url(f["media_key"]), "type": f["media_type"]} for f in feed],
        leaderboard=[{k: b[k] for k in ("name", "role", "points", "lines")}
                     for b in leaderboard(10)])


@app.route("/qr")
def qr():
    return render_template("qr.html", event=cfg().EVENT_NAME, url=request.host_url)


@app.route("/media/<path:key>")
def media(key):
    if storage.USE_SUPABASE:
        abort(404)
    return send_from_directory(storage.LOCAL_DIR, key)


# ---------- admin ----------

@app.route("/admin")
def admin():
    if not is_admin():
        return admin_login_page()

    def rows(status, limit):
        subs = db.query(f"""
            SELECT s.*, p.name FROM mixer_submissions s
            JOIN mixer_players p ON p.id = s.player_id
            WHERE s.status = ? AND s.media_key IS NOT NULL
            ORDER BY s.created_at {'ASC' if status == 'pending' else 'DESC'} LIMIT {int(limit)}""",
                        (status,))
        for s in subs:
            act = cfg().ACTIVITIES.get(s["activity_id"], {})
            s["title"], s["points"] = act.get("title", s["activity_id"]), act.get("points", 0)
            s["url"] = storage.url(s["media_key"])
        return subs

    return render_template("admin.html", pending=rows("pending", 50),
                           approved=rows("approved", 60), hidden=rows("hidden", 60),
                           board=leaderboard())


@app.post("/admin/review")
def admin_review():
    if not is_admin():
        abort(403)
    sub = db.query("SELECT * FROM mixer_submissions WHERE id = ?", (request.form.get("id", ""),), one=True)
    action = request.form.get("action")
    if sub and action == "approve":
        db.query("UPDATE mixer_submissions SET status = 'approved', reviewed_at = ? WHERE id = ?",
                 (now(), sub["id"]))
    elif sub and action == "reject":
        # Rejecting removes the points and the file; the player can resubmit.
        if sub["media_key"]:
            storage.delete(sub["media_key"])
        db.query("""UPDATE mixer_submissions SET status = 'rejected', media_key = NULL,
                    reviewed_at = ? WHERE id = ?""", (now(), sub["id"]))
        db.query("DELETE FROM mixer_votes WHERE submission_id = ?", (sub["id"],))
    elif sub and action == "hide":
        # Off the projector, but the player keeps the points.
        db.query("UPDATE mixer_submissions SET status = 'hidden' WHERE id = ?", (sub["id"],))
    elif sub and action == "caption":
        note = " ".join(request.form.get("note", "").split())[:80]
        db.query("UPDATE mixer_submissions SET note = ? WHERE id = ?", (note, sub["id"]))
    if sub and request.form.get("back") == "player":
        return redirect(url_for("admin_player", player_id=sub["player_id"]))
    return redirect(url_for("admin"))


@app.route("/admin/player/<player_id>")
def admin_player(player_id):
    """Everything one player has submitted, so invalid entries (including
    bingo squares that never go through the approval queue) can be removed."""
    if not is_admin():
        return redirect(url_for("admin"))
    player = db.query("SELECT * FROM mixer_players WHERE id = ?", (player_id,), one=True)
    if not player:
        abort(404)
    subs = db.query("SELECT * FROM mixer_submissions WHERE player_id = ? ORDER BY created_at DESC",
                    (player_id,))
    acts = cfg().ACTIVITIES
    kinds = {"bingo": "Bingo", "challenge": "Team up", "perform": "Perform"}
    for s in subs:
        act = acts.get(s["activity_id"])
        s["title"] = act["title"] if act else "(deleted activity)"
        s["kind"] = kinds.get(act["kind"], "") if act else ""
        s["points"] = act["points"] if act else 0
        s["url"] = storage.url(s["media_key"])
    pts, lines = score({s["activity_id"] for s in subs if s["status"] != "rejected"})
    return render_template("admin_player.html", player=player, subs=subs, points=pts, lines=lines,
                           role=ROLES.get(player["role"], ""))


@app.post("/admin/player/<player_id>/delete")
def admin_player_delete(player_id):
    """Remove a player entirely (e.g. a joke name), with their files."""
    if not is_admin():
        abort(403)
    for s in db.query("SELECT media_key FROM mixer_submissions WHERE player_id = ? AND media_key IS NOT NULL",
                      (player_id,)):
        storage.delete(s["media_key"])
    db.query("DELETE FROM mixer_submissions WHERE player_id = ?", (player_id,))
    db.query("DELETE FROM mixer_players WHERE id = ?", (player_id,))
    return redirect(url_for("admin"))


@app.post("/admin/reset")
def admin_reset():
    """Start over: 'scores' clears every submission and file but keeps the
    players; 'everything' removes the players too. Activities are untouched."""
    if not is_admin():
        abort(403)
    what = request.form.get("what")
    if request.form.get("confirm", "").strip().upper() != "RESET" or what not in ("scores", "everything"):
        return redirect(url_for("admin", reset_error=1) + "#reset")
    for s in db.query("SELECT media_key FROM mixer_submissions WHERE media_key IS NOT NULL"):
        storage.delete(s["media_key"])
    db.query("DELETE FROM mixer_submissions")
    if what == "everything":
        db.query("DELETE FROM mixer_players")
    return redirect(url_for("admin", reset_done=what))


@app.route("/admin/content", methods=["GET", "POST"])
def admin_content():
    if not is_admin():
        return redirect(url_for("admin"))
    data, error, saved = game.raw(), None, False
    if request.method == "POST":
        try:
            submitted = json.loads(request.form.get("data", ""))
        except ValueError:
            submitted = None
        if not isinstance(submitted, dict):
            error = "Couldn't read the form — try again."
        else:
            try:
                game.save(submitted)
                data, saved = game.raw(), True
            except ValueError as e:
                error, data = str(e), {**data, **submitted}  # keep their edits on screen
    return render_template("admin_content.html", data=data, proofs=game.PROOFS,
                           error=error, saved=saved), (400 if error else 200)


@app.post("/admin/content/reset")
def admin_content_reset():
    if not is_admin():
        abort(403)
    game.reset()
    return redirect(url_for("admin_content"))


@app.post("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port)  # set FLASK_DEBUG=1 for auto-reload while editing
