# Notes du projet — Copilote de reçus et dépenses

Document de référence unique. Contient : le projet, le dictionnaire de données,
le lexique complet, les tableaux de comparaison, et le journal des erreurs
rencontrées (précieux pour le rapport et la soutenance).

Dépôt : github.com/herverenard147/copilot_verification
Dataset : CORD · Environnement : Google Colab

---

# PARTIE 1 — LE PROJET

## En une phrase

Une app où l'on dépose la photo d'un reçu, qui en extrait automatiquement les
articles et les montants, vérifie que les comptes tombent juste, range tout dans
une base de dépenses, et laisse poser des questions dessus en langage naturel.

## Le pipeline

```
Image de reçu
    │
    ├──► [A] Baseline maison : mot + position → étiquette   ← TU L'ENTRAÎNES
    │
    └──► [B] Donut pré-entraîné : image → JSON              ← TU NE L'ENTRAÎNES PAS
    │
    ▼
JSON validé → Règles métier → Base de dépenses (pandas) → Graphiques
    │
    ▼
Embeddings → FAISS → Question en langage naturel → Réponse
    │
    ▼
Streamlit
```

## Les 10 notions du bootcamp et où elles tombent

| Notion demandée | Où elle tombe |
|---|---|
| Python propre, fonctions, POO | `src/` modulaire + classe `Receipt` |
| Data wrangling + visualisation | DataFrames + nettoyage des montants + Seaborn |
| Stats / ML | KMeans (catégories) + classifieur baseline |
| Deep learning | Le MLP entraîné + Donut (transformer) |
| NLP | Tokenisation, vectorisation |
| Modèle pré-entraîné | Donut, utilisé tel quel |
| Base vectorielle | FAISS |
| Prompt engineering | Extraction zero-shot marchand + date |
| Interface | Streamlit |
| Éthique | Biais géographique du dataset (test ticket ivoirien) |

## Architecture des fichiers

```
copilot_verification/
├── README.md
├── notebooks/          ← l'atelier (Colab) : explorer, tester, montrer
│   ├── 01_exploration.ipynb
│   ├── 02_extraction.ipynb
│   ├── 03_baseline_eval.ipynb
│   └── 04_rag_demo.ipynb
├── src/                ← la bibliothèque : code propre, réutilisable
│   ├── utils.py           clean_amount, ensure_list
│   ├── data_loader.py     CORD → DataFrames
│   ├── receipt.py         la classe Receipt (POO)
│   ├── extractor.py       le pont vers Donut
│   ├── rules.py           les règles métier
│   ├── evaluate.py        les métriques
│   └── baseline.py        features + dataset de mots
├── tests/
│   └── test_rules.py
└── app.py              ← Streamlit (jour 3)
```

**Règle simple :** si un bout de code sert à deux endroits, il va dans `src/`.
Les notebooks APPELLENT le code de `src/`, ils ne le recopient pas.

## Planning 4 jours

| Jour | Objectif | État |
|---|---|---|
| J0 | Formulaire, repo, Trello | ✅ |
| J1 | Charger CORD, explorer, nettoyer, Donut sort un JSON | ✅ |
| J2 | Classe Receipt, règles testées, baseline entraînée, comparaison | en cours |
| J3 | FAISS + prompting zero-shot + KMeans + Streamlit | à venir |
| J4 | Vidéo, PPT, README, branches, test ticket ivoirien | à venir |

---

# PARTIE 2 — DICTIONNAIRE DE DONNÉES

## Données brutes (avant transformation)

| Élément | Nature | Description | Modalité |
|---|---|---|---|
| `image` | Non structurée (image) | Photo du reçu | ~1 000 JPEG, tailles variables |
| `ground_truth` | Semi-structurée (JSON) | Transcription humaine | `gt_parse` (résultat) + `valid_line` (mots + positions) |

## `df_items` — une ligne = un article acheté

| Variable | Nature | Description | Modalité |
|---|---|---|---|
| `receipt_id` | Identifiant | Numéro du reçu d'origine | 0 à 799 (train) |
| `item_name` | Qualitative nominale | Nom de l'article | Milliers de valeurs (indonésien) |
| `quantity` | Quantitative discrète | Quantité achetée | Entiers, surtout 1 à 5 |
| `unit_price` | Quantitative continue | Prix unitaire (Rp) | Numérique, manquants possibles |
| `line_price` | Quantitative continue | Prix total de la ligne | ≈ quantité × prix unitaire |

