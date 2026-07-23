"""Embeddings, clustering et recherche vectorielle."""
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def get_encoder(name=MODEL_NAME):
    """Charge le modele d'embeddings (texte -> vecteur de 384 nombres)."""
    return SentenceTransformer(name)


def embed(texts, encoder):
    """Textes -> matrice d'embeddings normalises (pour la similarite cosinus)."""
    vecs = encoder.encode(list(texts), show_progress_bar=False,
                          convert_to_numpy=True)
    faiss.normalize_L2(vecs)
    return vecs


def build_index(vecs):
    """Construit un index FAISS de recherche par similarite."""
    index = faiss.IndexFlatIP(vecs.shape[1])   # IP = produit scalaire = cosinus
    index.add(vecs)
    return index


def search(query, encoder, index, texts, k=5):
    """Question -> les k textes les plus proches."""
    qv = embed([query], encoder)
    scores, ids = index.search(qv, k)
    return [(texts[i], float(s)) for i, s in zip(ids[0], scores[0]) if i >= 0]
