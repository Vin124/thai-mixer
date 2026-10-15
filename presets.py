"""
presets.py — the built-in packs a host can pick from when starting a party.
Each pack is plain data in the same shape as game.defaults(). PACKS is in
picker order (first = default); get(pack_id) looks one up.

Keep activity ids the same once a party has started: submissions are saved
against them. `proof` is "name", "photo", "video" or "either" (see content.py).
"""

import content


def _c(id, title, detail, points, proof="photo"):
    return {"id": id, "title": title, "detail": detail, "points": points, "proof": proof}


HOUSE_PARTY = {
    "id": "house-party",
    "title": "House Party",
    "emoji": "🎉",
    "description": "A classic mingle-and-meet game for any group of friends-of-friends.",
    "pack": {
        "event_name": "House Party Mixer",
        "square_points": 1,
        "line_bonus": 5,
        "free_square": "FREE — you showed up 🎉",
        "bingo_traits": [
            "Has lived in 3+ countries",
            "Speaks 3+ languages",
            "Has a pet",
            "Can juggle (or at least try)",
            "Has met a celebrity",
            "Was born in the same month as you",
            "Has been on TV or radio",
            "Can cook a signature dish",
            "Has a tattoo with a story",
            "Plays a musical instrument",
            "Has run a marathon or half marathon",
            "Has a birthday this month",
            "Has never seen a Star Wars movie",
            "Knows how to say 'cheers' in 3+ languages",
            "Has traveled solo",
            "Is an only child",
            "Has a twin or sibling who is a twin",
            "Can do a cartwheel right now",
            "Has been to a music festival",
            "Is wearing something handmade or vintage",
            "Has a job that nobody guesses",
            "Has an unusual hobby",
            "Has moved cities in the last year",
            "Can name every song on a favorite album",
        ],
        "challenges": [
            _c("c-group-selfie", "Group selfie with 4+ new faces", "Everyone in frame, big smiles.", 4),
            _c("c-same-pose", "Strike the same pose as someone you just met", "Both of you in one photo, matching.", 3),
            _c("c-handshake", "Invent a secret handshake with a stranger", "Show it off on camera.", 5, "either"),
            _c("c-mirror", "Mirror photo: copy a stranger's outfit pose", "Stand side by side and match it.", 3),
            _c("c-toast", "Toast with someone new", "Clink glasses and snap it.", 3),
            _c("c-human-pyramid", "Build the tallest silly human tower you safely can", "Safety first, silliness second.", 5, "either"),
        ],
        "performances": [
            _c("p-karaoke", "Karaoke one chorus", "Any song, any volume, full commitment.", 8, "video"),
            _c("p-impression", "Do your best celebrity impression", "Let the room guess who.", 6, "either"),
            _c("p-dance-solo", "Freestyle dance for 10 seconds", "No music required.", 5, "video"),
        ],
        "roles": [],
    },
}


ENTREPRENEURS = {
    "id": "entrepreneurs",
    "title": "Entrepreneurs",
    "emoji": "🚀",
    "description": "Founders, builders and the curious meet over a networking game that beats small talk.",
    "pack": {
        "event_name": "Founders Mixer",
        "square_points": 1,
        "line_bonus": 5,
        "free_square": "FREE — you took the leap 🚀",
        "bingo_traits": [
            "Has pivoted a company",
            "Has raised money from investors",
            "Has bootstrapped a business",
            "Has shut down a startup",
            "Is working on a side project right now",
            "Has hired their first employee",
            "Has pitched on stage",
            "Has a cofounder they met at a party",
            "Writes code",
            "Has a day job and a startup",
            "Has sold something online",
            "Has lived in 3+ countries",
            "Has been to Y Combinator or another accelerator event",
            "Has worked at a startup with fewer than 10 people",
            "Has a business idea they have never told anyone",
            "Has made a spreadsheet for fun",
            "Has read a business book twice",
            "Is a first-generation entrepreneur",
            "Runs a newsletter or podcast",
            "Has launched on Product Hunt",
            "Has a family business in their background",
            "Has been told 'that will never work'",
            "Knows what their startup's runway is",
            "Is looking for a cofounder or first hire",
        ],
        "challenges": [
            _c("c-elevator-photo", "Team up with an investor or founder for a power selfie", "Look like you just closed the deal.", 3),
            _c("c-intro-swap", "Introduce two people who should know each other", "Photo with both of them.", 5),
            _c("c-card-swap", "Swap contacts with 3 new people", "Group photo of all four of you.", 4),
            _c("c-logo-pose", "Pose as your favorite company's logo with a stranger", "Others must guess it.", 4, "either"),
            _c("c-feedback", "Get one honest piece of advice from a new person", "Photo with your advisor.", 3),
            _c("c-team-photo", "Fake 'founding team' photo with 4+ people", "Magazine-cover energy.", 5),
        ],
        "performances": [
            _c("p-pitch-30s", "Pitch your startup in 30 seconds", "Real idea or invented one, no notes.", 10, "video"),
            _c("p-pitch-object", "Sell a random object to the room", "Pick something nearby and pitch it.", 8, "video"),
            _c("p-fail-story", "Tell your best failure story in 30 seconds", "What happened and what you learned.", 7, "either"),
        ],
        "roles": [
            {"key": "founder", "label": "Founder", "hint": "building something"},
            {"key": "investor", "label": "Investor", "hint": "backing builders"},
            {"key": "curious", "label": "Curious", "hint": "here to learn"},
        ],
    },
}


