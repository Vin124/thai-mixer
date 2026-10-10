"""
content.py — the starting activities. The easy way to change them is the
editor at /admin/content; once something is saved there it replaces
everything in this file ("Reset to defaults" in the editor comes back here).

Rules of thumb:
- Keep each `id` the same once the event has started. Submissions are saved
  against the id, so renaming one orphans everything already submitted.
- `proof` is what the submit form asks for:
    "name"   → who they found (a photo is optional)
    "photo"  → a photo is required
    "video"  → a video is required
    "either" → a photo or a video
"""

EVENT_NAME = "Thai Club Mixer"

# Points for each bingo square, plus a bonus for every full line (row,
# column or diagonal) — the free centre square counts towards lines.
BINGO_SQUARE_POINTS = 1
BINGO_LINE_BONUS = 5

# Exactly 24 traits; the free square is put in the middle automatically.
# Ids are b0..b23 by position, so don't reorder these once people have
# started playing.
BINGO_TRAITS = [
    "Has met a Thai celebrity in person",
    "Is from Bangkok",
    "Is from ต่างจังหวัด (outside Bangkok)",
    "Has forgotten how to write some Thai letters (ฃ ฅ ฆ…)",
    "Their nickname is an English word (Bank, Ice, Beer…)",
    "Eats Thai food “phet mak” (very spicy)",
    "Can't handle spicy food (yes, really)",
    "Loves durian",
    "Drinks Thai tea every week",
    "Watches Thai dramas or BL",
    "Missed Songkran at home this year",
    "Went to an international school in Thailand",
    "Has lived outside Thailand for 3+ years",
    "Has been to a wat (Thai temple) here",
    "Is a พี่ (upperclassman)",
    "Is a น้อง (new member)",
    "Speaks 3+ languages",
    "Has the same birth month as you",
    "Is in the same major as you",
    "Brought Thai snacks or มาม่า in their luggage",
    "Has a pet",
    "Can cook a Thai dish",
    "Can do รำไทย (Thai dance) — make them show you",
    "Has had to explain their nickname to a foreigner",
]

FREE_SQUARE = "FREE — you showed up 🇹🇭"

CHALLENGES = [
    {"id": "c-wai-selfie", "points": 3, "proof": "photo",
     "title": "Team up with a พี่ for a wai selfie",
     "detail": "Both of you doing a proper wai."},
    {"id": "c-drama-poster", "points": 5, "proof": "photo",
     "title": "Team up with a พี่ to recreate a Thai drama poster",
     "detail": "Dramatic poses required."},
    {"id": "c-dance", "points": 5, "proof": "video",
     "title": "Team up with a พี่ for a 10-second dance",
     "detail": "Any song, any dance, both of you on camera."},
    {"id": "c-squad", "points": 5, "proof": "photo",
     "title": "Group photo with 5+ people you just met",
     "detail": "Everyone in frame."},
]

PERFORMANCES = [
    {"id": "p-sing", "points": 8, "proof": "video",
     "title": "Sing a Thai song",
     "detail": "Even one line counts — or take the penalty."},
    {"id": "p-tongue-twister", "points": 5, "proof": "video",
     "title": "Say “ไม้ใหม่ไหม้ไหม” three times fast",
     "detail": "Film it. Laughing is allowed."},
]

assert len(BINGO_TRAITS) == 24, "BINGO_TRAITS needs exactly 24 entries"