## `df_receipts` — une ligne = un reçu

| Variable | Nature | Description | Modalité |
|---|---|---|---|
| `receipt_id` | Identifiant | Numéro du reçu | 0 à 799 |
| `subtotal` | Quantitative continue | Sous-total avant taxe | Numérique, manquants possibles |
| `tax` | Quantitative continue | Taxe (PPN ~11 %) | Numérique, souvent absent |
| `total` | Quantitative continue | Montant total payé | Numérique |

## Variables construites pour la baseline (jour 2)

| Variable | Nature | Description | Modalité |
|---|---|---|---|
| `category` | Qualitative nominale | Étiquette d'un mot — **la variable à prédire** | ~30 modalités : `menu.nm`, `menu.price`, `total.total_price`… |
| `cx`, `cy` | Quantitative continue | Position du mot, normalisée | 0 à 1 |
| `len`, `digit_ratio`, … | Quantitative | Caractéristiques du mot | 0 à 1 |

## Remarques indispensables sur les données

> **Variables absentes.** Le nom du marchand et la date ont été retirés de la
> version publique de CORD pour raisons légales. Récupérés par prompting (J3).
>
> **Convention d'écriture.** `"25,000"` signifie 25 000. La virgule sépare les
> MILLIERS, pas les décimales. C'est le bug n°1 du dataset.
>
> **Schéma polymorphe.** Un élément seul est encodé comme un dict, plusieurs
> comme une liste. Vrai pour `menu`, `sub_total`, `total`, et pour certaines
> valeurs individuelles. D'où `ensure_list` et `merge_blocks`.
>
> **Valeurs manquantes.** Tous les reçus n'ont pas de taxe ou de sous-total.
> Traitées comme « information indisponible », distinct de « anomalie ».
>
> **Biais géographique.** Tous les reçus sont indonésiens. Le modèle ne
> généralise pas à un ticket ivoirien — à démontrer au J4.

---

# PARTIE 3 — LEXIQUE COMPLET

## 3.1 Les données

| Terme | C'est quoi, simplement | Dans notre projet |
|---|---|---|
| **CORD** | 1 000 photos de reçus indonésiens + leur transcription humaine | Matière première ET correcteur |
| **Dataset** | Collection d'exemples (manuel d'exercices avec corrigés) | CORD |
| **Split** | Découpage du dataset en paquets séparés | 800 train / 100 validation / 100 test |
| **Ground truth** | La « bonne réponse » écrite par un humain | Le JSON `gt_parse` |
| **`valid_line`** | La partie de CORD qui donne chaque MOT avec sa position et son étiquette | La mine d'or pour entraîner la baseline |
| **`quad`** | Le quadrilatère (4 coins en pixels) qui entoure un mot | Sert à calculer la position du mot |
| **JSON** | Format texte pour données organisées : `{"clé": "valeur"}` | Langue de la ground truth et de Donut |
| **DataFrame** | Un tableau en Python (comme Excel) | Nos reçus mis à plat |
| **pandas** | La librairie des tableaux | Fournit le DataFrame |
| **Data wrangling** | Nettoyer et transformer des données brutes | Virgules, listes/dicts, manquants |
| **Feature engineering** | Fabriquer des colonnes utiles à partir du brut | `clean_amount`, position des mots |
| **Feature (caractéristique)** | Une information chiffrée décrivant un exemple | Les 8 nombres qui décrivent un mot |
| **Valeur manquante (NaN)** | Une case vide | Info, pas bug |
| **Variable qualitative** | Décrit une catégorie ; pas de moyenne possible | `item_name`, `category` |
| **Variable quantitative** | Un nombre mesurable ; les calculs ont un sens | `total`, `quantity` |
| **Modalité** | L'ensemble des valeurs possibles d'une variable | ~30 modalités pour `category` |
| **Schéma polymorphe** | La même donnée change de forme selon les cas | `menu` : dict ou liste |

## 3.2 Le modèle qui lit (Donut)

