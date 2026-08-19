"""Dashboard Flask : analyse de portefeuille (Fortuneo + Trade Republic)."""

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
# Palette catégorielle à ordre fixe (voir dataviz skill) : la couleur suit l'entité, jamais son rang.
CATEGORICAL_PALETTE = [COLOR_BLUE, COLOR_ORANGE, COLOR_AQUA, COLOR_YELLOW, COLOR_MAGENTA, COLOR_GREEN, COLOR_VIOLET, COLOR_RED]
BROKER_LABELS = {"fortuneo": "Fortuneo", "trade_republic": "Trade Republic", "correction_manuelle": "Correction manuelle"}
# Couleur fixée par courtier (identité), jamais par rang/tri — un courtier garde sa
# couleur même si son poids dans le portefeuille passe devant ou derrière l'autre.
BROKER_COLORS = {"fortuneo": COLOR_BLUE, "trade_republic": COLOR_ORANGE, "correction_manuelle": COLOR_MUTED}
BROKER_ORDER = ["fortuneo", "trade_republic", "correction_manuelle"]

# Diversification géo/sectorielle : ordre fixe des libellés les plus probables (voir
# dataviz skill — couleur par entité, jamais par rang). Au-delà des 8 slots de la
# palette catégorielle, un libellé tombe en COLOR_MUTED plutôt que de générer une
# teinte à la volée — il reste identifiable dans la liste via son icône/drapeau.
COUNTRY_ORDER = ["États-Unis", "France", "Allemagne", "Chine", "Japon", "Royaume-Uni", "Taïwan", "Corée du Sud"]
COUNTRY_COLORS = dict(zip(COUNTRY_ORDER, CATEGORICAL_PALETTE))
COUNTRY_ICONS = {
    "États-Unis": "🇺🇸", "France": "🇫🇷", "Allemagne": "🇩🇪", "Chine": "🇨🇳", "Japon": "🇯🇵",
    "Royaume-Uni": "🇬🇧", "Taïwan": "🇹🇼", "Corée du Sud": "🇰🇷", "Australie": "🇦🇺", "Italie": "🇮🇹",
    "Canada": "🇨🇦", "Suisse": "🇨🇭", "Pays-Bas": "🇳🇱", "Inde": "🇮🇳", "Or physique": "🥇",
    "Danemark": "🇩🇰", "Suède": "🇸🇪", "Hong Kong": "🇭🇰", "Espagne": "🇪🇸", "Singapour": "🇸🇬",
    "Brésil": "🇧🇷", "Arabie Saoudite": "🇸🇦", "Afrique du Sud": "🇿🇦", "Mexique": "🇲🇽",
    "Indonésie": "🇮🇩", "Thaïlande": "🇹🇭", "Malaisie": "🇲🇾", "Émirats arabes unis": "🇦🇪",
    "Autres": "🌍", "Non renseigné": "❔",
}
SECTOR_ORDER = [
    "Technologie", "Financières", "Industrie", "Consommation discrétionnaire",
    "Santé", "Communication", "Consommation de base", "Énergie",
]
SECTOR_COLORS = dict(zip(SECTOR_ORDER, CATEGORICAL_PALETTE))
SECTOR_ICONS = {
    "Technologie": "💻", "Financières": "🏦", "Industrie": "🏭", "Consommation discrétionnaire": "🛍️",
    "Santé": "🏥", "Communication": "📡", "Consommation de base": "🥫", "Énergie": "⚡",
    "Matériaux": "🧱", "Services publics": "🔌", "Immobilier": "🏠", "Matières premières": "🥇",
    "Autres": "🌍", "Non renseigné": "❔",
}


def _fmt_eur(value: float) -> str:
    if pd.isna(value):
        return "—"
    return f"{value:,.0f} €".replace(",", " ")


