"""Flask dashboard: portfolio analysis (Fortuneo + Trade Republic)."""

import json
import os
import sys

import pandas as pd
import plotly.graph_objects as go
import plotly.utils
from flask import Flask, render_template

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import market_data
from analytics import exposure as exposure_mod, kpis, patrimoine as patrimoine_mod, performance, performance_by_asset, positions as positions_mod, projection as projection_mod, strategy as strategy_mod
from dashboard import palette
from importers import normalize
from paths import data_root

DATA_ROOT = data_root()

app = Flask(__name__)


@app.context_processor
def inject_palette():
    """Feeds base.html its :root blocks. The chrome and the figures then read the
    same declarations, instead of each keeping its own drifting copy.

    `icon_version` stamps the icon URLs: browsers cache a favicon far harder than
    any other asset — often straight through a hard reload — so a regenerated mark
    needs a new URL to be picked up at all.
    """
    return {
        "css_light": palette.css_block(palette.LIGHT, indent="    "),
        "css_dark": palette.css_block(palette.DARK, indent="      "),
        "icon_version": _icon_version(),
    }


def _icon_version() -> int:
    """Newest mtime across the icon files, so regenerating them busts the cache."""
    static = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    stamps = [0]
    for root, _dirs, files in os.walk(static):
        for name in files:
            if name.endswith((".ico", ".png", ".webmanifest")):
                try:
                    stamps.append(int(os.path.getmtime(os.path.join(root, name))))
                except OSError:
                    pass
    return max(stamps)


# Colour now lives in dashboard/palette.py; these are re-exported so the figure
# builders below read the same way they always did.
COLOR_BLUE = palette.COLOR_BLUE
COLOR_ORANGE = palette.COLOR_ORANGE
COLOR_AQUA = palette.COLOR_AQUA
COLOR_YELLOW = palette.COLOR_YELLOW
COLOR_MAGENTA = palette.COLOR_MAGENTA
COLOR_GREEN = palette.COLOR_GREEN
COLOR_PURPLE = palette.COLOR_PURPLE
COLOR_RED = palette.COLOR_RED
COLOR_MUTED = palette.COLOR_MUTED
COLOR_BRAND = palette.COLOR_BRAND
# Theme-aware where the browser can resolve it (see resolveCssVars in base.html):
# a single fixed green cannot serve both a paper and a near-black ground.
COLOR_GOOD = "var(--good)"
COLOR_CRITICAL = "var(--critical)"
CATEGORICAL_PALETTE = palette.CATEGORICAL_PALETTE

BROKER_LABELS = {"fortuneo": "Fortuneo", "trade_republic": "Trade Republic", "correction_manuelle": "Manual correction"}
# Color fixed per broker (identity), never by rank/sort order — a broker keeps its
# color even if its weight in the portfolio moves ahead of or behind the other.
BROKER_COLORS = {"fortuneo": COLOR_BLUE, "trade_republic": COLOR_ORANGE, "correction_manuelle": COLOR_MUTED}
BROKER_ORDER = ["fortuneo", "trade_republic", "correction_manuelle"]

# Net worth category taxonomy: kept in French internally (Actions, Obligations,
# Fonds Euros, Livrets, Autres) because it's the storage key shared with each
# user's private config/*.json (asset_classes.json, target_allocation.json) and
# data/accounts/accounts.json — none of which are tracked in Git. Renaming the
# taxonomy itself would silently break anyone's existing local setup. This dict
# is a display-only translation layer used by patrimoine.html.
CATEGORY_LABELS = {
    "Actions": "Stocks",
    "Obligations": "Bonds",
    "Fonds Euros": "Euro Funds",
    "Livrets": "Savings Accounts",
    "Autres": "Other",
    patrimoine_mod.INVESTMENT_CATEGORY: "Investments",
}

# Geo/sector diversification: fixed order of the most likely labels (see dataviz
# skill — color by entity, never by rank). Beyond the categorical palette's 8
# slots, a label falls back to COLOR_MUTED instead of generating a color on the
# fly — it stays identifiable in the list via its icon/label.
COUNTRY_ORDER = ["United States", "France", "Germany", "China", "Japan", "United Kingdom", "Taiwan", "South Korea"]
COUNTRY_COLORS = dict(zip(COUNTRY_ORDER, CATEGORICAL_PALETTE))
COUNTRY_ICONS = {
    "United States": "🇺🇸", "France": "🇫🇷", "Germany": "🇩🇪", "China": "🇨🇳", "Japan": "🇯🇵",
    "United Kingdom": "🇬🇧", "Taiwan": "🇹🇼", "South Korea": "🇰🇷", "Australia": "🇦🇺", "Italy": "🇮🇹",
    "Canada": "🇨🇦", "Switzerland": "🇨🇭", "Netherlands": "🇳🇱", "India": "🇮🇳", "Physical gold": "🥇",
    "Denmark": "🇩🇰", "Sweden": "🇸🇪", "Hong Kong": "🇭🇰", "Spain": "🇪🇸", "Singapore": "🇸🇬",
    "Brazil": "🇧🇷", "Saudi Arabia": "🇸🇦", "South Africa": "🇿🇦", "Mexico": "🇲🇽",
    "Indonesia": "🇮🇩", "Thailand": "🇹🇭", "Malaysia": "🇲🇾", "United Arab Emirates": "🇦🇪",
    "Other": "🌍", "Not specified": "❔",
}
# Forecast curves: the same colour per role as the efficient-frontier chart above,
# so a reader moving between the two pages never has to relearn which line is which.
# "Ideal at the same risk" is literally a point on that chart's dashed purple
# capital market line. Anything else the user picks is the neutral blue.
PROJECTION_COLORS = {"today": COLOR_ORANGE, "target": COLOR_AQUA, "ideal": COLOR_PURPLE}

