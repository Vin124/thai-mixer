"""
app.py — Mixer, the house-party game. Sign in with Google, create a game
from a pack (or your own set), share the QR / code, and guests play: bingo
(find someone who…), team-up challenges and performances with photo/video
proof, then vote on each other's photos for a winner.

Pages:
  /                 homepage: create a game, join one by code, your games
  /new              create a game (pick a pack or set)
  /join?code=       join by code
  /sets             make and manage your own sets (sets_views.py)
  /g/<code>         a game's join page (what its QR points at)
  /g/<code>/play    the player's phone view
  /g/<code>/screen  projector: live photo/video feed + leaderboard
  /g/<code>/admin   host controls (the host, or anyone in ADMIN_EMAILS)
  /g/<code>/qr      printable QR code for this game

Every /g/<code>/... route runs with that game loaded (see load_game), and
everything it reads or changes is limited to that game's players.
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
import presets
import sets
import storage

MAX_UPLOAD_MB = 50  # Supabase's free tier caps each file at 50 MB
MAX_VIDEO_SECONDS = 30


def _secret_key():
    """FLASK_SECRET_KEY if set, else a random key saved next to the app so
    logins survive restarts. Never a fixed default: anyone who knew it could
    forge a login."""
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
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    # Only send the cookie when the session changes. Otherwise a player-page
    # poll that was in flight during a sign-in answers with the old cookie
    # and signs the person straight back out.
    SESSION_REFRESH_EACH_REQUEST=False,
    SESSION_COOKIE_SAMESITE="Lax",
    # https-only cookies once hosted; plain http is fine on your own computer.
    SESSION_COOKIE_SECURE=(os.environ.get("COOKIE_SECURE") or ("1" if db.USE_PG else "0")) == "1",
)

# Google accounts that can run every game (including the original Thai Club
# one, which has no host), comma-separated.
ADMIN_EMAILS = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/heic", "image/heif"}
VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm"}
EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif",
              "image/heic": "heic", "image/heif": "heif", "video/mp4": "mp4",
              "video/quicktime": "mov", "video/webm": "webm"}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


db.init_db()
game.ensure_legacy(now())
storage.init_storage(MAX_UPLOAD_MB * 1024 * 1024, EXTENSIONS)


# ---------- who's asking ----------

def current_user():
    """The signed-in Google user's row, or None."""
    if "user" not in g:
        uid = session.get("user_id")
        g.user = db.query("SELECT * FROM mixer_users WHERE id = ?", (uid,), one=True) if uid else None
    return g.user


def is_superadmin():
    user = current_user()
    return bool(user and user["email"].lower() in ADMIN_EMAILS)


def is_host():
    """May the current user run the loaded game?"""
    user = current_user()
    return bool(user and (g.game_row["host_id"] == user["id"] or is_superadmin()))


def current_player():
    """The current person's player in the loaded game, or None. Google users
    are matched by account; people who joined the original event by name
    (before sign-in existed) by the player id in their cookie."""
    if "player" not in g:
        user, gid = current_user(), g.game_row["id"]
        if user:
            g.player = db.query("SELECT * FROM mixer_players WHERE game_id = ? AND user_id = ?",
                                (gid, user["id"]), one=True)
        else:
            g.player = None
        if not g.player and session.get("player_id"):
            g.player = db.query("""SELECT * FROM mixer_players
                                   WHERE id = ? AND game_id = ? AND user_id IS NULL""",
                                (session["player_id"], gid), one=True)
    return g.player


def safe_next(target):
    """Only same-site paths, so a crafted link can't bounce people elsewhere."""
    target = target or "/"
    if not target.startswith("/") or target.startswith("//") or "\\" in target:
        return "/"
    return target


# ---------- game loading ----------
# Every endpoint named game_* lives under /g/<code>/. The code is taken off
# the URL and the game loaded before the view runs, and url_for() inside a
# game fills the code back in, so templates write url_for('game_play').

@app.url_value_preprocessor
def load_game(endpoint, values):
    if endpoint and endpoint.startswith("game_") and values is not None and "code" in values:
        row = game.by_code(values.pop("code"))
        if not row:
            abort(404)
        g.game_row, g.code = row, row["code"]