def fr_number(value, decimals: int = 0, signed: bool = False) -> str:
    """Filtre Jinja : formate un nombre à la française (espace en séparateur de milliers, 10 000 et non 10,000)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    fmt = f"{{:{'+' if signed else ''},.{decimals}f}}"
    return fmt.format(value).replace(",", " ")


app.jinja_env.filters["fr"] = fr_number


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
    """Rouge (perte) → gris neutre (0) → vert (gain), poles diverging + midpoint gris
    (voir dataviz skill : jamais une teinte au centre d'un diverging)."""
    if bound <= 0 or pd.isna(value):
        return COLOR_MUTED
    t = max(-1.0, min(1.0, value / bound))
    if t < 0:
        return _lerp_color(COLOR_MUTED, COLOR_CRITICAL, -t)
    return _lerp_color(COLOR_MUTED, COLOR_GOOD, t)


def _contrast_text_color(hex_color: str) -> str:
    """Texte blanc ou encre sombre selon la luminance du fond — un texte blanc fixe
    devient illisible sur les teintes claires du dégradé (proche du gris neutre)."""
    r, g, b = _hex_to_rgb(hex_color)
    luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    return "#12120f" if luminance > 0.6 else "#ffffff"


def _build_allocation_treemap_fig(df: pd.DataFrame) -> dict:
    """Un rectangle par position ouverte : taille = valeur, couleur = plus-value latente
    (rouge = perte, vert = gain) — remplace la barre horizontale, illisible sur ce
    portefeuille avec un écart de poids de 29 % à 0,6 % (micro-lignes invisibles), et
    ajoute une dimension que la barre ne montrait pas : ce qui pèse le plus n'est pas
    forcément ce qui performe le mieux."""
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
            # Un vrai espace (surface derrière) sépare les tuiles plutôt qu'une bordure
            # peinte dessus — même logique que le "surface gap" des barres empilées.
            tiling=dict(pad=2),
            customdata=pnl_pct,
            hovertemplate="%{label}<br>%{value:,.0f} € (%{percentParent:.1%})<br>Plus-value latente : %{customdata:+.1f} %<extra></extra>",
        )
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        height=260,
        # Les tuiles trop petites pour leur texte le perdent plutôt que de l'afficher
        # débordant/tronqué — le détail reste disponible au survol et dans le tableau.
        uniformtext=dict(minsize=10, mode="hide"),
    )
    return fig.to_dict()


def _build_broker_fig(broker_df: pd.DataFrame) -> dict:
    """Repli en barre empilée quand la jauge balance (2 courtiers) ne s'applique pas
    (0, 1 ou 3+ courtiers actifs) — voir _build_broker_gauge_fig."""
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
                y=["Répartition"],
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
    """Jauge balance en demi-cercle entre les deux courtiers principaux : la valeur
    de la jauge est le poids (%) du premier, le reste de l'arc porte la couleur du
    second — chaque courtier garde sa couleur habituelle (BROKER_COLORS).
    Ne s'applique que pour exactement 2 courtiers actifs ; au-delà (ou en-deçà),
    _build_broker_fig (barre empilée) reste la forme la plus lisible."""
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
            # Le demi-cercle + le nombre sont poussés dans le tiers haut du cadre,
            # pour laisser une bande basse dégagée aux deux labels de courtier.
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
    """Mini-courbe décorative sous la valeur héro — tendance seule, pas d'axes ni
    de tooltip (le détail complet vit dans le graphe « Évolution du portefeuille »)."""
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
            name="Capital net investi",
            mode="lines",
            line=dict(color=COLOR_MUTED, width=2, dash="dot"),
            hovertemplate="%{x|%d/%m/%Y}<br>%{y:,.0f} €<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=hist["date"], y=hist["portfolio_value"],
            name="Valeur du portefeuille",
            mode="lines",
            line=dict(color=COLOR_BLUE, width=2),
            hovertemplate="%{x|%d/%m/%Y}<br>%{y:,.0f} €<extra></extra>",
        )
    )

    if not events.empty:
        buys = events[events["type"] == "BUY"]
        sells = events[events["type"] == "SELL"]
        if not buys.empty:
            fig.add_trace(
                go.Scatter(
                    x=buys["date"], y=buys["y"],
                    name="Achat",
                    mode="markers",
                    marker=dict(symbol="triangle-up", size=10, color=COLOR_AQUA, line=dict(width=1.5, color="var(--surface-1)")),
                    customdata=list(zip(buys["name"], buys["amount"])),
                    hovertemplate="Achat — %{customdata[0]}<br>%{customdata[1]:,.0f} €<extra></extra>",
                )
            )
        if not sells.empty:
            fig.add_trace(
                go.Scatter(
                    x=sells["date"], y=sells["y"],
                    name="Vente",
                    mode="markers",
                    marker=dict(symbol="triangle-down", size=10, color=COLOR_VIOLET, line=dict(width=1.5, color="var(--surface-1)")),
                    customdata=list(zip(sells["name"], sells["amount"])),
                    hovertemplate="Vente — %{customdata[0]}<br>%{customdata[1]:,.0f} €<extra></extra>",
                )
            )

    fig.update_layout(
        margin=dict(l=2, r=2, t=6, b=2),
        height=380,
        # fixedrange sur les deux axes : sans ça, un swipe tactile qui démarre sur le
        # graphique est capté par Plotly comme un pan/zoom au lieu de faire défiler la
        # page — le graphique semble "bloqué" au toucher. Le hover/tap reste actif.
        xaxis=dict(showgrid=False, fixedrange=True),
        yaxis=dict(showgrid=True, gridcolor="var(--grid)", tickformat=",.0f", ticksuffix=" €", fixedrange=True, tickfont=dict(size=11)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        hovermode="closest",
    )
    return fig.to_dict()


def _truncate_label(name: str, max_len: int = 24) -> str:
    """Tronque un libellé d'axe trop long (le nom complet reste dans le survol via
    customdata) — sur un graphique en barres horizontales, un nom de fonds de 30+
    caractères peut à lui seul doubler la marge auto-calculée par Plotly."""
    name = str(name)
    return name if len(name) <= max_len else name[: max_len - 1].rstrip() + "…"


def _build_ranking_fig(asset_perf: pd.DataFrame) -> dict:
    """Classement des fonds par rendement mensuel moyen (%) — pour repérer d'un coup d'œil
    les meilleurs et moins bons performeurs, indépendamment de leur ancienneté."""
    ranked = asset_perf.dropna(subset=["monthly_avg_pct"]).sort_values("monthly_avg_pct", ascending=True)
    if ranked.empty:
        return {}

    colors = [COLOR_GOOD if v >= 0 else COLOR_CRITICAL for v in ranked["monthly_avg_pct"]]
    labels = [f"{v:+.2f} %/mois" for v in ranked["monthly_avg_pct"]]
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
            hovertemplate="%{customdata}<br>%{x:+.2f} %/mois<extra></extra>",
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
        # Hauteur calculée par barre (voir plus haut) : exempté du rétrécissement
        # mobile générique (base.html/themeLayout), qui casserait l'épaisseur de barre.
        meta=dict(content_height=True),
    )
    return fig.to_dict()