SECTOR_ORDER = [
    "Technology", "Financials", "Industrials", "Consumer Discretionary",
    "Healthcare", "Communication", "Consumer Staples", "Energy",
]
SECTOR_COLORS = dict(zip(SECTOR_ORDER, CATEGORICAL_PALETTE))
SECTOR_ICONS = {
    "Technology": "💻", "Financials": "🏦", "Industrials": "🏭", "Consumer Discretionary": "🛍️",
    "Healthcare": "🏥", "Communication": "📡", "Consumer Staples": "🥫", "Energy": "⚡",
    "Materials": "🧱", "Utilities": "🔌", "Real Estate": "🏠", "Commodities": "🥇",
    "Other": "🌍", "Not specified": "❔",
}


def _fmt_eur(value: float) -> str:
    if pd.isna(value):
        return "—"
    return f"{value:,.0f} €".replace(",", " ")


def format_number(value, decimals: int = 0, signed: bool = False) -> str:
    """Jinja filter: formats a number with a space as the thousands separator (10 000, not 10,000)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    fmt = f"{{:{'+' if signed else ''},.{decimals}f}}"
    return fmt.format(value).replace(",", " ")


app.jinja_env.filters["fr"] = format_number


def _hex_to_rgb(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _lerp_color(c1_hex: str, c2_hex: str, t: float) -> str:
    r1, g1, b1 = _hex_to_rgb(c1_hex)
    r2, g2, b2 = _hex_to_rgb(c2_hex)
    r = round(r1 + (r2 - r1) * t)
    g = round(g1 + (g2 - g1) * t)
    b = round(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def _diverging_color(value: float, bound: float) -> str:
    """Red (loss) → neutral gray (0) → green (gain), diverging poles with a gray
    midpoint (see dataviz skill: never a hue at the center of a diverging scale)."""
    if bound <= 0 or pd.isna(value):
        return COLOR_MUTED
    t = max(-1.0, min(1.0, value / bound))
    if t < 0:
        return _lerp_color(palette.DIVERGING_MUTED, palette.DIVERGING_CRITICAL, -t)
    return _lerp_color(palette.DIVERGING_MUTED, palette.DIVERGING_GOOD, t)


def _contrast_text_color(hex_color: str) -> str:
    """White or dark ink text depending on background luminance — a fixed white
    text becomes unreadable on the gradient's lighter hues (close to neutral gray)."""
    r, g, b = _hex_to_rgb(hex_color)
    luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    return "#12120f" if luminance > 0.6 else "#ffffff"


def _build_allocation_treemap_fig(df: pd.DataFrame) -> dict:
    """One rectangle per open position: size = value, color = unrealized gain/loss
    (red = loss, green = gain) — replaces the horizontal bar, unreadable on a
    portfolio with weights ranging from 29% down to 0.6% (invisible micro-rows),
    and adds a dimension the bar didn't show: what weighs the most isn't
    necessarily what performs best."""
    open_pos = df[df["quantity"] > 1e-9].copy()
    total = open_pos["current_value"].sum()
    if open_pos.empty or total <= 0:
        return {}

    open_pos = open_pos.sort_values("current_value", ascending=False)
    pnl_pct = open_pos["unrealized_pnl_pct"].fillna(0.0)
    bound = max(float(pnl_pct.abs().max()), 5.0)
    colors = [_diverging_color(v, bound) for v in pnl_pct]
    text_colors = [_contrast_text_color(c) for c in colors]
    tile_text = [
        f"{name}<br>{_fmt_eur(v)} ({v / total * 100:.1f} %)<br>{p:+.1f} %"
        for name, v, p in zip(open_pos["name"], open_pos["current_value"], pnl_pct)
    ]

    fig = go.Figure(
        go.Treemap(
            labels=open_pos["name"],
            parents=[""] * len(open_pos),
            values=open_pos["current_value"],
            text=tile_text,
            textinfo="text",
            textfont=dict(size=12, color=text_colors),
            marker=dict(colors=colors),
            # A real gap (background showing through) separates tiles rather than a
            # border painted on top — same logic as the "surface gap" of stacked bars.
            tiling=dict(pad=2),
            customdata=pnl_pct,
            hovertemplate="%{label}<br>%{value:,.0f} € (%{percentParent:.1%})<br>Unrealized gain/loss: %{customdata:+.1f} %<extra></extra>",
        )
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        height=260,
        # Tiles too small for their text lose it rather than showing it
        # overflowing/truncated — detail stays available on hover and in the table.
        uniformtext=dict(minsize=10, mode="hide"),
    )
    return fig.to_dict()


def _build_broker_fig(broker_df: pd.DataFrame) -> dict:
    """Falls back to a stacked bar when the balance gauge (2 brokers) doesn't apply
    (0, 1, or 3+ active brokers) — see _build_broker_gauge_fig."""
    active = broker_df[broker_df["current_value"] > 1e-9]
    if active.empty:
        return {}
    total = active["current_value"].sum()
    traces = []
    for row in active.to_dict("records"):
        color = BROKER_COLORS.get(row["broker"], COLOR_MUTED)
        label = BROKER_LABELS.get(row["broker"], row["broker"])
        pct = row["current_value"] / total * 100 if total else 0
        traces.append(
            go.Bar(
                x=[row["current_value"]],
                y=["Allocation"],
                orientation="h",
                name=label,
                marker=dict(color=color),
                text=[f"{label} — {pct:.0f} %"],
                textposition="inside",
                insidetextanchor="middle",
                textfont=dict(color="#ffffff"),
                hovertemplate=f"{label}<br>%{{x:,.0f}} €<extra></extra>",
            )
        )
    fig = go.Figure(data=traces)
    fig.update_layout(
        barmode="stack",
        margin=dict(l=2, r=2, t=4, b=4),
        height=110,
        xaxis=dict(showgrid=False, visible=False, fixedrange=True),
        yaxis=dict(showgrid=False, visible=False, fixedrange=True),
        showlegend=False,
        bargap=0.5,
    )
    return fig.to_dict()