| Terme | C'est quoi, simplement | Dans notre projet |
|---|---|---|
| **Modèle** | Programme qui a « appris » à partir d'exemples | Donut lit des reçus |
| **Modèle pré-entraîné** | Déjà entraîné par d'autres, on le télécharge | `donut-base-finetuned-cord-v2` |
| **Donut** | Regarde l'image, écrit le JSON directement | Notre extracteur principal |
| **Transformer** | La famille d'architecture moderne (GPT, BERT, Donut) | Le « type de cerveau » de Donut |
| **OCR** | Reconnaissance optique de caractères | Donut n'en a pas besoin |
| **Inférence** | UTILISER un modèle entraîné pour prédire | Tout ce qu'on fait avec Donut |
| **Entraînement** | Le moment où un modèle APPREND | Seulement sur notre baseline |
| **Fine-tuning** | Ré-entraîner un pré-entraîné sur ses données | On n'en fait PAS |
| **Token** | Un morceau de texte (mot, bout de mot) | Donut écrit token par token |
| **Tokeniser** | Découper du texte en tokens | Fait par `sentencepiece` |
| **Processor** | L'interprète : image → format modèle, tokens → JSON | `processor()` et `token2json` |
| **Hugging Face** | La plateforme des datasets et modèles | Source de CORD et Donut |
| **GPU / CPU** | Processeur spécialiste du calcul massif / généraliste | GPU : 5 s au lieu de 60 s par reçu |
| **Prompt de tâche** | Le signal de départ donné au modèle | `<s_cord-v2>` |

## 3.3 Le modèle qu'on entraîne (baseline)

| Terme | C'est quoi, simplement | Dans notre projet |
|---|---|---|
| **Baseline** | Modèle simple servant de point de comparaison | Notre MLP maison |
| **Classification** | Prédire une catégorie parmi plusieurs | « Ce mot est-il un prix ? un nom ? » |
| **Apprentissage supervisé** | Apprendre sur des exemples ÉTIQUETÉS | Baseline sur les annotations CORD |
| **Label (étiquette)** | La bonne réponse attachée à un exemple | `menu.nm`, `total.total_price` |
| **LabelEncoder** | Traduit des étiquettes texte en nombres | Obligatoire : les modèles ne mangent que des nombres |
| **Encodage des labels** | L'opération ci-dessus (`"menu.nm"` → `0`) | Cause du bug de la cellule 13 |
| **`inverse_transform`** | La traduction retour, nombre → étiquette | Pour relire les prédictions |
| **MLP** | Multi-Layer Perceptron : le réseau de neurones le plus simple | Notre baseline : 2 couches (64, 32) |
| **Couche cachée** | Un étage de calcul entre l'entrée et la sortie | `hidden_layer_sizes=(64, 32)` |
| **scikit-learn** | La librairie ML classique de Python | Fournit MLPClassifier, KMeans, LabelEncoder |
| **Fonction de perte (loss)** | Le score d'erreur que le modèle réduit | Entropie croisée |
| **Entropie croisée** | La loss standard en classification | Punit fort les erreurs confiantes |
| **Itération / époque** | Un passage d'apprentissage sur les données | `max_iter=500` |
| **`loss_curve_`** | L'historique de la perte au fil des itérations | Le graphique qui descend = ça apprend |
| **Sur-apprentissage (overfitting)** | Mémoriser au lieu de comprendre : excellent sur le train, mauvais sur du neuf | Démontré cellule 12, corrigé cellule 13 |
| **Régularisation** | Les techniques anti-sur-apprentissage | `alpha`, early stopping |
| **`alpha` (L2)** | Pénalise les poids extrêmes du réseau | `alpha=1e-3` |
| **Early stopping** | Arrêter quand la validation stagne | `early_stopping=True` |
| **Dropout** | Éteindre des neurones au hasard pendant l'entraînement | Concept voisin de `alpha` |
| **Vectorisation** | Transformer du texte en nombres | Nos 8 features par mot |
| **`random_state`** | Fige le hasard pour des résultats reproductibles | `=42` partout |

## 3.4 Mesurer

