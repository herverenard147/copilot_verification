"""Interface Streamlit du Copilote de recus et depenses."""
import json
import numpy as np
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import seaborn as sns

import sys
sys.path.append(".")
from src.receipt import Receipt
from src.rules import audit
from src.semantic import get_encoder, embed, build_index, search

st.set_page_config(page_title="Copilote de reçus", page_icon="🧾", layout="wide")


@st.cache_data
def load_data():
    items = pd.read_csv("data/items.csv")
    receipts = pd.read_csv("data/receipts.csv")
    summaries = json.load(open("data/summaries.json"))
    return items, receipts, summaries


@st.cache_resource
def load_search():
    enc = get_encoder()
    _, _, summaries = load_data()
    return enc, build_index(embed(summaries, enc))


@st.cache_resource
def load_donut():
    import torch
    from transformers import DonutProcessor, VisionEncoderDecoderModel
    name = "naver-clova-ix/donut-base-finetuned-cord-v2"
    proc = DonutProcessor.from_pretrained(name)
    mod = VisionEncoderDecoderModel.from_pretrained(name)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    return proc, mod.to(dev), dev


items, receipts, summaries = load_data()

st.title("🧾 Copilote de reçus et dépenses")
st.caption("Extraction automatique · vérification comptable · recherche sémantique")

tab1, tab2, tab3 = st.tabs(["📤 Analyser un reçu", "📊 Tableau de bord", "💬 Questions"])

with tab1:
    st.subheader("Déposer une photo de reçu")
    up = st.file_uploader("Image du reçu", type=["jpg", "jpeg", "png"])
    if up:
        from PIL import Image
        from src.extractor import extract
        img = Image.open(up).convert("RGB")
        c1, c2 = st.columns(2)
        c1.image(img, caption="Reçu déposé", use_container_width=True)
        with c2:
            with st.spinner("Lecture par le modèle Donut..."):
                proc, mod, dev = load_donut()
                pred = extract(img, mod, proc, dev)
            st.json(pred)
            r = Receipt.from_gt_parse(pred)
            flags = audit(r)
            st.markdown("**Contrôle comptable**")
            for k, v in flags.items():
                if k == "anomaly":
                    continue
                icone = {True: "✅", False: "❌", None: "➖"}[v]
                st.write(f"{icone} {k}")
            if flags["anomaly"]:
                st.error("Anomalie détectée : les montants ne sont pas cohérents.")
            else:
                st.success("Aucune anomalie détectée.")

with tab2:
    st.subheader("Vue d'ensemble des dépenses")
    c1, c2, c3 = st.columns(3)
    c1.metric("Reçus analysés", len(receipts))
    c2.metric("Articles", len(items))
    c3.metric("Anomalies", int(receipts["anomaly"].sum()))

    if "category" in items.columns:
        dep = items.groupby("category")["line_price"].sum().sort_values() / 1000
        fig, ax = plt.subplots(figsize=(8, 4))
        sns.barplot(x=dep.values, y=dep.index, orient="h", ax=ax)
        ax.set_xlabel("Dépenses (milliers de Rp)")
        st.pyplot(fig)

    fig2, ax2 = plt.subplots(figsize=(8, 3))
    sns.histplot(receipts["total"].dropna() / 1000, bins=40, ax=ax2)
    ax2.set_xlabel("Total du reçu (milliers de Rp)")
    st.pyplot(fig2)

with tab3:
    st.subheader("Interroger l'historique de dépenses")
    q = st.text_input("Votre question", "Quels reçus contiennent des boissons ?")
    if st.button("Chercher"):
        enc, idx = load_search()
        res = search(q, enc, idx, summaries, k=5)
        st.markdown("**Reçus les plus pertinents :**")
        for texte, score in res:
            st.write(f"`{score:.2f}` — {texte}")
        st.info("La génération de réponse par LLM nécessite une clé API "
                "(démontrée dans le notebook 04).")