def _build_broker_gauge_fig(broker_df: pd.DataFrame) -> dict:
    """Half-circle balance gauge between the two main brokers: the gauge value is
    the weight (%) of the first, the rest of the arc carries the second's color —
    each broker keeps its usual color (BROKER_COLORS).
    Only applies for exactly 2 active brokers; beyond (or below) that,
    _build_broker_fig (stacked bar) remains the most readable form."""
    active = broker_df[broker_df["current_value"] > 1e-9]
    if len(active) != 2:
        return {}

    values = {r["broker"]: r["current_value"] for r in active.to_dict("records")}
    ordered = [b for b in BROKER_ORDER if b in values] + [b for b in values if b not in BROKER_ORDER]
    broker_a, broker_b = ordered[0], ordered[1]
    value_a, value_b = values[broker_a], values[broker_b]
    total = value_a + value_b
    pct_a = (value_a / total * 100) if total else 50.0
    color_a = BROKER_COLORS.get(broker_a, COLOR_BLUE)
    color_b = BROKER_COLORS.get(broker_b, COLOR_ORANGE)
    label_a = BROKER_LABELS.get(broker_a, broker_a)
    label_b = BROKER_LABELS.get(broker_b, broker_b)

    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=pct_a,
            number=dict(suffix=" %", font=dict(size=30, color=color_a)),
            gauge=dict(
                shape="angular",
                axis=dict(range=[0, 100], visible=False),
                bar=dict(color=color_a, thickness=1),
                bgcolor="rgba(0,0,0,0)",
                borderwidth=0,
                steps=[dict(range=[0, 100], color=color_b)],
                threshold=dict(line=dict(color=COLOR_MUTED, width=2), thickness=0.9, value=50),
            ),
            # The half-circle + number are pushed into the top third of the frame,
            # leaving a clear bottom band for the two broker labels.
            domain=dict(x=[0, 1], y=[0.32, 1]),
        )
    )
    fig.update_layout(
        margin=dict(l=8, r=8, t=4, b=4),
        height=250,
        annotations=[
            dict(
                text=f"{label_a}<br><span style='font-size:11px'>{_fmt_eur(value_a)}</span>",
                x=0.02, y=0, xanchor="left", yanchor="bottom", showarrow=False,
                font=dict(size=13, color=color_a),
            ),
            dict(
                text=f"{label_b}<br><span style='font-size:11px'>{_fmt_eur(value_b)}</span>",
                x=0.98, y=0, xanchor="right", yanchor="bottom", showarrow=False,
                font=dict(size=13, color=color_b),
            ),
        ],
    )
    return fig.to_dict()


def _build_sparkline_fig(hist: pd.DataFrame) -> dict:
    """Decorative mini-curve under the hero value — trend only, no axes or
    tooltip (full detail lives in the "Portfolio value over time" chart)."""
    if hist.empty:
        return {}
    tail = hist.tail(180)
    if tail["portfolio_value"].abs().sum() <= 0:
        return {}
    fig = go.Figure(
        go.Scatter(
            x=tail["date"], y=tail["portfolio_value"],
            mode="lines",
            line=dict(color=COLOR_BLUE, width=2),
            hoverinfo="skip",
        )
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=2, b=0),
        height=56,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        showlegend=False,
    )
    return fig.to_dict()


def _build_performance_fig(hist: pd.DataFrame, events: pd.DataFrame) -> dict:
    if hist.empty:
        return {}
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=hist["date"], y=hist["invested_capital"],
            name="Net invested capital",
            mode="lines",
            line=dict(color=COLOR_MUTED, width=2, dash="dot"),
            hovertemplate="%{x|%d %b %Y}<br>%{y:,.0f} €<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=hist["date"], y=hist["portfolio_value"],
            name="Portfolio value",
            mode="lines",
            # The headline curve wears the brand. This is the one place the brand
            # colour enters the data, and deliberately: the "you can click this"
            # signal is carried by the corner mark, which is a *shape*, so the
            # affordance never rested on hue alone.
            line=dict(color=COLOR_BRAND, width=2.5),
            hovertemplate="%{x|%d %b %Y}<br>%{y:,.0f} €<extra></extra>",
        )
    )

    if not events.empty:
        buys = events[events["type"] == "BUY"]
        sells = events[events["type"] == "SELL"]
        if not buys.empty:
            fig.add_trace(
                go.Scatter(
                    x=buys["date"], y=buys["y"],
                    name="Buy",
                    mode="markers",
                    marker=dict(symbol="triangle-up", size=10, color=COLOR_AQUA, line=dict(width=1.5, color="var(--surface-1)")),
                    customdata=list(zip(buys["name"], buys["amount"])),
                    hovertemplate="Buy — %{customdata[0]}<br>%{customdata[1]:,.0f} €<extra></extra>",
                )
            )
        if not sells.empty:
            fig.add_trace(
                go.Scatter(
                    x=sells["date"], y=sells["y"],
                    name="Sell",
                    mode="markers",
                    # Red against the green Buy: the universal convention, and the
                    # one the eye expects on a trade marker. (It was violet before
                    # the identity work — reverting to that exact violet is what
                    # collides with the brand indigo, hence red rather than a
                    # literal revert.)
                    marker=dict(symbol="triangle-down", size=10, color=COLOR_RED, line=dict(width=1.5, color="var(--surface-1)")),
                    customdata=list(zip(sells["name"], sells["amount"])),
                    hovertemplate="Sell — %{customdata[0]}<br>%{customdata[1]:,.0f} €<extra></extra>",
                )
            )

    fig.update_layout(
        margin=dict(l=2, r=2, t=6, b=2),
        height=380,
        # fixedrange on both axes: without it, a touch swipe starting on the chart
        # gets captured by Plotly as a pan/zoom instead of scrolling the page — the
        # chart feels "stuck" to touch. Hover/tap stays active.
        xaxis=dict(showgrid=False, fixedrange=True),
        yaxis=dict(showgrid=True, gridcolor="var(--grid)", tickformat=",.0f", ticksuffix=" €", fixedrange=True, tickfont=dict(size=11)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        hovermode="closest",
    )
    return fig.to_dict()


def _truncate_label(name: str, max_len: int = 24) -> str:
    """Truncates an axis label that's too long (the full name stays available on
    hover via customdata) — on a horizontal bar chart, a 30+ character fund name
    can by itself double the margin Plotly auto-computes."""
    name = str(name)
    return name if len(name) <= max_len else name[: max_len - 1].rstrip() + "…"


def _institution_colors(labels) -> dict:
    """A stable colour per bank or broker.

    Fortuneo and Trade Republic keep the identity they already carry on the
    Investments page (BROKER_COLORS, used by the broker gauge), so the two pages
    agree. Every other institution takes a free palette slot in alphabetical
    order — deliberately not in balance order, which is how the slices are sorted
    and would repaint a bank the moment its balance moved.
    """
    known = {BROKER_LABELS[key]: color for key, color in BROKER_COLORS.items()
             if key in BROKER_LABELS}
    spare = [c for c in CATEGORICAL_PALETTE if c not in known.values()]
    out = {name: color for name, color in known.items() if name in labels}
    for i, name in enumerate(sorted(n for n in labels if n not in known)):
        out[name] = spare[i % len(spare)] if spare else COLOR_MUTED
    return out


def _build_pie(slices: list, total_label: str = "Total") -> dict:
    """Each slice brings its own "color" — it is a property of the entity, not of
    where the entity happens to sit in the list.

    This used to zip the list against CATEGORICAL_PALETTE, which meant colour
    followed rank. Both callers sort by descending value, so a bank changed colour
    the day its balance overtook another one's, and the same blue stood for
    "Actions" in one chart and for a bank in the chart beside it.
    """
    colored = [s for s in slices if s["value"] > 1e-9]
    if not colored:
        return {}
    total = sum(s["value"] for s in colored)
    labels = [s["label"] for s in colored]
    values = [s["value"] for s in colored]
    colors = [s.get("color", COLOR_MUTED) for s in colored]

    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.5,
            sort=False,
            direction="clockwise",
            marker=dict(colors=colors, line=dict(color="var(--surface-1)", width=2)),
            textinfo="label+percent",
            textposition="outside",
            textfont=dict(size=12),
            hovertemplate="%{label}<br>%{value:,.0f} €  (%{percent})<extra></extra>",
        )
    )
    fig.update_layout(
        margin=dict(l=20, r=20, t=16, b=16),
        height=460,
        showlegend=False,
        annotations=[dict(
            text=f"{_fmt_eur(total)}<br><span style='font-size:11px'>{total_label}</span>",
            x=0.5, y=0.5, font=dict(size=20), showarrow=False,
        )],
    )
    return fig.to_dict()


