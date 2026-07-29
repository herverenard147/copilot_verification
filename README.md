# 🧾 ReceiptFlow - Copilote de reçus et dépenses

> De la photo d'un reçu à des dépenses structurées, vérifiées et
> comptabilisées.



[Analyze-result](capture/Capture d’écran du 2026-07-28 23-11-04.png)

[mode démo](capture/Capture d’écran du 2026-07-28 23-14-01.png)

[reçu avec son écriture comptable visible](capture/Capture d’écran du 2026-07-28 23-16-01.png)

## 📹 Démonstration

[[Lien vers la demo]](https://www.loom.com/share/6956e73c95e54420b8984bef4f0c980d)

## Le problème

Traiter des notes de frais manuellement est lent et source d'erreurs :
saisie ligne par ligne, vérification des montants, classement comptable.
Ce projet automatise cette chaîne, d'une simple photo à une écriture
comptable proposée.

## Le pipeline

📷 Image  →  🤖 Donut  →  ✅ Règles  →  📊 Comptabilité  →  💬 FAISS+LLM  →  🖥️ Interface
(reçu)      (extraction)  (contrôle)    (SYSCOHADA)        (RAG)           (web)

1. **Extraction** — Donut (modèle pré-entraîné) lit l'image et produit
   un JSON structuré
2. **Vérification** — 4 règles métier, logique à 3 états (conforme /
   anomalie / non vérifiable)
3. **Comptabilité** — écriture SYSCOHADA proposée, multi-comptes selon
   les catégories d'articles
4. **Recherche** — FAISS + LLM (RAG) pour interroger ses dépenses en
   langage naturel

## Résultats

| Modèle                           | Exactitude (total) | JSON valide |
| -------------------------------- | ------------------ | ----------- |
| Donut (pré-entraîné)             | **97,87 %**        | 100 %       |
| Baseline MLP (entraînée par moi) | 19,15 %            | —           |

> L'écart est structurel : la baseline étiquette des mots sans savoir
> les regrouper en lignes d'articles. Donut génère la structure entière.
> Note aussi : la baseline est avantagée (positions de vérité terrain,
> pas un OCR réel) — l'écart réel serait plus grand encore.

**Démonstration du sur-apprentissage :**

| Configuration                        | Train  | Validation | Écart  |
| ------------------------------------ | ------ | ---------- | ------ |
| Sans régularisation                  | 63,5 % | 52,4 %     | 11,2 % |
| Avec régularisation + early stopping | 58,0 % | 53,7 %     | 4,3 %  |

[courbe de perte](capture/Capture d’écran du 2026-07-28 23-20-27.png)

**Règles métier sur les 800 reçus CORD :**

- 156 anomalies détectées (19,5 %)
- 466 reçus sans champ taxe (58 %) → traités comme "non vérifiable",
  pas comme anomalie (logique à 3 états)
- 224 reçus (28 %) produisent une écriture comptable multi-comptes

## Dataset

CORD (Consolidated Receipt Dataset) — ~1 000 reçus indonésiens annotés,
licence CC BY 4.0. Découpage 800 train / 100 validation / 100 test.

⚠️ **Particularités du dataset :**

- Le nom du marchand et la date sont absents des annotations publiques
  (retirés pour raisons légales) → récupérés par prompting zero-shot
- Les montants suivent la convention `"25,000"` = 25 000 (virgule =
  séparateur de milliers, pas décimal)
- Le schéma JSON est polymorphe (dict ou liste selon le nombre
  d'éléments) — à plusieurs niveaux de profondeur

```json
{
  "menu": [
    {"nm": "NASI GORENG", "cnt": "2", "unitprice": "25,000", "price": "50,000"},
    {"nm": "ES TEH", "cnt": "1", "unitprice": "8,000", "price": "8,000"}
  ],
  "sub_total": {"subtotal_price": "58,000", "tax_price": "5,800"},
  "total": {"total_price": "63,800"}
}
```

---

## Fonctionnalités

- ✅ Extraction automatique image → JSON structuré (Donut pré-entraîné)
- ✅ Baseline entraînée maison (MLP), comparée à Donut sur métrique commune
- ✅ 4 règles métier à 3 états (conforme / anomalie / non vérifiable)
- ✅ Comptabilité SYSCOHADA — écriture multi-comptes, TVA récupérable/non
- ✅ Recherche sémantique (FAISS) + questions en langage naturel (RAG)
- ✅ Clustering non supervisé (KMeans) pour catégoriser les dépenses
- ✅ Prompt engineering zero-shot (marchand, date — champs absents de CORD)
- ✅ Interface web (FastAPI + HTML/CSS/JS), + vue technique Streamlit
- ✅ Cloisonnement des données par session, persistance SQLite locale
- ✅ Édition manuelle : montants, catégorie, compte comptable, numéro de
  facture
- ✅ Réflexion éthique : biais géographique, DISCLAIMER comptable

## Architecture

copilot_verification/
├── api.py FastAPI — endpoints
├── app.py Streamlit — vue technique de secours
├── web/ Front HTML/CSS/JS
├── src/
│ ├── utils.py nettoyage des montants
│ ├── data_loader.py CORD → DataFrames
│ ├── receipt.py classe Receipt (POO)
│ ├── extractor.py pont vers Donut
│ ├── rules.py 4 règles métier
│ ├── accounting.py SYSCOHADA, écritures, TVA
│ ├── baseline.py le MLP entraîné
│ ├── evaluate.py métriques
│ ├── expenses.py base de dépenses
│ ├── semantic.py embeddings + FAISS
│ ├── llm.py prompting multi-backend
│ ├── session_store.py cloisonnement + persistance SQLite
│ └── preprocess.py redressement, contraste, garde-fou résolution
├── data/ artefacts (CSV, poids, résultats)
├── tests/ 88 tests
├── notebooks/ pipeline complet exécuté
└── docs/ audit, journal des erreurs

```
## Installation

```bash
git clone https://github.com/herverenard147/copilot_verification.git
cd copilot_verification
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn api:app --port 8500
```

Ouvrir `http://127.0.0.1:8500`. Premier lancement : Donut se télécharge
(~800 Mo, une fois). Optionnel : une clé Groq gratuite active le RAG et
l'extraction zero-shot (configurable dans Réglages).

## Notions du bootcamp

| Notion               | Où                                        |
| -------------------- | ----------------------------------------- |
| Python propre, POO   | `src/receipt.py`, modules séparés         |
| Data wrangling + viz | `data_loader.py`, notebook (graphiques)   |
| ML classique         | Baseline MLP + KMeans                     |
| Deep learning        | MLP entraîné (sur-apprentissage démontré) |
| NLP                  | Tokenisation, embeddings                  |
| Modèle pré-entraîné  | Donut                                     |
| Base vectorielle     | FAISS                                     |
| Prompt engineering   | Zero-shot + RAG                           |
| Interface            | FastAPI + HTML/CSS/JS                     |
| Éthique              | Biais géographique, DISCLAIMER            |

## Limites (assumées, pas cachées)

1. **Domaine restreint** — testé sur une facture française : montants
   corrects, en-tête confondu avec des articles. Sur un ticket ivoirien :
   échec complet. [IMAGE : les deux tests, côte à côte]
2. **Champs censurés** — marchand/date récupérés par prompting, non
   validés automatiquement
3. **Baseline avantagée** — positions de vérité terrain, pas un vrai OCR
4. **Anomalies non labellisées** — détectées par règles, pas validées
   par un humain sur CORD
5. **Comptabilité indicative** — plan simplifié, à valider par un
   professionnel
6. **Clustering non supervisé** — catégories non validées par une
   vérité terrain

## Éthique

Les datasets publics de Document AI couvrent l'Asie et l'Amérique du
Nord — pas l'Afrique de l'Ouest. Un outil bâti sur ces données offre un
service inégal selon l'origine géographique de l'utilisateur, invisible
dans les métriques agrégées puisque le jeu de test partage le biais du
jeu d'entraînement. Testé et documenté, pas supposé.

> ⚠️ L'affectation comptable proposée est indicative. Elle doit être
> validée par un professionnel avant tout usage officiel.

## Attribution

Dataset CORD © NAVER CLOVA AI Research, CC BY 4.0.
Park, S. et al. (2019). *CORD: A Consolidated Receipt Dataset for
Post-OCR Parsing.* Document Intelligence Workshop, NeurIPS.
