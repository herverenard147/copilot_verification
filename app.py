"""Interface Streamlit du Copilote de recus et depenses.

Style et conventions : voir DESIGN.md (palette, typographie, chips a 3
etats, tag ambre "a verifier", tableaux debit/credit).
"""
import json
import os

import numpy as np
import pandas as pd
import streamlit as st

from src.receipt import Receipt
from src.rules import check_line_sum, check_total, check_tax_rate, TAX_RATES
from src.accounting import (
    journal_entry, is_balanced, vat_recoverable, map_category_to_account,
    vat_summary, expense_report, DISCLAIMER,
    CHART_OF_ACCOUNTS, DEFAULT_CATEGORY_ACCOUNTS,
)

st.set_page_config(page_title="Copilote de reçus", page_icon="🧾", layout="wide")

COUNTRY_LABELS = {"CI": "Côte d'Ivoire — TVA 18%", "ID": "Indonésie — TVA 11%"}
PAYMENT_LABELS = {"cash": "Espèces (caisse)", "bank": "Virement bancaire", "credit": "À crédit (fournisseur)"}


# ---------------------------------------------------------------------------
# Etat de session (valeurs par defaut)
# ---------------------------------------------------------------------------
def init_state():
    defaults = {
        "country": "CI",
        "payment_mode": "cash",
        "category_mapping": dict(DEFAULT_CATEGORY_ACCOUNTS),
        "current_result": None,      # dict : donnees du recu en cours d'analyse
        "analyze_error": None,
        "manual_entries": [],        # recus valides manuellement pendant la session
        "qa_history": [],
        "groq_api_key": os.environ.get("GROQ_API_KEY", ""),
        "selected_receipt_id": None,
        "selected_anomaly_id": None,
        "show_batch_upload": False,
        "upload_key_version": 0,   # incremente pour reinitialiser le file_uploader (evite de retraiter un fichier deja consomme)
        "settings": {
            "max_amount": 500000.0,
            "duplicate_detection": True,
            "line_sum_tolerance": 0.02,
            "total_tolerance": 0.02,
            "tax_band": 0.05,
        },
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


init_state()


# ---------------------------------------------------------------------------
# Donnees : chargement avec repli sur des donnees d'exemple
# ---------------------------------------------------------------------------
def _example_data():
    """Petit jeu de donnees synthetique, utilise quand data/*.csv est absent
    (ex. premiere execution, avant d'avoir lance le notebook 04)."""
    receipts = pd.DataFrame([
        {"receipt_id": 0, "n_items": 2, "items_sum": 25000.0, "subtotal": 25000.0, "tax": 4500.0, "total": 29500.0,
         "line_sum_ok": True, "total_ok": True, "tax_ok": True, "anomaly": False, "category": "food"},
        {"receipt_id": 1, "n_items": 1, "items_sum": 47000.0, "subtotal": 52000.0, "tax": None, "total": 52000.0,
         "line_sum_ok": False, "total_ok": None, "tax_ok": None, "anomaly": True, "category": "transport"},
        {"receipt_id": 2, "n_items": 3, "items_sum": 108900.0, "subtotal": 108900.0, "tax": 19602.0, "total": 128502.0,
         "line_sum_ok": True, "total_ok": True, "tax_ok": True, "anomaly": False, "category": "supplies"},
        {"receipt_id": 3, "n_items": 1, "items_sum": 15000.0, "subtotal": 15000.0, "tax": None, "total": 15000.0,
         "line_sum_ok": True, "total_ok": None, "tax_ok": None, "anomaly": False, "category": "food"},
        {"receipt_id": 4, "n_items": 2, "items_sum": 60000.0, "subtotal": 60000.0, "tax": 10800.0, "total": 71000.0,
         "line_sum_ok": True, "total_ok": False, "tax_ok": True, "anomaly": True, "category": "telecom"},
    ])
    items = pd.DataFrame([
        {"receipt_id": 0, "name": "Nasi Goreng", "quantity": 1, "unit_price": 15000.0, "line_price": 15000.0},
        {"receipt_id": 0, "name": "Es Teh", "quantity": 2, "unit_price": 5000.0, "line_price": 10000.0},
        {"receipt_id": 1, "name": "Course taxi", "quantity": 1, "unit_price": 47000.0, "line_price": 47000.0},
        {"receipt_id": 2, "name": "Ramette papier A4", "quantity": 3, "unit_price": 36300.0, "line_price": 108900.0},
        {"receipt_id": 3, "name": "Café", "quantity": 1, "unit_price": 15000.0, "line_price": 15000.0},
        {"receipt_id": 4, "name": "Forfait internet", "quantity": 1, "unit_price": 60000.0, "line_price": 60000.0},
    ])
    return items, receipts


@st.cache_data
def load_data():
    try:
        items = pd.read_csv("data/items.csv")
        receipts = pd.read_csv("data/receipts.csv")
    except FileNotFoundError:
        items, receipts = _example_data()

    if "category" not in receipts.columns and "category" in items.columns:
        # categorie dominante par recu (mode des categories de ses articles) —
        # utile a l'onglet Comptabilite pour le mapping categorie -> compte.
        dominant = items.groupby("receipt_id")["category"].agg(
            lambda s: s.mode().iat[0] if not s.mode().empty else None
        )
        receipts = receipts.merge(dominant.rename("category"), on="receipt_id", how="left")

    try:
        with open("data/summaries.json") as f:
            summaries = json.load(f)
    except FileNotFoundError:
        categories = receipts["category"] if "category" in receipts.columns else ["divers"] * len(receipts)
        summaries = [
            f"Reçu #{rid} — {cat or 'divers'} — total {total}"
            for rid, cat, total in zip(receipts["receipt_id"], categories, receipts["total"])
        ]
    return items, receipts, summaries


@st.cache_resource(show_spinner=False)
def load_donut():
    """Chargement paresseux de Donut (~800 Mo). N'est appele qu'au moment
    ou l'utilisateur depose reellement une image (jamais au demarrage)."""
    import torch
    from transformers import DonutProcessor, VisionEncoderDecoderModel
    name = "naver-clova-ix/donut-base-finetuned-cord-v2"
    processor = DonutProcessor.from_pretrained(name)
    model = VisionEncoderDecoderModel.from_pretrained(name)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    return processor, model.to(device), device


@st.cache_resource(show_spinner=False)
def load_search_index(summaries_tuple):
    """Index FAISS pour l'onglet Questions. Degradation gracieuse si FAISS
    ou sentence-transformers ne sont pas installes / indisponibles."""
    try:
        from src.semantic import get_encoder, embed, build_index
        encoder = get_encoder()
        index = build_index(embed(list(summaries_tuple), encoder))
        return encoder, index
    except Exception:
        return None, None


@st.cache_resource(show_spinner=False)
def _init_groq(api_key):
    """Initialise le backend Groq une seule fois par cle. Les erreurs (cle
    invalide, quota, reseau) remontent a l'appelant, qui degrade avec
    la reponse-gabarit plutot que de planter l'onglet Questions."""
    from src.llm import init_llm
    init_llm(backend="groq", api_key=api_key)
    return True


# ---------------------------------------------------------------------------
# Petits composants d'UI reutilisables
# ---------------------------------------------------------------------------
CHIP_STYLE = {
    True: ("#10B981", "#ECFDF5", "✅"),
    False: ("#BA1A1A", "#FFDAD6", "❌"),
    None: ("#64748B", "#F1F5F9", "➖"),
}


def chip(label, value):
    """Chip a 3 etats. None est visuellement NEUTRE (gris), jamais
    alarmant : ~50% des recus CORD n'ont pas de champ taxe, un ➖ rouge
    rendrait l'app inutilisable."""
    color, bg, icon = CHIP_STYLE[value]
    st.markdown(
        f'<span style="display:inline-flex;align-items:center;gap:6px;'
        f'padding:4px 12px;border-radius:9999px;background:{bg};color:{color};'
        f'font-size:13px;font-weight:600;margin:2px 6px 2px 0;">{icon} {label}</span>',
        unsafe_allow_html=True,
    )


def to_verify_tag(text="à vérifier"):
    """Tag ambre pour un CHAMP douteux — distinct des chips ci-dessus,
    volontairement sans pourcentage de confiance (voir DESIGN.md)."""
    st.markdown(
        f'<span style="background:#FEF3C7;color:#92400E;padding:2px 8px;'
        f'border-radius:4px;font-size:12px;font-weight:700;">⚠️ {text}</span>',
        unsafe_allow_html=True,
    )


def money(value, currency=""):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "—"
    return f"{value:,.0f}{currency}".replace(",", " ")


def _nan_to_none(value):
    """pandas lit les cases vides d'un CSV comme NaN, pas None : NaN est
    truthy et casse les tests `if not receipt.tax` de rules.py/accounting.py."""
    return None if pd.isna(value) else value


# ---------------------------------------------------------------------------
# Reglages (barre laterale, accessible depuis tous les onglets)
# ---------------------------------------------------------------------------
def render_settings_sidebar(receipts):
    with st.sidebar:
        st.header("⚙️ Réglages")

        with st.expander("Pays et taux de TVA", expanded=False):
            for code, rate in TAX_RATES.items():
                st.caption(f"{COUNTRY_LABELS.get(code, code)} : {rate * 100:.0f}%")

        with st.expander("Plafonds et doublons"):
            st.session_state.settings["max_amount"] = st.number_input(
                "Plafond de reçu (déclenche une revue manuelle)",
                min_value=0.0, value=st.session_state.settings["max_amount"], step=10000.0,
            )
            st.session_state.settings["duplicate_detection"] = st.checkbox(
                "Détection automatique des doublons",
                value=st.session_state.settings["duplicate_detection"],
                help="Signale les reçus au montant identique déjà présents dans la base.",
            )

        with st.expander("Mapping catégorie → compte"):
            st.caption("Modifiable : sert de base à l'affectation comptable automatique.")
            mapping_df = pd.DataFrame(
                [{"catégorie": k, "compte": v} for k, v in st.session_state.category_mapping.items()]
            )
            edited = st.data_editor(mapping_df, num_rows="dynamic", key="mapping_editor",
                                     width='stretch')
            st.session_state.category_mapping = {
                row["catégorie"]: row["compte"] for _, row in edited.iterrows()
                if row["catégorie"] and row["compte"]
            }

        with st.expander("Tolérances des règles"):
            s = st.session_state.settings
            s["line_sum_tolerance"] = st.slider("Écart lignes / sous-total toléré", 0.0, 0.10, s["line_sum_tolerance"])
            s["total_tolerance"] = st.slider("Écart sous-total+taxe / total toléré", 0.0, 0.10, s["total_tolerance"])
            s["tax_band"] = st.slider("Bande de plausibilité du taux de taxe", 0.0, 0.10, s["tax_band"])

        with st.expander("Assistant IA (optionnel)"):
            st.caption("Sans clé, l'onglet Questions reste utilisable : recherche FAISS "
                       "seule, sans réponse générée par un LLM (dégradation gracieuse).")
            st.session_state.groq_api_key = st.text_input(
                "Clé API Groq", value=st.session_state.groq_api_key, type="password",
                help="Gratuite sur console.groq.com — laissez vide pour désactiver la génération de réponse.",
            )

        with st.expander("Export / purge"):
            st.download_button(
                "Exporter tous les reçus (CSV)",
                data=receipts.to_csv(index=False).encode("utf-8"),
                file_name="receipts_export.csv", mime="text/csv",
            )
            if st.button("Purger le cache local"):
                st.cache_data.clear()
                st.toast("🧹 Cache local vidé")
                st.rerun()


# ---------------------------------------------------------------------------
# Onglet 1 : Analyser
# ---------------------------------------------------------------------------
def compute_analysis(receipt, category, merchant):
    """Recalcule regles + ecriture comptable a partir de l'etat courant.
    Appele apres CHAQUE correction manuelle (data_editor, number_input...)."""
    settings = st.session_state.settings
    flags = {
        "line_sum_ok": check_line_sum(receipt, tolerance=settings["line_sum_tolerance"]),
        "total_ok": check_total(receipt, tolerance=settings["total_tolerance"]),
        "tax_ok": check_tax_rate(receipt, country=st.session_state.country, band=settings["tax_band"]),
    }
    try:
        entry = journal_entry(
            receipt, category=category, payment_mode=st.session_state.payment_mode,
            country=st.session_state.country, merchant=merchant,
        )
        balanced = is_balanced(entry)
    except ValueError:
        entry, balanced = None, None
    recoverable, reason = vat_recoverable(receipt, merchant=merchant)
    return flags, entry, balanced, recoverable, reason


def render_analyze_empty(receipts):
    st.subheader("Déposer une photo de reçu")
    uploaded = st.file_uploader(
        "Image du reçu", type=["jpg", "jpeg", "png"],
        key=f"single_upload_{st.session_state.upload_key_version}",
    )

    st.session_state.show_batch_upload = st.toggle(
        "Importer plusieurs reçus à la fois", value=st.session_state.show_batch_upload,
    )
    if st.session_state.show_batch_upload:
        render_batch_upload()

    if uploaded is not None:
        process_upload(uploaded)
        st.rerun()

    st.markdown("##### Derniers reçus")
    cols = st.columns(3)
    last_receipts = receipts.tail(3).iloc[::-1]
    for col, (_, row) in zip(cols, last_receipts.iterrows()):
        with col:
            st.markdown(f"**Reçu #{int(row['receipt_id'])}**")
            st.caption(row.get("category", "—") or "—")
            st.markdown(f"<span style='font-family:monospace'>{money(row['total'])}</span>", unsafe_allow_html=True)
    if last_receipts.empty:
        st.caption("Aucun reçu pour l'instant.")


def render_batch_upload():
    st.markdown("###### File d'import multiple")
    files = st.file_uploader(
        "Reçus (plusieurs fichiers)", type=["jpg", "jpeg", "png"],
        accept_multiple_files=True, key="batch_upload",
    )
    if not files:
        st.caption("Aucun fichier en attente.")
        return
    rows = [{"fichier": f.name, "statut": "En file d'attente", "total": "—"} for f in files]
    st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
    st.caption("L'analyse par lot traite chaque reçu comme un dépôt simple : sélectionnez un fichier à la fois "
               "pour l'instant (le traitement par lot complet est prévu dans une itération future).")


def process_upload(uploaded_file):
    from PIL import Image
    img = Image.open(uploaded_file).convert("RGB")

    with st.status("Analyse du reçu en cours...", expanded=True) as status:
        try:
            status.write("📥 Image chargée")
            status.write("🧠 Chargement du modèle Donut (peut prendre un moment la première fois)...")
            processor, model, device = load_donut()
            status.write("🔍 Lecture du reçu par Donut...")
            from src.extractor import extract
            prediction = extract(img, model, processor, device)
            status.write("🧮 Vérification des règles comptables...")
            receipt = Receipt.from_gt_parse(prediction)
            status.update(label="Analyse terminée", state="complete", expanded=False)
        except Exception as exc:
            status.update(label="Échec de l'analyse", state="error")
            st.session_state.analyze_error = str(exc)
            st.session_state.current_result = None
            return

    st.session_state.current_result = {
        "image": img,
        "raw_json": prediction,
        "items": receipt.items,
        "subtotal": receipt.subtotal,
        "tax": receipt.tax,
        "total": receipt.total,
        "category": "food",       # pas de clustering en direct ici ; categorie par defaut modifiable
        "merchant": None,          # absent de CORD par construction
    }
    st.session_state.analyze_error = None


def render_analyze_error():
    st.error("**Impossible de lire ce reçu.**")
    st.markdown(
        "L'image est peut-être floue, recadrée, ou dans un format non pris en charge. "
        "Le moteur d'extraction a besoin d'une vue nette et complète du document."
    )
    with st.expander("Causes probables"):
        st.markdown(
            "- Contraste insuffisant entre le reçu et l'arrière-plan\n"
            "- Mise au point non stabilisée au moment de la photo\n"
            "- Un ou plusieurs coins du reçu hors cadre"
        )
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📷 Essayer une autre image"):
            st.session_state.analyze_error = None
            st.session_state.upload_key_version += 1   # ne pas retraiter le fichier en echec
            st.rerun()
    with col2:
        if st.button("✏️ Saisir les données manuellement"):
            st.session_state.analyze_error = None
            st.session_state.current_result = {
                "image": None, "raw_json": {}, "items": [],
                "subtotal": None, "tax": None, "total": None,
                "category": "food", "merchant": None,
            }
            st.rerun()


def render_analyze_result(receipts):
    result = st.session_state.current_result
    col_img, col_data = st.columns([1, 1.4])

    with col_img:
        if result["image"] is not None:
            st.image(result["image"], caption="Reçu déposé", width='stretch')
        else:
            st.info("Saisie manuelle — aucune image associée.")

    with col_data:
        st.markdown("##### Articles extraits")
        items_df = pd.DataFrame(result["items"]) if result["items"] else pd.DataFrame(
            columns=["name", "quantity", "unit_price", "line_price"])
        edited_items = st.data_editor(
            items_df, num_rows="dynamic", width='stretch',
            column_config={
                "name": "Article", "quantity": "Qté",
                "unit_price": st.column_config.NumberColumn("Prix unitaire", format="%.0f"),
                "line_price": st.column_config.NumberColumn("Total ligne", format="%.0f"),
            },
            key="items_editor",
        )
        result["items"] = edited_items.to_dict("records")

        # capture AVANT que les number_input ne remplacent les None par 0.0
        field_was_missing = not result["subtotal"] or result["tax"] is None or not result["total"]

        c1, c2, c3 = st.columns(3)
        result["subtotal"] = c1.number_input("Sous-total", value=result["subtotal"] or 0.0, step=100.0)
        result["tax"] = c2.number_input("Taxe", value=result["tax"] or 0.0, step=100.0)
        result["total"] = c3.number_input("Total", value=result["total"] or 0.0, step=100.0)

        if field_was_missing:
            to_verify_tag("champ absent ou nul")

        accounts = list(CHART_OF_ACCOUNTS)
        current_account = map_category_to_account(result["category"], mapping=st.session_state.category_mapping)
        chosen_account = st.selectbox(
            "Compte de charge (réassignable)", options=accounts,
            index=accounts.index(current_account) if current_account in accounts else 0,
            format_func=lambda a: f"{a} — {CHART_OF_ACCOUNTS[a]}",
        )

    # --- Recalcul systematique a partir de l'etat courant (widgets ci-dessus) ---
    receipt = Receipt(
        items=result["items"], subtotal=result["subtotal"] or None,
        tax=result["tax"] or None, total=result["total"] or None,
    )
    flags, entry, balanced, recoverable, reason = compute_analysis(receipt, result["category"], result["merchant"])
    # journal_entry() mappe la categorie via la table par defaut ; si l'utilisateur
    # a reassigne le compte manuellement (selectbox ci-dessus), on l'applique a la
    # ligne de charge sans recalculer les montants (deja corrects, ecriture reste equilibree).
    if entry is not None and entry[0]["account"] != chosen_account:
        entry[0]["account"] = chosen_account
        merchant_label = result["merchant"] or "fournisseur non identifié"
        entry[0]["label"] = f"{CHART_OF_ACCOUNTS[chosen_account]} — {merchant_label}"

    st.markdown("##### Contrôles")
    chip("Lignes / sous-total", flags["line_sum_ok"])
    chip("Sous-total + taxe / total", flags["total_ok"])
    chip("Taux de taxe plausible", flags["tax_ok"])
    chip("Équilibre de l'écriture", balanced)

    if result["total"] and result["total"] > st.session_state.settings["max_amount"]:
        st.warning(f"⚠️ Montant au-dessus du plafond de revue manuelle "
                   f"({money(st.session_state.settings['max_amount'])}).")
    if st.session_state.settings["duplicate_detection"] and result["total"]:
        dup = receipts[np.isclose(receipts["total"].fillna(-1), result["total"], atol=1.0)]
        if not dup.empty:
            st.warning(f"⚠️ Doublon possible : {len(dup)} reçu(s) existant(s) au même montant.")

    st.markdown("##### Écriture comptable proposée")
    if entry is None:
        st.info("Impossible de proposer une écriture : total, sous-total et lignes sont tous vides.")
    else:
        entry_df = pd.DataFrame(entry)[["account", "label", "debit", "credit"]]
        entry_df.columns = ["Compte", "Libellé", "Débit", "Crédit"]
        st.dataframe(
            entry_df, width='stretch', hide_index=True,
            column_config={
                "Débit": st.column_config.NumberColumn(format="%.0f"),
                "Crédit": st.column_config.NumberColumn(format="%.0f"),
            },
        )
        total_debit = entry_df["Débit"].sum()
        total_credit = entry_df["Crédit"].sum()
        st.caption(f"Total débit : {money(total_debit)}  ·  Total crédit : {money(total_credit)}  ·  "
                   f"{'✅ équilibré' if balanced else '❌ déséquilibré'}")
        if recoverable == 0 and result["tax"]:
            st.warning(f"⚠️ TVA non récupérable — {reason}. Elle est réintégrée dans la charge.")

    with st.expander("Voir le JSON brut"):
        st.json(result["raw_json"])

    if st.button("✅ Valider et enregistrer dans les dépenses", type="primary", disabled=entry is None):
        st.session_state.manual_entries.append({
            "items": result["items"], "subtotal": result["subtotal"], "tax": result["tax"],
            "total": result["total"], "category": result["category"], "entry": entry,
        })
        st.session_state.current_result = None
        st.session_state.upload_key_version += 1   # repartir d'un uploader vide
        st.toast("✅ Écriture enregistrée dans les dépenses")
        st.rerun()


def render_analyze_tab(receipts):
    header_left, header_right = st.columns(2)
    with header_left:
        st.session_state.country = st.selectbox(
            "Pays", options=list(COUNTRY_LABELS), format_func=lambda c: COUNTRY_LABELS[c],
            index=list(COUNTRY_LABELS).index(st.session_state.country),
        )
    with header_right:
        st.session_state.payment_mode = st.selectbox(
            "Mode de paiement", options=list(PAYMENT_LABELS), format_func=lambda m: PAYMENT_LABELS[m],
            index=list(PAYMENT_LABELS).index(st.session_state.payment_mode),
        )

    if st.session_state.analyze_error:
        render_analyze_error()
    elif st.session_state.current_result is not None:
        render_analyze_result(receipts)
    else:
        render_analyze_empty(receipts)


# ---------------------------------------------------------------------------
# Onglet 2 : Tableau de bord
# ---------------------------------------------------------------------------
def render_receipt_detail(receipts, items, receipt_id):
    row = receipts[receipts["receipt_id"] == receipt_id]
    if row.empty:
        return
    row = row.iloc[0]
    st.markdown(f"#### Reçu #{receipt_id}")
    edit_mode = st.toggle("Éditer", key=f"edit_{receipt_id}")
    receipt_items = items[items["receipt_id"] == receipt_id] if "receipt_id" in items.columns else pd.DataFrame()

    c1, c2, c3 = st.columns(3)
    c1.metric("Sous-total", money(row.get("subtotal")))
    c2.metric("Taxe", money(row.get("tax")))
    c3.metric("Total", money(row.get("total")))

    if edit_mode:
        st.data_editor(receipt_items, num_rows="dynamic", width='stretch', key=f"items_edit_{receipt_id}")
        st.caption("Les modifications ici sont visuelles pour cette session (pas encore réécrites sur disque).")
    else:
        st.dataframe(receipt_items, width='stretch', hide_index=True)

    if st.button("Fermer le détail", key=f"close_{receipt_id}"):
        st.session_state.selected_receipt_id = None
        st.rerun()
    st.divider()


def _failing_rule(row):
    """Identifie QUELLE regle a echoue en premier (line_sum > total > taxe),
    et les deux valeurs a comparer pour l'expliquer. Reutilise pour le libelle
    court (liste des anomalies) et le detail arithmetique complet."""
    if row.get("line_sum_ok") is False:
        return "Somme des lignes ≠ sous-total", "Somme des lignes", row.get("items_sum"), "Sous-total déclaré", row.get("subtotal")
    if row.get("total_ok") is False:
        subtotal_plus_tax = (row.get("subtotal") or 0) + (row.get("tax") or 0)
        return "Sous-total + taxe ≠ total", "Sous-total + taxe", subtotal_plus_tax, "Total déclaré", row.get("total")
    if row.get("tax_ok") is False:
        return "Taux de taxe suspect", "Taxe déclarée", row.get("tax"), "Sous-total déclaré", row.get("subtotal")
    return "Anomalie non classée", None, None, None, None


def render_anomaly_detail(receipts, receipt_id):
    row = receipts[receipts["receipt_id"] == receipt_id]
    if row.empty:
        return
    row = row.iloc[0]
    st.markdown(f"#### Anomalie — Reçu #{receipt_id}")

    règle, label_a, val_a, label_b, val_b = _failing_rule(row)
    st.caption(règle)
    if (val_a is not None and val_b not in (None, 0)
            and not pd.isna(val_a) and not pd.isna(val_b)):
        ecart = val_b - val_a
        pct = abs(ecart) / val_b * 100
        st.markdown(
            f"**{label_a} :** {money(val_a)} · **{label_b} :** {money(val_b)} · "
            f"**Écart :** {money(abs(ecart))} ({pct:.1f}%)"
        )
    else:
        st.caption("Données insuffisantes pour calculer l'écart précis.")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Corriger ce reçu", key=f"fix_{receipt_id}"):
            st.session_state.selected_receipt_id = receipt_id
            st.session_state.selected_anomaly_id = None
            st.rerun()
    with col2:
        justification = st.text_input("Justification de l'acceptation", key=f"just_{receipt_id}")
        if st.button("Accepter tel quel", key=f"accept_{receipt_id}", disabled=not justification):
            st.toast(f"Reçu #{receipt_id} accepté : {justification}")
            st.session_state.selected_anomaly_id = None
            st.rerun()
    if st.button("Fermer", key=f"close_anomaly_{receipt_id}"):
        st.session_state.selected_anomaly_id = None
        st.rerun()
    st.divider()


def render_dashboard_tab(items, receipts):
    if receipts.empty:
        st.info("Aucun reçu analysé pour l'instant. Rendez-vous dans l'onglet **Analyser** pour commencer.")
        return

    n_anomalies = int(receipts["anomaly"].sum()) if "anomaly" in receipts.columns else 0
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Reçus analysés", len(receipts))
    c2.metric("Articles", len(items))
    c3.metric("Dépense totale", money(receipts["total"].sum()))
    c4.metric("Anomalies", n_anomalies, delta="à revoir" if n_anomalies else None,
              delta_color="inverse" if n_anomalies else "off")

    if st.session_state.selected_receipt_id is not None:
        render_receipt_detail(receipts, items, st.session_state.selected_receipt_id)
    if st.session_state.selected_anomaly_id is not None:
        render_anomaly_detail(receipts, st.session_state.selected_anomaly_id)

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("##### Dépenses par catégorie")
        if "category" in items.columns:
            dep = items.groupby("category")["line_price"].sum().sort_values()
            st.bar_chart(dep)
        else:
            st.caption("Catégories non disponibles (nécessite le clustering du notebook 04).")
    with col_b:
        st.markdown("##### Répartition des montants")
        st.bar_chart(receipts["total"].dropna())

    if n_anomalies:
        st.markdown("##### Anomalies actives")
        for _, row in receipts[receipts["anomaly"] == True].iterrows():  # noqa: E712
            rid = int(row["receipt_id"])
            with st.container(border=True):
                left, right = st.columns([3, 1])
                with left:
                    règle, label_a, val_a, label_b, val_b = _failing_rule(row)
                    st.markdown(f"**Reçu #{rid}** — {règle}")
                    if label_a:
                        st.caption(f"{label_a} : {money(val_a)}  ·  {label_b} : {money(val_b)}")
                with right:
                    if st.button("Voir le détail", key=f"anomaly_btn_{rid}"):
                        st.session_state.selected_anomaly_id = rid
                        st.rerun()

    st.markdown("##### Tous les reçus")
    search = st.text_input("Filtrer (catégorie, id...)", "")
    table = receipts.copy()
    if search:
        mask = table.astype(str).apply(lambda col: col.str.contains(search, case=False, na=False)).any(axis=1)
        table = table[mask]
    st.dataframe(table, width='stretch', hide_index=True)
    st.download_button("Télécharger (CSV)", data=table.to_csv(index=False).encode("utf-8"),
                        file_name="receipts_filtered.csv", mime="text/csv")


# ---------------------------------------------------------------------------
# Onglet 3 : Comptabilite
# ---------------------------------------------------------------------------
def render_accounting_tab(receipts):
    if receipts.empty:
        st.info("Aucun reçu à comptabiliser pour l'instant.")
        return

    period = st.selectbox("Période", ["Mois en cours", "Trimestre en cours", "Personnalisée"])

    vat_records = []
    all_entries = []
    for _, row in receipts.iterrows():
        merchant = _nan_to_none(row.get("merchant"))
        r = Receipt(
            items=[], subtotal=_nan_to_none(row.get("subtotal")), tax=_nan_to_none(row.get("tax")),
            total=_nan_to_none(row.get("total")), receipt_id=row["receipt_id"],
        )
        recoverable, reason = vat_recoverable(r, merchant=merchant)
        vat_records.append({"tax": r.tax or 0, "recoverable": recoverable, "reason": reason})
        try:
            entry = journal_entry(
                r, category=_nan_to_none(row.get("category")), payment_mode=st.session_state.payment_mode,
                country=st.session_state.country, merchant=merchant,
            )
            for line in entry:
                line["receipt_id"] = row["receipt_id"]
            all_entries.append((row["receipt_id"], entry))
        except ValueError:
            continue

    summary = vat_summary(vat_records)
    st.markdown(f"##### TVA — {period}")
    col_rec, col_non = st.columns(2)
    with col_rec:
        st.metric("Récupérable", money(summary["recoverable_total"]))
    with col_non:
        st.metric("Non récupérable", money(summary["non_recoverable_total"]))
        for reason, detail in summary["non_recoverable_reasons"].items():
            st.caption(f"• {reason} : {detail['count']} reçu(s), {money(detail['amount'])}")

    report = expense_report(receipts, period)
    st.markdown("##### Note de frais agrégée")
    c1, c2, c3 = st.columns(3)
    c1.metric("Total HT", money(report["total_ht"]))
    c2.metric("Total TVA", money(report["total_tax"]))
    c3.metric("Total TTC", money(report["total_ttc"]))

    st.markdown("##### Journal général, groupé par reçu")
    flat_entries = []
    for rid, entry in all_entries:
        balanced = is_balanced(entry)
        for line in entry:
            flat_entries.append({**line, "équilibré": "✅" if balanced else "❌"})
    if flat_entries:
        journal_df = pd.DataFrame(flat_entries)[["receipt_id", "account", "label", "debit", "credit", "équilibré"]]
        journal_df.columns = ["Reçu", "Compte", "Libellé", "Débit", "Crédit", "Équilibré"]

        def highlight_unbalanced(row):
            color = "background-color: #FFDAD6" if row["Équilibré"] == "❌" else ""
            return [color] * len(row)

        st.dataframe(
            journal_df.style.apply(highlight_unbalanced, axis=1),
            width='stretch', hide_index=True,
        )
        with st.expander("Exporter le journal"):
            fmt = st.radio("Format", ["CSV"], horizontal=True)
            filename = st.text_input("Nom de fichier", "journal_comptable.csv")
            st.download_button(
                "📥 Télécharger", data=journal_df.to_csv(index=False).encode("utf-8"),
                file_name=filename or "journal_comptable.csv", mime="text/csv",
            )
    else:
        st.caption("Pas assez de données pour construire le journal.")

    st.caption(f"ℹ️ {DISCLAIMER}")


# ---------------------------------------------------------------------------
# Onglet 4 : Questions
# ---------------------------------------------------------------------------
SUGGESTED_QUESTIONS = [
    "Combien ai-je dépensé en boissons ?",
    "Montre-moi les reçus de plus de 100 000",
    "Quel est le total du dernier trimestre ?",
]


def _fill_question(text):
    st.session_state.question_input = text
    st.session_state.trigger_search = True


def render_ask_tab(summaries):
    st.markdown("### Interroger l'historique de dépenses")
    question = st.text_input("Votre question", key="question_input", placeholder="Ex. : combien ai-je dépensé en transport ce mois-ci ?")

    chip_cols = st.columns(len(SUGGESTED_QUESTIONS))
    for col, suggestion in zip(chip_cols, SUGGESTED_QUESTIONS):
        col.button(suggestion, key=f"suggest_{suggestion}", on_click=_fill_question, args=(suggestion,))

    do_search = st.button("Chercher", type="primary") or st.session_state.pop("trigger_search", False)
    if do_search and question:
        encoder, index = load_search_index(tuple(summaries))
        if encoder is None:
            st.warning("⚠️ Recherche sémantique indisponible (FAISS / sentence-transformers non installés ou "
                       "modèle inaccessible). Vérifiez `requirements.txt` et votre connexion.")
        else:
            from src.semantic import search
            results = search(question, encoder, index, summaries, k=5)

            llm_answer = None
            if results and st.session_state.groq_api_key:
                try:
                    _init_groq(st.session_state.groq_api_key)
                    from src.llm import answer_question
                    llm_answer = answer_question(question, [texte for texte, _ in results])
                except Exception:
                    llm_answer = None   # degradation gracieuse : on retombe sur la reponse-gabarit

            with st.container(border=True):
                st.markdown("**Réponse**")
                if llm_answer:
                    st.write(llm_answer)
                elif results:
                    st.write(f"D'après les reçus les plus pertinents, voici ce que je trouve pour : *{question}*")
                    if st.session_state.groq_api_key:
                        st.caption("⚠️ Génération LLM indisponible pour l'instant — réponse basée sur les sources seules.")
                else:
                    st.write("Aucun reçu pertinent trouvé.")

            st.markdown("##### Reçus sources (fondent la réponse — principe du RAG)")
            for texte, score in results:
                with st.container(border=True):
                    st.progress(min(max(score, 0.0), 1.0), text=f"Pertinence {score:.0%}")
                    st.write(texte)

            st.session_state.qa_history.insert(0, question)

    if st.session_state.qa_history:
        st.markdown("##### Questions précédentes")
        for q in st.session_state.qa_history[:10]:
            st.caption(f"• {q}")


# ---------------------------------------------------------------------------
# Onglet 5 : Technique
# ---------------------------------------------------------------------------
def render_technical_tab():
    st.markdown("### Donut vs baseline")
    try:
        results = pd.read_csv("data/results.csv")
        st.caption("Source : data/results.csv")
        st.dataframe(
            results, width='stretch', hide_index=True,
            column_config={
                "modele": "Modèle",
                "exactitude_total": st.column_config.NumberColumn("Exactitude totale", format="percent"),
                "json_valide": st.column_config.NumberColumn("JSON valide", format="percent"),
                "entraine_par_moi": "Entraîné par moi",
            },
        )
    except FileNotFoundError:
        st.caption("data/results.csv absent — lancez evaluate.py (notebook 04) pour générer les résultats réels.")

    st.markdown("### Sur-apprentissage (baseline maison)")
    try:
        overfitting = pd.read_csv("data/overfitting.csv")
        st.caption("Source : data/overfitting.csv")
        sans_regul = overfitting.iloc[0]
        avec_regul = overfitting.iloc[-1]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Écart sans régularisation", f"{sans_regul['ecart']:.1%}")
        c2.metric("Écart avec régularisation", f"{avec_regul['ecart']:.1%}",
                  delta=f"{(avec_regul['ecart'] - sans_regul['ecart']):.1%}", delta_color="inverse")
        c3.metric("Train accuracy (régularisé)", f"{avec_regul['train']:.1%}")
        c4.metric("Val accuracy (régularisé)", f"{avec_regul['validation']:.1%}")
        st.dataframe(overfitting, width='stretch', hide_index=True)
    except FileNotFoundError:
        st.caption("data/overfitting.csv absent.")

    st.markdown("##### Courbe de perte (entraînement baseline)")
    try:
        loss_curve = pd.read_csv("data/loss_curve.csv")
        st.caption("Source : data/loss_curve.csv")
        st.line_chart(loss_curve.set_index("iteration")["loss"])
    except FileNotFoundError:
        st.caption("data/loss_curve.csv absent.")

    with st.container(border=True):
        st.markdown("##### Méthodologie : drapeau binaire plutôt que pourcentage de confiance")
        st.markdown(
            "Un champ est marqué **« à vérifier »** (booléen) s'il est absent, nul, ou s'il fait échouer une "
            "règle de contrôle. Nous n'affichons **volontairement aucun pourcentage de confiance** : un score "
            "comme « 85% » laisse croire à une fiabilité mesurée, alors qu'il ne reflète souvent que la "
            "confiance interne du modèle — pas l'exactitude réelle du champ. Le binaire évite ce faux sentiment "
            "de certitude et pousse à la vérification humaine quand le doute existe."
        )


# ---------------------------------------------------------------------------
# Point d'entree
# ---------------------------------------------------------------------------
def main():
    items, receipts, summaries = load_data()
    render_settings_sidebar(receipts)

    st.title("🧾 Copilote de reçus et dépenses")
    st.caption("Extraction automatique · vérification comptable · recherche sémantique")

    tab_analyze, tab_dashboard, tab_accounting, tab_ask, tab_technical = st.tabs(
        ["Analyser", "Tableau de bord", "Comptabilité", "Questions", "Technique"]
    )
    with tab_analyze:
        render_analyze_tab(receipts)
    with tab_dashboard:
        render_dashboard_tab(items, receipts)
    with tab_accounting:
        render_accounting_tab(receipts)
    with tab_ask:
        render_ask_tab(summaries)
    with tab_technical:
        render_technical_tab()


main()