def _bucket_diversification(rows: list, colors: dict, icons: dict, top_n: int = 10) -> list:
    """Keeps the top_n rows by value, groups the rest under 'Other'. Color follows
    the label's identity (fixed dict, 8 hues), never its rank in this ranking —
    beyond 8 distinct entities, neutral gray is reused rather than generating a
    color on the fly (see dataviz skill); identity stays carried by the
    icon/label in the list, not by color alone."""
    rows = sorted(rows, key=lambda r: -r["value"])
    total = sum(r["value"] for r in rows)
    if total <= 0:
        return []
    head, tail = rows[:top_n], rows[top_n:]
    if tail:
        tail_value = sum(r["value"] for r in tail)
        existing_other = next((r for r in head if r["label"] == "Other"), None)
        if existing_other:
            existing_other = dict(existing_other, value=existing_other["value"] + tail_value)
            head = [existing_other if r["label"] == "Other" else r for r in head]
        else:
            head = head + [{"label": "Other", "value": tail_value}]
    head.sort(key=lambda r: -r["value"])
    return [
        {
            "label": r["label"],
            "value": r["value"],
            "pct": r["value"] / total * 100,
            "color": colors.get(r["label"], COLOR_MUTED),
            "icon": icons.get(r["label"], "🌍"),
        }
        for r in head
    ]


def _build_diversification_payload(pos_df: pd.DataFrame) -> dict:
    open_pos = pos_df[pos_df["quantity"] > 1e-9]
    positions = [
        {"asset_key": r["asset_key"], "name": r["name"], "value": r["current_value"]}
        for r in open_pos.to_dict("records")
    ]
    div = exposure_mod.build_diversification(positions)

    def rows(d: dict) -> list:
        return [{"label": k, "value": v} for k, v in d.items()]

    portfolio = {
        "country": _bucket_diversification(rows(div["portfolio"]["country"]), COUNTRY_COLORS, COUNTRY_ICONS),
        "sector": _bucket_diversification(rows(div["portfolio"]["sector"]), SECTOR_COLORS, SECTOR_ICONS),
    }
    funds = sorted(
        (
            {
                "asset_key": f["asset_key"],
                "name": f["name"],
                "value": f["value"],
                "country": _bucket_diversification(rows(f["country"]), COUNTRY_COLORS, COUNTRY_ICONS),
                "sector": _bucket_diversification(rows(f["sector"]), SECTOR_COLORS, SECTOR_ICONS),
            }
            for f in div["funds"]
        ),
        key=lambda f: -f["value"],
    )
    return {"portfolio": portfolio, "funds": funds}


