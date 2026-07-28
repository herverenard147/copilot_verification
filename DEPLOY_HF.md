# Déploiement sur Hugging Face Spaces (Docker, CPU gratuit)

Ce dossier contient tout le nécessaire pour héberger l'application FastAPI
**complète** (Donut + FAISS + sentence-transformers) sur un Space Hugging Face
gratuit (CPU, 16 Go RAM). Aucune version allégée.

Fichiers dédiés au déploiement :

- `Dockerfile` — image `python:3.11-slim`, utilisateur non-root uid 1000
  (comme HF Spaces), install de `requirements.txt`, port **7860**, démarrage
  `uvicorn api:app --host 0.0.0.0 --port 7860`.
- `.dockerignore` — n'envoie que le code + `data/` (corpus CORD) au build.
- `README.md` — en-tête YAML lu par HF (`sdk: docker`, `app_port: 7860`).

---

## Étapes à suivre sur huggingface.co (interface web)

1. **Créer un compte** sur https://huggingface.co (gratuit) si ce n'est pas fait.

2. **Créer le Space** : bouton **New** (en haut à droite) → **Space**, ou
   directement https://huggingface.co/new-space.
   - **Owner** : votre compte.
   - **Space name** : `copilote-recus` (ou autre).
   - **License** : `mit`.
   - **Select the Space SDK** : choisir **Docker** → **Blank / Dockerfile**
     (PAS Gradio/Streamlit).
   - **Space hardware** : laisser **CPU basic — 2 vCPU, 16 GB — FREE**.
   - Visibilité : **Public** (les Spaces privés gratuits fonctionnent aussi).
   - Cliquer **Create Space**.

3. **Envoyer le code vers le Space.** Un Space EST un dépôt git hébergé par HF.
   Deux options :

   **Option A — pousser ce dépôt vers le Space (le plus simple)**
   Depuis le dossier du projet :
   ```bash
   git remote add space https://huggingface.co/spaces/<votre-compte>/copilote-recus
   git push space feature/deploy-hf-spaces:main
   ```
   HF demandera identifiant + **token d'accès** (voir étape 4). Le build Docker
   démarre automatiquement dès réception sur la branche `main` du Space.

   **Option B — glisser-déposer via l'interface web**
   Onglet **Files** du Space → **Add file** → uploader `Dockerfile`,
   `README.md`, `requirements.txt`, `api.py`, et les dossiers `src/`, `web/`,
   `data/`. Plus fastidieux ; l'option A est recommandée.

4. **Créer un token d'accès** (pour le push git) :
   https://huggingface.co/settings/tokens → **New token** → rôle **Write** →
   copier le token et l'utiliser comme mot de passe lors du `git push`.

5. **Suivre le build** : onglet **Logs** du Space (sous-onglet **Build** puis
   **Container**). Le premier build prend **plusieurs minutes** (installation de
   torch, transformers, etc.). Quand le statut passe à **Running**, l'app est en
   ligne à l'URL du Space.

---

## Clé Groq (RAG optionnel) — via secret, jamais en dur

Le code lit la clé dans la variable d'environnement **`GROQ_API_KEY`**
(`src/llm.py`). Elle n'est **jamais** écrite dans le code ni dans le Dockerfile.

Pour la fournir en ligne :

1. Space → onglet **Settings** → section **Variables and secrets**.
2. **New secret** (pas « variable » : un *secret* est chiffré et masqué).
   - **Name** : `GROQ_API_KEY`
   - **Value** : votre clé `gsk_...`
3. **Save**. Le Space redémarre et la clé est disponible comme variable
   d'environnement pour l'app.

> Sans cette clé, l'app fonctionne quand même : le RAG/LLM se dégrade
> proprement (recherche sémantique locale FAISS conservée).

---

## Persistance : réinitialisation attendue (acceptable pour la démo)

Le Space gratuit se met en veille après inactivité et le conteneur est
éphémère : la base SQLite locale (`.local_state/sessions.db`) est **remise à
zéro à chaque redémarrage**. C'est **acceptable** — il ne s'agit pas de données
de production : le **mode démonstration** recharge les **800 reçus CORD** à la
demande depuis `data/` (versionné dans l'image). Aucune donnée utilisateur
réelle n'est perdue.

---

## Téléchargement de Donut au premier appel (délai attendu — anticipé)

Les modèles ne sont **pas** embarqués dans l'image. Au tout premier
`/api/extract`, l'app télécharge depuis le Hub :

- **Donut** `naver-clova-ix/donut-base-finetuned-cord-v2` (~800 Mo),
- l'encodeur **MiniLM** `sentence-transformers/all-MiniLM-L6-v2` (~90 Mo) au
  premier usage de l'onglet Questions.

Ils sont mis en cache dans `HF_HOME=/home/user/.cache/huggingface` (dossier
inscriptible défini dans le Dockerfile).

> **Vérifié en local** : dans un conteneur Docker **froid** (aucun cache), le
> téléchargement + chargement de Donut a pris **~4 min** (réseau lent) ; le
> cache résultant pèse ~1,6 Go. Sur l'infra HF (meilleure bande passante),
> compter plutôt **~1–3 min**. Ce n'est **pas** supposé : le test a réellement
> été exécuté.

**Conséquence attendue :**

- **1er upload : ~1–4 min** (téléchargement du modèle + 1re inférence CPU),
  selon la bande passante.
- **Uploads suivants : quelques secondes** (modèle en cache), tant que le
  conteneur reste actif.
- Après une mise en veille/redémarrage, le cache est vidé → le premier upload
  suivant est de nouveau plus lent. Comportement normal d'un Space gratuit.

Pour une démo fluide devant public : faire **un upload « à blanc »** quelques
minutes avant, pour que Donut soit déjà en cache au moment de la présentation.
