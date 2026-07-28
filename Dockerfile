# Déploiement Hugging Face Spaces (SDK: docker, CPU 16 Go).
# App FastAPI COMPLÈTE : Donut + FAISS + sentence-transformers, rien d'allégé.
#
# Donut (~800 Mo) et l'encodeur MiniLM ne sont PAS embarqués dans l'image :
# ils sont téléchargés depuis le Hub au premier appel, dans HF_HOME (voir plus
# bas). Le tout premier /api/extract est donc plus lent (mesuré ~4 min en
# conteneur froid : download + chargement + inférence CPU, selon le réseau) ;
# les suivants réutilisent le cache tant que le conteneur vit.
FROM python:3.11-slim

# Bibliothèques système requises par opencv-headless / torch / faiss.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# HF Spaces exécute le conteneur en utilisateur non-root (uid 1000). On crée
# ce même utilisateur pour que les dossiers de cache et la base SQLite soient
# inscriptibles.
RUN useradd -m -u 1000 user
USER user

ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    # Cache des modèles téléchargés (Donut, MiniLM) — dossier inscriptible.
    HF_HOME=/home/user/.cache/huggingface \
    # Base SQLite locale : éphémère (réinitialisée à chaque redémarrage du
    # conteneur), dans un dossier inscriptible par 'user'.
    COPILOTE_STATE_FILE=/home/user/app/.local_state/sessions.db

WORKDIR /home/user/app

# 1) Dépendances d'abord (couche Docker mise en cache tant que requirements
#    ne change pas). torch en version CPU explicite : évite d'embarquer les
#    ~2 Go de bibliothèques CUDA inutiles sur un Space CPU.
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

# 2) Code + données (src/, web/, api.py, data/ avec le corpus CORD de démo).
COPY --chown=user . .

EXPOSE 7860

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "7860"]