def _build_drift_fig(targets: list) -> dict:
    """Gap to target, in percentage points of net worth, per strategy line.

    Bars are colored by direction rather than by identity: what matters here is
    "too much / not enough", the same reading as _build_target_gap_fig.
    """
    rows = [t for t in targets if abs(t["drift_pt"]) > 0.01 or t["target_pct"] > 0]
    if not rows:
        return {}
    rows = sorted(rows, key=lambda t: t["drift_pt"])
    labels = [_truncate_label(t["label"], 28) for t in rows]
    gaps = [t["drift_pt"] for t in rows]
    colors = [COLOR_MUTED if t["status"] == "on" else (COLOR_RED if t["drift_pt"] > 0 else COLOR_BLUE)
              for t in rows]

    fig = go.Figure(
        go.Bar(
            x=gaps, y=labels, orientation="h",
            marker=dict(color=colors),
            text=[f"{g:+.1f} pt" for g in gaps],
            textposition="outside", textfont=dict(size=12), cliponaxis=False,
            customdata=[(t["label"], t["current_eur"], t["target_eur"], t["drift_eur"]) for t in rows],
            hovertemplate=("%{customdata[0]}<br>Now %{customdata[1]:,.0f} € · "
                           "target %{customdata[2]:,.0f} €<br>Gap %{customdata[3]:+,.0f} €<extra></extra>"),
        )
    )
    span = max(max(abs(g) for g in gaps), 2)
    fig.update_layout(
        margin=dict(l=4, r=56, t=6, b=22),
        height=max(220, 44 * len(rows) + 60),
        font=dict(size=13),
        xaxis=dict(showgrid=True, gridcolor="var(--grid)", zeroline=True,
                   zerolinecolor="var(--baseline)", zerolinewidth=1,
                   range=[-span * 1.35, span * 1.35], ticksuffix=" pt",
                   tickfont=dict(size=12), fixedrange=True),
        yaxis=dict(showgrid=False, automargin=True, tickfont=dict(size=13), fixedrange=True),
        showlegend=False, bargap=0.32,
        meta=dict(content_height=True),
    )
    return fig.to_dict()


def _build_mix_fig(targets: list, sleeve: dict, total: float) -> dict:
    """Current vs target composition, as two stacked bars.

    Two bars rather than a pair of donuts: the eye compares lengths along a shared
    baseline far better than angles across two circles.
    """
    ordered = [t for t in targets if t["target_pct"] > 0 or t["current_eur"] > 1]
    if not ordered or total <= 0:
        return {}
    # Colors follow the line's identity — its position in the policy file — never
    # its current weight, so a line keeps its hue as the allocation moves.
    palette = dict(zip([t["key"] for t in ordered if not t["is_cash"]], CATEGORICAL_PALETTE))

    traces = []
    for t in ordered:
        color = COLOR_MUTED if t["is_cash"] else palette.get(t["key"], COLOR_MUTED)
        traces.append(
            go.Bar(
                y=["Target", "Today"],
                x=[t["target_pct"], t["current_pct"]],
                orientation="h", name=t["label"],
                marker=dict(color=color, line=dict(color="var(--surface-1)", width=2)),
                hovertemplate=f"{t['label']}<br>%{{x:.1f}} %<extra></extra>",
            )
        )
    if sleeve["cap_pct"]:
        traces.append(
            go.Bar(
                y=["Target", "Today"],
                x=[sleeve["cap_pct"], sleeve["used_pct"]],
                orientation="h", name="Trading sleeve",
                marker=dict(color=COLOR_PURPLE, line=dict(color="var(--surface-1)", width=2)),
                hovertemplate="Trading sleeve<br>%{x:.1f} %<extra></extra>",
            )
        )
    fig = go.Figure(data=traces)
    # No Plotly legend: a horizontal one is laid out inside the figure box, so past
    # a handful of lines it wraps straight over the bars (fine on the 3-line demo,
    # unreadable on a real policy). The page renders the swatches itself, in HTML
    # below the chart, where they wrap like any other text — see strategy.html.
    fig.update_layout(
        barmode="stack",
        margin=dict(l=4, r=4, t=6, b=4),
        height=150,
        xaxis=dict(showgrid=False, visible=False, fixedrange=True, range=[0, 100]),
        yaxis=dict(showgrid=False, fixedrange=True, tickfont=dict(size=13)),
        showlegend=False,
        bargap=0.42,
    )
    return fig.to_dict()


def _build_frontier_fig(analytics: dict, current: dict | None) -> dict:
    """The efficient frontier, with today's portfolio and the target on it.

    The whole point of the chart is the vertical distance between "Today" and the
    frontier: it shows how much return is being left on the table at the risk
    already being taken.
    """
    if not analytics or not analytics.get("frontier"):
        return {}
    frontier = analytics["frontier"]
    rf = analytics["risk_free_net_pct"]
    target = analytics.get("target_portfolio") or {}
    tangency = analytics.get("tangency") or {}

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=[a["vol_pct"] for a in analytics["assets"]],
            y=[a["expected_net_pct"] for a in analytics["assets"]],
            mode="markers", name="Individual lines",
            marker=dict(size=9, color=COLOR_MUTED, opacity=0.65,
                        line=dict(width=1.5, color="var(--surface-1)")),
            customdata=[(a["label"], a["beta"]) for a in analytics["assets"]],
            hovertemplate="%{customdata[0]}<br>Vol %{x:.1f} % · return %{y:.2f} %<br>Beta %{customdata[1]:.2f}<extra></extra>",
        )
    )
    if tangency:
        fig.add_trace(
            go.Scatter(
                x=[0, tangency["vol_pct"]], y=[rf, tangency["ret_pct"]],
                mode="lines", name="Savings + tangency",
                line=dict(color=COLOR_PURPLE, width=2, dash="dash"),
                hoverinfo="skip",
            )
        )
    fig.add_trace(
        go.Scatter(
            x=[f["vol_pct"] for f in frontier], y=[f["ret_pct"] for f in frontier],
            mode="lines", name="Efficient frontier",
            line=dict(color=COLOR_BLUE, width=3),
            hovertemplate="Vol %{x:.1f} % · return %{y:.2f} %<extra></extra>",
        )
    )
    if tangency:
        fig.add_trace(
            go.Scatter(
                x=[tangency["vol_pct"]], y=[tangency["ret_pct"]],
                mode="markers", name="Tangency",
                marker=dict(size=15, color=COLOR_BLUE, symbol="circle",
                            line=dict(width=2.5, color="var(--surface-1)")),
                hovertemplate=f"Tangency<br>Sharpe {tangency.get('sharpe')}<br>"
                              "Vol %{x:.1f} % · return %{y:.2f} %<extra></extra>",
            )
        )
    if target:
        fig.add_trace(
            go.Scatter(
                x=[target["vol_pct"]], y=[target["ret_pct"]],
                mode="markers+text", name="Target",
                marker=dict(size=15, color=COLOR_AQUA, symbol="diamond",
                            line=dict(width=2.5, color="var(--surface-1)")),
                text=["Target"], textposition="top center", textfont=dict(size=12),
                hovertemplate=f"Target · beta {target.get('beta')}<br>"
                              "Vol %{x:.1f} % · return %{y:.2f} %<extra></extra>",
            )
        )
    if current:
        fig.add_trace(
            go.Scatter(
                x=[current["vol_pct"]], y=[current["ret_pct"]],
                mode="markers+text", name="Today",
                marker=dict(size=15, color=COLOR_ORANGE, symbol="x",
                            line=dict(width=2, color="var(--surface-1)")),
                text=["Today"], textposition="bottom center", textfont=dict(size=12),
                hovertemplate=f"Today · beta {current.get('beta')}<br>"
                              "Vol %{x:.1f} % · return %{y:.2f} %<extra></extra>",
            )
        )
    fig.add_trace(
        go.Scatter(
            x=[0], y=[rf], mode="markers", name="Guaranteed savings",
            marker=dict(size=11, color=COLOR_PURPLE, symbol="square",
                        line=dict(width=2, color="var(--surface-1)")),
            hovertemplate=f"Guaranteed savings<br>{rf:.2f} % net, no volatility<extra></extra>",
        )
    )
    fig.update_layout(
        margin=dict(l=2, r=8, t=6, b=2),
        height=420,
        xaxis=dict(title="Annualised volatility", ticksuffix=" %", showgrid=True,
                   gridcolor="var(--grid)", fixedrange=True, rangemode="tozero"),
        yaxis=dict(title="Expected return, after tax", ticksuffix=" %", showgrid=True,
                   gridcolor="var(--grid)", fixedrange=True),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(size=11)),
        hovermode="closest",
    )
    return fig.to_dict()