def _build_pie(slices: list, total_label: str = "Total") -> dict:
    # Couleur assignée par position dans la liste d'ORIGINE (avant filtrage des valeurs
    # nulles) : une catégorie à 0 € aujourd'hui garde son slot de couleur pour le jour où
    # elle ne sera plus vide, au lieu de décaler la couleur de toutes les suivantes.
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
    """Écart (actuel - cible) en points de pourcentage, par catégorie."""
    rows = [c for c in comparison if c["target_pct"] is not None]
    if not rows:
        return {}
    rows = sorted(rows, key=lambda c: c["gap_pct"])
    cats = [c["category"] for c in rows]
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
            hovertemplate="%{y}<br>Écart : %{x:+.1f} pt vs cible<extra></extra>",
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
        # Cf. _build_ranking_fig : hauteur par barre, exemptée du rétrécissement mobile.
        meta=dict(content_height=True),
    )
    return fig.to_dict()


def _bucket_diversification(rows: list, colors: dict, icons: dict, top_n: int = 10) -> list:
    """Garde les top_n lignes par valeur, regroupe le reste dans 'Autres'. La couleur
    suit l'identité du libellé (dict fixe, 8 teintes), jamais son rang dans ce
    classement — au-delà de 8 entités distinctes, le gris neutre est réutilisé
    plutôt que de générer une teinte à la volée (voir dataviz skill) ; l'identité
    reste portée par l'icône/le libellé dans la liste, pas par la seule couleur."""
    rows = sorted(rows, key=lambda r: -r["value"])
    total = sum(r["value"] for r in rows)
    if total <= 0:
        return []
    head, tail = rows[:top_n], rows[top_n:]
    if tail:
        tail_value = sum(r["value"] for r in tail)
        existing_autres = next((r for r in head if r["label"] == "Autres"), None)
        if existing_autres:
            existing_autres = dict(existing_autres, value=existing_autres["value"] + tail_value)
            head = [existing_autres if r["label"] == "Autres" else r for r in head]
        else:
            head = head + [{"label": "Autres", "value": tail_value}]
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

    category_slices = [{"label": c["category"], "value": c["value"]} for c in data["comparison"]]

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
        figs_json=json.dumps(figs, cls=plotly.utils.PlotlyJSONEncoder),
        last_update=pd.Timestamp.now().strftime("%d/%m/%Y %H:%M"),
    )


def _lan_ip() -> str:
    """Meilleure estimation de l'IP locale (celle utilisée pour joindre l'extérieur),
    pour afficher l'URL à ouvrir depuis le téléphone sans dépendre d'un vrai réseau."""
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
    print(f"Sur le même Wi-Fi, depuis ton téléphone : http://{_lan_ip()}:5050")
    app.run(debug=True, host="0.0.0.0", port=5050)
