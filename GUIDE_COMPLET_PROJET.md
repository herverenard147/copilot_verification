# Guide complet du projet — Copilote de reçus et dépenses

Ce document explique TOUT le projet comme si tu n'y avais jamais touché.
Lis-le la veille de la soutenance, c'est ton filet de sécurité.

---

## 1. LE PROJET EN UNE PHRASE

Une application web où l'on dépose la photo d'un reçu ou d'une facture,
et qui automatiquement : extrait les articles et les montants, vérifie que
les comptes tombent juste, propose une écriture comptable, et permet
d'interroger ses dépenses en langage naturel.

---

## 2. POURQUOI CE PROJET EXISTE

Le traitement des notes de frais est un problème réel : un employé revient
de déplacement avec une pile de tickets, et quelqu'un doit les saisir un
par un, vérifier que les montants sont cohérents, les classer par catégorie,
et produire des écritures comptables. C'est long, sujet aux erreurs, et
personne n'aime le faire.

Ce projet automatise cette chaîne :

```
Photo du reçu → Lecture automatique → Vérification → Comptabilité → Recherche
```

---

## 3. LES DONNÉES — LE DATASET CORD

### 3.1 Ce que c'est

CORD (Consolidated Receipt Dataset) = 1 000 photos de reçus de caisse
indonésiens, chacune accompagnée de sa transcription faite par un humain.
C'est à la fois notre matière première ET notre correcteur : on peut
vérifier si notre machine lit bien en comparant sa lecture à la réponse
humaine.

### 3.2 Le découpage

- **800 reçus d'entraînement** : ceux sur lesquels le modèle apprend
- **100 de validation** : pour régler les paramètres sans tricher
- **100 de test** : l'examen final, regardé UNE seule fois

### 3.3 Les trois pièges du dataset (à connaître par cœur)

**Piège 1 : les montants.** `"25,000"` veut dire vingt-cinq mille roupies,
pas 25. La virgule sépare les milliers, pas les décimales. Si on fait
`float("25,000".replace(",","."))`, on divise tous les montants par 1000
en silence. → Corrigé par `clean_amount()` dans `src/utils.py`.

**Piège 2 : le schéma polymorphe.** Un seul article est un dictionnaire,
plusieurs sont une liste. Ça vaut pour `menu`, `sub_total`, `total`, et
même la RACINE de la sortie de Donut. On a eu ce bug QUATRE fois (erreurs
E1, E8 dans le journal). → Corrigé par `ensure_list()` et `merge_blocks()`.

**Piège 3 : les champs absents.** Le nom du marchand et la date ont été
retirés de la version publique pour raisons légales indonésiennes. On ne
peut pas les apprendre en supervisé → récupérés par prompting zero-shot.

### 3.4 Ce que ça donne concrètement

Un JSON comme celui-ci :

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

## 4. LE MODÈLE D'EXTRACTION — DONUT

### 4.1 Ce qu'il fait

Donut regarde directement l'image du reçu et écrit le JSON structuré,
sans étape OCR séparée. Il « lit » l'image avec un encodeur visuel (Swin),
puis « écrit » le résultat token par token avec un décodeur (BART). C'est
pour ça qu'il n'a pas besoin d'OCR : il lit et structure d'un seul geste.

### 4.2 Pourquoi on ne l'a PAS entraîné

Le modèle qu'on utilise (`naver-clova-ix/donut-base-finetuned-cord-v2`)
a déjà été entraîné sur CORD par ses auteurs. On le télécharge et on
l'utilise tel quel — c'est de l'INFÉRENCE, pas de l'entraînement. Le brief
du bootcamp dit exactement : « use a pre-trained model, even if just for
one part ».

### 4.3 Ses résultats

- **Exactitude sur le champ total : 97,87 %** sur 50 reçus du split test
- **Taux de sortie JSON valide : 100 %**
- Temps d'inférence : ~5 s sur GPU, ~30-60 s sur CPU

### 4.4 Ses limites (à dire en soutenance)

- Entraîné sur des reçus indonésiens → ne généralise pas aux tickets
  ivoiriens (testé et démontré)
- Sur une facture française de graphiste, il extrait correctement les
  montants MAIS confond l'en-tête (nom, email, adresse) avec des articles
  → problème de post-traitement, pas de lecture
- Sur des photos de basse résolution (<0,3 Mpx), il hallucine du texte
  plausible au lieu d'échouer proprement → garde-fou de résolution ajouté

---

## 5. LA BASELINE — LE MODÈLE QU'ON A ENTRAÎNÉ SOI-MÊME

### 5.1 Ce qu'elle fait

Un petit réseau de neurones (MLP, 2 couches de 64 et 32 neurones) qui
prend chaque MOT du reçu avec sa position et prédit son étiquette :
"est-ce un nom d'article ? un prix ? une quantité ?"