# Correlation ramp. Fixed hexes rather than theme variables: the cells cover the
# page background, so the same ramp reads correctly in light and dark mode, and
# knowing the exact fill lets us pick a contrasting ink per cell.
# Interpolated arithmetically, so these are literals rather than var() —
# but taken from the palette, not invented here as they used to be.
CORR_NEUTRAL = palette.LIGHT["--grid"]
CORR_HIGH = palette.BRAND_LIGHT
CORR_NEG = palette.DATA_LIGHT["orange"]
CORR_MIN, CORR_MAX = -40, 100


def _correlation_cell_color(z: float) -> str:
    if z < 0:
        return _lerp_color(CORR_NEUTRAL, CORR_NEG, min(1.0, -z / 40))
    return _lerp_color(CORR_NEUTRAL, CORR_HIGH, min(1.0, z / 100))


def _build_correlation_fig(analytics: dict) -> dict:
    """Correlation heatmap, with the number written in each cell.

    Plotly paints every cell's text in a single color, which is unreadable at one
    end of the ramp or the other. So the numbers are drawn as annotations instead,
    each picking white or dark ink from its own cell's luminance
    (_contrast_text_color) — the same trick the allocation treemap uses.
    """
    if not analytics or not analytics.get("correlation"):
        return {}
    corr = analytics["correlation"]
    labels = [_truncate_label(l, 22) for l in corr["labels"]]
    matrix = corr["matrix"]
    n = len(labels)

    # The diagonal is always 100 and carries no information; leaving it blank stops
    # it from being the darkest thing on the chart.
    z = [[None if i == j else matrix[i][j] for j in range(n)] for i in range(n)]
    span = CORR_MAX - CORR_MIN
    fig = go.Figure(
        go.Heatmap(
            z=z, x=labels, y=labels,
            colorscale=[[0.0, CORR_NEG], [(0 - CORR_MIN) / span, CORR_NEUTRAL], [1.0, CORR_HIGH]],
            zmin=CORR_MIN, zmax=CORR_MAX,
            xgap=3, ygap=3,
            showscale=False,
            hoverongaps=False,
            hovertemplate="%{y}<br>%{x}<br>Correlation %{z} %<extra></extra>",
        )
    )

    annotations = []
    for i in range(n):
        for j in range(n):
            if i == j:
                annotations.append(dict(x=labels[j], y=labels[i], text="—", showarrow=False,
                                        font=dict(size=11, color=COLOR_MUTED)))
                continue
            value = matrix[i][j]
            annotations.append(dict(
                x=labels[j], y=labels[i], text=str(value), showarrow=False,
                font=dict(size=11, color=_contrast_text_color(_correlation_cell_color(value))),
            ))

    fig.update_layout(
        margin=dict(l=2, r=2, t=6, b=2),
        height=max(340, 44 * n + 130),
        annotations=annotations,
        xaxis=dict(tickangle=-40, tickfont=dict(size=11), fixedrange=True, automargin=True,
                   side="top", showgrid=False),
        yaxis=dict(tickfont=dict(size=11), fixedrange=True, automargin=True,
                   autorange="reversed", showgrid=False),
        meta=dict(content_height=True),
    )
    return fig.to_dict()