@app.url_defaults
def add_game_code(endpoint, values):
    if endpoint.startswith("game_") and "code" not in values and "code" in g:
        values["code"] = g.code


def cfg():
    """The loaded game's activities."""
    if "game" not in g:
        g.game = game.build(g.game_row["pack"])
    return g.game


def require_host():
    if not is_host():
        abort(403)


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
    gid = g.game_row["id"]
    players = db.query("SELECT id, name, role FROM mixer_players WHERE game_id = ?", (gid,))
    rows = db.query("""SELECT s.player_id, s.activity_id FROM mixer_submissions s
                       JOIN mixer_players p ON p.id = s.player_id
                       WHERE p.game_id = ? AND s.status <> 'rejected'""", (gid,))
    done = {}
    for r in rows:
        done.setdefault(r["player_id"], set()).add(r["activity_id"])
    board = []
    for p in players:
        pts, lines = score(done.get(p["id"], set()))
        board.append({"name": p["name"], "role": cfg().ROLES.get(p["role"], ""),
                      "points": pts, "lines": lines, "id": p["id"]})
    board.sort(key=lambda b: (-b["points"], b["name"].lower()))
    return board[:limit] if limit else board


def game_submission(sub_id):
    """A submission by id, only if it belongs to a player in the loaded game."""
    return db.query("""SELECT s.* FROM mixer_submissions s JOIN mixer_players p ON p.id = s.player_id
                       WHERE s.id = ? AND p.game_id = ?""", (sub_id, g.game_row["id"]), one=True)


def game_player(player_id):
    return db.query("SELECT * FROM mixer_players WHERE id = ? AND game_id = ?",
                    (player_id, g.game_row["id"]), one=True)


# ---------- sign in ----------

@app.route("/login/google")
def login_google():
    """Start Google sign-in; ?next= is where to land afterwards."""
    nxt = safe_next(request.args.get("next"))
    if not auth.ENABLED:
        return home_page(error="Google sign-in isn't set up on this server.", status=503)
    verifier = auth.new_verifier()
    session["oauth"] = {"verifier": verifier, "next": nxt}
    return redirect(auth.authorize_url(url_for("auth_callback", _external=True), verifier))


@app.route("/auth/callback")
def auth_callback():
    """Google -> Supabase -> here with ?code=. Remember the account, then go
    where the person was heading."""
    flow = session.pop("oauth", None)
    code = request.args.get("code")
    if not flow or not code:
        return home_page(error=request.args.get("error_description")
                         or "Sign-in didn't finish — try again.", status=400)
    try:
        user = auth.exchange(code, flow["verifier"])
    except auth.AuthError as e:
        return home_page(error=str(e), status=400)
    if db.query("SELECT 1 FROM mixer_users WHERE id = ?", (user["id"],), one=True):
        db.query("UPDATE mixer_users SET email = ? WHERE id = ?", (user["email"], user["id"]))
    else:
        db.query("INSERT INTO mixer_users (id, email, name, created_at) VALUES (?, ?, ?, ?)",
                 (user["id"], user["email"], user["name"], now()))
    session.permanent = True
    session["user_id"] = user["id"]
    return redirect(safe_next(flow["next"]))