### 5.2 Le feature engineering (les 8 caractéristiques)

Pour chaque mot, on calcule 8 nombres :

1. Position horizontale (0 à 1) — un prix est souvent à DROITE
2. Position verticale (0 à 1) — le total est en BAS
3. Longueur du mot — un prix est court
4. Proportion de chiffres — un prix est plein de chiffres
5. Contient une virgule ou un point ? — séparateur de milliers
6. Tout en majuscules ? — souvent un titre
7. Que des lettres ? — pas un montant
8. Contient "x" ? — marqueur de quantité ("2x")

Comment un humain repère-t-il un prix sur un ticket ? Il regarde à droite,
il cherche des chiffres avec des virgules. Ces 8 features traduisent ce
regard en nombres.

### 5.3 Le sur-apprentissage (LA démonstration clé)

| Configuration                        | Train  | Validation | Écart      |
| ------------------------------------ | ------ | ---------- | ---------- |
| Sans régularisation (2000 ex.)       | 63,5 % | 52,4 %     | **11,2 %** |
| Avec régularisation + early stopping | 58,0 % | 53,7 %     | **4,3 %**  |

L'écart se resserre de 11,2 % à 4,3 %. Note que l'exactitude
d'entraînement BAISSE (63,5 → 58,0) pendant que la validation MONTE
(52,4 → 53,7). C'est exactement ce que fait la régularisation : elle
sacrifie l'ajustement aux données d'entraînement pour gagner en
généralisation.

### 5.4 Le résultat comparé

- **Donut : 97,87 %** sur le total
- **Baseline : 19,15 %** sur le total

L'écart est énorme et c'est NORMAL — la baseline étiquette des mots sans
savoir les regrouper en lignes d'articles. Elle peut dire "ceci est un
prix" sans savoir à quel article il se rattache. Donut génère la structure
entière. C'est une limite STRUCTURELLE, pas un défaut d'entraînement.

Et la baseline est AVANTAGÉE : elle utilise les positions de mots de la
vérité terrain, pas un vrai OCR. L'écart réel serait encore plus grand.

---

## 6. LES RÈGLES MÉTIER — LE CONTRÔLEUR COMPTABLE

4 règles, chacune avec 3 réponses possibles : ✅ conforme, ❌ anomalie,
➖ non vérifiable (information absente). Cette logique à trois états est
FONDAMENTALE : sans le ➖, les 466 reçus sans taxe seraient tous signalés
en rouge à tort.

### R1 — Somme des articles

La somme de toutes les lignes doit valoir le sous-total (±2 %).
Quand ça échoue : un article manque ou a été mal lu.

### R2 — Calcul du total

Sous-total + taxe doit valoir le total (±2 %).
Quand ça échoue : souvent un frais de service non extrait (fréquent dans
les restaurants indonésiens).

### R3 — Taux de taxe

