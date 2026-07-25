# Documentation technique — Copilote de reçus et dépenses

Dépôt : github.com/herverenard147/copilot_verification
Ce fichier est destiné au dossier racine du dépôt.

---

## 1. Vue d'ensemble

Application de traitement automatisé de reçus. Une image entre, un JSON
structuré et vérifié sort, alimente une base de dépenses interrogeable en
langage naturel.

```
┌──────────────┐
│ Image reçu   │
└──────┬───────┘
       ▼
┌──────────────────────────────┐
│ EXTRACTION                   │
│  A. Donut pré-entraîné       │  image → JSON (voie principale)
│  B. Baseline MLP entraînée   │  mot+position → étiquette (comparaison)
└──────┬───────────────────────┘
       ▼
┌──────────────────────────────┐
│ NORMALISATION                │  clean_amount, ensure_list, merge_blocks
│ classe Receipt               │  objet métier unifié
└──────┬───────────────────────┘
       ▼
┌──────────────────────────────┐
│ RÈGLES MÉTIER                │  R1 somme lignes / R2 total / R3 taxe
│ → drapeaux d'anomalie        │  logique à 3 états : True / False / None
└──────┬───────────────────────┘
       ▼
┌──────────────────────────────┐
│ BASE DE DÉPENSES (pandas)    │  df_items · df_receipts
│ + catégories (KMeans)        │  clustering non supervisé sur embeddings
└──────┬───────────────────────┘
       ▼
┌──────────────────────────────┐
│ RECHERCHE SÉMANTIQUE (FAISS) │  résumés de reçus vectorisés
│ + RAG (LLM)                  │  retrieval puis génération
└──────┬───────────────────────┘
       ▼
┌──────────────────────────────┐
│ INTERFACE STREAMLIT          │  3 onglets : analyser / dashboard / questions
└──────────────────────────────┘
```

---

## 2. Arborescence

```
copilot_verification/
├── README.md
├── DOCUMENTATION_TECHNIQUE.md
├── requirements.txt
├── app.py                     Interface Streamlit
├── data/                      Artefacts générés (CSV, résumés)
├── notebooks/
│   ├── 01_exploration.ipynb   Chargement, exploration, nettoyage, viz
│   ├── 02_extraction.ipynb    Donut : premier JSON
│   ├── 03_baseline_eval.ipynb Baseline MLP, règles, comparaison
│   └── 04_rag_demo.ipynb      KMeans, FAISS, prompting, RAG
├── src/
│   ├── utils.py
│   ├── data_loader.py
│   ├── receipt.py
│   ├── extractor.py
│   ├── rules.py
│   ├── evaluate.py
│   ├── baseline.py
│   ├── expenses.py
│   ├── semantic.py
│   └── llm.py
└── tests/
    └── test_rules.py
```

**Principe de séparation.** Les notebooks explorent et démontrent ; `src/`
contient le code réutilisable. Un notebook n'implémente jamais de logique
métier : il appelle `src/`.

---

## 3. Référence des modules

### `src/utils.py`

| Fonction | Signature | Rôle |
|---|---|---|
| `clean_amount` | `(raw) -> float \| None` | Convertit un montant CORD en nombre. Convention indonésienne : `"25,000"` → `25000.0` (virgule = milliers). |
| `ensure_list` | `(x) -> list` | Uniformise le schéma polymorphe de CORD : un dict seul devient une liste d'un élément. |

### `src/data_loader.py`

| Fonction | Signature | Rôle |
|---|---|---|
| `receipt_to_rows` | `(gt_parse, receipt_id) -> list[dict]` | Aplatit les articles d'un reçu en lignes. |
| `merge_blocks` | `(x) -> dict` | Fusionne une liste de blocs `sub_total`/`total` en un dict unique (le dernier bloc gagne). |
| `totals_of` | `(gt_parse) -> dict` | Extrait subtotal, tax, total. |
| `load_dataframes` | `(split) -> (DataFrame, DataFrame)` | Split HuggingFace → tableaux articles et reçus. |

### `src/receipt.py`

Classe `Receipt` — l'objet métier central.

| Membre | Rôle |
|---|---|
| `__init__(items, subtotal, tax, total, receipt_id)` | Constructeur. |
| `from_gt_parse(gt_parse, receipt_id)` *(classmethod)* | Fabrique un `Receipt` depuis un JSON CORD **ou une sortie Donut** — même moule pour les deux. |
| `items_sum()` | Somme des prix de ligne connus. |
| `__repr__()` | Affichage lisible. |

### `src/extractor.py`