def _build_stress_fig(stress: list, total: float, tolerance_pct: float | None) -> dict:
    """Simulated loss per scenario, today vs target, against the stated tolerance."""
    if not stress:
        return {}
    scenarios = [_truncate_label(s["scenario"], 34) for s in stress]
    fig = go.Figure()
    for name, key, color in (("Today", "current_pct", COLOR_ORANGE),
                             ("Target", "target_pct", COLOR_BLUE)):
        fig.add_trace(
            go.Bar(
                x=[s[key] for s in stress], y=scenarios, orientation="h", name=name,
                marker=dict(color=color),
                text=[f"{s[key]:+.1f} %" for s in stress],
                textposition="outside", textfont=dict(size=11), cliponaxis=False,
                customdata=[s[key] / 100 * total for s in stress],
                hovertemplate=f"{name}<br>%{{x:+.1f}} %<br>%{{customdata:,.0f}} €<extra></extra>",
            )
        )
    worst = min(min(s["current_pct"], s["target_pct"]) for s in stress)
    span = min(worst, tolerance_pct or worst)
    if tolerance_pct is not None:
        fig.add_vline(
            x=tolerance_pct, line=dict(color=COLOR_CRITICAL, width=2, dash="dot"),
            annotation_text=f"tolerance {tolerance_pct:.0f} %",
            annotation_position="bottom left",
            annotation_font=dict(size=11, color=COLOR_CRITICAL),
        )
    fig.update_layout(
        barmode="group",
        margin=dict(l=4, r=48, t=6, b=22),
        height=max(230, 78 * len(stress) + 70),
        xaxis=dict(showgrid=True, gridcolor="var(--grid)", zeroline=True,
                   zerolinecolor="var(--baseline)", ticksuffix=" %",
                   range=[span * 1.22, 2], fixedrange=True, tickfont=dict(size=12)),
        yaxis=dict(showgrid=False, automargin=True, tickfont=dict(size=12), fixedrange=True),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        bargap=0.3,
        meta=dict(content_height=True),
    )
    return fig.to_dict()


@app.route("/")
def index():
    transactions = normalize.load_all(DATA_ROOT)

    if transactions.empty:
        return render_template("index.html", active_page="bourse", empty=True)

    normalize.save_processed(transactions, DATA_ROOT)

    pos_dict = positions_mod.build_positions(transactions)
    pos_df = positions_mod.positions_frame(pos_dict)
    pos_df = kpis.enrich_with_prices(pos_df)

    summary = kpis.summary(pos_df, transactions)
    broker_df = kpis.by_broker(pos_df)
    hist = performance.build_history(transactions, pos_df)
    trade_events = performance.build_trade_events(transactions, hist)

    fees_map = market_data.load_fees_map()
    asset_perf = performance_by_asset.build_asset_performance(transactions, pos_df)
    asset_perf["ter_pct"] = asset_perf["asset_key"].map(fees_map)

    open_pos_for_legend = pos_df[pos_df["quantity"] > 1e-9]
    allocation_pnl_bound = max(
        float(open_pos_for_legend["unrealized_pnl_pct"].abs().max()) if not open_pos_for_legend.empty else 0.0,
        5.0,
    )

    figs = {
        "performance": _build_performance_fig(hist, trade_events),
        "sparkline": _build_sparkline_fig(hist),
        "allocation": _build_allocation_treemap_fig(pos_df),
        "broker": _build_broker_gauge_fig(broker_df) or _build_broker_fig(broker_df),
    }

    diversification = _build_diversification_payload(pos_df)

    open_positions = (
        pos_df[pos_df["quantity"] > 1e-9]
        .sort_values("current_value", ascending=False)
        .to_dict("records")
    )

    asset_perf_rows = asset_perf.sort_values("monthly_avg_pct", ascending=False).to_dict("records")

    fees_rows = (
        pos_df[(pos_df["quantity"] > 1e-9) & (pos_df["asset_key"].isin(fees_map))]
        .assign(
            ter_pct=lambda d: d["asset_key"].map(fees_map),
            annual_fee_eur=lambda d: d["current_value"] * d["asset_key"].map(fees_map) / 100,
        )
        .sort_values("annual_fee_eur", ascending=False)
        .to_dict("records")
    )
    total_annual_fees = sum(r["annual_fee_eur"] for r in fees_rows)

    recent_tx = (
        transactions.sort_values("date", ascending=False)
        .head(25)
        .assign(date=lambda d: d["date"].dt.strftime("%d/%m/%Y"), name=lambda d: d["name"].fillna(""))
        .to_dict("records")
    )

    dividends = (
        transactions[transactions["type"] == "DIVIDEND"]
        .sort_values("date", ascending=False)
        .assign(date=lambda d: d["date"].dt.strftime("%d/%m/%Y"), name=lambda d: d["name"].fillna(""))
        .to_dict("records")
    )

    return render_template(
        "index.html",
        active_page="bourse",
        empty=False,
        summary=summary,
        broker_df=broker_df.to_dict("records"),
        positions=open_positions,
        asset_perf=asset_perf_rows,
        fees_rows=fees_rows,
        total_annual_fees=total_annual_fees,
        allocation_pnl_bound=allocation_pnl_bound,
        recent_tx=recent_tx,
        dividends=dividends,
        diversification=diversification,
        figs_json=json.dumps(figs, cls=plotly.utils.PlotlyJSONEncoder),
        diversification_json=json.dumps(diversification, cls=plotly.utils.PlotlyJSONEncoder),
        broker_labels=BROKER_LABELS,
        last_update=pd.Timestamp.now().strftime("%d/%m/%Y %H:%M"),
    )