ASIAN_DIASPORA = {
    "id": "asian-diaspora",
    "title": "Asian Diaspora",
    "emoji": "🥢",
    "description": "A warm, funny mixer about shared stories of food, family and growing up between cultures.",
    "pack": {
        "event_name": "Diaspora Mixer",
        "square_points": 1,
        "line_bonus": 5,
        "free_square": "FREE — welcome home 🏮",
        "bingo_traits": [
            "Has a rice cooker older than they are",
            "Grew up taking their shoes off at the door",
            "Has been handed a plate of cut fruit as an act of love",
            "Has a family group chat that never sleeps",
            "Speaks a language at home they did not study in school",
            "Has translated for a relative at an appointment",
            "Has a nickname only family uses",
            "Has packed lunch they were proud of (eventually)",
            "Celebrates Lunar New Year, Diwali, Songkran or Eid",
            "Has received a red envelope or lucky money",
            "Has an auntie or uncle who is not actually a relative",
            "Cooks one family recipe without measuring",
            "Has brought snacks home from a trip in their suitcase",
            "Has a favorite instant noodle brand and defends it",
            "Has a go-to karaoke song in another language",
            "Has been to a family wedding with 200+ guests",
            "Has grown up with a tea ritual",
            "Eats rice at least once a day",
            "Learned a family dance or festival tradition",
            "Has worn traditional clothes for a celebration",
            "Has an opinion about the best boba or milk tea order",
            "Has taught a friend to use chopsticks or eat with their hands",
            "Has watched K-dramas, anime, Bollywood or C-dramas",
            "Has been told 'eat more' at least three times in one meal",
        ],
        "challenges": [
            _c("c-dish-share", "Team up with someone to name a dish you both grew up with", "Photo of the two of you with a dish you can both name.", 4),
            _c("c-greeting-swap", "Teach each other a greeting in your languages", "Photo together, both saying hello.", 3),
            _c("c-festival-pose", "Recreate a family-photo pose with 4+ people", "Everyone gets a role: elder, host, cousin, photographer.", 5),
            _c("c-snack-swap", "Share a snack from your culture with someone new", "Photo of the trade.", 3),
            _c("c-auntie-photo", "Photo with someone who gives big auntie or uncle energy", "A friendly one, with their blessing.", 3),
            _c("c-new-friend-meal", "Plan a meal with someone new", "Photo of you both, plus where you're going to eat.", 4, "either"),
        ],
        "performances": [
            _c("p-family-recipe", "Describe a family recipe in 30 seconds", "The ingredient nobody can measure counts.", 6, "video"),
            _c("p-lullaby", "Sing or hum a song from your childhood", "Even one line counts.", 7, "video"),
            _c("p-hello-world", "Say hello in as many languages as you can in 15 seconds", "Your own and others you know.", 6, "either"),
            _c("p-group-dance", "Teach the group a dance move from a celebration", "Wedding, festival or Bollywood hook step.", 8, "video"),
        ],
        "roles": [],
    },
}


THAI_CLUB = {
    "id": "thai-club",
    "title": "Thai Club",
    "emoji": "🐘",
    "description": "The original Thai Club mixer: พี่ meet น้อง with Thai-flavored bingo and challenges.",
    "pack": {
        "event_name": content.EVENT_NAME,
        "square_points": content.BINGO_SQUARE_POINTS,
        "line_bonus": content.BINGO_LINE_BONUS,
        "free_square": content.FREE_SQUARE,
        "bingo_traits": list(content.BINGO_TRAITS),
        "challenges": [dict(a) for a in content.CHALLENGES],
        "performances": [dict(a) for a in content.PERFORMANCES],
        "roles": [
            {"key": "phi", "label": "พี่", "hint": "upperclassman"},
            {"key": "nong", "label": "น้อง", "hint": "new member"},
        ],
    },
}


