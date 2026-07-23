# Jour 4 — Livrables, présentation et soutenance

Tout ce qui reste après le code. Compte une journée pleine : ces livrables
pèsent autant que le pipeline dans la notation.

---

# PARTIE 1 — CHECKLIST DES LIVRABLES

D'après le brief du bootcamp, section V :

| # | Livrable | Statut | Où |
|---|---|---|---|
| 1 | Dépôt GitHub **avec branches** | ⬜ | main / dev / feature/* |
| 2 | README bien rédigé | ⬜ | racine du dépôt |
| 3 | Vidéo 3-4 min (fonctionnalités, code, résultats) | ⬜ | dépôt ou Drive public + lien README |
| 4 | PowerPoint (template fourni) | ⬜ | poussé sur le dépôt |
| 5 | Trello à jour | ⬜ | lien envoyé à l'instructeur |
| 6 | *Optionnel* — article Medium | ⬜ | recommandé, non obligatoire |

---

# PARTIE 2 — TEST DU TICKET IVOIRIEN (30 min)

La partie la plus originale du projet. À faire en premier, elle nourrit le
README, le PPT et la vidéo.

## Protocole

1. Photographier 1 ou 2 tickets de caisse ivoiriens (bonne lumière, ticket à
   plat, cadrage serré).
2. Les passer dans Donut :

```python
from PIL import Image
from src.extractor import extract
from src.receipt import Receipt
from src.rules import audit

img = Image.open("/content/ticket_abidjan.jpg").convert("RGB")
pred = extract(img, model, processor, device)
print(pred)

r = Receipt.from_gt_parse(pred)
print("Audit ID :", audit(r, country="ID"))
print("Audit CI :", audit(r, country="CI"))   # TVA 18 %
```

3. Comparer à l'œil ce que dit le ticket et ce que Donut a produit.

## Ce qu'on en tire

| Observation attendue | Ce que ça démontre |
|---|---|
| Articles mal lus ou inventés | Fossé de domaine : le modèle n'a jamais vu de français ni de FCFA |
| Montants mal normalisés | Convention d'écriture différente (espace ou point comme séparateur) |
| Règles qui fonctionnent quand même sur des montants corrects | Le moteur de règles est **généralisable**, l'extracteur non |

## Le paragraphe à écrire

> Le modèle Donut a été entraîné exclusivement sur des reçus indonésiens. Testé
> sur un ticket de caisse ivoirien, il produit une extraction dégradée : les
> noms d'articles en français sont mal reconnus et les montants en FCFA suivent
> une convention d'écriture absente de son apprentissage. Ce test illustre
> concrètement le biais géographique des jeux de données publics de Document AI,
> qui couvrent l'Asie et l'Amérique du Nord mais pas l'Afrique de l'Ouest. Un
> outil de notes de frais bâti sur ces données offrirait un service inégal selon
> l'origine géographique de l'utilisateur — une inégalité invisible dans les
> métriques agrégées, puisque le jeu de test partage le biais du jeu
> d'entraînement. Le moteur de règles métier, lui, reste transposable : il suffit
> de paramétrer le taux de taxe (11 % en Indonésie, 18 % en Côte d'Ivoire).

---

# PARTIE 3 — NETTOYAGE DES BRANCHES

Le barème vérifie l'usage des branches. Séquence à exécuter :

```bash
# 1. Fusionner le travail dans dev
git checkout dev
git merge feature/data-exploration
git merge feature/baseline-eval
git merge feature/rag-app
git push origin dev

# 2. Puis dev vers main quand tout est stable
git checkout main
git merge dev
git push origin main
```

**Mieux : passer par des Pull Requests** sur GitHub plutôt que des merges
directs. Une PR laisse une trace visible et datée du workflow — exactement ce
qu'un correcteur cherche. Ouvre-en une par branche, ajoute une ligne de
description, merge.

Vérification finale :

```bash
git log --oneline --graph --all --decorate
```

Le graphe doit montrer les branches qui divergent puis convergent.

---

# PARTIE 4 — LE README

Structure recommandée. À écrire dans le dépôt, en français ou en anglais
(rester cohérent avec le formulaire).

```markdown
# 🧾 Copilote de reçus et dépenses

De la photo d'un reçu à des dépenses structurées, vérifiées et interrogeables.

[Capture d'écran de l'interface]

## Le problème
Traiter des notes de frais à la main est lent et sujet aux erreurs. Ce projet
automatise la chaîne complète : lecture du reçu, structuration, contrôle
comptable, analyse et interrogation.

## Démo
📹 [Vidéo de démonstration (3 min)](lien)

## Fonctionnalités
- Extraction automatique image → JSON structuré (Donut pré-entraîné)
- Contrôle comptable automatique (3 règles métier, drapeaux d'anomalie)
- Catégorisation automatique des dépenses (KMeans sur embeddings)
- Recherche sémantique dans l'historique (FAISS)
- Extraction du marchand et de la date par prompting zero-shot
- Interface web Streamlit (3 onglets)

## Architecture
[Le schéma ASCII de la documentation technique]

## Jeu de données
CORD — ~1 000 reçus indonésiens annotés, licence CC BY 4.0.
Découpage 800 / 100 / 100.

⚠️ Particularités : marchand et date retirés de la version publique pour
raisons légales ; les montants suivent la convention `"25,000"` = 25 000.

[Le dictionnaire de données]

## Résultats
| Modèle | Exactitude (total.total_price) |
|---|---|
| Donut pré-entraîné | XX % |
| Baseline MLP (avantagée par les positions GT) | XX % |

Démonstration du sur-apprentissage :
| Configuration | Train | Validation |
|---|---|---|
| Sans régularisation | XX | XX |
| Avec régularisation + early stopping | XX | XX |

## Installation
[…]

## Structure du projet
[…]

## Notions mises en œuvre
[La liste des 10 notions avec où elles tombent]

## Limites et éthique
[Les 7 limites + la section biais géographique]

## Attribution
Dataset CORD © NAVER CLOVA AI Research, CC BY 4.0.
Park, S. et al. (2019). CORD: A Consolidated Receipt Dataset for Post-OCR
Parsing. Document Intelligence Workshop, NeurIPS.
```

**Conseils de rédaction.** Une capture d'écran en haut vaut trois paragraphes.
Les tableaux de résultats doivent contenir de vrais chiffres, pas des
approximations. La section limites est un atout, pas un aveu.

---

# PARTIE 5 — LE POWERPOINT

12 slides, une idée par slide. Utilise le template fourni par le bootcamp.

| # | Titre | Contenu | Note |
|---|---|---|---|
| 1 | Titre | Nom du projet, ton nom, date | — |
| 2 | Le problème | Traitement manuel des notes de frais : lent, erreurs, pas d'analyse | Une image de pile de reçus |
| 3 | La solution | Le schéma du pipeline en une image | **La slide la plus importante** |
| 4 | Le jeu de données | CORD : 1 000 reçus, 800/100/100, exemple image + JSON | Montre un vrai reçu |
| 5 | Dictionnaire de données | Le tableau des variables | Prouve que tu connais tes données |
| 6 | Les pièges rencontrés | Virgules = milliers · schéma polymorphe · champs censurés | Sincérité = crédibilité |
| 7 | Extraction | Donut : image → JSON, sans OCR. Capture d'un résultat | Explique le *pourquoi* du choix |
| 8 | Baseline et comparaison | Le tableau des exactitudes + pourquoi l'écart | Ton cœur technique |
| 9 | Sur-apprentissage | Les 4 chiffres train/val + la courbe de perte | Démontre que tu comprends le ML |
| 10 | Règles métier et anomalies | Les 3 règles, la logique à 3 états, le taux d'anomalies | Le côté « produit » |
| 11 | Recherche et questions | FAISS + RAG, une capture du Q&A | Case base vectorielle |
| 12 | Éthique et limites | Le test ivoirien + les limites assumées | **La slide qui te distingue** |

**À éviter.** Des slides de code brut (ça se voit dans la vidéo, pas au
projecteur). Des captures illisibles. Plus de 5 lignes de texte par slide.

---

# PARTIE 6 — LA VIDÉO (3-4 min)

Le brief exige de montrer **les fonctionnalités, le code ET les résultats**.

## Script minuté

| Temps | Séquence | Ce que tu montres | Ce que tu dis |
|---|---|---|---|
| 0:00–0:20 | Intro | Ton visage ou la slide titre | Le problème en deux phrases, ce que fait l'outil |
| 0:20–1:10 | **Démo live** | L'app Streamlit : upload d'un reçu → JSON → drapeaux | « Je dépose une photo… le modèle extrait… les règles vérifient » |
| 1:10–1:35 | Dashboard | L'onglet 2 : métriques, catégories, distribution | « Les catégories sont découvertes automatiquement par clustering » |
| 1:35–2:00 | Questions | L'onglet 3 : une recherche sémantique | « Recherche par le sens, pas par mot-clé » |
| 2:00–2:45 | **Le code** | `src/` dans l'éditeur : `receipt.py`, `rules.py`, un bout de `baseline.py` | « Le code est modulaire, les notebooks appellent src/ » |
| 2:45–3:20 | **Les résultats** | Le tableau Donut vs baseline, la courbe de perte, les chiffres du sur-apprentissage | Les chiffres, à voix haute |
| 3:20–3:45 | Limites | Le ticket ivoirien mal lu | « Biais géographique, démontré et assumé » |
| 3:45–4:00 | Clôture | Le dépôt GitHub | Merci |

## Conseils pratiques

- Enregistre avec Loom, OBS ou l'enregistreur d'écran de ton système.
- **Fais tourner l'app avant de lancer l'enregistrement** — un chargement de
  modèle de 40 s à l'écran, c'est 20 % de ta vidéo perdue.
- Répète une fois à blanc. Le premier essai dépasse toujours.
- Si la vidéo dépasse 25 Mo, mets-la sur Google Drive en accès public et colle
  le lien dans le README.

---

# PARTIE 7 — PRÉPARATION À LA SOUTENANCE

Les questions probables, et les réponses.

### « Pourquoi tu n'as pas entraîné Donut toi-même ? »

Le brief demande d'utiliser un modèle pré-entraîné, pas d'en fine-tuner un. Le
fine-tuning aurait coûté 6 à 8 heures de GPU pour un gain marginal sur du CORD
— le modèle publié est déjà entraîné sur exactement ce jeu de données. J'ai
investi ce temps dans le protocole d'évaluation, les règles métier et
l'interface, qui portent davantage de valeur. En revanche, j'ai entraîné un
modèle de bout en bout : la baseline, qui me sert de point de comparaison.

### « Pourquoi ta baseline est-elle si loin derrière ? »

Deux raisons, et la seconde est structurelle. D'abord elle est plus simple :
8 features contre un transformer multimodal. Mais surtout, elle **étiquette des
mots sans savoir les regrouper** : elle peut identifier « ceci est un prix »
sans savoir à quel article il se rattache. Donut génère la structure entière.
C'est précisément pourquoi les approches génératives ont remplacé la
classification de tokens en Document AI. Et à noter : ma baseline est
*avantagée*, elle utilise les positions de mots de la vérité terrain plutôt
qu'un OCR réel — l'écart réel serait plus grand.

### « Comment sais-tu que ton modèle est bon ? »

Je ne me fie pas à une impression. J'ai un split test de 100 reçus jamais
utilisés pour les décisions, une métrique d'exactitude par champ, un taux de
sortie exploitable, et un point de comparaison. Un score isolé ne veut rien
dire : c'est l'écart avec la baseline qui est informatif.

### « Explique le sur-apprentissage sur ton projet. »

Avec 2 000 exemples et aucune protection, mon MLP atteignait XX % sur le train
et seulement XX % en validation : il mémorisait au lieu de généraliser. En
ajoutant une régularisation L2 et un early stopping, et en utilisant toutes les
données, l'écart s'est resserré à XX / XX. La courbe de perte montre la
descente, et l'early stopping coupe quand la validation cesse de progresser.

### « Pourquoi trois états dans tes règles au lieu de vrai/faux ? »

Parce que « je ne peux pas juger » n'est pas « anomalie ». Beaucoup de reçus
CORD n'ont pas de champ taxe. Avec un booléen, ils seraient tous signalés comme
suspects — des faux positifs massifs qui rendraient l'outil inutilisable. Le
`None` distingue l'absence d'information de la détection d'un problème.

### « Ton système marcherait-il en Côte d'Ivoire ? »

L'extracteur non, et je l'ai testé plutôt que supposé : sur un ticket
ivoirien, Donut produit une extraction dégradée. Il n'a jamais vu de français
ni de FCFA. Le moteur de règles, lui, est transposable — j'ai paramétré le taux
de taxe, 11 % pour l'Indonésie, 18 % pour la Côte d'Ivoire. C'est une
illustration concrète du biais géographique des jeux de données publics.

### « Qu'est-ce que le RAG et pourquoi ici ? »

Retrieval-Augmented Generation : on cherche d'abord les documents pertinents,
puis on demande au modèle de langage de répondre **à partir de ces documents
seulement**. Sans ça, le LLM inventerait des chiffres. Ici, FAISS retrouve les
reçus sémantiquement proches de la question, et le LLM ne fait que synthétiser
ce qu'il lit.

### « Quelle est la plus grande faiblesse de ton projet ? »

L'absence de vérité terrain pour trois choses : les catégories découvertes par
clustering, les champs marchand/date extraits par prompting, et les anomalies.
Pour les anomalies, je génère des perturbations synthétiques pour mesurer
précision et rappel — mais des erreurs fabriquées ne ressemblent pas à des
erreurs réelles. Je le documente comme limite plutôt que de présenter un
chiffre trompeur.

### « Qu'est-ce que tu ferais avec deux semaines de plus ? »

Trois choses, par ordre de valeur. Un, constituer un petit jeu de reçus
ouest-africains annotés et fine-tuner Donut dessus, pour lever le biais
géographique. Deux, remplacer les positions de vérité terrain de ma baseline par
un OCR réel, pour mesurer la performance en conditions réelles. Trois, évaluer
l'extraction des lignes d'articles et pas seulement le total, avec un matching
qui ignore l'ordre.

---

# PARTIE 8 — CHECKLIST FINALE

Avant de rendre :

- [ ] Dépôt **public**, testé en navigation privée
- [ ] Branches visibles : main, dev, au moins deux feature/*
- [ ] README complet, avec capture d'écran et vrais chiffres
- [ ] `DOCUMENTATION_TECHNIQUE.md` poussé
- [ ] `requirements.txt` présent et à jour
- [ ] Les 4 notebooks poussés, exécutés, sorties visibles
- [ ] `pytest tests/ -q` passe
- [ ] Vidéo enregistrée, lien fonctionnel dans le README
- [ ] PowerPoint poussé sur le dépôt
- [ ] Trello à jour, toutes cartes en Terminé
- [ ] Aucun token ou clé API dans le code ou les notebooks
- [ ] Le tableau de résultats rempli avec de vrais chiffres
- [ ] Le test ivoirien documenté

**Piège classique de dernière minute.** Vérifie qu'aucune sortie de notebook ne
contient ta clé API Gemini ou ton token GitHub. Cherche `ghp_`, `github_pat_`
et `AIza` dans tes fichiers avant de pousser :

```bash
grep -rn "ghp_\|github_pat_\|AIza" . --include="*.ipynb" --include="*.py"
```

Si quelque chose remonte, nettoie la sortie de la cellule et révoque la clé.