| Terme | C'est quoi, simplement | Dans notre projet |
|---|---|---|
| **Métrique** | Un chiffre qui mesure la qualité | Nos juges impartiaux |
| **Exactitude (accuracy)** | % de réponses correctes | Par champ : le total est-il bon ? |
| **Taux de JSON valide** | % de sorties exploitables | Un modèle qui sort du charabia est inutilisable |
| **Précision** | Quand j'alerte, ai-je raison ? | Pour les anomalies |
| **Rappel** | Est-ce que je rate des cas ? | Pour les anomalies |
| **Règles métier** | Vérifications logiques issues du domaine | Somme lignes = sous-total ? |
| **Anomalie** | Un reçu qui viole une règle | Signalé par un drapeau |
| **Tolérance** | La marge acceptée avant de crier à l'erreur | 2 %, pour absorber les arrondis |
| **Logique à trois états** | Vrai / Faux / « je ne sais pas » (`None`) | Ne pas confondre « pas d'info » et « anomalie » |

## 3.5 Chercher et questionner (jour 3)

| Terme | C'est quoi, simplement | Dans notre projet |
|---|---|---|
| **Embedding** | Texte → vecteur de nombres ; sens proches = vecteurs proches | Chaque reçu devient un point |
| **Base vectorielle** | Base de données qui retrouve les vecteurs les plus proches | Où l'on range les embeddings |
| **FAISS** | Librairie de recherche vectorielle rapide (Meta) | Notre base vectorielle |
| **RAG** | Chercher les documents pertinents PUIS demander au LLM de répondre | « Combien en boissons ? » |
| **LLM** | Grand modèle de langage (GPT, Claude, Gemini) | Pour le Q&A et le zero-shot |
| **API** | Appeler un service distant depuis son code | Comment on parle au LLM |
| **Prompt engineering** | L'art de formuler la demande au LLM | Prompts marchand/date et Q&A |
| **Zero-shot** | Demander une tâche SANS donner d'exemple | Extraire le marchand |
| **Few-shot** | Idem AVEC quelques exemples dans le prompt | Solution de secours |
| **Clustering** | Regrouper ce qui se ressemble, SANS étiquettes | Catégories de dépenses |
| **KMeans** | L'algorithme de clustering classique | Notre outil catégories |
| **Apprentissage non supervisé** | Apprendre SANS bonnes réponses | Le KMeans |
| **Streamlit** | Faire une app web en pur Python | Notre interface |

## 3.6 Les outils de travail

| Terme | C'est quoi, simplement | Dans notre projet |
|---|---|---|
| **Colab** | Notebook Python dans le navigateur, GPU gratuit | Notre atelier |
| **Notebook** | Document mêlant code, résultats et texte | Nos `.ipynb` |
| **Librairie** | Code écrit par d'autres, réutilisable | pandas, transformers… |
| **pip** | L'installateur de librairies | `pip install` |
| **`%%writefile`** | Magie Colab : écrit la cellule DANS un fichier | Comment on remplit `src/` |
| **`importlib.reload`** | Recharge un module modifié sans redémarrer | Après chaque `%%writefile` |
| **`sys.path.append`** | Dit à Python où chercher nos modules | Le pont notebook ↔ `src/` |
| **Git** | Système de sauvegarde versionnée | La mémoire du projet |
| **GitHub** | Le site qui héberge les repos | Où vit `copilot_verification` |
| **Repo** | Dossier de projet suivi par Git | `copilot_verification` |
| **Clone** | Télécharger une copie complète | Début de chaque session Colab |
| **Commit** | Enregistrer un instantané EN LOCAL | Sauvegarde nommée |
| **Push** | Envoyer les commits VERS GitHub | La sauvegarde qui survit à Colab |
| **Branche** | Ligne de travail parallèle | `main` / `dev` / `feature/...` |
| **Merge** | Fusionner une branche dans une autre | feature → dev → main |
| **Pull Request (PR)** | Demande de fusion, visible et traçable | Laisse une trace pour le barème |
| **Token GitHub** | Mot de passe temporaire pour Colab | `ghp_...` — RIEN à voir avec les tokens de modèle |
| **Erreur 401 / 403** | 401 = « je ne sais pas qui tu es » ; 403 = « je sais, mais tu n'as pas le droit » | Diagnostic d'un push refusé |
| **`assert`** | « Je jure que ceci est vrai », plante sinon | Nos mini-examens |
| **pytest** | L'outil qui lance tous les tests d'un coup | `pytest tests/ -q` |
| **`try/except`** | « Ça peut échouer, voilà quoi faire alors » | Autour de Donut et des API |
| **Traceback** | Le message d'erreur Python (se lit de bas en haut) | Notre outil de diagnostic |
| **Docstring** | Le texte entre `"""` qui documente | Dans tous nos fichiers |
| **POO** | Regrouper données + comportements dans des classes | La classe `Receipt` |
| **Classe / objet** | La classe est le moule, l'objet ce qui en sort | `Receipt` / chaque reçu |
| **`@classmethod`** | Une méthode qui fabrique un objet autrement | `Receipt.from_gt_parse(...)` |
| **`__init__`** | Le constructeur : ce qui se passe à la création | Range les données dans l'objet |
| **`__repr__`** | Comment l'objet s'affiche quand on le `print` | `Receipt(id=0, 5 articles…)` |

