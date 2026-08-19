# 📊 Portfolio Dashboard

Dashboard d'analyse de portefeuille boursier (PEA + CTO) à partir des exports CSV
de courtiers (Fortuneo, Trade Republic). Reconstruit les positions et le PnL
depuis le journal de transactions brut (pas d'API courtier), calcule les
dividendes, les frais de gestion, la diversification géographique/sectorielle,
et compare le patrimoine global (bourse + épargne) à une allocation cible.

**[➡ Voir la démo en ligne](https://à-compléter-après-déploiement.onrender.com)**
*(données 100 % fictives — voir [Confidentialité](#-confidentialité) ci-dessous.
Le service gratuit s'endort après 15 min d'inactivité : le premier chargement
peut prendre ~30 s.)*

## Fonctionnalités

- **Reconstruction de positions** au coût moyen pondéré à partir du journal brut
  (achats/ventes/dividendes), sans dépendre d'une API de courtier.
- **Prix live** via [yfinance](https://pypi.org/project/yfinance/) pour les
  actifs mappés (`config/tickers.json`), avec repli explicite sur le prix de
  revient moyen pour les autres — jamais de prix inventé.
- **Vue Bourse** : performance dans le temps, classement des actifs, répartition
  par courtier, diversification géographique/sectorielle, frais de gestion
  annuels, journal des transactions/dividendes.
- **Vue Patrimoine global** : bourse + comptes d'épargne (Livret A, PEL,
  assurance-vie...), comparaison à une allocation cible avec écarts.
- **PWA installable** sur téléphone (icône d'accueil, plein écran), pensé
  mobile-first (listes tactiles, graphiques compacts, navigation par onglets).

## Architecture

```
portfolio-dashboard/
├── data/                    # Données RÉELLES — jamais commitées (.gitignore)
│   ├── fortuneo/             # Exports "Historique des opérations" Fortuneo
│   ├── trade_republic/       # Exports "transactions_*.csv" Trade Republic
│   ├── accounts/accounts.json  # Comptes d'épargne, saisis à la main
│   └── processed/            # transactions.csv normalisé (généré)
├── config/                  # Mappings personnels — jamais commités (.gitignore)
│   ├── tickers.json          # asset_key -> ticker Yahoo Finance
│   ├── fees.json              # asset_key -> TER annuel (%)
│   ├── asset_classes.json     # asset_key -> classe d'actif
│   ├── target_allocation.json # allocation cible du patrimoine (%)
│   └── exposure.json          # asset_key -> ventilation pays/secteur
├── demo/                    # Équivalent 100 % FICTIF de data/ + config/,
│   │                          committé pour la démo publique
│   └── ...                   # même structure que data/ et config/
├── scripts/
│   └── generate_demo_data.py # (Re)génère demo/ à partir de zéro
├── importers/
│   ├── fortuneo.py            # Parseur Fortuneo (CSV ';', cp1252)
│   ├── trade_republic.py      # Parseur Trade Republic (CSV ',', UTF-8)
│   ├── corrections.py         # Achats correctifs manuels (historique incomplet)
│   └── normalize.py           # Fusionne toutes les sources en un journal commun
├── analytics/
│   ├── positions.py           # Coût moyen pondéré + PnL réalisé
│   ├── kpis.py                 # Agrégation des KPIs globaux
│   ├── performance.py          # Valeur du portefeuille dans le temps
│   ├── performance_by_asset.py # Performance par actif
│   ├── patrimoine.py           # Vue patrimoine global (bourse + épargne)
│   └── exposure.py             # Diversification géographique/sectorielle
├── market_data.py            # Prix live via yfinance (+ cache disque)
├── paths.py                  # Résolution data/config, override via PORTFOLIO_ROOT
├── dashboard/
│   ├── app.py                  # Serveur Flask + génération des graphiques Plotly
│   └── templates/               # base.html, index.html (Bourse), patrimoine.html
├── wsgi.py                    # Point d'entrée gunicorn (déploiement)
├── main.py                    # Import CSV + résumé en ligne de commande
├── Procfile / render.yaml     # Déploiement Render
└── requirements.txt
```

## Setup (avec tes propres données)

```bash
pip install -r requirements.txt
```

1. Déposer les exports CSV dans `data/fortuneo/` et `data/trade_republic/`
   (plusieurs fichiers acceptés par dossier, dédupliqués automatiquement).
2. Renseigner `data/accounts/accounts.json` avec tes comptes d'épargne (voir
   `analytics/patrimoine.py` pour le schéma attendu).
3. (Optionnel mais recommandé) Compléter `config/tickers.json` avec les tickers
   Yahoo Finance de chaque actif détenu, pour obtenir des prix live plutôt que le
   prix de revient moyen (PRU). Vérifier chaque ticker sur
   [finance.yahoo.com](https://finance.yahoo.com) avant de le renseigner —
   un mauvais ticker fausserait la valorisation.
4. Compléter `config/asset_classes.json`, `config/fees.json`,
   `config/target_allocation.json` et `config/exposure.json` selon les mêmes clés.
5. Lancer le résumé en ligne de commande :
   ```bash
   python main.py
   ```
6. Lancer le dashboard :
   ```bash
   python dashboard/app.py
   ```
   Puis ouvrir **http://localhost:5050** (accessible aussi depuis le même
   Wi-Fi via l'IP affichée au démarrage — utile pour tester sur mobile).

## Mode démo (sans données personnelles)

L'app peut tourner entièrement sur un jeu de données fictif, via la variable
d'environnement `PORTFOLIO_ROOT` qui redirige `data/` et `config/` vers un autre
dossier de même structure :

```bash
# Windows PowerShell
$env:PORTFOLIO_ROOT = "demo"; python dashboard/app.py
# macOS / Linux
PORTFOLIO_ROOT=demo python dashboard/app.py
```

Le contenu de `demo/` est généré par `scripts/generate_demo_data.py` — un
portefeuille et des comptes entièrement inventés, construits sur de vrais
tickers cotés (Apple, LVMH, Sanofi, Coca-Cola, ETF monde) pour que les prix
live restent crédibles. C'est ce dossier qui alimente le déploiement public.

## Déploiement (Render)

Le repo inclut un `render.yaml` prêt à l'emploi :

1. Créer un compte [Render](https://render.com) et connecter le repo GitHub.
2. **New +** → **Blueprint**, sélectionner ce repo — Render lit `render.yaml`
   et configure automatiquement le service (`gunicorn wsgi:app`,
   `PORTFOLIO_ROOT=demo`).
3. Déployer. Le plan gratuit s'endort après 15 min d'inactivité (premier
   chargement plus lent après une pause).

Le serveur de dev Flask (`python dashboard/app.py`) n'est **pas** utilisé en
production — `wsgi.py` + `gunicorn` s'en chargent.

## Formats CSV supportés

### Fortuneo — "Historique des opérations bourse"
CSV `;`, encodage Windows-1252, colonnes : `libellé;Opération;Place;Date;Qté;Prix
d'éxé;Montant brut;Courtage/Prélèvement;Montant net;Devise`.

### Trade Republic — export "Transactions"
CSV `,` avec guillemets, UTF-8, colonnes : `datetime,date,account_type,category,
type,asset_class,name,symbol,shares,price,amount,fee,tax,currency,...`. Le champ
`symbol` contient en réalité l'ISIN.

## Notes de calcul

- **Coût moyen pondéré** : chaque achat augmente la quantité et le coût total
  détenu ; chaque vente retire la quantité vendue au coût moyen courant et
  déclenche le PnL réalisé correspondant.
- **Dividendes Fortuneo** : seules les lignes `Encaissement coupons
  intérêt/dividende` sont comptées comme dividende réel. Les lignes `OST de
  création de coupons` / `ANNUL. OST...` (écritures techniques de détachement
  de coupon optionnel) sont conservées dans le journal mais exclues des totaux,
  faute de certitude sur leur traitement comptable exact — à vérifier
  ponctuellement contre le relevé Fortuneo si une précision au centime est
  nécessaire.
- **Capital net investi** (graphique de performance) = flux de trésorerie net
  vers les investissements (achats − ventes), pas le coût de revient comptable
  strict des positions ouvertes.
- **Prix historiques** : pour les actifs sans ticker mappé, l'historique de prix
  est approximé par le prix de revient moyen actuel (ligne plate) — la courbe de
  performance n'est donc fiable que pour les actifs mappés dans
  `config/tickers.json`.

## Confidentialité

Aucune donnée personnelle n'est envoyée où que ce soit ni committée dans Git :

- `data/fortuneo/*.csv`, `data/trade_republic/*.csv`, `data/processed/*.csv`,
  `data/accounts/` et tous les fichiers de `config/*.json` (tickers, frais,
  classes d'actif, allocation cible, exposition — ils révèlent la composition
  exacte du portefeuille réel) sont exclus via `.gitignore`.
- La démo publique tourne exclusivement sur `demo/`, un jeu de données fictif
  committé volontairement (voir [Mode démo](#mode-démo-sans-données-personnelles)).
- Tout le calcul tourne en local (ou sur l'instance de déploiement que tu
  contrôles) ; le seul appel réseau sortant est vers Yahoo Finance pour les prix.
