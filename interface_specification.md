# Spécification — Interface et module comptable (v2)

Copilote de reçus et dépenses · présentation le 29 juillet 2026

**Nouveautés v2** : module de gestion comptable, fonctionnalités priorité 3
intégrées, planning révisé sur 6 jours.

---

# PARTIE 1 — LE MODULE COMPTABLE

## 1.1 Ce que ça change

Sans comptabilité, le copilote répond à « les montants sont-ils cohérents ? ».
Avec, il répond à « que dois-je faire de ce reçu ? ». Il passe d'outil de
vérification à outil de gestion.

```
AVANT                          APRÈS
Image → JSON → règles          Image → JSON → règles
                                     → écriture comptable
                                     → TVA récupérable
                                     → note de frais
                                     → export logiciel comptable
```

## 1.2 Les trois apports

**Une règle métier mathématiquement rigoureuse.** Dans toute écriture
comptable, la somme des débits égale la somme des crédits. C'est vérifiable
exactement, pas à une tolérance près. Ta règle R4 est la plus solide des
quatre.

**Une conséquence réelle de la limite du dataset.** En fiscalité, la TVA n'est
récupérable que si la facture identifie le fournisseur. CORD n'a pas de champ
marchand. Donc : *« TVA non récupérable — fournisseur non identifié »*. La
contrainte technique devient un cas métier légitime, pas un trou.

