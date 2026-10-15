"""
auth.py — Sign in with Google through Supabase Auth (the same setup as the
Hello-World app), using the PKCE flow over plain HTTP so the app needs no
Supabase SDK:

  1. authorize_url(): the browser goes to Supabase, which sends it to Google.
  2. Google -> Supabase -> /auth/callback?code=...
  3. exchange(): trade that code plus our secret verifier for the user.

After that the app keeps its own Flask session; Supabase's tokens aren't kept.
"""

import base64
import hashlib
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
# Only ever used server-side, so the service key works when there's no anon key.
API_KEY = os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
ENABLED = bool(SUPABASE_URL and API_KEY)


class AuthError(Exception):
    pass


def new_verifier():
    return secrets.token_urlsafe(64)


def authorize_url(redirect_to, verifier):
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    query = urllib.parse.urlencode({
        "provider": "google", "redirect_to": redirect_to,
        "code_challenge": challenge, "code_challenge_method": "s256"})
    return f"{SUPABASE_URL}/auth/v1/authorize?{query}"


def exchange(code, verifier):
    """The signed-in user as {"id", "email", "name"}. Raises AuthError."""
    req = urllib.request.Request(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=pkce", method="POST",
        data=json.dumps({"auth_code": code, "code_verifier": verifier}).encode(),
        headers={"apikey": API_KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            user = json.load(resp)["user"]
    except urllib.error.HTTPError as e:
        try:
            detail = json.load(e)
            msg = detail.get("msg") or detail.get("error_description") or detail.get("message")
        except ValueError:
            msg = None
        raise AuthError(msg or "Sign-in failed — try again.") from e
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
        raise AuthError("Couldn't reach the sign-in service — try again.") from e
    # The admin allowlist trusts this email, so it must be one Google confirmed.
    if not user.get("email_confirmed_at"):
        raise AuthError("That account's email isn't verified.")
    meta = user.get("user_metadata") or {}
    return {"id": user["id"], "email": (user.get("email") or "").lower(),
            "name": " ".join((meta.get("full_name") or meta.get("name") or "").split())[:40]}