@app.post("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("player_id", None)
    return redirect(url_for("home"))


def login_redirect():
    return redirect(url_for("login_google", next=request.full_path.rstrip("?")))


# ---------- homepage, create, join ----------

def home_page(error=None, status=200):
    user = current_user()
    games = [{"code": r["code"], "title": r["title"], "is_host": bool(r["is_host"]),
              "players": int(r["players"])} for r in game.for_user(user["id"])] if user else []
    return render_template(
        "home.html", user={"name": user["name"], "email": user["email"]} if user else None,
        games=games, sign_in=auth.ENABLED, error=error,
        packs=[{k: p[k] for k in ("id", "title", "emoji", "description")} for p in presets.PACKS]
    ), status


@app.route("/")
def home():
    return home_page()


@app.route("/join")
def join_code():
    row = game.by_code(request.args.get("code"))
    if not row:
        return home_page(error="No game with that code — check the letters and try again.",
                         status=404)
    return redirect(url_for("game_join", code=row["code"]))


@app.route("/new", methods=["GET", "POST"])
def new_game():
    user = current_user()
    if not user:
        return login_redirect()
    library = sets.library(user["id"])
    chosen = request.values.get("pack") or presets.PACKS[0]["id"]
    error = None
    if request.method == "POST":
        found = sets.load(chosen, user["id"])
        title = " ".join(request.form.get("title", "").split())[:60]
        if not found:
            error = "Pick a pack to play."
        else:
            set_title, pack = found
            pack["event_name"] = title or pack["event_name"]
            try:
                row = game.create(pack["event_name"], user["id"], pack, chosen, now())
            except ValueError as e:  # a custom set saved before a rule changed
                error = str(e)
            else:
                return redirect(url_for("game_admin", code=row["code"]))
    return render_template("new_game.html", library=library, chosen=chosen, error=error,
                           title=request.form.get("title", "")), (400 if error else 200)


@app.route("/g/<code>", methods=["GET", "POST"], endpoint="game_join")
def game_join():
    """Where the QR lands: sign in, pick a name (and role, if the pack has
    roles), and you're in."""
    if current_player():
        return redirect(url_for("game_play"))
    user = current_user()
    error, name, role = None, user["name"] if user else "", None
    if request.method == "POST" and user:
        name = " ".join(request.form.get("name", "").split())[:40]
        role = request.form.get("role", "")
        if not name:
            error = "Type your name so people can find you."
        elif cfg().ROLES and role not in cfg().ROLES:
            error = "Pick one of the options."
        elif db.query("SELECT 1 FROM mixer_players WHERE game_id = ? AND name_key = ?",
                      (g.game_row["id"], name.lower()), one=True):
            error = f"Someone in this game is already “{name}”. Add your last initial or a nickname."
        else:
            try:
                db.query("""INSERT INTO mixer_players (id, game_id, user_id, name, name_key, role,
                                                       created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)""",
                         (str(uuid.uuid4()), g.game_row["id"], user["id"], name, name.lower(),
                          role if cfg().ROLES else "", now()))
            except db.IntegrityError:
                # A unique index said no: either a double-tapped Join (the
                # first request already made the player) or the name was
                # taken a moment ago.
                pass
            g.pop("player", None)
            if current_player():
                return redirect(url_for("game_play"))
            error = f"Someone just joined as “{name}”. Add your last initial or a nickname."
    return render_template("join.html", event=cfg().EVENT_NAME, roles=cfg().ROLES,
                           hints=cfg().ROLE_HINTS, user=user, sign_in=auth.ENABLED, error=error,
                           name=name, role=role, code=g.code), (400 if error else 200)


@app.post("/g/<code>/leave", endpoint="game_leave")
def game_leave():
    session.pop("player_id", None)
    return redirect(url_for("home"))


# Links and QR codes printed for the original single-event site.
@app.route("/play")
@app.route("/screen")
@app.route("/qr")
@app.route("/admin")
def legacy_redirect():
    page = request.path.strip("/")
    target = {"play": "game_play", "screen": "game_screen", "qr": "game_qr",
              "admin": "game_admin"}[page]
    return redirect(url_for(target, code=game.LEGACY_CODE))


# ---------- player pages ----------

@app.route("/g/<code>/play", endpoint="game_play")
def play():
    player = current_player()
    if not player:
        return redirect(url_for("game_join"))
    return render_template(
        "play.html", event=cfg().EVENT_NAME, player=player,
        role_label=cfg().ROLES.get(player["role"], ""), game=game_payload(), is_host=is_host())


def game_payload():
    """Activities as the phone page needs them (re-sent with every /api/me
    poll so host edits show up without a reload)."""
    return {"event": cfg().EVENT_NAME, "bingo": cfg().BINGO, "challenges": cfg().CHALLENGES,
            "performances": cfg().PERFORMANCES, "lineBonus": cfg().BINGO_LINE_BONUS,
            "maxUploadMb": MAX_UPLOAD_MB, "maxVideoSeconds": MAX_VIDEO_SECONDS,
            "directUpload": storage.USE_SUPABASE}


@app.route("/g/<code>/api/me", endpoint="game_api_me")
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


@app.post("/g/<code>/api/upload-url", endpoint="game_api_upload_url")
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


@app.post("/g/<code>/api/submit", endpoint="game_api_submit")
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

    # No approval step: media goes straight to the projector. Hosts can
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


@app.post("/g/<code>/api/undo", endpoint="game_api_undo")
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
    """Every photo/video on this game's projector with its vote totals and
    the viewer's own vote. order: 'new' (newest first) or 'top' (best score
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
        WHERE p.game_id = ? AND s.status = 'approved' AND s.media_key IS NOT NULL
        GROUP BY s.id, p.id
        ORDER BY {order_by}""", (viewer_id, g.game_row["id"]))
    return [{"id": r["id"], "name": r["name"], "note": r["note"],
             "title": cfg().ACTIVITIES.get(r["activity_id"], {}).get("title", ""),
             "url": storage.url(r["media_key"]), "type": r["media_type"],
             "score": int(r["score"]), "up": int(r["up"]), "down": int(r["down"]),
             "myVote": r["my_vote"] or 0, "mine": r["player_id"] == viewer_id} for r in rows]


