"""Single source of truth for every colour in the app.

Colour used to be declared twice — CSS custom properties for the chrome, hex
literals for the Plotly figures — and the two drifted. Everything is declared
here now, and base.html renders its `:root` blocks from these dicts.

Everything is derived from one hue
---------------------------------
Every value below was generated in LCh and checked rather than picked by eye
(CIEDE2000 separation, WCAG contrast) — six hand-picked attempts had failed that
check. The two exceptions are --page and --surface-1, which are held at the
original neutrals on purpose; see below.

  * The **grounds stay neutral** — white paper, near-black — by explicit choice.
    They were tinted with the brand hue at one point and reverted: tinted grounds
    change the feel of every screen, and that was not wanted here.
  * The **greys between them** (grid, baseline, text) still carry the brand hue at
    low chroma. That is the difference between "a warm grey" and "this app's grey",
    and it does not disturb the page the way a tinted ground does.
  * Every **data colour** shares one lightness/chroma register and differs only in
    hue, so the eight read as a family instead of eight shouts. Their hues are
    evenly spread: flattened into a single register, two colours separate only by
    hue angle, and the inherited set was lopsided (orange and red 18 degrees
    apart) and collapsed.
  * **Gain and loss** answer to text contrast instead, being read as words.

Asset classes group into two families, because they really do, and because the
app's whole argument is about that boundary:

    teal    Actions, Obligations   money exposed to the market
    neutral Fonds Euros, Livrets   capital-guaranteed money
    amber   Autres                 gold, outside both

The guaranteed pair is the brand's own neutral, on purpose: guaranteed money
renders as the app's furniture. It sits nearer the brand hue than anything else
does, and what keeps them apart is chroma (9 against 61) plus role — a pale dot
in a table is never mistaken for a saturated corner mark.
"""

# --------------------------------------------------------------------- brand
BRAND_LIGHT = "#1a2ba6"
BRAND_DARK = "#a491ff"   # was a chroma-42 wash; the tinted grounds
                                        # let it carry real colour on near-black

# ---------------------------------------------------------------- data hues
# Per theme: one lightness/chroma register, hues evenly spread.
DATA_LIGHT = {
    "blue": "#0081cc", "orange": "#b56928",
    "aqua": "#048c7d", "yellow": "#8b7d12",
    "magenta": "#c9518a", "green": "#3c8c3d",
    "purple": "#a861b6", "red": "#ce5458",
}
DATA_DARK = {
    "blue": "#70aff3", "orange": "#de9d6c",
    "aqua": "#36beac", "yellow": "#bcab62",
    "magenta": "#eb8fb6", "green": "#80b97b",
    "purple": "#cf98d8", "red": "#f1908e",
}
DATA_TOKENS = {name: f"--data-{name}" for name in DATA_LIGHT}

# Figures reference these as var(--data-x) so they follow the theme; the browser
# resolves them at render time (see resolveCssVars in base.html).
COLOR_BLUE = "var(--data-blue)"
COLOR_ORANGE = "var(--data-orange)"
COLOR_AQUA = "var(--data-aqua)"
COLOR_YELLOW = "var(--data-yellow)"
COLOR_MAGENTA = "var(--data-magenta)"
COLOR_GREEN = "var(--data-green)"
COLOR_PURPLE = "var(--data-purple)"
COLOR_RED = "var(--data-red)"
COLOR_MUTED = "var(--text-muted)"
COLOR_GOOD = "var(--good)"
COLOR_CRITICAL = "var(--critical)"
COLOR_BRAND = "var(--brand)"

# Fixed-order categorical palette: colour follows the entity, never its rank.
CATEGORICAL_PALETTE = [COLOR_BLUE, COLOR_ORANGE, COLOR_AQUA, COLOR_YELLOW,
                       COLOR_MAGENTA, COLOR_GREEN, COLOR_PURPLE, COLOR_RED]

GOOD_LIGHT, GOOD_DARK = "#047f02", "#3ad12a"
CRITICAL_LIGHT, CRITICAL_DARK = "#db0129", "#ff9b90"

