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
    {
        "title": "The Cartographer's Daughter",
        "runtime": 132,
        "certification": "UA13+",
        "status": "now_showing",
        "language": "en",
        "genres": ["Drama", "Adventure", "Mystery"],
        "tagline": "Every map hides the place someone did not want found.",
        "synopsis": (
            "When a reclusive mapmaker dies leaving behind an atlas of places that do not exist, "
            "his estranged daughter Ilse returns to the coastal town she fled at seventeen to settle "
            "his affairs. What begins as an inventory of paper becomes an excavation of memory: each "
            "invented island corresponds to a year of her childhood, each phantom river to a promise "
            "he broke. Following the atlas north into fjord country, Ilse finds a community that has "
            "quietly organised itself around her father's fictions, and must decide whether the truth "
            "she came for is worth the world it would dismantle. A patient, luminous drama about "
            "inheritance, cartography, and the maps we draw to survive our parents."
        ),
        "rating": 8.1,
        "attributes": {"mood": ["contemplative", "melancholy", "hopeful"], "pace": "slow", "themes": ["family", "grief", "identity"], "ending": "bittersweet"},
    },
    {
        "title": "Vellore Express",
        "runtime": 148,
        "certification": "UA16+",
        "status": "now_showing",
        "language": "ta",
        "genres": ["Action", "Thriller", "Crime"],
        "tagline": "Eleven coaches. Four hours. One way off this train.",
        "synopsis": (
            "A decommissioned night train carrying a sealed evidence locker from Chennai to Vellore "
            "becomes a moving battleground when the constable escorting it realises three of his own "
            "unit are on the payroll of the man the evidence would convict. Shot almost entirely in "
            "real carriages, the film unfolds in near real time across eleven coaches, each a distinct "
            "arena with its own rules, allies and exits. Beneath the propulsive set pieces is a "
            "sharper argument about institutional rot and the ordinary people who decide, on a "
            "particular night, not to look away."
        ),
        "rating": 8.6,
        "attributes": {"mood": ["tense", "propulsive"], "pace": "fast", "themes": ["corruption", "loyalty", "justice"], "ending": "decisive"},
    },
    {
        "title": "Nimbus",
        "runtime": 116,
        "certification": "U",
        "status": "now_showing",
        "language": "en",
        "genres": ["Animation", "Family", "Fantasy"],
        "tagline": "Some clouds are just looking for somewhere to rain.",
        "synopsis": (
            "In a sky-city where every citizen is assigned a cloud at birth, a small storm cloud named "
            "Nimbus is judged defective for raining at the wrong moments -- at goodbyes, at kindnesses, "
            "at the exact instant someone needs to be told they matter. Exiled to the drylands below, "
            "Nimbus meets a girl tending a garden that has not seen water in nine years. Hand-painted "
            "in a watercolour style that lets weather behave like emotion, the film is a generous, "
            "very funny argument that the thing you were told is wrong with you may be the only useful "
            "thing about you."
        ),
        "rating": 8.9,
        "attributes": {"mood": ["warm", "uplifting", "gentle"], "pace": "medium", "themes": ["belonging", "difference", "friendship"], "ending": "happy"},
    },
    {
        "title": "Deep Field",
        "runtime": 155,
        "certification": "UA13+",
        "status": "now_showing",
        "language": "en",
        "genres": ["Sci-Fi", "Drama", "Mystery"],
        "tagline": "The universe answered. It just took four hundred years.",
        "synopsis": (
            "Dr Amara Osei spends her career pointing an array at an empty patch of sky, chasing a "
            "signal nobody else believes in. When the reply arrives it is not a message but a "
            "correction -- a revised value for a physical constant humanity has had wrong since Newton. "
            "Rebuilding physics from that single number costs Amara her collaborators, her marriage "
            "and eventually her certainty about which version of events she has actually lived. "
            "A rigorous, cool-headed science-fiction drama that treats scientific method as narrative "
            "structure and asks what it costs to be the person who was right too early."
        ),
        "rating": 8.4,
        "attributes": {"mood": ["cerebral", "awe", "isolating"], "pace": "slow", "themes": ["obsession", "discovery", "sacrifice"], "ending": "ambiguous"},
    },
    {
        "title": "Ghar Wapsi",
        "runtime": 139,
        "certification": "U",
        "status": "now_showing",
        "language": "hi",
        "genres": ["Comedy", "Drama", "Family"],
        "tagline": "You can go home again. You just can't get any peace there.",
        "synopsis": (
            "After eleven years in Toronto, Rhea returns to her family's Lucknow home for what she "
            "insists is a two-week visit, and finds her parents have rented out her childhood bedroom, "
            "her brother has moved his failing catering business into the courtyard, and the entire "
            "mohalla has opinions about her unmarried status. Warm, densely populated and very funny, "
            "the film builds from farce into something quietly serious about the arithmetic of "
            "migration: what you gain, what you leave, and the people who kept the house standing "
            "while you were gone."
        ),
        "rating": 7.8,
        "attributes": {"mood": ["warm", "funny", "nostalgic"], "pace": "medium", "themes": ["family", "migration", "belonging"], "ending": "happy"},
    },
    {
        "title": "The Salt Kilns",
        "runtime": 127,
        "certification": "A",
        "status": "now_showing",
        "language": "ml",
        "genres": ["Horror", "Mystery", "Drama"],
        "tagline": "The village kept the fires lit for a reason.",
        "synopsis": (
            "A structural surveyor arrives at an abandoned coastal saltworks to certify it for "
            "demolition and finds the kilns still warm, though the village has been empty for six "
            "years. The further she reads into the works ledger, the clearer it becomes that the "
            "fires were maintained as an obligation rather than an industry. Slow-burning folk horror "
            "built almost entirely from sound design and negative space, more interested in the "
            "economics of a bargain than in the thing the bargain was made with."
        ),
        "rating": 7.6,
        "attributes": {"mood": ["dread", "oppressive", "eerie"], "pace": "slow", "themes": ["folklore", "sacrifice", "isolation"], "ending": "bleak"},
    },
    {
        "title": "Powerplay",
        "runtime": 141,
        "certification": "UA13+",
        "status": "now_showing",
        "language": "te",
        "genres": ["Sport", "Drama", "Biography"],
        "tagline": "Second innings are earned, not given.",
        "synopsis": (
            "Banned for three years over a spot-fixing allegation he has always denied, a former "
            "state cricket captain takes the only job available to him: coaching an under-19 girls' "
            "side in a district that has never sent a player past the state trials. The cricket is "
            "shot with real technical seriousness -- field settings matter, the wicket changes across "
            "sessions -- and the drama refuses easy redemption, staying interested in the harder "
            "question of what a man owes the people he let down."
        ),
        "rating": 8.2,
        "attributes": {"mood": ["rousing", "determined"], "pace": "medium", "themes": ["redemption", "mentorship", "class"], "ending": "triumphant"},
    },
    {
        "title": "Low Tide, Late Light",
        "runtime": 104,
        "certification": "UA13+",
        "status": "now_showing",
        "language": "kn",
        "genres": ["Romance", "Drama"],
        "tagline": "Two weeks, one coastline, no promises.",
        "synopsis": (
            "A marine biologist counting a collapsing mussel population and a session musician "
            "avoiding a wedding he does not want share a rented house on the Karwar coast for a "
            "fortnight. Almost nothing happens: they survey, they cook, they argue about whether "
            "measurement is a form of hope. Shot on long lenses in available light, the film is a "
            "study of two careful people deciding, slowly and with full information, to risk being "
            "known."
        ),
        "rating": 7.9,
        "attributes": {"mood": ["tender", "quiet", "wistful"], "pace": "slow", "themes": ["intimacy", "ecology", "choice"], "ending": "open"},
    },
    {
        "title": "Iron Meridian",
        "runtime": 168,
        "certification": "UA16+",
        "status": "now_showing",
        "language": "en",
        "genres": ["Action", "War", "Adventure"],
        "tagline": "The line held. That was the whole plan.",
        "synopsis": (
            "1943, a rail junction in the Caucasus that both armies need and neither can supply. "
            "A signals officer with no combat experience inherits command of a scratch garrison of "
            "engineers, cooks and walking wounded, and holds a position for nine days using timetables, "
            "demolition charges and an increasingly creative relationship with the truth. Enormous in "
            "scale but unusually specific in its tactics, the film treats logistics as heroism and "
            "refuses to pretend that surviving and winning are the same thing."
        ),
        "rating": 8.7,
        "attributes": {"mood": ["grim", "stirring", "tense"], "pace": "medium", "themes": ["duty", "attrition", "leadership"], "ending": "costly"},
    },
    {
        "title": "Paper Tigers",
        "runtime": 121,
        "certification": "UA13+",
        "status": "coming_soon",
        "language": "hi",
        "genres": ["Comedy", "Crime"],
        "tagline": "They were terrible at crime. They were worse at quitting.",
        "synopsis": (
            "Three laid-off print-shop employees discover their decommissioned press is the last "
            "machine in the state capable of reproducing a particular security watermark, and talk "
            "themselves into exactly one job. Every subsequent decision is worse than the one before "
            "it. A fast, dry, ensemble crime comedy about competence in the wrong domain, and the "
            "specific dignity of people who are extremely good at an obsolete thing."
        ),
        "rating": None,
        "attributes": {"mood": ["dry", "farcical", "buoyant"], "pace": "fast", "themes": ["obsolescence", "friendship", "greed"], "ending": "unknown"},
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