Le ratio taxe/sous-total doit être plausible pour le pays sélectionné
(≈11 % en Indonésie, ≈18 % en Côte d'Ivoire).
Le sélecteur de pays est important : avec le mauvais pays, la taxe sera
toujours signalée rouge.

### R4 — Équilibre comptable

Dans l'écriture comptable, la somme des débits doit égaler la somme des
crédits. C'est la seule règle EXACTE (pas de tolérance de 2 %).

### Les chiffres sur CORD

- 156 anomalies détectées sur 800 reçus (19,5 %)
- La cause la plus fréquente : R2 (119 cas) — frais de service non extraits
- 466 reçus sur 800 n'ont pas de taxe → chip ➖, pas ❌

---

## 7. LA COMPTABILITÉ — MODULE SYSCOHADA

### 7.1 Le plan de comptes simplifié

| Compte | Quoi                                          |
| ------ | --------------------------------------------- |
| 601    | Achats de marchandises (nourriture, boissons) |
| 605    | Autres achats (emballage, fournitures)        |
| 6181   | Transport                                     |
| 627    | Publicité, réception                          |
| 628    | Télécommunications                            |
| 638    | Autres charges (par défaut)                   |
| 4452   | TVA récupérable                               |
| 401    | Fournisseurs (achat à crédit)                 |
| 521    | Banque                                        |
| 571    | Caisse (espèces)                              |

### 7.2 Comment ça marche

Chaque article est classé par catégorie (KMeans), chaque catégorie est
mappée à un compte comptable. L'écriture produit autant de lignes de débit
que de comptes distincts utilisés :

Exemple d'un reçu avec de la nourriture ET de l'emballage :

```
Compte 601 : Achats          → débit 40 000
Compte 605 : Emballage       → débit  8 000
Compte 571 : Caisse          → crédit 48 000
                                ————————————
                    Total :    48 000 = 48 000 ✓
```

### 7.3 La TVA non récupérable

La TVA n'est déductible que si le fournisseur est identifié. Or le champ
marchand est absent de CORD → TVA non récupérable sur la quasi-totalité
des reçus. C'est un cas métier LÉGITIME, pas un bug : un vrai comptable
refuserait aussi un crédit de TVA sans facture nominative.

### 7.4 Multi-comptes : les chiffres

Après élargissement de la table de mots-clés :

- 224/800 reçus (28 %) produisent une écriture multi-comptes
- 204 à 2 comptes, 20 à 3 comptes
- Contre 0/800 avant l'élargissement

### 7.5 Le DISCLAIMER (à dire en soutenance)

L'affectation des comptes est INDICATIVE. Elle doit être validée par un
professionnel. L'outil aide à la saisie, il ne remplace pas un comptable
et n'est pas un logiciel certifié.

---

## 8. LA RECHERCHE SÉMANTIQUE ET LE RAG

### 8.1 Les embeddings

Chaque reçu est transformé en un résumé textuel, puis en un vecteur de
384 nombres par le modèle `all-MiniLM-L6-v2`. Deux reçus qui parlent de
choses similaires auront des vecteurs proches — c'est la « proximité
sémantique ».

### 8.2 FAISS

L'index FAISS stocke ces vecteurs et retrouve les plus proches d'une
requête. Quand tu tapes « boissons fraîches », FAISS ne cherche pas le mot
exact « boissons » — il cherche des reçus dont le SENS est proche. C'est
la recherche sémantique, pas une recherche par mot-clé.

### 8.3 Le RAG (Retrieval-Augmented Generation)

1. L'utilisateur pose une question
2. FAISS retrouve les reçus les plus proches (retrieval)
3. Le LLM (via Groq) lit ces reçus et rédige une réponse (generation)

Sans le retrieval, le LLM inventerait des chiffres. Le RAG garantit que la
réponse est FONDÉE sur des documents retrouvés.

### 8.4 Le prompt engineering

Les champs marchand et date sont ABSENTS de CORD. On les récupère en
ZERO-SHOT : on demande directement au LLM d'extraire ces informations du
texte brut du reçu, sans lui donner d'exemple. C'est la seule voie
possible puisque ces champs n'existent pas dans les annotations.

---

## 9. L'ARCHITECTURE TECHNIQUE

### 9.1 Les deux applications

- **FastAPI + HTML/CSS/JS** : l'application utilisateur (ce qu'on montre)
- **Streamlit (app.py)** : la vue technique de secours (les notebooks
  sont la vraie présentation technique)

### 9.2 La structure des fichiers

```
copilot_verification/
├── api.py                    ← FastAPI, les endpoints
├── app.py                    ← Streamlit, vue technique de secours
├── web/                      ← le front HTML/CSS/JS
│   ├── index.html
│   ├── css/styles.css
│   └── js/app.js, api.js
├── src/                      ← le cœur du projet
│   ├── utils.py                 clean_amount, ensure_list
│   ├── data_loader.py           CORD → DataFrames
│   ├── receipt.py               la classe Receipt
│   ├── extractor.py             le pont vers Donut
│   ├── rules.py                 les 4 règles métier
│   ├── accounting.py            SYSCOHADA, écritures, TVA
│   ├── baseline.py              le MLP qu'on entraîne
│   ├── evaluate.py              les métriques
│   ├── expenses.py              la base de dépenses
│   ├── semantic.py              embeddings + FAISS
│   ├── llm.py                   prompting multi-backend
│   ├── session_store.py         cloisonnement par session
│   └── preprocess.py            redressement, contraste
├── data/                      ← les artefacts
│   ├── items.csv, receipts.csv  la base de dépenses
│   ├── results.csv              Donut vs baseline
│   ├── overfitting.csv          les 4 chiffres
│   ├── baseline_mlp.joblib      les poids de ta baseline
│   └── ...
├── tests/                     ← 68 tests
├── notebooks/                 ← le notebook exécuté
└── docs/                      ← audit, journal des erreurs
```

### 9.3 Comment lancer

```bash
cd copilot_verification
source .venv/bin/activate      # ou créer le venv
pip install -r requirements.txt
uvicorn api:app --port 8500    # ouvrir http://127.0.0.1:8500
```

### 9.4 Le cloisonnement de session

Les données utilisateur (reçus validés) vivent en mémoire, séparées du
corpus CORD. Un mode démonstration charge les 800 reçus CORD avec un
bandeau visible. La persistance entre redémarrages est assurée par un
fichier JSON local hors du dépôt.

---

## 10. LES 10 NOTIONS DU BOOTCAMP — OÙ ELLES SONT