| Fonction | Signature | Rôle |
|---|---|---|
| `extract` | `(image, model, processor, device) -> dict` | Pont vers Donut. Prépare l'image, génère la séquence, nettoie les tokens spéciaux, convertit en dict via `token2json`. |

### `src/rules.py`

Moteur de règles. **Trois états de retour** : `True` (conforme), `False`
(anomalie), `None` (information insuffisante pour juger).

| Fonction | Règle |
|---|---|
| `check_line_sum(receipt, tolerance=0.02)` | R1 — somme des lignes ≈ sous-total |
| `check_total(receipt, tolerance=0.02)` | R2 — sous-total + taxe ≈ total |
| `check_tax_rate(receipt, country, band)` | R3 — taux de taxe plausible (`ID` 11 %, `CI` 18 %) |
| `audit(receipt, country)` | Applique tout, renvoie les drapeaux + `anomaly` |

`TAX_RATES = {"ID": 0.11, "CI": 0.18}` — le paramètre `country` rend le moteur
généralisable même si l'extracteur, lui, reste spécifique à l'Indonésie.

### `src/evaluate.py`

| Fonction | Rôle |
|---|---|
| `get_amount(gt_parse, block, key)` | Extrait un montant d'un JSON CORD-like. |
| `field_accuracy(preds, gts, block, key)` | % de reçus où le montant prédit égale le vrai, sur ceux où le vrai existe. |
| `valid_json_rate(preds)` | % de sorties exploitables. |

### `src/baseline.py`

| Fonction | Rôle |
|---|---|
| `featurize_word(text, cx, cy, img_w, img_h)` | Feature engineering : un mot → 8 nombres (position normalisée, longueur, proportion de chiffres, séparateur de milliers, majuscules, alphabétique, marqueur `x`). |
| `word_center(quad)` | Centre du quadrilatère d'un mot. |
| `build_word_dataset(split)` | Split → `(X, y)` pour l'apprentissage supervisé. |

**Note d'implémentation.** Les étiquettes sont des chaînes (`"menu.nm"`). Elles
doivent être encodées en entiers via `LabelEncoder` avant `MLPClassifier(...)`
avec `early_stopping=True` : scikit-learn applique `isnan` aux prédictions
pendant la validation, ce qui échoue sur du texte. `inverse_transform` permet
de relire les prédictions.

### `src/expenses.py`

| Fonction | Rôle |
|---|---|
| `build_expense_db(split, limit)` | Construit `df_items` et `df_receipts`, audits inclus. |
| `receipt_text(gt_full)` | Reconstruit le texte brut d'un reçu depuis `valid_line` (entrée du prompting). |

### `src/semantic.py`

| Fonction | Rôle |
|---|---|
| `get_encoder(name)` | Charge `all-MiniLM-L6-v2` (384 dimensions, CPU-compatible). |
| `embed(texts, encoder)` | Textes → matrice normalisée L2. |
| `build_index(vecs)` | `IndexFlatIP` : produit scalaire sur vecteurs normalisés = similarité cosinus. |
| `search(query, encoder, index, texts, k)` | Question → k textes les plus proches, avec scores. |

### `src/llm.py`

| Fonction | Rôle |
|---|---|
| `init_llm(api_key, model_name)` | Initialise le client Gemini. |
| `extract_merchant_date(receipt_text)` | **Zero-shot** : marchand et date, absents des labels CORD. Prompt à consignes explicites, sortie JSON contrainte, parsing défensif. |
| `answer_question(question, contexts)` | **RAG** : réponse fondée uniquement sur les reçus fournis. |

---

## 4. Flux de données

```
ds["train"][i]
  ├─ ["image"]         ──► extract()              ──► dict prédit
  └─ ["ground_truth"]
       ├─ ["gt_parse"]  ──► Receipt.from_gt_parse ──► Receipt ──► audit()
       └─ ["valid_line"]──► build_word_dataset    ──► (X, y)  ──► MLPClassifier
                        └─► receipt_text          ──► extract_merchant_date()

df_items ──► embed(noms) ──► KMeans      ──► catégories
résumés  ──► embed()     ──► FAISS index ──► search() ──► answer_question()
```

---

## 5. Installation et exécution

### Prérequis

```
Python 3.10+
GPU recommandé (Donut : ~5 s/reçu sur T4, ~60 s sur CPU)
```

### Installation

```bash
git clone https://github.com/herverenard147/copilot_verification.git
cd copilot_verification
pip install -r requirements.txt
```

`requirements.txt` :

```
transformers>=4.40
datasets
sentencepiece
torch
pandas
numpy
matplotlib
seaborn
scikit-learn
sentence-transformers
faiss-cpu
google-generativeai
streamlit
pytest
Pillow
```

