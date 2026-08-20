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
from analytics import exposure as exposure_mod, kpis, patrimoine as patrimoine_mod, performance, performance_by_asset, positions as positions_mod
from importers import normalize
from paths import data_root

DATA_ROOT = data_root()

app = Flask(__name__)

COLOR_BLUE = "#2a78d6"
COLOR_ORANGE = "#eb6834"
COLOR_AQUA = "#1baf7a"
COLOR_YELLOW = "#eda100"
COLOR_MAGENTA = "#e87ba4"
COLOR_GREEN = "#008300"
COLOR_VIOLET = "#4a3aa7"
COLOR_RED = "#e34948"
COLOR_MUTED = "#898781"
COLOR_GOOD = "#0ca30c"
COLOR_CRITICAL = "#d03b3b"
# Fixed-order categorical palette (see dataviz skill): color follows the entity, never its rank.
CATEGORICAL_PALETTE = [COLOR_BLUE, COLOR_ORANGE, COLOR_AQUA, COLOR_YELLOW, COLOR_MAGENTA, COLOR_GREEN, COLOR_VIOLET, COLOR_RED]
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
        return _lerp_color(COLOR_MUTED, COLOR_CRITICAL, -t)
    return _lerp_color(COLOR_MUTED, COLOR_GOOD, t)


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
            line=dict(color=COLOR_BLUE, width=2),
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
                    marker=dict(symbol="triangle-down", size=10, color=COLOR_VIOLET, line=dict(width=1.5, color="var(--surface-1)")),
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


def _build_ranking_fig(asset_perf: pd.DataFrame) -> dict:
    """Ranks funds by average monthly return (%) — to spot the best and worst
    performers at a glance, regardless of how long they've been held."""
    ranked = asset_perf.dropna(subset=["monthly_avg_pct"]).sort_values("monthly_avg_pct", ascending=True)
    if ranked.empty:
        return {}

    colors = [COLOR_GOOD if v >= 0 else COLOR_CRITICAL for v in ranked["monthly_avg_pct"]]
    labels = [f"{v:+.2f} %/mo" for v in ranked["monthly_avg_pct"]]
    display_names = [_truncate_label(n) for n in ranked["name"]]

    fig = go.Figure(
        go.Bar(
            x=ranked["monthly_avg_pct"],
            y=display_names,
            orientation="h",
            marker=dict(color=colors),
            text=labels,
            textposition="outside",
            textfont=dict(size=12),
            cliponaxis=False,
            customdata=ranked["name"],
            hovertemplate="%{customdata}<br>%{x:+.2f} %/mo<extra></extra>",
        )
    )
    span = max(ranked["monthly_avg_pct"].abs().max(), 0.1)
    fig.update_layout(
        margin=dict(l=4, r=56, t=6, b=22),
        height=max(220, 40 * len(ranked) + 60),
        font=dict(size=13),
        xaxis=dict(
            showgrid=True, gridcolor="var(--grid)", zeroline=True, zerolinecolor="var(--baseline)", zerolinewidth=1,
            range=[-span * 1.35, span * 1.35], title=None, tickfont=dict(size=12), fixedrange=True,
        ),
        yaxis=dict(showgrid=False, automargin=True, tickfont=dict(size=13), fixedrange=True),
        showlegend=False,
        bargap=0.3,
        # Height computed per bar (see above): exempted from the generic mobile
        # shrink (base.html/themeLayout), which would break the bar thickness.
        meta=dict(content_height=True),
    )
    return fig.to_dict()


def _build_pie(slices: list, total_label: str = "Total") -> dict:
    # Color assigned by position in the ORIGINAL list (before filtering out zero
    # values): a category at €0 today keeps its color slot for the day it's no
    # longer empty, instead of shifting the color of every category after it.
    colored = [(s, c) for s, c in zip(slices, CATEGORICAL_PALETTE) if s["value"] > 1e-9]
    if not colored:
        return {}
    total = sum(s["value"] for s, _ in colored)
    labels = [s["label"] for s, _ in colored]
    values = [s["value"] for s, _ in colored]
    colors = [c for _, c in colored]

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


def _build_target_gap_fig(comparison: list) -> dict:
    """Gap (actual - target) in percentage points, by category."""
    rows = [c for c in comparison if c["target_pct"] is not None]
    if not rows:
        return {}
    rows = sorted(rows, key=lambda c: c["gap_pct"])
    cats = [CATEGORY_LABELS.get(c["category"], c["category"]) for c in rows]
    gaps = [c["gap_pct"] for c in rows]
    colors = [COLOR_BLUE if g < 0 else COLOR_RED for g in gaps]
    labels = [f"{g:+.1f} pt" for g in gaps]

    fig = go.Figure(
        go.Bar(
            x=gaps,
            y=cats,
            orientation="h",
            marker=dict(color=colors),
            text=labels,
            textposition="outside",
            textfont=dict(size=12),
            cliponaxis=False,
            hovertemplate="%{y}<br>Gap: %{x:+.1f} pt vs target<extra></extra>",
        )
    )
    span = max(max(abs(g) for g in gaps), 2)
    fig.update_layout(
        margin=dict(l=4, r=48, t=6, b=22),
        height=max(200, 46 * len(cats) + 60),
        font=dict(size=13),
        xaxis=dict(
            showgrid=True, gridcolor="var(--grid)", zeroline=True, zerolinecolor="var(--baseline)", zerolinewidth=1,
            range=[-span * 1.3, span * 1.3], title=None, tickfont=dict(size=12), ticksuffix=" pt", fixedrange=True,
        ),
        yaxis=dict(showgrid=False, automargin=True, tickfont=dict(size=13), fixedrange=True),
        showlegend=False,
        bargap=0.35,
        # See _build_ranking_fig: per-bar height, exempted from the mobile shrink.
        meta=dict(content_height=True),
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
        "ranking": _build_ranking_fig(asset_perf),
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

    open_perf = asset_perf[asset_perf["quantity"] > 1e-9].copy()
    total_open_value = open_perf["current_value"].sum()
    open_perf["allocation_pct"] = (
        open_perf["current_value"] / total_open_value * 100 if total_open_value else 0.0
    )
    invest_next_rows = open_perf.sort_values("allocation_pct").to_dict("records")

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
        invest_next=invest_next_rows,
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
        bourse_by_broker = {
            BROKER_LABELS.get(row["broker"], row["broker"]): row["current_value"]
            for row in broker_df.to_dict("records")
        }

    data = patrimoine_mod.build_patrimoine(bourse_value, bourse_by_broker, bourse_positions)

    category_slices = [
        {"label": CATEGORY_LABELS.get(c["category"], c["category"]), "value": c["value"]}
        for c in data["comparison"]
    ]

    figs = {
        "repartition": _build_pie(category_slices),
        "bank_repartition": _build_pie(data["bank_slices"], total_label="Total"),
        "target_gap": _build_target_gap_fig(data["comparison"]),
    }

    return render_template(
        "patrimoine.html",
        active_page="patrimoine",
        total=data["total"],
        bourse_value=data["bourse_value"],
        epargne_total=data["epargne_total"],
        accounts=data["accounts"],
        comparison=data["comparison"],
        by_category=data["by_category"],
        category_labels=CATEGORY_LABELS,
        figs_json=json.dumps(figs, cls=plotly.utils.PlotlyJSONEncoder),
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