**Un ancrage local.** Le plan de comptes SYSCOHADA (référentiel OHADA, en
vigueur en Côte d'Ivoire) renforce la pertinence régionale du projet et
prolonge le test du ticket ivoirien.

## 1.3 Avertissement à faire figurer

> ⚠️ L'affectation des comptes proposée par cet outil est **indicative**. Elle
> est fondée sur une lecture simplifiée du plan comptable SYSCOHADA et doit
> être validée par un professionnel de la comptabilité avant tout usage réel.
> Cet outil est une aide à la saisie, pas un logiciel comptable certifié, et ne
> constitue ni un conseil comptable ni un conseil fiscal.

À mettre dans le README, dans le module, et à dire en soutenance. C'est de
l'honnêteté élémentaire, et ça se remarque positivement.

## 1.4 Plan de comptes retenu (SYSCOHADA simplifié)

| Compte | Libellé | Usage |
|---|---|---|
| 601 | Achats de marchandises | Achats destinés à la revente |
| 605 | Autres achats (eau, électricité, fournitures) | Consommables |
| 6181 | Frais de transport | Déplacements |
| 627 | Publicité, publications, relations publiques | Réception, restauration |
| 628 | Frais de télécommunications | Téléphone, internet |
| 638 | Autres charges externes | **Compte par défaut** |
| 4452 | État — TVA récupérable sur achats | TVA déductible |
| 401 | Fournisseurs | Achat à crédit |
| 571 | Caisse | Paiement espèces |
| 521 | Banque | Paiement carte/virement |

## 1.5 Anatomie d'une écriture

Reçu : restauration, 50 000 HT, TVA 18 % = 9 000, total 59 000, payé en espèces.

| Compte | Libellé | Débit | Crédit |
|---|---|---:|---:|
| 627 | Frais de réception | 50 000 | |
| 4452 | TVA récupérable | 9 000 | |
| 571 | Caisse | | 59 000 |
| | **Total** | **59 000** | **59 000** |

✅ Équilibrée. Si le fournisseur n'est pas identifié, la ligne 4452 disparaît et
les 9 000 sont réintégrés en charge (compte 627 = 59 000) — c'est la règle
fiscale, et c'est exactement le cas de la majorité des reçus CORD.

## 1.6 Interface du module `src/accounting.py`

| Fonction | Rôle |
|---|---|
| `CHART_OF_ACCOUNTS` | Le plan de comptes ci-dessus |
| `map_category_to_account(category)` | Catégorie KMeans → compte 6xx, défaut 638 |
| `journal_entry(receipt, category, payment_mode, country)` | Produit les lignes débit/crédit |
| `is_balanced(entry, tolerance=0.01)` | **R4** — débits == crédits |
| `vat_recoverable(receipt, merchant)` | `(montant, raison)`. Sans fournisseur : `(0, "Fournisseur non identifié")` |
| `vat_summary(entries)` | Récupérable vs non récupérable, avec les motifs |
| `expense_report(df_receipts, period)` | Note de frais agrégée : HT / TVA / TTC |
| `export_journal_csv(entries, path)` | Export importable en logiciel comptable |

## 1.7 Les règles métier, version complète

| # | Règle | Nature | Testable ? |
|---|---|---|---|
| R1 | Somme des lignes ≈ sous-total | Arithmétique, tolérance 2 % | ✅ |
| R2 | Sous-total + taxe ≈ total | Arithmétique, tolérance 2 % | ✅ |
| R3 | Taux de taxe plausible (ID 11 % / CI 18 %) | Domaine, bande ±5 pts | ✅ |
| **R4** | **Débits = crédits** | **Comptable, exact** | ✅ |
| **R5** | **TVA récupérable seulement si fournisseur identifié** | **Fiscale** | ✅ |
| R6 | Doublon (hash articles + total) | Contrôle interne | ✅ |
| R7 | Plafond de dépense dépassé | Politique, configurable | ✅ |
| R8 | Champ obligatoire manquant | Complétude | ✅ |

Toutes gardent la **logique à trois états** : `True` conforme, `False` anomalie,
`None` non vérifiable.

---

# PARTIE 2 — LES FONCTIONNALITÉS DE L'INTERFACE

## 2.1 Priorité 1 — le pipeline visible

| # | Fonctionnalité | Pourquoi |
|---|---|---|
| 1 | Dépôt d'image (glisser-déposer + aperçu) | Point d'entrée |
| 2 | Extraction en tableau lisible, JSON brut en volet repliable | Un tableau convainc un utilisateur, un JSON convainc un développeur — les deux |
| 3 | Vue côte à côte image ↔ données | Vérification visuelle immédiate ; la séquence clé de la vidéo |
| 4 | Badges des règles ✅ ❌ ➖ | Le ➖ matérialise la logique à 3 états, visuellement neutre |
| 5 | KPI du tableau de bord | Vue d'ensemble |
| 6 | Graphique dépenses par catégorie | Montre le KMeans |
| 7 | Recherche sémantique | Montre FAISS |

## 2.2 Priorité 2 — ce qui distingue

| # | Fonctionnalité | Pourquoi |
|---|---|---|
| 8 | **Correction manuelle des champs** (`st.data_editor`) | ⭐ Le système assiste, il ne tranche pas. Les règles se recalculent en direct. |
| 9 | Liste des anomalies avec la règle et les montants en conflit | Explicabilité concrète |
| 10 | Historique filtrable | Fait une vraie base de dépenses |
| 11 | Sélecteur de pays (ID 11 % / CI 18 %) | Matérialise la généralisation des règles |
| 12 | Questions en langage naturel (RAG) | Prompting + génération |

## 2.3 Nouveautés v2 — comptabilité

| # | Fonctionnalité | Pourquoi |
|---|---|---|
| 16 | **Écriture comptable proposée** par reçu, en tableau débit/crédit | Le cœur du module |
| 17 | **Statut d'équilibre** de l'écriture (R4) | Règle exacte, pas approchée |
| 18 | **Synthèse TVA** : récupérable / non récupérable avec motifs | Là où la limite du dataset devient un cas métier |
| 19 | **Note de frais** par période, agrégée par catégorie | Livrable métier réel |
| 20 | **Journal comptable** exportable en CSV | Interopérabilité |
| 21 | **Choix du mode de paiement** (espèces / banque / crédit) | Détermine le compte crédité |

## 2.4 Priorité 3 — intégrées en v2

Elles étaient en attente ; avec 6 jours, elles rentrent.

| # | Fonctionnalité | Où | Effort |
|---|---|---|---|
| 13 | **Export CSV de la base de dépenses** | Onglet Tableau de bord, `st.download_button` | 15 min |
| 14 | **Indicateur de confiance par champ** | Onglet Analyser, à côté de chaque champ | 1 h |
| 15 | **Comparaison Donut vs baseline** | Onglet Technique dédié | 45 min |

**Détail n°14 — l'indicateur de confiance.** Donut ne fournit pas de score de
confiance directement exploitable. Deux approches honnêtes :

- *Simple* : un proxy par cohérence — un champ est « à vérifier » s'il est
  absent, s'il vaut zéro, ou s'il fait échouer une règle. Ce n'est pas une
  probabilité, c'est un signalement. À nommer « à vérifier », pas « confiance
  87 % ».
- *Rigoureux* : récupérer les log-probabilités de génération avec
  `output_scores=True` dans `model.generate()`, et moyenner par champ. Plus
  juste, plus coûteux à implémenter.

Choisis le simple, et **dis en soutenance pourquoi** : un faux score de
confiance est pire que pas de score, parce qu'il inspire une confiance que rien
ne justifie. C'est un excellent point d'honnêteté méthodologique.

**Détail n°15 — l'onglet Technique.** Il sert à montrer au correcteur ce qu'une
démo produit ne montre pas : le tableau Donut vs baseline, les quatre chiffres
du sur-apprentissage, la courbe de perte. C'est ta rigueur technique, rendue
visible dans l'application elle-même.

## 2.5 Ce qu'il ne faut toujours pas faire

Authentification, base de données serveur, mode sombre, responsive mobile,
animations. Zéro point, beaucoup d'heures.

---

# PARTIE 3 — STRUCTURE DE L'INTERFACE

Quatre onglets.

```
┌─────────────────────────────────────────────────────────────┐
│  🧾 Copilote de reçus et dépenses                           │
│  ┌──────────┬──────────────┬──────────────┬──────────────┐ │
│  │ Analyser │ Tableau bord │ Comptabilité │  Technique   │ │
│  └──────────┴──────────────┴──────────────┴──────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

**Onglet 1 — Analyser.** Upload → image à gauche, données éditables à droite →
badges des règles → écriture comptable proposée avec statut d'équilibre →
JSON brut repliable → bouton Valider. Sélecteurs pays et mode de paiement.

**Onglet 2 — Tableau de bord.** 4 KPI → graphique catégories → histogramme des
totaux → liste des anomalies expliquées → tableau filtrable → export CSV.

**Onglet 3 — Comptabilité.** Sélecteur de période → synthèse TVA avec motifs →
note de frais agrégée → journal des écritures → export CSV du journal.

**Onglet 4 — Technique.** Donut vs baseline → sur-apprentissage avant/après →
courbe de perte → note méthodologique sur l'indicateur de confiance.

---

# PARTIE 4 — TRADUCTION EN STREAMLIT

| Élément | Composant |
|---|---|
| Navigation | `st.tabs([...])` |
| Dépôt | `st.file_uploader(type=["jpg","jpeg","png"])` |
| Deux colonnes | `st.columns([1, 1])` |
| **Tableau éditable** | `st.data_editor(df, num_rows="dynamic")` ⭐ |
| Champs montants | `st.number_input(...)` |
| Badges | `st.success` / `st.error` / `st.info` |
| KPI | `st.metric(label, value, delta)` |
| Sélecteurs | `st.selectbox(...)` |
| JSON repliable | `with st.expander(...): st.json(...)` |
| Graphiques | `st.pyplot(fig)` |
| Tableaux | `st.dataframe(df, use_container_width=True)` |
| **Export CSV** | `st.download_button("Exporter", df.to_csv(index=False), "depenses.csv", "text/csv")` |
| Cartes | `st.container(border=True)` |
| Thème | `.streamlit/config.toml` |

## Le composant clé

```python
df_corrige = st.data_editor(pd.DataFrame(r.items), num_rows="dynamic")
# reconstruire le Receipt avec les valeurs corrigees, puis :
flags = audit(receipt_corrige, country=pays)
entry = journal_entry(receipt_corrige, categorie, mode_paiement)
```

Les badges et l'écriture se mettent à jour à chaque correction. C'est la
séquence la plus convaincante de la vidéo : montre un champ mal extrait, une
règle en ❌, corrige, la règle passe en ✅ et l'écriture s'équilibre.

## Thème

`.streamlit/config.toml` :

```toml
[theme]
primaryColor = "#1E5F74"
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#F4F6F8"
textColor = "#1A1A1A"
font = "sans serif"
```

## Contrainte technique impérative

Le modèle Donut pèse ~800 Mo. **Chargement paresseux obligatoire** : ne le
charge qu'au moment où un fichier est uploadé, via `@st.cache_resource`, dans
un `try/except`. Les onglets 2, 3 et 4 doivent fonctionner à partir des CSV de
`data/`, sans jamais toucher au modèle. Sinon l'app met 40 secondes à démarrer
et devient inutilisable en démo.

---

# PARTIE 5 — PLANNING RÉVISÉ (6 JOURS)

Présentation le 29 juillet.

| Jour | Date | Contenu | Livrable du soir |
|---|---|---|---|
| **J3** | 23/07 | Base de dépenses, KMeans, FAISS, prompting zero-shot, RAG, Streamlit v1 | L'app tourne, 3 onglets |
| **J4** | 24/07 | `accounting.py` + tests + onglet Comptabilité | Une écriture équilibrée à l'écran |
| **J5** | 25/07 | Correction manuelle, anomalies expliquées, export CSV, onglet Technique | L'app est complète |
| **J6** | 26/07 | Test ticket ivoirien, indicateur de confiance, polissage, nettoyage des branches | Le projet est figé |
| **J7** | 27/07 | README, documentation technique, PowerPoint | Les écrits sont faits |
| **J8** | 28/07 | Vidéo, répétition de la soutenance, checklist finale | Tout est poussé |
| | 29/07 | **Présentation** | |

**Marge.** Le J8 est volontairement léger : la vidéo demande toujours deux
prises de plus que prévu, et il faut du temps pour les imprévus. Ne comble pas
cette marge avec des fonctionnalités.

**Ordre de construction, si tu dois couper.** Les paliers 1 à 4 couvrent le
barème complet. Les paliers 5 à 8 sont ce qui distingue.

1. 3 onglets + upload + extraction + JSON
2. Tableau lisible + badges des règles
3. Tableau de bord (KPI + 2 graphiques)
4. Recherche sémantique
5. `st.data_editor` (correction manuelle)
6. Module comptable + onglet Comptabilité
7. Sélecteur de pays + anomalies expliquées
8. Export CSV + onglet Technique + confiance

---

# PARTIE 6 — CE QUE ÇA CHANGE POUR LA SOUTENANCE

## Nouvelles questions probables

**« Ton outil remplace-t-il un comptable ? »**
Non, et c'est écrit dans le README. Il propose une pré-affectation comptable à
partir de règles simplifiées SYSCOHADA, qui doit être validée par un
professionnel. Il fait gagner du temps de saisie, il ne porte pas de jugement
comptable.

**« Pourquoi la TVA n'est-elle pas récupérable sur la plupart de tes reçus ? »**
Parce que la TVA n'est déductible que si la facture identifie le fournisseur, et
que le champ marchand a été retiré de la version publique de CORD pour raisons
légales. Plutôt que d'inventer un fournisseur, le système signale explicitement
« TVA non récupérable — fournisseur non identifié ». La limite du jeu de données
produit ici une conséquence métier correcte.

**« Comment vérifies-tu qu'une écriture est juste ? »**
Par l'équilibre débit/crédit, qui est une contrainte exacte et non une
tolérance. C'est ma règle la plus rigoureuse : les trois autres acceptent 2 %
d'écart pour absorber les arrondis de caisse, celle-ci non.

**« Ton indicateur de confiance est-il fiable ? »**
Ce n'est pas un score de confiance, et je l'ai nommé « à vérifier »
délibérément. Donut ne fournit pas de probabilité exploitable simplement ;
j'utilise un proxy par cohérence (champ absent, nul, ou faisant échouer une
règle). Afficher « confiance 87 % » aurait été plus impressionnant et
malhonnête : un faux score inspire une confiance que rien ne justifie.

## Nouvelle slide PowerPoint

Intercaler entre les règles métier et la recherche sémantique :

> **Slide — De la vérification à la comptabilité**
> Une écriture débit/crédit à l'écran, équilibrée.
> Le message : *« le copilote ne dit pas seulement si le reçu est cohérent, il
> dit quoi en faire »*.
