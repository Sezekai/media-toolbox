"""Colour themes. Each one is based on a reference design from the Appearance brief."""

DEFAULT_THEME = "Default Green"

# Keys are the colour names used across the app. GREEN is the main action colour and ON_GREEN is the text on it.
COLOUR_NAMES = (
    "APP_BG", "SIDEBAR", "CARD", "CARD_BORDER", "FIELD", "TRACK", "NAV_HOVER", "NAV_ACTIVE",
    "TEXT", "MUTED", "GREEN", "GREEN_HOVER", "ON_GREEN", "SECONDARY", "SECONDARY_HOVER",
    "RED", "RED_HOVER", "SELECT", "HEADING",
)

PALETTES = {
    "Default Green": dict(
        APP_BG="#0d0d0f", SIDEBAR="#121215", CARD="#1b1b20", CARD_BORDER="#2a2a31", FIELD="#101014",
        TRACK="#2a2a33", NAV_HOVER="#1f1f25", NAV_ACTIVE="#2b2b34", TEXT="#f5f5f7", MUTED="#a4a4ae",
        GREEN="#1f9d55", GREEN_HOVER="#27b865", ON_GREEN="#ffffff", SECONDARY="#2b2b33",
        SECONDARY_HOVER="#3a3a44", RED="#c0392b", RED_HOVER="#d94b3c", SELECT="#2e4a70", HEADING="#23232a",
    ),
    # Reference: the "Nova" profile screen (black with gold rings and accents)
    "Gold Night": dict(
        APP_BG="#0a0a0c", SIDEBAR="#0f0f12", CARD="#17161a", CARD_BORDER="#2e2a20", FIELD="#0d0d10",
        TRACK="#2a2620", NAV_HOVER="#1d1b17", NAV_ACTIVE="#2c2616", TEXT="#f7f1e3", MUTED="#aa9f84",
        GREEN="#e0a526", GREEN_HOVER="#f2b938", ON_GREEN="#171204", SECONDARY="#24232a",
        SECONDARY_HOVER="#33313b", RED="#c0392b", RED_HOVER="#d94b3c", SELECT="#40341a", HEADING="#1a191e",
    ),
    # Reference: the "Discipline" dashboard (black with lime green)
    "Discipline Lime": dict(
        APP_BG="#0b0d0a", SIDEBAR="#10130e", CARD="#161a13", CARD_BORDER="#26301f", FIELD="#0c0f0a",
        TRACK="#232b1d", NAV_HOVER="#1a2016", NAV_ACTIVE="#26331b", TEXT="#f2f5ee", MUTED="#9aa58f",
        GREEN="#8fd13a", GREEN_HOVER="#a6e556", ON_GREEN="#0d1205", SECONDARY="#20281b",
        SECONDARY_HOVER="#2e3a26", RED="#c0392b", RED_HOVER="#d94b3c", SELECT="#2f4a1c", HEADING="#161c12",
    ),
    # Reference: the "Win-back journey" flowchart (black with orange)
    "Ember Orange": dict(
        APP_BG="#0a0a0b", SIDEBAR="#0e0e10", CARD="#161618", CARD_BORDER="#2c2622", FIELD="#0d0d0e",
        TRACK="#2a2a2c", NAV_HOVER="#1c1c1f", NAV_ACTIVE="#2b1d13", TEXT="#f5f5f5", MUTED="#9d9da2",
        GREEN="#ff7a1a", GREEN_HOVER="#ff9440", ON_GREEN="#1a0c02", SECONDARY="#242427",
        SECONDARY_HOVER="#323237", RED="#d6452f", RED_HOVER="#e8604a", SELECT="#5a2e10", HEADING="#18181b",
    ),
    # Reference: the BitTorrent sidebar (dark glass with violet)
    "Violet Glass": dict(
        APP_BG="#15161a", SIDEBAR="#1c1d23", CARD="#24252c", CARD_BORDER="#34353f", FIELD="#17181e",
        TRACK="#2d2e38", NAV_HOVER="#2a2b34", NAV_ACTIVE="#34294c", TEXT="#f4f4f8", MUTED="#a0a3b0",
        GREEN="#8b5cf6", GREEN_HOVER="#a382ff", ON_GREEN="#ffffff", SECONDARY="#2c2d37",
        SECONDARY_HOVER="#3b3c48", RED="#c0392b", RED_HOVER="#d94b3c", SELECT="#3b2f63", HEADING="#1f2028",
    ),
    # Reference: the YouTube sidebar (rose and deep red glass)
    "Rose Glass": dict(
        APP_BG="#2a1215", SIDEBAR="#381619", CARD="#4a2024", CARD_BORDER="#6b3138", FIELD="#2a1215",
        TRACK="#5a2a2f", NAV_HOVER="#5c262b", NAV_ACTIVE="#7a3038", TEXT="#fff5f5", MUTED="#f0c6c8",
        GREEN="#e8505b", GREEN_HOVER="#f2737c", ON_GREEN="#ffffff", SECONDARY="#5a2a2f",
        SECONDARY_HOVER="#6e343a", RED="#b8323c", RED_HOVER="#cc4049", SELECT="#8a3a42", HEADING="#3a1619",
    ),
    # Reference: the eco sidebar (deep emerald with mint)
    "Emerald Leaf": dict(
        APP_BG="#06261e", SIDEBAR="#0a3327", CARD="#0f3d2f", CARD_BORDER="#1d5a48", FIELD="#072a20",
        TRACK="#1b5241", NAV_HOVER="#144c3b", NAV_ACTIVE="#1f6150", TEXT="#f2fff9", MUTED="#a9d8c6",
        GREEN="#3ddc97", GREEN_HOVER="#5ce8ad", ON_GREEN="#03261b", SECONDARY="#145340",
        SECONDARY_HOVER="#1d6650", RED="#e05d5d", RED_HOVER="#ea7070", SELECT="#1f6b55", HEADING="#0a3327",
    ),
    # Reference: the music player (midnight navy with lavender)
    "Midnight Aurora": dict(
        APP_BG="#0e1020", SIDEBAR="#141731", CARD="#1c2040", CARD_BORDER="#2e3564", FIELD="#121530",
        TRACK="#2a3062", NAV_HOVER="#232854", NAV_ACTIVE="#34396e", TEXT="#f1f2ff", MUTED="#a6abd6",
        GREEN="#b9c4ff", GREEN_HOVER="#d0d8ff", ON_GREEN="#0e1020", SECONDARY="#262b57",
        SECONDARY_HOVER="#343b72", RED="#e0606a", RED_HOVER="#ea7680", SELECT="#3c4590", HEADING="#171b3b",
    ),
}

# One size setting scales text and elements together. 100% is the default layout.
SIZE_CHOICES = {(f"{p}% (normal)" if p == 100 else f"{p}%"): p / 100 for p in range(50, 165, 5)}

# Corner styles scale every rounded corner by the same factor.
CORNER_STYLES = {"Square": 0.0, "Soft": 0.5, "Rounded": 1.0, "Very rounded": 1.5}

# Font families offered in the Appearance page (only the ones installed on the PC are shown)
FONT_CHOICES = ["Inter", "Segoe UI", "Bahnschrift", "Calibri", "Arial", "Verdana", "Trebuchet MS", "Georgia"]