### Exécution des notebooks

Dans l'ordre : `01_exploration` → `02_extraction` → `03_baseline_eval` →
`04_rag_demo`. Le dernier génère les artefacts de `data/` nécessaires à l'app.

### Lancement de l'interface

```bash
streamlit run app.py
```

Sur Colab, exposer le port :

```python
!streamlit run app.py &>/content/streamlit.log &
!curl -s ipv4.icanhazip.com          # mot de passe du tunnel
!npx --yes localtunnel --port 8501
```

### Tests

```bash
pytest tests/ -q
```

---

## 6. Choix techniques et justifications

| Décision | Alternative écartée | Raison |
|---|---|---|
| Donut utilisé tel quel | Fine-tuning sur CORD | Le brief demande d'utiliser un modèle pré-entraîné ; le fine-tuning coûte des heures de GPU pour un gain marginal sur le barème. |
| Baseline MLP maison | Aucune baseline | Sans point de comparaison, un score isolé ne veut rien dire. La baseline couvre aussi supervisé/loss/overfitting/régularisation. |
| Règles à 3 états | Booléen simple | Confondre « information absente » et « anomalie » produirait des faux positifs massifs sur les reçus sans champ taxe. |
| `IndexFlatIP` + normalisation L2 | `IndexFlatL2` | Similarité cosinus, plus adaptée aux embeddings de phrases. Index exact : à 800 vecteurs, l'approximation est inutile. |
| Streamlit | Gradio | Application multi-onglets (analyse + dashboard + questions) plutôt que démo d'une fonction unique. |
| KMeans sur embeddings de noms | KMeans sur TF-IDF | Les embeddings capturent la proximité sémantique, pas seulement lexicale. |

---

## 7. Limites connues

1. **Domaine restreint.** Tous les reçus d'entraînement de Donut sont
   indonésiens. Performance non garantie ailleurs — démontré sur un ticket
   ivoirien (voir rapport).

2. **Champs censurés.** `store_info`, `payment_info` et `etc` ont été retirés de
   la version publique de CORD pour raisons légales. Marchand et date sont donc
   récupérés par prompting, sans vérité terrain pour les évaluer
   automatiquement.

3. **Baseline avantagée.** Elle consomme les positions de mots de la ground
   truth, pas un OCR réel. L'écart mesuré avec Donut sous-estime l'écart réel.

4. **Comparaison partielle.** L'évaluation porte sur `total.total_price`. La
   baseline étiquette des mots sans savoir les regrouper en lignes d'articles :
   limite structurelle des approches par classification de tokens, et
   justification de l'existence des modèles génératifs comme Donut.

5. **Anomalies non labellisées.** CORD ne contient pas de reçus erronés
   identifiés. La détection est évaluée sur des perturbations synthétiques, qui
   ne reflètent pas la distribution des erreurs réelles.

6. **Clustering non supervisé.** Les catégories découvertes par KMeans sont
   cohérentes pour certains groupes, floues pour d'autres. Aucune vérité terrain
   ne permet de les valider objectivement.

7. **Dépendance API.** Le zero-shot et le RAG requièrent une clé Gemini. Sans
   clé, la recherche sémantique fonctionne mais la génération de réponse non.

---

## 8. Éthique et biais

**Biais géographique.** Les jeux de données publics de Document AI couvrent
l'Asie et l'Amérique du Nord ; l'Afrique de l'Ouest en est absente. Un outil de
notes de frais bâti sur CORD fonctionnerait pour un employé de Jakarta et
échouerait pour un employé d'Abidjan — inégalité de service invisible dans les
métriques agrégées, puisque le jeu de test partage le biais du jeu
d'entraînement.

**Censure des données et transparence.** Le retrait des champs marchand et date
répond à des contraintes légales indonésiennes. Cette contrainte est documentée
plutôt que contournée silencieusement : le système ne prétend pas connaître ce
qu'il ne peut pas apprendre, il signale que ces champs proviennent d'une
inférence non vérifiée.

**Explicabilité.** Le moteur de règles est délibérément déterministe et lisible :
un utilisateur à qui l'on refuse une note de frais peut savoir quelle règle a
déclenché, avec quels montants. Une détection d'anomalies purement apprise
serait plus performante mais opaque — arbitrage assumé en faveur de
l'explicabilité pour un usage à conséquences administratives.

**Risque d'usage.** Un système d'extraction imparfait utilisé sans contrôle
humain peut produire des rejets de remboursement injustifiés. Les drapeaux
d'anomalie sont conçus comme une aide à la décision, pas comme un verdict.
