"""Static seed content.

Kept as plain data, separate from the loading logic, so it is easy to extend
without touching the code that inserts it. The synopses are deliberately rich --
they are the text the embedding pipeline works on, and thin descriptions make
semantic search look broken when the real fault is the corpus.
"""

from __future__ import annotations

CITIES = [
    {"name": "Bengaluru", "slug": "bengaluru", "state": "Karnataka", "lat": 12.9716, "lon": 77.5946, "order": 1},
    {"name": "Mumbai", "slug": "mumbai", "state": "Maharashtra", "lat": 19.0760, "lon": 72.8777, "order": 2},
    {"name": "Hyderabad", "slug": "hyderabad", "state": "Telangana", "lat": 17.3850, "lon": 78.4867, "order": 3},
]

LANGUAGES = [
    {"code": "en", "name": "English", "native": "English"},
    {"code": "hi", "name": "Hindi", "native": "हिन्दी"},
    {"code": "kn", "name": "Kannada", "native": "ಕನ್ನಡ"},
    {"code": "ta", "name": "Tamil", "native": "தமிழ்"},
    {"code": "te", "name": "Telugu", "native": "తెలుగు"},
    {"code": "ml", "name": "Malayalam", "native": "മലയാളം"},
]

GENRES = [
    "Action", "Adventure", "Animation", "Biography", "Comedy", "Crime",
    "Drama", "Family", "Fantasy", "Horror", "Musical", "Mystery",
    "Romance", "Sci-Fi", "Sport", "Thriller", "War",
]

FORMATS = [
    {"code": "2D", "name": "2D", "surcharge_minor": 0, "order": 1},
    {"code": "3D", "name": "3D", "surcharge_minor": 5000, "order": 2},
    {"code": "IMAX", "name": "IMAX 2D", "surcharge_minor": 15000, "order": 3},
    {"code": "IMAX3D", "name": "IMAX 3D", "surcharge_minor": 20000, "order": 4},
    {"code": "4DX", "name": "4DX", "surcharge_minor": 25000, "order": 5},
]

# How each brand positions itself on price. Applied to the seat-category
# defaults, which are per cinema -- this is the whole point of the pricing
# model: a movie has no price, a hall does.
BRAND_PRICE_FACTOR = {
    "PVR": 1.35,        # premium multiplex
    "INOX": 1.0,        # mainstream
    "Cinepolis": 0.75,  # value
}

# code, name, default price (paise), display order, colour
SEAT_CATEGORIES = [
    ("CLASSIC", "Classic", 18000, 1, "#64748b"),
    ("PRIME", "Prime", 26000, 2, "#0ea5e9"),
    ("RECLINER", "Recliner", 45000, 3, "#f59e0b"),
]

CINEMA_BLUEPRINTS = [
    {"brand": "PVR", "suffix": "Forum Mall", "locality": "Koramangala", "amenities": ["Dolby Atmos", "Parking", "F&B", "Wheelchair Access"]},
    {"brand": "INOX", "suffix": "Garuda Mall", "locality": "Magrath Road", "amenities": ["4DX", "Parking", "F&B"]},
    {"brand": "Cinepolis", "suffix": "Nexus Mall", "locality": "Whitefield", "amenities": ["IMAX", "Recliners", "F&B", "Valet"]},
]