@app.route("/g/<code>/api/photos", endpoint="game_api_photos")
def api_photos():
    player = current_player()
    if not player:
        return jsonify(error="not_joined"), 401
    order = "top" if request.args.get("order") == "top" else "new"
    return jsonify(photos=photo_feed(player["id"], order))


@app.post("/g/<code>/api/vote", endpoint="game_api_vote")
def api_vote():
    """value 1 = up, -1 = down, 0 = take my vote back."""
    player = current_player()
    if not player:
        return jsonify(error="Your session expired — rejoin from the QR code."), 401
    value = request.form.get("value", type=int)
    if value not in (-1, 0, 1):
        return jsonify(error="Bad vote."), 400
    sub = game_submission(request.form.get("submission_id", ""))
    if not sub or sub["status"] != "approved" or not sub["media_key"]:
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

@app.route("/g/<code>/screen", endpoint="game_screen")
def screen():
    return render_template("screen.html", event=cfg().EVENT_NAME, code=g.code,
                           join_url=url_for("game_join", _external=True))


@app.route("/g/<code>/api/screen", endpoint="game_api_screen")
def api_screen():
    feed = db.query("""
        SELECT s.id, s.activity_id, s.note, s.media_key, s.media_type, s.reviewed_at, p.name
        FROM mixer_submissions s JOIN mixer_players p ON p.id = s.player_id
        WHERE p.game_id = ? AND s.status = 'approved' AND s.media_key IS NOT NULL
        ORDER BY s.reviewed_at DESC LIMIT 24""", (g.game_row["id"],))
    return jsonify(
        feed=[{"id": f["id"], "name": f["name"], "note": f["note"],
               "title": cfg().ACTIVITIES.get(f["activity_id"], {}).get("title", ""),
               "url": storage.url(f["media_key"]), "type": f["media_type"]} for f in feed],
        leaderboard=[{k: b[k] for k in ("name", "role", "points", "lines")}
                     for b in leaderboard(10)])


@app.route("/g/<code>/qr", endpoint="game_qr")
def qr():
    return render_template("qr.html", event=cfg().EVENT_NAME, code=g.code,
                           url=url_for("game_join", _external=True))


@app.route("/media/<path:key>")
def media(key):
    if storage.USE_SUPABASE:
        abort(404)
    return send_from_directory(storage.LOCAL_DIR, key)


# ---------- host controls ----------

@app.route("/g/<code>/admin", endpoint="game_admin")
def admin():
    if not current_user():
        return login_redirect()
    require_host()

    def rows(status, limit):
        subs = db.query(f"""
            SELECT s.*, p.name FROM mixer_submissions s
            JOIN mixer_players p ON p.id = s.player_id
            WHERE p.game_id = ? AND s.status = ? AND s.media_key IS NOT NULL
            ORDER BY s.created_at {'ASC' if status == 'pending' else 'DESC'} LIMIT {int(limit)}""",
                        (g.game_row["id"], status))
        for s in subs:
            act = cfg().ACTIVITIES.get(s["activity_id"], {})
            s["title"], s["points"] = act.get("title", s["activity_id"]), act.get("points", 0)
            s["url"] = storage.url(s["media_key"])
        return subs

    return render_template("admin.html", pending=rows("pending", 50),
                           approved=rows("approved", 60), hidden=rows("hidden", 60),
                           board=leaderboard(), event=cfg().EVENT_NAME, code=g.code,
                           join_url=url_for("game_join", _external=True),
                           playing=bool(current_player()))