---

# PARTIE 4 — TABLEAUX DE COMPARAISON

## A. Les trois façons d'extraire un reçu

| | OCR + règles (regex) | Baseline entraînée | Donut pré-entraîné |
|---|---|---|---|
| Comment | Lire le texte, puis « si ça ressemble à un prix… » | Étiquette chaque mot d'après texte + position | Regarde l'image, écrit le JSON |
| Qui l'entraîne | Personne | **NOUS** (secondes, CPU) | Ses auteurs |
| Qualité | Faible | Moyenne | Élevée |
| Sait structurer ? | Non | **Non** (étiquette sans regrouper) | **Oui** |
| Apporte au barème | — | Supervisé, loss, overfitting, régularisation | Modèle pré-entraîné, deep learning |
| **Notre choix** | Non retenu | ✅ Baseline (J2) | ✅ Extracteur principal (J1) |

> Le cœur technique = comparer les colonnes 2 et 3 avec la même métrique.
> Et surtout EXPLIQUER l'écart : la baseline étiquette des mots mais ne sait pas
> regrouper les articles en lignes. C'est structurel — et c'est précisément
> POURQUOI des modèles génératifs comme Donut existent.

## B. Utiliser vs adapter vs entraîner

| | Inférence pré-entraînée | Fine-tuning | Entraînement de zéro |
|---|---|---|---|
| C'est quoi | Utiliser tel quel | Ré-entraîner sur SES données | Tout apprendre depuis rien |
| Coût | Minutes | Heures, GPU sérieux | Jours/semaines |
| **Nous** | ✅ Donut | ❌ hors périmètre | ❌ jamais |

## C. Zero-shot vs few-shot vs supervisé

| | Zero-shot | Few-shot | Supervisé |
|---|---|---|---|
| Exemples fournis | Aucun | Quelques-uns dans le prompt | Des centaines, en entraînement |
| Outil | LLM via prompt | LLM via prompt | Modèle qu'on entraîne |
| **Nous** | ✅ Marchand + date | Secours | ✅ Baseline |

## D. Supervisé vs non supervisé

| | Supervisé | Non supervisé |
|---|---|---|
| Bonnes réponses fournies ? | Oui (labels) | Non |
| Question type | « Ce mot est-il un prix ? » | « Quels articles se ressemblent ? » |
| **Nous** | ✅ Baseline | ✅ KMeans |

## E. Train vs validation vs test

| | Train (800) | Validation (100) | Test (100) |
|---|---|---|---|
| Rôle | Apprendre | Se régler | L'examen final |
| Regardé | Tout le temps | Souvent | UNE fois, à la fin |
| Si on triche | — | Léger sur-ajustement | Résultats mensongers |

## F. JSON vs DataFrame

| | JSON | DataFrame |
|---|---|---|
| Forme | Hiérarchique (imbriqué) | Plat (lignes × colonnes) |
| Bon pour | Machines, modèles, API | Analyse humaine, stats, graphiques |
| **Nous** | Entrée/sortie des modèles | Analyse — d'où `data_loader.py` |

## G. Matplotlib vs Seaborn