MOVIES = [
    # ---------------------------------------------------------- now showing ---
    {
        "title": "Avengers Endgame: Encore",
        "runtime": 189,
        "certification": "UA13+",
        "status": "now_showing",
        "language": "en",
        "genres": ["Action", "Adventure", "Sci-Fi"],
        "tagline": "The end, played once more.",
        "synopsis": (
            "A remastered return to the battle that closed the Infinity Saga, re-graded for laser "
            "projection and remixed for Atmos, with restored footage assembled from the original "
            "production reels. Presented in IMAX 3D and 4DX at selected screens."
        ),
        "rating": 8.4,
        "attributes": {"mood": ["epic", "nostalgic"], "pace": "fast", "themes": ["sacrifice", "legacy", "time"], "ending": "decisive"},
    },
    {
        "title": "Avengers: Doomsday",
        "runtime": 174,
        "certification": "UA13+",
        "status": "now_showing",
        "language": "en",
        "genres": ["Action", "Adventure", "Sci-Fi"],
        "tagline": "A throne above every world.",
        "synopsis": (
            "Doctor Doom moves against a fractured multiverse, and the surviving Avengers must "
            "assemble across timelines that no longer agree on who they are. Directed by the Russo "
            "brothers as the next chapter of the Multiverse Saga."
        ),
        "rating": 8.7,
        "attributes": {"mood": ["tense", "epic"], "pace": "fast", "themes": ["power", "identity", "multiverse"], "ending": "open"},
    },
    {
        "title": "Ramayana",
        "runtime": 195,
        "certification": "U",
        "status": "now_showing",
        "language": "hi",
        "genres": ["Action", "Adventure", "Drama"],
        "tagline": "The oldest story, told at last in full.",
        "synopsis": (
            "Nitesh Tiwari's large-scale mythological retelling of the Ramayana, following Rama's "
            "exile, Sita's abduction and the war against Ravana. Mounted as the first of two parts, "
            "with a score by Hans Zimmer and A. R. Rahman."
        ),
        "rating": 8.9,
        "attributes": {"mood": ["reverent", "epic"], "pace": "medium", "themes": ["duty", "devotion", "war"], "ending": "decisive"},
    },
    {
        "title": "Chiranjeevi Hanuman: The Eternal",
        "runtime": 142,
        "certification": "U",
        "status": "now_showing",
        "language": "te",
        "genres": ["Animation", "Action", "Fantasy"],
        "tagline": "Strength was never the gift. Faith was.",
        "synopsis": (
            "An animated epic on the life of Hanuman, from the boyhood that cost him the memory of "
            "his own power to the leap across the ocean. Hand-keyed action sequences and a devotional "
            "score aimed squarely at a family audience."
        ),
        "rating": 8.2,
        "attributes": {"mood": ["uplifting", "reverent"], "pace": "medium", "themes": ["devotion", "courage", "humility"], "ending": "happy"},
    },
    {
        "title": "Dada - The Sourav Ganguly Story",
        "runtime": 158,
        "certification": "U",
        "status": "now_showing",
        "language": "hi",
        "genres": ["Biography", "Drama", "Sport"],
        "tagline": "They dropped him. He came back as captain.",
        "synopsis": (
            "The story of Sourav Ganguly -- the early Test hundred at Lord's, the years in the "
            "wilderness, and the captaincy that rebuilt Indian cricket's belief in itself after the "
            "match-fixing years. A biopic about temperament as much as talent."
        ),
        "rating": 8.0,
        "attributes": {"mood": ["stirring", "defiant"], "pace": "medium", "themes": ["resilience", "leadership", "nation"], "ending": "triumphant"},
    },
    {
        "title": "The Paradise",
        "runtime": 165,
        "certification": "UA16+",
        "status": "now_showing",
        "language": "te",
        "genres": ["Action", "Drama", "Crime"],
        "tagline": "Every empire is built on somebody's ground.",
        "synopsis": (
            "Srikanth Odela's raw, rain-soaked drama set in the settlements on a city's industrial "
            "edge, where a young man's rise through the local order forces a reckoning with the "
            "community that made him. Nani in a deliberately unglamorous lead turn."
        ),
        "rating": 8.5,
        "attributes": {"mood": ["gritty", "intense"], "pace": "medium", "themes": ["class", "belonging", "violence"], "ending": "bittersweet"},
    },

    # ------------------------------------------------------------- upcoming ---
    {
        "title": "Monsoon Circuit",
        "runtime": 137,
        "certification": "UA16+",
        "status": "coming_soon",
        "language": "ta",
        "genres": ["Action", "Thriller"],
        "tagline": "Four days of rain. One road out.",
        "synopsis": (
            "A long-distance lorry driver agrees to move one unmarked crate down the ghat road during "
            "the heaviest monsoon in forty years, and discovers by the second checkpoint that "
            "everyone waiting for him already knows his name."
        ),
        "rating": 0.0,
        "attributes": {"mood": ["tense", "propulsive"], "pace": "fast", "themes": ["survival", "trust"], "ending": "open"},
    },
    {
        "title": "The Last Ledger",
        "runtime": 129,
        "certification": "UA13+",
        "status": "coming_soon",
        "language": "ml",
        "genres": ["Crime", "Drama", "Mystery"],
        "tagline": "Some books are meant to be balanced, not read.",
        "synopsis": (
            "A retired temple accountant is asked to audit sixty years of offerings and finds a "
            "second set of entries in his own late father's hand. A quiet procedural about "
            "inheritance and the arithmetic of guilt."
        ),
        "rating": 0.0,
        "attributes": {"mood": ["contemplative", "uneasy"], "pace": "slow", "themes": ["family", "corruption", "faith"], "ending": "ambiguous"},
    },
    {
        "title": "Starlight Bazaar",
        "runtime": 148,
        "certification": "U",
        "status": "coming_soon",
        "language": "hi",
        "genres": ["Musical", "Romance", "Comedy"],
        "tagline": "Open all night, for anyone still hoping.",
        "synopsis": (
            "A failing night market gets one more season when a wedding singer and a fruit-seller's "
            "daughter agree to stage a show nobody asked for. Eleven original numbers, shot almost "
            "entirely between midnight and dawn."
        ),
        "rating": 0.0,
        "attributes": {"mood": ["warm", "playful"], "pace": "medium", "themes": ["community", "love", "reinvention"], "ending": "happy"},
    },
    {
        "title": "Iron Coast",
        "runtime": 161,
        "certification": "UA16+",
        "status": "coming_soon",
        "language": "en",
        "genres": ["War", "Drama"],
        "tagline": "Hold the beach. Nothing else was ordered.",
        "synopsis": (
            "Two hundred men are told to hold a stretch of shingle for six hours. The relief does not "
            "come, and the order is never rescinded. A study of obedience shot in continuous takes "
            "on the coastline where it happened."
        ),
        "rating": 0.0,
        "attributes": {"mood": ["bleak", "tense"], "pace": "slow", "themes": ["duty", "futility", "brotherhood"], "ending": "bleak"},
    },
    # --------------------------------------------------- additional catalogue ---
    {
        "title": "Kaveri Nights",
        "runtime": 141, "certification": "UA13+", "status": "now_showing",
        "language": "kn", "genres": ["Romance", "Drama", "Musical"],
        "tagline": "The river remembers what the city forgot.",
        "synopsis": (
            "A Bengaluru sound engineer returns to her grandmother's village to record the last "
            "surviving singers of a boat-song tradition, and finds the man she left behind running "
            "the ferry. A gentle, music-soaked romance about the cost of leaving and the harder cost "
            "of coming back."
        ),
        "rating": 7.8,
        "attributes": {"mood": ["warm", "wistful"], "pace": "slow", "themes": ["home", "music", "love"], "ending": "hopeful"},
    },
    {
        "title": "Nine Yards of Silence",
        "runtime": 127, "certification": "UA16+", "status": "now_showing",
        "language": "ta", "genres": ["Drama", "Mystery"],
        "tagline": "She wove the whole story into it.",
        "synopsis": (
            "When a master weaver dies mid-commission, her apprentice discovers the unfinished sari "
            "encodes forty years of the village's secrets in its border pattern. A quiet mystery "
            "about craft as testimony."
        ),
        "rating": 8.3,
        "attributes": {"mood": ["contemplative", "uneasy"], "pace": "slow", "themes": ["craft", "memory", "truth"], "ending": "ambiguous"},
    },
    {
        "title": "Tiffin Run",
        "runtime": 118, "certification": "U", "status": "now_showing",
        "language": "hi", "genres": ["Comedy", "Drama", "Family"],
        "tagline": "Two hundred thousand lunches. Zero mistakes. Until today.",
        "synopsis": (
            "A Mumbai dabbawala with an unbroken thirty-year delivery record misroutes a single "
            "tiffin, and spends one increasingly farcical day chasing it across the city before the "
            "afternoon shift ends. Warm, fast, and quietly furious about who the city runs on."
        ),
        "rating": 8.1,
        "attributes": {"mood": ["playful", "warm"], "pace": "fast", "themes": ["work", "pride", "city"], "ending": "happy"},
    },
    {
        "title": "The Quiet Coast",
        "runtime": 134, "certification": "UA13+", "status": "now_showing",
        "language": "ml", "genres": ["Thriller", "Drama"],
        "tagline": "Nothing washes up here by accident.",
        "synopsis": (
            "A coastal police constable two months from retirement is handed a drowning that the "
            "district would rather file as an accident. Shot in fishing villages during the off "
            "season, with an ending that refuses to comfort anyone."
        ),
        "rating": 8.4,
        "attributes": {"mood": ["tense", "bleak"], "pace": "medium", "themes": ["duty", "corruption", "class"], "ending": "bleak"},
    },
    {
        "title": "Rocket Boys of Ward 12",
        "runtime": 112, "certification": "U", "status": "now_showing",
        "language": "te", "genres": ["Family", "Comedy", "Adventure"],
        "tagline": "Aim for orbit. Settle for the water tank.",
        "synopsis": (
            "Four children in a Hyderabad municipal ward build a rocket from scrap to win a science "
            "fair they were not invited to. A generous, very funny film about improvisation and the "
            "adults who eventually get out of the way."
        ),
        "rating": 8.0,
        "attributes": {"mood": ["uplifting", "playful"], "pace": "fast", "themes": ["friendship", "ingenuity", "class"], "ending": "happy"},
    },
    {
        "title": "Ledger of Small Debts",
        "runtime": 145, "certification": "UA16+", "status": "now_showing",
        "language": "hi", "genres": ["Crime", "Thriller"],
        "tagline": "He forgave everyone. He forgot no one.",
        "synopsis": (
            "A neighbourhood moneylender's death exposes a notebook of favours owed across three "
            "decades, and everyone named in it has a reason to want the pages gone. A slow-burn "
            "crime drama structured as a series of collections."
        ),
        "rating": 7.9,
        "attributes": {"mood": ["gritty", "tense"], "pace": "medium", "themes": ["debt", "loyalty", "revenge"], "ending": "decisive"},
    },
    {
        "title": "Signal Lost",
        "runtime": 108, "certification": "UA16+", "status": "coming_soon",
        "language": "en", "genres": ["Horror", "Mystery"],
        "tagline": "The tower stopped transmitting in 1974. Something still answers.",
        "synopsis": (
            "Two engineers sent to decommission a Himalayan relay station begin receiving replies to "
            "test broadcasts nobody else can hear. A restrained, largely diegetic horror film built "
            "almost entirely out of sound."
        ),
        "rating": 0.0,
        "attributes": {"mood": ["dread", "claustrophobic"], "pace": "slow", "themes": ["isolation", "sound", "madness"], "ending": "open"},
    },
    {
        "title": "Second Innings",
        "runtime": 132, "certification": "U", "status": "coming_soon",
        "language": "hi", "genres": ["Sport", "Comedy", "Drama"],
        "tagline": "Average age fifty-eight. Ambition unchanged.",
        "synopsis": (
            "A retired bank clerk assembles a veterans' cricket side from his housing society to "
            "contest a tournament designed for men half their age. Broad, affectionate, and sharper "
            "than it looks about what retirement takes away."
        ),
        "rating": 0.0,
        "attributes": {"mood": ["warm", "stirring"], "pace": "medium", "themes": ["ageing", "friendship", "sport"], "ending": "triumphant"},
    },
    {
        "title": "The Cartographer of Ash",
        "runtime": 156, "certification": "UA16+", "status": "coming_soon",
        "language": "en", "genres": ["Sci-Fi", "Drama"],
        "tagline": "Someone has to write down what was here.",
        "synopsis": (
            "In the fifth year after the fires, a surveyor walks the evacuated interior mapping what "
            "remains, and keeps meeting a woman who insists the settlements are still inhabited. A "
            "spare, walking-paced science fiction film about record-keeping as grief."
        ),
        "rating": 0.0,
        "attributes": {"mood": ["bleak", "contemplative"], "pace": "slow", "themes": ["loss", "memory", "duty"], "ending": "ambiguous"},
    },
    {
        "title": "Marigold Circuit Court",
        "runtime": 124, "certification": "U", "status": "coming_soon",
        "language": "kn", "genres": ["Comedy", "Drama"],
        "tagline": "Order in the courtyard.",
        "synopsis": (
            "A district judge posted to a town with no functioning courthouse holds proceedings in a "
            "flower market, and discovers that justice conducted in public view behaves entirely "
            "differently. A comedy with a serious spine."
        ),
        "rating": 0.0,
        "attributes": {"mood": ["playful", "warm"], "pace": "medium", "themes": ["justice", "community", "bureaucracy"], "ending": "hopeful"},
    },
]

