# Mixer 🎉

A house-party game you run from a QR code. Sign in with Google, start a game from a pack, and share the QR or the 6-letter code. Guests play from their phones:

- **Bingo**: "find someone who…", a 5×5 card with points per square and a bonus for each full line
- **Team up**: photo or video challenges you do with someone new
- **Perform**: a short filmed moment on stage
- **Vote / Winner**: up- or down-vote everyone's photos; the most-loved one wins
- **Leaderboard**: live points and rank

Packs: House Party, Entrepreneurs, Asian Diaspora, Thai Club, Work Team and Freshers (in `presets.py`), plus any **set** you make yourself at `/sets`. Sets are private unless you switch on "share publicly". A game keeps its own copy of the pack, so its host can edit the activities mid-party without changing the set.

| Page | Who | What |
|---|---|---|
| `/` | everyone | homepage: create a game, join by code, your games |
| `/new` | hosts | pick a pack and start a game |
| `/sets` | anyone signed in | make, edit and share your own sets |
| `/g/<code>` | guests | what the QR points at: join, then play |
| `/g/<code>/screen` | projector | live photo/video feed, top 10, QR |
| `/g/<code>/admin` | the game's host | review media, edit activities, fix anyone's score |
| `/g/<code>/qr` | print it | a big QR code for this game |

Everyone signs in with Google. The person who created a game is its host; anyone in `ADMIN_EMAILS` can run every game. The original Thai Club event lives on as the game with code **THAI**, with all its players and photos, and the old `/play`, `/screen`, `/admin` and `/qr` links point there.

## Change the activities

On a game's host page open **Edit activities**. You can rewrite any bingo square, add, reorder or delete challenges and performances, change points and the proof each one needs, and edit the roles people pick when they join. Players' phones pick up edits within about 15 seconds. **Reset** goes back to the pack the game was made from.

## Fix scores

Tap a player's name on the host page's leaderboard to see everything they've submitted, including bingo names, which never go through the approval queue. **Remove points** takes off the points for anything that doesn't count, and the player can redo it. You can also delete a player entirely, for example someone who joined with a joke name. Each row of the leaderboard has a **Delete** button for this.

Photos and videos on the projector can be given a caption, **hidden** (off the screen, but the person keeps their points) or **deleted** (the points come off too).

After a practice run, use **Reset** at the bottom of the host page, where you type RESET to confirm. You can clear all scores and photos but keep the players, or delete everyone. Edited activities are kept either way.

## Run it on your computer

```bash
pip install -r requirements.txt
python app.py
```

Players and admins sign in with Google through Supabase Auth, so even locally you need `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` in a `.env` file (see below), plus `ADMIN_EMAILS=you@gmail.com` to run every game. Then open http://localhost:5050. With no other settings it uses a local SQLite file (`mixer.db`) and an `uploads/` folder. To try it on your phone, use your computer's local IP (printed at startup) on the same Wi-Fi.

## Host it for the event

Most hosts wipe the server's disk on redeploy, so for the real event, store data and files in **Supabase** (free tier):

1. Create a Supabase project.
2. Set these environment variables on your host (see `.env.example`):
   - `DATABASE_URL`: Project Settings → Database → Connection string → **Session pooler**
   - `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` (the **service_role** key, which is secret and only goes on the server): Project Settings → API
   - `ADMIN_EMAILS`: comma-separated Google accounts that can run every game (including THAI, which has no host)
   - In Supabase: Authentication → Sign In / Providers → **Google** on (with a Google Cloud OAuth client whose redirect URI is `https://<project-ref>.supabase.co/auth/v1/callback`), and Authentication → URL Configuration → add `https://<your-site>/auth/callback` to the redirect URLs
   - `FLASK_SECRET_KEY`: any long random string (`python -c "import secrets; print(secrets.token_hex(32))"`)
3. Deploy to any Python host. On first start the app creates its tables (with row-level security on) and a public `mixer-media` storage bucket by itself.
   - **Render**: New Web Service from this repo. Build `pip install -r requirements.txt`, start `gunicorn app:app --preload --workers 2 --threads 4 --timeout 120`.
   - **Railway / Heroku-style hosts**: the `Procfile` is already set up.
4. Sign in on the live site, create a game, then from its host page print the QR (`/g/<code>/qr`) and open the projector page (`/g/<code>/screen`) on a laptop.

Free hosts (such as Render's free tier) go to sleep when no one is using them, so open the site a few minutes before the event starts.

## Test it

`python tests/smoke.py` runs the whole app against a throwaway SQLite file with Google sign-in faked.

## Good to know

- **Limits:** videos can be 30 s at most and files 50 MB at most (Supabase's free per-file cap). Photos are shrunk on the phone before upload, so they're fast even on bad Wi-Fi.
- **iPhone videos** are often HEVC `.mov`, which Chrome on Windows may not play. Run the projector page in **Safari, or Edge with the HEVC extension**, or test one clip beforehand.
- Players sign in with Google, so they get back to their points from any phone. Names only have to be unique within a game.
- Media links are random and not listed anywhere, but anyone who has a link can open it. Rejecting a submission deletes its file.