# The treemap's gain/loss ramp interpolates hex arithmetically (_lerp_color), so
# it cannot take a var() and stays theme-independent — as it always has. Pinned
# here so it at least has one declared source.
# Taken from the data register, not the semantic pair: treemap tiles are large
# fields of colour, and the signal green is tuned to be read as *text*, so it
# shouted next to everything else.
DIVERGING_GOOD, DIVERGING_CRITICAL = DATA_LIGHT["green"], DATA_LIGHT["red"]
DIVERGING_MUTED = "#837f8d"

# -------------------------------------------------------------- asset classes
# Keyed by the French storage keys shared with each user's private config files
# (see CATEGORY_LABELS in app.py for why the taxonomy is not renamed).
ASSET_LIGHT = {
    "Actions": "#027474",
    "Obligations": "#0f9b9b",
    "Fonds Euros": "#7e7a89",
    "Livrets": "#adaab4",
    "Autres": "#a68d03",
}
ASSET_DARK = {
    "Actions": "#4cc1c0",
    "Obligations": "#379393",
    "Fonds Euros": "#9894a3",
    "Livrets": "#c8c5d0",
    "Autres": "#dfc65a",
}
ASSET_TOKENS = {
    "Actions": "--asset-actions",
    "Obligations": "--asset-obligations",
    "Fonds Euros": "--asset-fonds-euros",
    "Livrets": "--asset-livrets",
    "Autres": "--asset-autres",
}


def asset_var(category: str) -> str:
    """CSS reference for an asset class, resolved client-side per theme."""
    token = ASSET_TOKENS.get(category)
    return f"var({token})" if token else COLOR_MUTED


# ------------------------------------------------------------------- themes
def _theme(neutral: dict, data: dict, assets: dict, contrast: str) -> dict:
    return {
        "--surface-1": neutral["--surface-1"],
        "--page": neutral["--page"],
        "--text-primary": neutral["--text-primary"],
        "--text-secondary": neutral["--text-secondary"],
        "--text-muted": neutral["--text-muted"],
        "--grid": neutral["--grid"],
        "--baseline": neutral["--baseline"],
        "--border": neutral["--border"],
        "--row-hover": neutral["--row-hover"],
        "--chip-bg": neutral["--chip-bg"],
        "--good": neutral["--good"],
        "--critical": neutral["--critical"],
        "--info": neutral["--info"],
        "--brand": neutral["--brand"],
        "--brand-contrast": contrast,
        **{DATA_TOKENS[k]: v for k, v in data.items()},
        **{ASSET_TOKENS[k]: v for k, v in assets.items()},
    }


_LIGHT_NEUTRAL = {
    "--surface-1": "#fcfcfb",
    "--page": "#f9f9f7",
    "--text-primary": "#211d2e",
    "--text-secondary": "#4f4c5b",
    "--text-muted": "#837f8d",
    "--grid": "#e1dee9",
    "--baseline": "#c3bfce",
    "--border": "rgba(33,29,46,0.12)",
    "--row-hover": "rgba(33,29,46,0.04)",
    "--chip-bg": "rgba(33,29,46,0.06)",
    "--good": GOOD_LIGHT,
    "--critical": CRITICAL_LIGHT,
    "--info": DATA_LIGHT["blue"],
    "--brand": BRAND_LIGHT,
}
_DARK_NEUTRAL = {
    "--surface-1": "#1a1a19",
    "--page": "#0d0d0d",
    "--text-primary": "#faf8fe",
    "--text-secondary": "#c8c5d0",
    "--text-muted": "#8d8a97",
    "--grid": "#3a3743",
    "--baseline": "#4a4754",
    "--border": "rgba(250,248,254,0.13)",
    "--row-hover": "rgba(250,248,254,0.05)",
    "--chip-bg": "rgba(250,248,254,0.08)",
    "--good": GOOD_DARK,
    "--critical": CRITICAL_DARK,
    "--info": DATA_DARK["blue"],
    "--brand": BRAND_DARK,
}

LIGHT = _theme(_LIGHT_NEUTRAL, DATA_LIGHT, ASSET_LIGHT, "#fcfcfb")
DARK = _theme(_DARK_NEUTRAL, DATA_DARK, ASSET_DARK, "#0d0d0d")


def css_block(tokens: dict, indent: str = "    ") -> str:
    """The custom-property declarations for one theme, ready to drop into :root."""
    return "\n".join(f"{indent}{name}: {value};" for name, value in tokens.items())