PEOPLE = [
    ("Ilse Marchetti", "cast"), ("Ravi Anantharaman", "cast"), ("Nandita Bose", "cast"),
    ("Amara Osei", "cast"), ("Karan Vaz", "cast"), ("Meera Pillai", "cast"),
    ("Joseph Kuruvilla", "crew"), ("Sarita Rao", "crew"), ("Daniel Okonkwo", "crew"),
    ("Priya Raghunathan", "crew"), ("Tobias Lindqvist", "crew"), ("Anjali Sequeira", "cast"),
]

FNB_ITEMS = [
    ("Salted Popcorn (Large)", "popcorn", 32000, True),
    ("Cheese Popcorn (Medium)", "popcorn", 28000, True),
    ("Caramel Popcorn (Large)", "popcorn", 35000, True),
    ("Pepsi (Large)", "beverages", 26000, True),
    ("Cold Coffee", "beverages", 22000, True),
    ("Nachos with Salsa", "snacks", 30000, True),
    ("Veg Puff", "snacks", 12000, True),
    ("Chicken Roll", "snacks", 18000, False),
    ("Combo: Popcorn + 2 Pepsi", "combos", 55000, True),
    ("Combo: Nachos + Cold Coffee", "combos", 48000, True),
]

OFFERS = [
    {
        "code": "FIRSTSHOW", "name": "20% off your first booking",
        "type": "percent", "percent": 20, "max_discount_minor": 15000,
        "min_order_minor": 20000, "per_user": 1, "total": 10000,
        "description": "New to CineAI? Take 20% off your first booking, up to Rs 150.",
        "conditions": {},
    },
    {
        "code": "WEEKDAY100", "name": "Rs 100 off on weekday shows",
        "type": "flat", "flat_off_minor": 10000,
        "min_order_minor": 50000, "per_user": 5, "total": None,
        "description": "Flat Rs 100 off Monday to Thursday shows on orders above Rs 500.",
        "conditions": {"days_of_week": [0, 1, 2, 3]},
    },
    {
        "code": "IMAXTREAT", "name": "15% off IMAX",
        "type": "percent", "percent": 15, "max_discount_minor": 30000,
        "min_order_minor": 60000, "per_user": 2, "total": 5000,
        "description": "15% off IMAX and IMAX 3D shows, up to Rs 300.",
        "conditions": {"formats": ["IMAX", "IMAX3D"]},
    },
]
