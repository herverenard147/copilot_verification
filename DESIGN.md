# DESIGN.md — Receipt & Expense Copilot

Source : maquettes Stitch, projet **"Precise Receipt Ledger"** (design system
*Precise Ledger*), 15 écrans. Ce document est la référence de style pour
`app.py` et pour toute session future. Il documente aussi les écarts
assumés entre la maquette et l'implémentation réelle (Streamlit + données
CORD réelles), voir section "Écarts assumés" en fin de fichier.

## Palette (hex exacts)

| Rôle | Hex | Usage |
|---|---|---|
| Primary (texte/icônes actives) | `#00475A` | Onglet actif, liens, focus |
| Primary container (brand teal) | `#1E5F74` | Boutons primaires, indicateur d'onglet actif (barre 2px) |
| On-primary | `#FFFFFF` | Texte sur fond primary |
| Secondary | `#5C5F60` | Texte secondaire |
| Secondary container | `#DEE0E1` | Fonds neutres discrets |
| Tertiary | `#004B31` / `#006544` | Accent secondaire (rarement utilisé) |
| Success (statut ✅) | `#10B981` (Emerald 500) | Chip succès, montants validés |
| Warning / "à vérifier" | Amber 500 (`#F59E0B` usuel Tailwind, non fixé précisément dans le design system) | Tag ambre "à vérifier", faible confiance OCR |
| Error (statut ❌) | `#BA1A1A` (error) / fond `#FFDAD6` (error container) | Chip erreur, échec de traitement |
| Neutral (statut ➖) | `#64748B` (Slate 500) | Chip neutre — "je ne sais pas", PAS une erreur |
| Background (canvas) | `#F8F9FF` (proche de `#F8FAFB` mentionné dans le style guide) | Fond de page |
| Surface / cartes | `#FFFFFF` | Cartes, modales |
| Bordures | `#E2E8F0` (Slate 200, mentionné dans le style guide) / `#C0C8CC` (outline_variant du token) | Bordures 1px partout, pas d'ombre portée |
| Texte principal | `#0B1C30` (on_surface) | Corps de texte |
| Texte secondaire | `#40484C` (on_surface_variant) | Libellés, légendes |

Le design system rejette les ombres portées ("Structural Definition") :
la profondeur vient uniquement de bordures 1px à faible contraste et d'un
léger changement de teinte de fond (canvas gris-bleu très pâle vs cartes
blanches). Le focus actif = bordure 1px primary + halo 2px à 10% d'opacité.

## Typographie

- **Police de corps et titres** : Hanken Grotesk
- **Police des nombres/tableaux financiers** : JetBrains Mono (tabular
  figures) — **tous les montants, IDs de reçu et quantités doivent utiliser
  cette police ou des chiffres tabulaires**, pour aligner les décimales.

| Niveau | Taille | Poids | Interligne | Letter-spacing |
|---|---|---|---|---|
| headline-lg | 30px | 600 | 38px | -0.02em |
| headline-md | 24px | 600 | 32px | -0.01em |
| headline-sm | 20px | 600 | 28px | — |
| body-lg | 16px | 400 | 24px | — |
| body-md | 14px | 400 | 20px | — |
| body-sm | 13px | 400 | 18px | — |
| tabular-num (JetBrains Mono) | 14px | 500 | 20px | — |
| label-caps (labels de formulaire, UPPERCASE) | 11px | 700 | 16px | +0.05em |

## Espacement et forme

- Rythme de base 4px : xs=4px, sm=8px, md=16px, lg=24px, xl=40px.
- Largeur max de conteneur : 1280px, gouttière 20px.
- Header persistant fixe à **64px** de hauteur, fond blanc, bordure basse
  `#E2E8F0`.
- Rayon de bordure : **4px** par défaut (boutons, inputs, cartes) ; **8px**
  pour les grands conteneurs (zone principale du dashboard).
- Tableaux : padding vertical "condensé" de 8px par ligne pour maximiser la
  densité d'information.

## Conventions transverses

### Chips de contrôle à 3 états (✅ / ❌ / ➖)