| #   | Notion               | Où exactement                                           |
| --- | -------------------- | ------------------------------------------------------- |
| 1   | Python propre, POO   | `src/receipt.py` (classe Receipt), modules séparés      |
| 2   | Data wrangling + viz | `data_loader.py`, notebook (3 graphiques seaborn)       |
| 3   | ML classique         | Baseline MLP + KMeans (8 clusters de dépenses)          |
| 4   | Deep learning        | Le MLP entraîné (2 couches 64/32)                       |
| 5   | NLP                  | Tokenisation, vectorisation, embeddings                 |
| 6   | Modèle pré-entraîné  | Donut (utilisé, pas entraîné)                           |
| 7   | Base vectorielle     | FAISS (recherche sémantique)                            |
| 8   | Prompt engineering   | Zero-shot marchand/date + RAG Q&A                       |
| 9   | Interface            | FastAPI + HTML/CSS/JS (et Streamlit en backup)          |
| 10  | Éthique              | Biais géographique, DISCLAIMER comptable, explicabilité |

---

## 11. LES ERREURS RENCONTRÉES (JOURNAL)

| #   | Erreur                                                    | Ce qu'on a appris                                                |
| --- | --------------------------------------------------------- | ---------------------------------------------------------------- |
| E1  | `'list' object has no attribute 'get'` sur `sub_total`    | Le schéma polymorphe de CORD frappe à plusieurs niveaux          |
| E2  | Les tests passent mais le code plante                     | Un test garantit ce qu'il vérifie, rien de plus                  |
| E3  | `ModuleNotFoundError: src.utils`                          | Un push non vérifié est un push qui n'a pas eu lieu              |
| E4  | Push refusé 403                                           | Token fine-grained sans permission Contents:write                |
| E5  | `isnan` sur MLPClassifier                                 | Les modèles mangent des nombres, pas du texte → LabelEncoder     |
| E8  | Le même bug polymorphe à la RACINE                        | Normaliser à la frontière, pas localement                        |
| E9  | `_append_to_csv` polluait le corpus CORD                  | La séparation données/utilisateur n'est pas cosmétique           |
| E10 | Bench sur des vignettes (0,04 Mpx)                        | Valider les propriétés du jeu de test avant de conclure          |
| E11 | Le compteur d'articles récompensait l'hallucination       | Une métrique doit mesurer la justesse, pas le volume             |
| E12 | Cache navigateur servait un vieux JS                      | Cache-Control: no-cache sur les fichiers statiques               |
| E13 | « Le détail de reçu manque » → il n'avait jamais été créé | Avant de chercher un bug complexe, vérifier que l'élément existe |

---

## 12. LES LIMITES À ASSUMER (PAS À CACHER)

1. **Domaine restreint** : Donut est entraîné sur l'Indonésie. Testé sur
   une facture française → montants corrects, en-tête confondu avec des
   articles. Testé sur des tickets ivoiriens → résultats dégradés.

2. **Champs censurés** : marchand et date absents de CORD. Récupérés par
   prompting, évalués informellement seulement.

3. **Baseline avantagée** : elle consomme les positions de la vérité
   terrain, pas un vrai OCR. L'écart 97,87 % vs 19,15 % sous-estime
   l'écart réel.

4. **Anomalies non labellisées** : CORD ne contient pas de « mauvais
   reçus » identifiés. Les 156 anomalies sont détectées par des règles,
   pas validées par un humain.

5. **Comptabilité indicative** : plan de comptes simplifié, non certifié.

6. **Clustering non supervisé** : les catégories KMeans ne sont validées
   par aucune vérité terrain.

7. **Vision fallback indisponible** : aucun modèle vision accessible avec
   la clé Groq gratuite au moment du test.

---

## 13. CE QUI RESTE À FAIRE

### Fait ✅

- [x] Pipeline complet : image → JSON → règles → comptabilité → RAG
- [x] Interface web (FastAPI + front)
- [x] 68 tests automatisés
- [x] Notebook exécuté avec sorties
- [x] Persistance des sessions
- [x] Cloisonnement utilisateur / corpus
- [x] UX explicative (indicateurs avec vrais chiffres)
- [x] Branche poussée sur GitHub

### À faire avant le 29

- [x] Merger feature/web-front → dev → main
- [x] README complet avec vrais chiffres
- [x] PowerPoint (5 slides)
- [ ] Vidéo 3-4 min
- [ ] Trello à jour (toutes les cartes en Terminé)
- [x] Test d'installation propre (pip install dans un venv neuf)
- [ ] Répétition orale (chronomètre en main)

### Pour plus tard (perspectives)

- Post-traitement intelligent (filtrer les en-têtes des articles)
- Fine-tuning Donut sur des factures françaises/ivoiriennes
- Boucle de feedback utilisateur → amélioration du modèle
- Authentification et comptes utilisateurs
- Conformité fiscale indonésienne (Coretax, NPWP)