| | Matplotlib | Seaborn |
|---|---|---|
| Niveau | Bas niveau, tout contrôler | Construit dessus, joli par défaut |
| **Nous** | La toile (figures, axes) | Les graphiques — les deux ensemble |

## H. FAISS vs ChromaDB

| | FAISS | ChromaDB |
|---|---|---|
| Nature | Librairie de calcul pur, très rapide | Base clé en main (stockage, filtres) |
| **Nous** | ✅ (cité dans le brief) | Équivalent à notre échelle |

## I. Streamlit vs Gradio

| | Streamlit | Gradio |
|---|---|---|
| Style | Petite app web complète | Démo rapide autour d'une fonction |
| **Nous** | ✅ (app « dépenses + chat ») | Accepté aussi par le brief |

## J. Précision vs rappel

| | Précision | Rappel |
|---|---|---|
| Question | Quand j'alerte, ai-je raison ? | Est-ce que je rate des cas ? |
| Erreur mesurée | Fausses alertes | Cas manqués |
| Tension | Alerter moins → précision ↑, rappel ↓ | Alerter plus → l'inverse |

## K. Les deux « tokens » (piège de vocabulaire)

| | Token (modèle) | Token (GitHub) |
|---|---|---|
| C'est quoi | Un morceau de texte lu/écrit par le modèle | Un mot de passe `ghp_...` |
| Monde | Intelligence artificielle | Sécurité |
| Lien entre les deux | Aucun — pur hasard de vocabulaire | |

## L. clone vs pull vs commit vs push

| | clone | pull | commit | push |
|---|---|---|---|---|
| Fait quoi | Copie TOUT (1re fois) | Récupère les nouveautés | Sauvegarde EN LOCAL | Envoie vers GitHub |
| Analogie | Acheter le classeur | Ajouter les pages neuves | Écrire une page datée | Photocopier au coffre |

## M. assert vs try/except

| | assert | try/except |
|---|---|---|
| Philosophie | « Ça DOIT être vrai, sinon on arrête » | « Ça peut échouer, voilà le plan B » |
| Usage | Tests, développement | Face à l'imprévu légitime |
| **Nous** | Cellule 7, `tests/` | Autour de Donut et des API |

## N. Token classic vs fine-grained (GitHub)

| | Classic (`ghp_...`) | Fine-grained (`github_pat_...`) |
|---|---|---|
| Permissions | Une case `repo` = tout | À régler repo par repo, permission par permission |
| Piège | — | Sans « Contents: Read and write » → **403** |
| **Recommandé ici** | ✅ plus simple | ⚠️ si mal configuré, refus d'écriture |

## O. Étiquettes texte vs encodées

| | Étiquettes texte | Étiquettes encodées |
|---|---|---|
| Exemple | `"menu.nm"` | `0` |
| Lisible par l'humain | ✅ | ❌ |
| Utilisable par le modèle | ⚠️ parfois seulement | ✅ toujours |
| Outil | — | `LabelEncoder` (+ `inverse_transform` pour relire) |

---

# PARTIE 5 — JOURNAL DES ERREURS RENCONTRÉES

À reprendre dans la section « difficultés » du rapport et de la soutenance.
C'est ce qui prouve qu'on a travaillé AVEC les données, pas juste survolé.

## E1 — `'list' object has no attribute 'get'` (jour 1)

**Cause.** Le schéma de CORD est polymorphe : `sub_total` est parfois un dict,
parfois une LISTE de blocs (ex. sous-total avant et après remise). Le code
supposait un dict.

**Correctif.** Fonction `merge_blocks` qui fusionne une liste de blocs en un
seul dict. Le piège existe à plusieurs niveaux de profondeur — d'où aussi la
fonction `first()` pour les valeurs individuelles.

**Leçon.** Une bizarrerie de dataset frappe rarement à un seul endroit. Il faut
une normalisation SYSTÉMATIQUE, pas ponctuelle.

## E2 — Les tests passent mais le code plante quand même (jour 1)

**Constat.** La cellule 7 (`assert`) était verte, et la cellule 9 a planté.

**Explication.** Les fonctions testées (`clean_amount`, `ensure_list`) faisaient
parfaitement leur travail. Le bug venait d'un cas de figure des données que
personne n'avait prévu.

