# Glossaire

Ce bloc-notes sert à recueillir tout ce dont nous avons besoin pour la conception de notre plateforme.

**CORD** — Consolidated Receipt Dataset, un jeu de données créé par Clova AI (Naver) pour le "post-OCR parsing" de reçus/tickets de caisse. Chaque image est accompagnée par sa transcription faite par un humain.

**OCR** (Optical Character Recognition / Reconnaissance Optique de Caractères) — Permet de transformer une image (photo d'un texte, scan) en un fichier texte. Tu lui donnes cette image et il en fait sortir le texte qu'elle contient, sans comprendre pour autant ce qui est écrit.

**Parsing** — L'action d'analyser un texte pour en extraire une structure logique. Ici : prendre le texte brut sorti par l'OCR et le découper en champs identifiés (nom du magasin, produit, prix, total...).

**Post-OCR Parsing** — Vient après l'OCR, pour comprendre le texte en question.

**Dataset** — Un ensemble de données utilisées pour entraîner ou évaluer un modèle de machine learning.

**Box-level annotation** (annotation au niveau des boîtes) — Le fait de dessiner une boîte sur chaque zone de texte détectée sur l'image, pour lui attribuer le texte contenu dedans.

**Labels sémantiques** (semantic labels) — En plus de donner le texte dans la boîte, on lui attribue une signification, en vue de lui donner un contexte.

**Superclasses / sous-classes** — Une hiérarchie de catégories. CORD a 8 catégories larges (superclasses) — ex : informations magasin, menu, sous-total, total, paiement — et chacune se divise en catégories plus fines (54 sous-classes) — ex : dans "menu", tu as "nom du produit", "quantité", "prix unitaire" séparément.

**Benchmark** — Un jeu de données standard utilisé par toute la communauté en vue de tester tous les modèles sur les mêmes critères.

**Document Understanding / Key Information Extraction (KIE)** — Le domaine de recherche qui vise à faire comprendre à un modèle la structure et le sens d'un document. En gros, pas juste lire, mais aussi extraire uniquement les parties clés qui nous intéressent dans un document.

**Modèles multimodaux** — Un modèle multimodal est un modèle qui prend en compte plusieurs types/canaux de données. En comparaison, un modèle unimodal se concentre sur un point bien précis :

- Un modèle NLP classique (comme un DistilBERT sur tweet_eval) est unimodal : il ne voit que du texte. Il ignore complètement la mise en page, les couleurs, les images.
- Un modèle de vision classique (classification d'images) est unimodal aussi : il ne voit que des pixels, aucun texte.

Un multimodal, lui, prend plusieurs canaux :

- Le texte — ce que l'OCR a extrait de chaque boîte ("Coca-Cola", "12.50")
- La position spatiale — les coordonnées (x, y) de chaque boîte sur l'image (est-ce en haut, en bas, à gauche, aligné avec quoi)
- L'image elle-même — parfois même les pixels bruts autour du texte (police, couleur, encadrés, logos)

**Token** — Le fait de découper des mots, des bouts de mots, des symboles en petits morceaux.

**Split** — Le fait de diviser le dataset en 3 (entraînement 80% / validation 10% / test 10%).

**Inférence** — Le fait d'utiliser un modèle déjà entraîné en vue d'obtenir une prédiction.
