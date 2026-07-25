# Journal des erreurs — suite (E10+)

> Les erreurs **E1 à E5** sont consignées dans `notes_projet.md` (Partie 5).
> Le bug **E8** (schéma polymorphe à la racine) est décrit dans le commit
> `7ac46f2` et l'audit `docs/AUDIT_2026-07-24.md`. Ce fichier prolonge le
> journal à partir de E10.

---

## E10 — Bench invalide : vignettes au lieu de vraies photos (J-4)

**Symptôme.** Le premier `data/bench_results.csv` semblait mesurer l'effet du
prétraitement, mais ses images de test provenaient de **banques de vignettes**
(noms `...260nw-...`), de résolution réelle **0,04 à 0,15 Mpx**.

**Cause.** Donut attend ~1,23 Mpx ; une vraie photo de téléphone fait ~12 Mpx.
À 0,04–0,15 Mpx, il n'y a physiquement plus assez de pixels pour lire un ticket.
Le banc comparait donc des configurations sur des entrées hors de tout régime
d'utilisation réel.

**Conséquence.** **Toute conclusion sur le prétraitement tirée de ce premier
bench est nulle et non avenue.** Le CSV a été régénéré sur de vraies photos
(9 tickets ivoiriens 7,2 Mpx + tickets CORD 0,28–1,64 Mpx).

**Correctif.** Garde-fou de résolution dans `src/preprocess.py`
(`resolution_info`, seuil `MIN_PIXELS` ≈ 0,25 Mpx) appelé par `/api/extract`
**avant** toute extraction : une image trop petite est rejetée proprement
(HTTP non-500, message structuré `"Image trop basse résolution"`), jamais
hallucinée. Une vignette conservée (`00_vignette_sous_seuil_resolution.jpg`)
sert désormais de test positif.

**Leçon.** Un jeu de test doit ressembler au régime d'utilisation réel. Un
benchmark sur des entrées hors-domaine ne mesure pas la performance, il fabrique
un chiffre.

---

## E11 — Métrique trompeuse : compter les articles récompensait l'hallucination (J-4)

**Symptôme.** Le bench utilisait le **nombre d'articles extraits** comme proxy
de qualité. Sur l'image la plus basse résolution, la sortie contenait des
**idéogrammes chinois** et des prix qui étaient des mots
(`"MOSELANG"`, `creditcardprice: 1,363,500236鋯烴`, un total de `234 295 700 Rp`).

**Cause.** Donut est un modèle **génératif** : privé de pixels lisibles, il
produit du texte *plausible* plutôt que d'échouer. Un crop qui « extrait
7 articles » de flou n'a pas fait 7 erreurs de lecture — il a fait
**7 inventions**. Compter les articles récompense donc l'hallucination :
« 7 articles » paraissait meilleur que « 0 article honnête », alors que c'est
l'inverse.

**Correctif.** Deux garde-fous croisés :
1. **R9 — `check_magnitude`** dans `src/rules.py` : anomalie si
   `total > 50 × somme_lignes` ou `total < somme_lignes / 50`. Aurait attrapé
   le total de 234 295 700 Rp (largement > 50× la somme des lignes). Intégrée à
   `audit()` comme 4ᵉ drapeau `magnitude_ok`.
2. **Colonne `plausible`** dans `scripts/bench_extraction.py` : un résultat est
   marqué non plausible si beaucoup d'articles sur image basse résolution, ou
   `magnitude_ok` False, ou caractères hors jeu attendu (plages Unicode CJK).
   Le résumé du bench dit désormais explicitement, par image, si le résultat
   ressemble à une hallucination plutôt qu'à une vraie lecture.

**Leçon.** Une métrique doit pénaliser l'invention, pas seulement mesurer la
quantité. Sans contrôle de plausibilité, « plus de sorties » peut signifier
« plus d'hallucinations ». Un bench truqué est pire qu'une absence de bench.

---

## E12 — Front obsolète : StaticFiles sans Cache-Control (J-3)

**Symptôme.** Après une modification du front, le navigateur continuait de
servir un ancien `app.js`/`api.js` : l'onglet Questions (et d'autres) semblait
répondre « d'un ancien état ». Un hard-refresh (Ctrl+Shift+R) corrigeait le
symptôme — signature classique d'un cache navigateur.

**Cause.** `StaticFiles` de FastAPI ne pose **aucun en-tête `Cache-Control`**.
Le navigateur applique alors un cache heuristique et peut resservir une version
périmée des fichiers statiques sans revalider.

**Vérifié écarté (fausses pistes).** L'index FAISS des reçus utilisateur est
**reconstruit à chaque requête** (`api_search` : `build_index(embed(...))` sur
`session.search_texts()`) — testé en réel : un article au nom unique validé
apparaît immédiatement dans la recherche. Et le endpoint distingue bien
`scope:"user"` de `scope:"reference"`. Donc ni l'index ni le libellé n'étaient
en cause : c'était le cache.

**Correctif.** Le middleware pose `Cache-Control: no-cache` sur toute réponse
**hors `/api`** (front statique). « no-cache » n'interdit pas le cache : il
**oblige à revalider** via l'ETag (déjà émis par StaticFiles) → `304 Not
Modified` si inchangé (rapide), `200` + contenu neuf sinon (jamais périmé).
Vérifié : `curl -I /js/app.js` renvoie `cache-control: no-cache` + `etag`, et
`If-None-Match` renvoie `304`.

**Leçon.** Servir un front statique sans politique de cache explicite est un
piège récurrent : toute future modif du front réapparaîtra « obsolète » chez un
utilisateur qui a déjà chargé la page. Le `no-cache` + ETag est le réglage sûr
pour une app servie localement.