**Leçon fondamentale.** Un test garantit ce qu'il vérifie, RIEN DE PLUS. Les
tests attrapent les erreurs prévues ; l'exploration des vraies données révèle
les erreurs imprévues. Les deux sont nécessaires.

## E3 — `ModuleNotFoundError: No module named 'src.utils'` (jour 2)

**Cause.** Les fichiers du jour 1 n'étaient pas dans le dépôt : le push avait
échoué sans qu'on le remarque, et Colab efface tout entre les sessions.

**Leçon.** Un push non vérifié est un push qui n'a pas eu lieu. Réflexe à
prendre : après chaque push, `git status` doit dire « up to date with origin ».

## E4 — Push refusé, erreur 403 (jour 2)

**Cause.** Token fine-grained (`github_pat_...`) sans la permission
« Contents: Read and write ». Le 403 signifie « authentifié mais pas autorisé »,
à distinguer du 401 (« pas authentifié »).

**Correctif.** Token classic avec la portée `repo`, ou ajout de la permission
Contents sur le fine-grained.

**Bonus sécurité.** `getpass` cache le token à la saisie, mais `git remote -v`
le RÉAFFICHE en clair. Filtrer : `!git remote -v | sed 's|:[^@]*@|:***@|'`.

## E5 — `ufunc 'isnan' not supported` sur `MLPClassifier` (jour 2)

**Cause.** Avec `early_stopping=True`, scikit-learn évalue le modèle à chaque
itération et teste `isnan` sur les prédictions. Nos étiquettes étaient des
CHAÎNES (`"menu.nm"`), et `isnan` n'a pas de sens sur du texte.

**Correctif.** `LabelEncoder` : encoder les étiquettes en entiers avant
l'entraînement, et `inverse_transform` pour relire les prédictions.

**Leçon.** Un modèle ne manipule que des nombres. L'encodage des labels n'est
pas une astuce de contournement, c'est une étape standard du pipeline ML.

---

# PARTIE 6 — RÉSULTATS À CONSIGNER

À remplir au fur et à mesure ; ce sont les chiffres du rapport et du PPT.

| Mesure | Valeur | Où |
|---|---|---|
| Nombre de reçus (train / val / test) | 800 / 100 / 100 | J1 |
| Nombre d'articles extraits (train) | … | J1 |
| Reçus signalés en anomalie par les règles | … / 800 | J2 |
| Exactitude naïve — TRAIN | … | J2 cellule 12 |
| Exactitude naïve — VALIDATION | … | J2 cellule 12 |
| Exactitude régularisée — TRAIN | … | J2 cellule 13 |
| Exactitude régularisée — VALIDATION | … | J2 cellule 13 |
| Exactitude `total.total_price` — Donut | … | J2 cellule 18 |
| Exactitude `total.total_price` — Baseline | … | J2 cellule 18 |
| Taux de sortie exploitable (Donut) | … | J2 cellule 18 |
| Résultat sur ticket ivoirien | … | J4 |

**L'écart naïf vs régularisé** est la démonstration du sur-apprentissage et de sa
parade : c'est le tableau le plus important de la soutenance.

---

# PARTIE 7 — HONNÊTETÉS À ÉCRIRE DANS LE RAPPORT

Ces limites, assumées, valent plus de points que des résultats gonflés.

1. **La baseline est avantagée** : elle utilise les positions de mots de la
   ground truth, pas un vrai OCR. Elle perd quand même face à Donut ; l'écart
   réel serait plus grand.

2. **La comparaison ne porte que sur un champ** (le total). La baseline étiquette
   des mots mais ne sait pas regrouper les articles en lignes — limite
   structurelle, pas défaut d'entraînement.

3. **Aucune anomalie réelle n'est labellisée** dans CORD. Les règles sont
   évaluées sur des perturbations synthétiques, qui ne reflètent pas la
   distribution des vraies erreurs.

4. **Biais géographique** : reçus indonésiens uniquement. Généralisation non
   testée ailleurs — sauf notre test sur ticket ivoirien, qui le démontre.

5. **Champs censurés** : marchand et date absents des labels publics pour raisons
   légales. Récupérés par prompting, évalués informellement seulement.