Le design system officiel ne définit que **3 états de chip** :
- **Succès** : texte + fond vert clair, icône coche.
- **Erreur** : texte + fond rouge clair, icône croix.
- **Neutre** : texte + fond gris clair (slate), icône tiret — **c'est l'état
  "je ne sais pas", pas un état alarmant**. Plusieurs maquettes (ex. l'écran
  Analyze - Result) utilisent par erreur un jaune/ambre ou un rouge pour ce
  qui devrait être neutre (ex. "taux de taxe" quand la taxe est absente) :
  **ne pas reproduire cette incohérence** — le ➖ doit rester visuellement
  neutre, jamais alarmant, sinon l'app parait constamment en échec sur les
  ~50% de reçus CORD sans champ taxe.

### Tag ambre "à vérifier"

Distinct des 3 chips ci-dessus : un **tag ambre** signale un champ à
vérifier manuellement (absent, nul, ou faisant échouer une règle). Il
qualifie un CHAMP (ligne, montant), pas le résultat d'une règle globale.
Vu dans les maquettes sous forme de badge "REVIEW REQUIRED", de suffixe
"VERIFY" sur une ligne, ou de tag "warning" sur un article.

**Écart volontaire** : plusieurs écrans (Analyze - Result JSON brut,
Analyze - Processing, Receipt Detail) affichent un **pourcentage de
confiance** (ex. `confidence: 0.94`, "98.4%"). L'app ne doit **PAS**
reproduire ce pourcentage — remarque cohérente avec l'écran Technical
Review lui-même, dont l'encadré méthodologique explique que les scores de
confiance sont "avoided as they introduce systemic risk" au profit d'un
drapeau binaire "à vérifier". Le design se contredit d'un écran à l'autre
sur ce point ; on suit la version qui correspond à la consigne produit.

### Tableaux débit/crédit

Colonnes fixes : **Account | Label | Debit | Credit** (vues sur "Analyze -
Result" pour l'écriture proposée, et sur "Accounting - Overview" pour le
journal général). Un indicateur "Balanced" / "Unbalanced" (vert/rouge)
accompagne chaque groupe d'écriture. Montants toujours alignés à droite,
chiffres tabulaires.

### Autres conventions observées

- Sélecteur pays/TVA : "Côte d'Ivoire (18% VAT)" / "Indonesia (11% VAT)"
  (+ "European Union 20%" dans la maquette, hors périmètre du projet).
- Mode de paiement : Cash / Bank / Credit — correspond exactement aux 3
  comptes de crédit de `src/accounting.py` (571/521/401).