WORK_TEAM = {
    "id": "work-team",
    "title": "Work Team",
    "emoji": "💼",
    "description": "A safe-for-work offsite or office-party game that gets coworkers talking beyond their desks.",
    "pack": {
        "event_name": "Team Mixer",
        "square_points": 1,
        "line_bonus": 5,
        "free_square": "FREE — you made it to the party 💼",
        "bingo_traits": [
            "Has worked here for 5+ years",
            "Joined the team in the last 3 months",
            "Works from home most days",
            "Has never missed a team lunch",
            "Has a desk plant that is still alive",
            "Has a hidden talent coworkers don't know about",
            "Has changed careers",
            "Used to work in a totally different industry",
            "Drinks more than 3 coffees a day",
            "Has a pet that has joined a video call",
            "Speaks 3+ languages",
            "Has lived in 3+ cities",
            "Is the first in their family to work in this field",
            "Has a side project or hobby business",
            "Has volunteered for something this year",
            "Has been to a conference this year",
            "Has the same birthday month as you",
            "Has a favorite keyboard shortcut they swear by",
            "Has been on mute and kept talking",
            "Brings lunch from home every day",
            "Has an unusual commute",
            "Can play a musical instrument",
            "Has a favorite spot in the office or home setup",
            "Knows someone on the team outside of work",
        ],
        "challenges": [
            _c("c-team-selfie", "Selfie with someone from a different team", "Both of you in frame.", 3),
            _c("c-desk-photo", "Photo with someone you've only met on a video call", "Say hello in person.", 4),
            _c("c-group-photo", "Group photo with 5+ people from 3 teams", "Everyone smiling.", 5),
            _c("c-handshake-work", "Create a team handshake with a new colleague", "Show it on camera.", 4, "either"),
            _c("c-lunch-plan", "Plan a lunch with someone you've never worked with", "Photo of the two of you with the plan.", 3),
            _c("c-hype-pose", "Strike a power pose with someone new", "Same pose, same confidence.", 3),
        ],
        "performances": [
            _c("p-office-karaoke", "Sing one line of an office-appropriate song", "Any song, no lyrics sheet.", 8, "video"),
            _c("p-meeting-skit", "Act out a meeting that could have been an email", "Two or more people, 20 seconds.", 8, "video"),
            _c("p-talent", "Show a hidden talent in 15 seconds", "Juggling, singing, anything.", 7, "either"),
        ],
        "roles": [],
    },
}


FRESHERS = {
    "id": "freshers",
    "title": "Freshers Week",
    "emoji": "🎓",
    "description": "Break the ice with new classmates through a bingo and challenge game for the first week of term.",
    "pack": {
        "event_name": "Freshers Mixer",
        "square_points": 1,
        "line_bonus": 5,
        "free_square": "FREE — new chapter 🎓",
        "bingo_traits": [
            "Is from another country",
            "Is from another state or province",
            "Has the same major as you",
            "Has a different major than you",
            "Got lost on campus today",
            "Has a roommate they just met",
            "Is living away from home for the first time",
            "Has already joined a club",
            "Is here on a scholarship",
            "Is a transfer student",
            "Speaks 3+ languages",
            "Plays a sport",
            "Can cook something besides instant noodles",
            "Has a favorite campus coffee spot",
            "Has been to a university party",
            "Has a pet at home they miss",
            "Brought a plant or decoration for their room",
            "Has never done laundry on their own",
            "Is the first in their family at university",
            "Has a birthday this month",
            "Has read the whole syllabus",
            "Plays an instrument",
            "Is a night owl",
            "Is an early riser",
        ],
        "challenges": [
            _c("c-campus-selfie", "Selfie with a landmark and a new classmate", "Find a spot on campus.", 4),
            _c("c-study-buddy", "Find a study buddy and take a photo together", "Swap numbers too.", 3),
            _c("c-group-fresher", "Group photo with 5+ freshers", "Everyone in frame.", 5),
            _c("c-hometown-map", "Photo of two people from the farthest-apart hometowns", "Show them on a map.", 4),
            _c("c-icebreaker-pose", "Team up for a 'first day of school' pose", "Backpack optional.", 3),
            _c("c-meal-plan", "Plan a dining hall meal with someone new", "Photo of both of you.", 3, "either"),
        ],
        "performances": [
            _c("p-intro-30s", "Introduce yourself in 30 seconds", "Name, major, one fun fact.", 6, "video"),
            _c("p-school-song", "Sing a song from your childhood", "Even a line counts.", 7, "video"),
            _c("p-dance-offer", "Do your best dance move from home", "Sudden and full commitment.", 6, "either"),
        ],
        "roles": [
            {"key": "fresher", "label": "Fresher", "hint": "new this term"},
            {"key": "senior", "label": "Senior", "hint": "showing the ropes"},
        ],
    },
}


PACKS = [HOUSE_PARTY, ENTREPRENEURS, ASIAN_DIASPORA, THAI_CLUB, WORK_TEAM, FRESHERS]


def get(pack_id):
    """The PACKS entry with this id, else None."""
    for p in PACKS:
        if p["id"] == pack_id:
            return p
    return None