@app.post("/g/<code>/admin/review", endpoint="game_admin_review")
def admin_review():
    require_host()
    sub = game_submission(request.form.get("id", ""))
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
        return redirect(url_for("game_admin_player", player_id=sub["player_id"]))
    return redirect(url_for("game_admin"))


@app.route("/g/<code>/admin/player/<player_id>", endpoint="game_admin_player")
def admin_player(player_id):
    """Everything one player has submitted, so invalid entries (including
    bingo squares that never go through the approval queue) can be removed."""
    if not current_user():
        return login_redirect()
    require_host()
    player = game_player(player_id)
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
                           role=cfg().ROLES.get(player["role"], ""))


@app.post("/g/<code>/admin/player/<player_id>/delete", endpoint="game_admin_player_delete")
def admin_player_delete(player_id):
    """Remove a player entirely (e.g. a joke name), with their files."""
    require_host()
    player = game_player(player_id)
    if player:
        for s in db.query("""SELECT media_key FROM mixer_submissions
                             WHERE player_id = ? AND media_key IS NOT NULL""", (player["id"],)):
            storage.delete(s["media_key"])
        db.query("DELETE FROM mixer_submissions WHERE player_id = ?", (player["id"],))
        db.query("DELETE FROM mixer_players WHERE id = ?", (player["id"],))
    return redirect(url_for("game_admin"))


@app.post("/g/<code>/admin/reset", endpoint="game_admin_reset")
def admin_reset():
    """Start over: 'scores' clears this game's submissions and files but keeps
    the players; 'everything' removes the players too. Activities are untouched."""
    require_host()
    what = request.form.get("what")
    if request.form.get("confirm", "").strip().upper() != "RESET" or what not in ("scores", "everything"):
        return redirect(url_for("game_admin", reset_error=1) + "#reset")
    gid = g.game_row["id"]
    in_game = "player_id IN (SELECT id FROM mixer_players WHERE game_id = ?)"
    for s in db.query(f"SELECT media_key FROM mixer_submissions WHERE {in_game} AND media_key IS NOT NULL",
                      (gid,)):
        storage.delete(s["media_key"])
    db.query(f"DELETE FROM mixer_submissions WHERE {in_game}", (gid,))
    if what == "everything":
        db.query("DELETE FROM mixer_players WHERE game_id = ?", (gid,))
    return redirect(url_for("game_admin", reset_done=what))


@app.route("/g/<code>/admin/content", methods=["GET", "POST"], endpoint="game_admin_content")
def admin_content():
    if not current_user():
        return login_redirect()
    require_host()
    data, error, saved = g.game_row["pack"], None, False
    if request.method == "POST":
        try:
            submitted = json.loads(request.form.get("data", ""))
        except ValueError:
            submitted = None
        if isinstance(submitted, dict) and "roles" not in submitted:
            submitted["roles"] = data.get("roles", [])  # editor without a roles section
        try:
            game.save_pack(g.game_row["id"], submitted)
            data, saved = game.by_code(g.code)["pack"], True
        except ValueError as e:
            error = str(e)
            if isinstance(submitted, dict):
                data = {**data, **submitted}  # keep their edits on screen
    return render_template("admin_content.html", data=data, proofs=game.PROOFS,
                           error=error, saved=saved), (400 if error else 200)


@app.post("/g/<code>/admin/content/reset", endpoint="game_admin_content_reset")
def admin_content_reset():
    """Put this game's activities back to the pack it was made from."""
    require_host()
    row = g.game_row
    if row["id"] == game.LEGACY_ID:
        pack = game.legacy_pack()
    else:
        found = sets.load(row["pack_id"], row["host_id"]) if row["pack_id"] else None
        pack = found[1] if found else None
    if pack:
        pack["event_name"] = row["pack"]["event_name"]
        game.save_pack(row["id"], pack)
    return redirect(url_for("game_admin_content"))


import sets_views  # noqa: E402  (registers /sets routes on app)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port)  # set FLASK_DEBUG=1 for auto-reload while editing