- Détail d'anomalie : rupture arithmétique affichée explicitement
  ("SUM OF LINE ITEMS: 47 000 · DECLARED SUBTOTAL: 52 000 · DIFFERENCE:
  5 000"), jamais un simple badge "erreur".
- Erreurs : toujours un message clair + causes probables + actions de
  récupération, jamais de trace technique brute.

## Résumé par écran (15)

1. **Analyze - Start** (état vide) : sélecteur pays/TVA + mode de paiement
   dans le header ; zone de dépôt centrale + lien "upload multiple" ; 3
   cartes de reçus récents (marchand, date, montant, miniature).
2. **Analyze - Processing** (traitement) : titre "Analysis in Progress",
   étape "STEP 2 OF 3", barre de progression, message explicatif, tableau
   des champs en cours d'extraction. *(pas de pourcentage de confiance dans
   l'implémentation réelle, cf. écart ci-dessus.)*
3. **Analyze - Result** (résultat) : 2 colonnes — image du reçu à gauche ;
   à droite, tableau de lignes éditables, sous-total/taxe/total, badge
   "REVIEW REQUIRED", 3-4 chips de contrôle, carte "écriture comptable
   proposée" (Account/Label/Debit/Credit + solde), bouton de validation,
   JSON brut en expander.
4. **Analyze - Error** (erreur) : message "Could not read this receipt" +
   3 causes probables concrètes + 2 actions ("Try another image" / "Enter
   the data manually") + badge qualité faible. Aucune trace technique.
5. **Dashboard - Overview** : 4 cartes KPI (reçus traités, articles
   extraits, dépense totale, anomalies), graphique dépenses par catégorie,
   histogramme des totaux, section "Active Anomalies" (montant calculé vs
   extrait, action Fix/Merge), tableau filtrable paginé.
6. **Dashboard - Empty State** : 4 cartes KPI à zéro, message "No receipts
   yet", 3 CTA (analyser / import batch / connecter ERP).
7. **Receipt Detail** : lecture seule avec bouton Éditer, image + zoom,
   métadonnées marchand/date, lignes d'articles, statut "VALIDATED" /
   "SYNCED TO XERO", panneau "Journal Mapping" (débit/crédit + catégorie).
8. **Anomaly Detail** : rupture arithmétique explicite (somme lignes /
   sous-total déclaré / écart), tableau des lignes détectées avec tag
   d'avertissement sur la ligne suspecte, métadonnées, actions "Corriger" /
   "Accepter avec justification".
9. **Accounting - Overview** : sélecteur de période (Month/Quarter/Custom),
   carte TVA en 2 moitiés (récupérable avec motif ; non récupérable avec
   motifs et décomptes : "Fournisseur non identifié: 42 reçus", "Données
   incomplètes: 12 reçus"), tableau de synthèse par catégorie (Net/VAT/
   Gross), journal général avec statut Balanced/Unbalanced par groupe,
   export CSV, disclaimer en pied de page.
10. **Ask Your Expenses** : input proéminent, historique des questions
    récentes, chips de questions suggérées, carte réponse, 3 reçus sources
    avec score de pertinence (98%/94%/82%) et lien "View Detail".
11. **Technical Review** : tableau comparatif Donut vs baseline (accuracy,
    précision, taux JSON valide, latence), tableau épochs train/val
    (overfitting), encadré méthodologique binaire-vs-pourcentage (justifie
    l'absence de score de confiance dans l'app), infos infra.
12. **Batch Upload Queue** : zone de dépôt multiple, barre de progression
    globale, tableau de fichiers (miniature/nom/statut/total/résumé/
    actions) avec 4 statuts (Done vert, Processing bleu+spinner, Failed
    rouge, Queued gris), filtres "Review failures only" / "Validate all".
13. **Save Confirmation Overlay** : modale de succès, icône coche verte,
    "Saved to expenses", résumé (total/catégorie/compte), actions
    "Analyze another" / "View in dashboard".
14. **Settings Dashboard** : pays par défaut + taux de TVA, détection de
    doublons (toggle), plafond de reçu (déclenche revue manuelle), tableau
    mapping catégorie→compte éditable (+ bouton "add New Rule"), tolérances
    (description du seuil arithmétique), export config / purge cache,
    horodatage dernière sauvegarde.
15. **Export Dialog Modal** : format (CSV/Excel), portée des données
    (filtres actuels / tout / période / sélection), preset comptable
    (Standard ERP, QuickBooks, Xero, Sage Intacct), nom de fichier, actions
    Annuler/Télécharger.

## Écarts assumés (Stitch → implémentation réelle)

Ces choix sont pris consciemment quand le design contredit une contrainte
produit ou technique explicite ; ils seront rappelés dans le résumé final
de chaque session qui touche `app.py`.

1. **Pas de pourcentage de confiance** nulle part dans l'app (ni JSON, ni
   UI), même si plusieurs maquettes en affichent un — remplacé partout par
   le tag binaire "à vérifier".
2. **Chips à exactement 3 états** (✅/❌/➖), le ➖ toujours neutre — les
   variantes 4 couleurs vues sur certains écrans (Batch Upload, Analyze
   Result) ne sont pas reproduites telles quelles.
3. **Marchand et date peuvent être absents** (`None`) dans toute l'UI —
   les maquettes les affichent toujours renseignés, la réalité CORD est
   différente (champs retirés des labels publics).
4. **Pays limités à CI (18%) et ID (11%)** — l'option "European Union 20%"
   des maquettes est hors périmètre.
5. **Aucune balise `<form>` HTML**, composants Streamlit natifs uniquement
   — les maquettes HTML utilisent des formulaires web classiques.