@app.route("/patrimoine")
def patrimoine():
    transactions = normalize.load_all(DATA_ROOT)

    bourse_value = 0.0
    bourse_by_broker = {}
    by_broker_raw = {}
    bourse_positions = []
    if not transactions.empty:
        pos_dict = positions_mod.build_positions(transactions)
        pos_df = positions_mod.positions_frame(pos_dict)
        pos_df = kpis.enrich_with_prices(pos_df)
        open_pos = pos_df[pos_df["quantity"] > 1e-9]
        bourse_value = float(open_pos["current_value"].sum())
        bourse_positions = [
            {"asset_key": row["asset_key"], "value": row["current_value"]}
            for row in open_pos.to_dict("records")
        ]
        broker_df = kpis.by_broker(pos_df)
        by_broker_raw = {row["broker"]: row["current_value"] for row in broker_df.to_dict("records")}
        bourse_by_broker = {
            BROKER_LABELS.get(broker, broker): value for broker, value in by_broker_raw.items()
        }

    data = patrimoine_mod.build_patrimoine(bourse_value, bourse_by_broker, bourse_positions)
    # Savings and investment envelopes in one table: the page is called Net Worth,
    # so its account list should add up to the net worth shown above it.
    all_accounts = data["accounts"] + patrimoine_mod.build_investment_accounts(
        by_broker_raw, BROKER_LABELS, transactions)

    # Asset classes carry their own colour, resolved per theme in the browser.
    category_slices = [
        {"label": CATEGORY_LABELS.get(c["category"], c["category"]),
         "value": c["value"],
         "color": palette.asset_var(c["category"])}
        for c in data["comparison"]
    ]
    bank_colors = _institution_colors([s["label"] for s in data["bank_slices"]])
    bank_slices = [dict(s, color=bank_colors.get(s["label"], COLOR_MUTED))
                   for s in data["bank_slices"]]

    figs = {
        "repartition": _build_pie(category_slices),
        "bank_repartition": _build_pie(bank_slices, total_label="Total"),
    }

    return render_template(
        "patrimoine.html",
        active_page="patrimoine",
        total=data["total"],
        bourse_value=data["bourse_value"],
        epargne_total=data["epargne_total"],
        accounts=all_accounts,
        by_category=data["by_category"],
        category_labels=CATEGORY_LABELS,
        figs_json=json.dumps(figs, cls=plotly.utils.PlotlyJSONEncoder),
        last_update=pd.Timestamp.now().strftime("%d/%m/%Y %H:%M"),
    )


@app.route("/strategy")
def strategy():
    policy = strategy_mod.load_policy()
    if policy is None:
        return render_template("strategy.html", active_page="strategy", no_policy=True,
                               last_update=pd.Timestamp.now().strftime("%d/%m/%Y %H:%M"))

    transactions = normalize.load_all(DATA_ROOT)
    positions = []
    if not transactions.empty:
        pos_dict = positions_mod.build_positions(transactions)
        pos_df = kpis.enrich_with_prices(positions_mod.positions_frame(pos_dict))
        positions = [
            {"asset_key": r["asset_key"], "name": r["name"],
             "value": r["current_value"], "broker": r["broker"]}
            for r in pos_df[pos_df["quantity"] > 1e-9].to_dict("records")
        ]

    accounts = [a for a in patrimoine_mod.load_accounts() if a.get("visible", True)]
    cash_total = sum(a["balance"] for a in accounts)
    total = sum(p["value"] for p in positions) + cash_total

    analytics = strategy_mod.load_analytics()
    data = strategy_mod.build(policy, positions, accounts, cash_total, total, analytics,
                              transactions)

    current_risk, stress = None, []
    if analytics:
        weights = strategy_mod.current_weights(policy, positions, total)
        current_risk = strategy_mod.portfolio_risk(analytics, weights)
        stress = strategy_mod.stress_losses(analytics, policy, weights)

    tolerance = (data["risk"] or {}).get("max_drawdown_tolerance_pct")
    figs = {
        "drift": _build_drift_fig(data["targets"]),
        "mix": _build_mix_fig(data["targets"], data["sleeve"], total),
        "frontier": _build_frontier_fig(analytics, current_risk),
        "correlation": _build_correlation_fig(analytics),
        "stress": _build_stress_fig(stress, total, tolerance),
    }

    return render_template(
        "strategy.html",
        active_page="strategy",
        no_policy=False,
        data=data,
        analytics=analytics,
        current_risk=current_risk,
        stress=stress,
        tolerance_pct=tolerance,
        figs_json=json.dumps(figs, cls=plotly.utils.PlotlyJSONEncoder),
        last_update=pd.Timestamp.now().strftime("%d/%m/%Y %H:%M"),
    )


@app.route("/projection")
def projection():
    """Forecast: where today's net worth lands, and where an ideal mix would land.

    Ships parameters rather than a finished figure. Every control on the page
    moves the curve, and rebuilding it server-side would cost a page reload — and
    a fresh Yahoo Finance round-trip — on each drag of a slider. So the
    compounding happens once, in the browser, feeding both the chart and the goal
    calculator from the same simulator (see projection.html).
    """
    transactions = normalize.load_all(DATA_ROOT)
    positions = []
    if not transactions.empty:
        pos_dict = positions_mod.build_positions(transactions)
        pos_df = kpis.enrich_with_prices(positions_mod.positions_frame(pos_dict))
        positions = [
            {"asset_key": r["asset_key"], "value": r["current_value"]}
            for r in pos_df[pos_df["quantity"] > 1e-9].to_dict("records")
        ]

    accounts = [a for a in patrimoine_mod.load_accounts() if a.get("visible", True)]
    capital = projection_mod.starting_capital(positions, accounts)

    policy = strategy_mod.load_policy()
    analytics = strategy_mod.load_analytics()
    current_risk = None
    if policy and analytics and capital["total_eur"]:
        weights = strategy_mod.current_weights(policy, positions, capital["total_eur"])
        current_risk = strategy_mod.portfolio_risk(analytics, weights)

    scenarios = [
        dict(s, color=PROJECTION_COLORS.get(s["key"], COLOR_BLUE))
        for s in projection_mod.build_scenarios(analytics, current_risk)
    ]
    model = {
        "capital": capital,
        "scenarios": scenarios,
        "selected": projection_mod.default_scenario(scenarios),
        # Judgements, both of them — shown so the page can print what it assumed.
        "inflation_pct": (analytics or {}).get("inflation_pct") or 0.0,
        "risk_free_pct": (analytics or {}).get("risk_free_net_pct") or 0.0,
        "custom_color": COLOR_BLUE,
    }

    return render_template(
        "projection.html",
        active_page="projection",
        capital=capital,
        scenarios=scenarios,
        analytics=analytics,
        model=model,
        last_update=pd.Timestamp.now().strftime("%d/%m/%Y %H:%M"),
    )


def _lan_ip() -> str:
    """Best-effort local IP guess (the one used to reach the outside world), to
    display the URL to open from a phone without depending on a real network lookup."""
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    print(f"On the same Wi-Fi, from your phone: http://{_lan_ip()}:5050")
    app.run(debug=True, host="0.0.0.0", port=5050)
