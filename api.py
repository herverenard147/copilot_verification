"""API FastAPI du Copilote de recus.

Endpoints MINCES : ils appellent le backend existant (src/) et renvoient du
JSON. Aucune logique metier n'est reecrite ici -- extraction (Donut), regles,
comptabilite, recherche vivent dans src/. L'API ne fait qu'exposer, orchestrer
le fallback vision, et servir le front statique de web/.

Lancer :  uvicorn api:app --reload
"""
import io
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel

from src.receipt import Receipt
from src.rules import audit, TAX_RATES
from src.accounting import (
    journal_entry, is_balanced, vat_recoverable, vat_summary, expense_report,
    DISCLAIMER, CHART_OF_ACCOUNTS, PAYMENT_ACCOUNTS,
)
from src.preprocess import preprocess_image
from src.extractor import extract
from src.llm import extract_receipt_via_vision

DATA = Path("data")
WEB = Path("web")

app = FastAPI(title="Copilote de reçus — API")

# ---------------------------------------------------------------------------
# Ressources lourdes en chargement PARESSEUX (jamais au demarrage)
# ---------------------------------------------------------------------------
_donut = None            # (processor, model, device)
_search = None           # (encoder, index, summaries)


def get_donut():
    """Charge Donut (~800 Mo) une seule fois, au premier /api/extract."""
    global _donut
    if _donut is None:
        import torch
        from transformers import DonutProcessor, VisionEncoderDecoderModel
        name = "naver-clova-ix/donut-base-finetuned-cord-v2"
        processor = DonutProcessor.from_pretrained(name)
        model = VisionEncoderDecoderModel.from_pretrained(name)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _donut = (processor, model.to(device), device)
    return _donut


def get_search():
    """Construit l'index FAISS une fois. Renvoie (None, None, summaries) si
    FAISS / sentence-transformers indisponibles (degradation gracieuse)."""
    global _search
    if _search is None:
        summaries = _load_summaries()
        try:
            from src.semantic import get_encoder, embed, build_index
            encoder = get_encoder()
            index = build_index(embed(summaries, encoder))
            _search = (encoder, index, summaries)
        except Exception:
            _search = (None, None, summaries)
    return _search


# ---------------------------------------------------------------------------
# Donnees (CSV reels) + utilitaires JSON
# ---------------------------------------------------------------------------
def _load_summaries():
    try:
        import json
        with open(DATA / "summaries.json", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def load_items():
    try:
        return pd.read_csv(DATA / "items.csv")
    except FileNotFoundError:
        return pd.DataFrame(columns=["receipt_id", "name", "quantity", "unit_price", "line_price", "category"])


def load_receipts():
    """Charge receipts.csv et enrichit d'une categorie dominante par recu
    (deduite de items.csv) si la colonne n'existe pas -- necessaire au mapping
    categorie -> compte de l'onglet Comptabilite."""
    try:
        receipts = pd.read_csv(DATA / "receipts.csv")
    except FileNotFoundError:
        return pd.DataFrame(columns=["receipt_id", "n_items", "items_sum", "subtotal",
                                      "tax", "total", "line_sum_ok", "total_ok",
                                      "tax_ok", "anomaly", "category"])
    if "category" not in receipts.columns:
        items = load_items()
        if "category" in items.columns:
            dominant = items.groupby("receipt_id")["category"].agg(
                lambda s: s.mode().iat[0] if not s.mode().empty else None)
            receipts = receipts.merge(dominant.rename("category"), on="receipt_id", how="left")
    return receipts


def to_jsonable(obj):
    """Rend un objet serialisable en JSON STRICT : NaN/NaT -> null, types numpy
    -> types Python. Sans ca, le JSON contiendrait des tokens `NaN` invalides
    que le navigateur refuse de parser."""
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return to_jsonable(obj.tolist())
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        obj = float(obj)
    if isinstance(obj, float):
        return None if math.isnan(obj) else obj
    if obj is pd.NaT or (obj is not None and obj is pd.NA):
        return None
    return obj


def ok(payload):
    return JSONResponse(to_jsonable(payload))


def error(message, status=400):
    """Erreur JSON propre, message humain, JAMAIS de traceback vers le front."""
    return JSONResponse({"error": message}, status_code=status)


def _nan(value):
    """Case CSV vide (NaN pandas) -> None (NaN est truthy et casse la logique
    a 3 etats des regles)."""
    return None if value is None or (isinstance(value, float) and math.isnan(value)) else value


def failing_rule(row):
    """Quelle regle a echoue en premier + les deux valeurs a comparer.
    Porte la meme logique que l'app Streamlit pour un affichage coherent."""
    if row.get("line_sum_ok") is False or row.get("line_sum_ok") == False:  # noqa: E712
        return ("Somme des lignes ≠ sous-total", "Somme des lignes",
                _nan(row.get("items_sum")), "Sous-total déclaré", _nan(row.get("subtotal")))
    if row.get("total_ok") is False or row.get("total_ok") == False:  # noqa: E712
        subtotal_plus_tax = (_nan(row.get("subtotal")) or 0) + (_nan(row.get("tax")) or 0)
        return ("Sous-total + taxe ≠ total", "Sous-total + taxe",
                subtotal_plus_tax, "Total déclaré", _nan(row.get("total")))
    if row.get("tax_ok") is False or row.get("tax_ok") == False:  # noqa: E712
        return ("Taux de taxe suspect", "Taxe déclarée",
                _nan(row.get("tax")), "Sous-total déclaré", _nan(row.get("subtotal")))
    return ("Anomalie non classée", None, None, None, None)


def build_receipt_bundle(receipt, country, payment_mode, merchant, category=None):
    """audit + ecriture + TVA a partir d'un Receipt. Coeur partage par
    /api/extract et /api/validate."""
    flags = audit(receipt, country=country)
    try:
        entry = journal_entry(receipt, category=category, payment_mode=payment_mode,
                              country=country, merchant=merchant)
        balanced = is_balanced(entry)
    except (ValueError, KeyError):
        entry, balanced = None, None
    recoverable, reason = vat_recoverable(receipt, merchant=merchant)
    return {
        "receipt": {
            "items": receipt.items,
            "subtotal": receipt.subtotal,
            "tax": receipt.tax,
            "total": receipt.total,
            "items_sum": receipt.items_sum(),
            "merchant": merchant,
        },
        "audit": flags,
        "journal": entry,
        "balanced": balanced,
        "vat": {"recoverable": recoverable, "reason": reason},
    }


# ---------------------------------------------------------------------------
# POST /api/extract
# ---------------------------------------------------------------------------
@app.post("/api/extract")
def api_extract(file: UploadFile = File(...), country: str = Form("CI"),
                payment_mode: str = Form("cash"), merchant: str = Form(None)):
    try:
        raw = file.file.read()
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception:
        return error("Image illisible. Vérifiez qu'il s'agit bien d'un JPG ou PNG valide.", 400)

    try:
        pre_img, pre_info = preprocess_image(image)
    except Exception:
        pre_img, pre_info = image.convert("RGB"), {"deskewed": False, "clahe": False}

    engine = "donut"
    fallback_note = None

    # 1) Donut (son domaine : reçus indonesiens CORD)
    try:
        processor, model, device = get_donut()
        prediction = extract(pre_img, model, processor, device)
    except Exception:
        prediction = {}
        fallback_note = "Donut indisponible (modèle non chargé)."
    receipt = Receipt.from_gt_parse(prediction)

    # 2) Fallback vision ASSUME : pays CI (hors domaine) OU sortie Donut vide
    donut_incoherent = (not receipt.items) and (not receipt.total)
    want_fallback = (country == "CI") or donut_incoherent
    if want_fallback and os.environ.get("GROQ_API_KEY"):
        try:
            vision_pred = extract_receipt_via_vision(pre_img)
            vision_receipt = Receipt.from_gt_parse(vision_pred)
            if vision_receipt.items or vision_receipt.total:
                prediction, receipt, engine = vision_pred, vision_receipt, "llm_fallback"
        except Exception:
            fallback_note = "Fallback vision indisponible (modèle ou quota Groq)."
    elif want_fallback:
        fallback_note = "Fallback vision non tenté : aucune clé GROQ_API_KEY configurée."

    bundle = build_receipt_bundle(receipt, country, payment_mode, _nan(merchant))
    bundle.update({
        "engine": engine,
        "fallback_note": fallback_note,
        "raw_json": prediction,
        "preprocess": pre_info,
        "country": country,
        "payment_mode": payment_mode,
    })
    return ok(bundle)


# ---------------------------------------------------------------------------
# POST /api/validate  (recalcul live si persist=false, ecriture CSV si true)
# ---------------------------------------------------------------------------
class ValidatePayload(BaseModel):
    items: list = []
    subtotal: float | None = None
    tax: float | None = None
    total: float | None = None
    category: str | None = None
    account: str | None = None          # compte choisi manuellement (selectbox du front)
    merchant: str | None = None
    country: str = "CI"
    payment_mode: str = "cash"
    persist: bool = True


@app.post("/api/validate")
def api_validate(payload: ValidatePayload):
    # normalise les articles recus du front
    items = []
    for it in payload.items:
        items.append({
            "name": it.get("name"),
            "quantity": it.get("quantity"),
            "unit_price": it.get("unit_price"),
            "line_price": it.get("line_price"),
        })
    receipt = Receipt(items=items, subtotal=payload.subtotal, tax=payload.tax,
                      total=payload.total)
    bundle = build_receipt_bundle(receipt, payload.country, payload.payment_mode,
                                  _nan(payload.merchant), category=payload.category)

    # compte reassigne manuellement : on remplace le compte de la ligne de charge
    # sans toucher aux montants (l'ecriture reste equilibree).
    if payload.account and bundle["journal"] and bundle["journal"][0]["account"] != payload.account:
        merchant_label = _nan(payload.merchant) or "fournisseur non identifié"
        label_account = CHART_OF_ACCOUNTS.get(payload.account, "Charge")
        bundle["journal"][0]["account"] = payload.account
        bundle["journal"][0]["label"] = f"{label_account} — {merchant_label}"

    bundle["persisted"] = False

    if payload.persist:
        try:
            new_id = _append_to_csv(receipt, payload.category, bundle["audit"])
            bundle["persisted"] = True
            bundle["receipt_id"] = new_id
        except Exception as exc:  # ne jamais renvoyer un traceback
            return error(f"Enregistrement impossible : {type(exc).__name__}. "
                         "Le reçu a été vérifié mais pas sauvegardé.", 500)
    return ok(bundle)


def _append_to_csv(receipt, category, flags):
    """Ajoute le recu valide a data/items.csv et data/receipts.csv."""
    receipts = load_receipts()
    items = load_items()
    new_id = int(receipts["receipt_id"].max()) + 1 if len(receipts) else 0

    item_rows = [{
        "receipt_id": new_id, "name": it.get("name"), "quantity": it.get("quantity"),
        "unit_price": it.get("unit_price"), "line_price": it.get("line_price"),
        "category": category,
    } for it in receipt.items]

    receipt_row = {
        "receipt_id": new_id, "n_items": len(receipt.items),
        "items_sum": receipt.items_sum(), "subtotal": receipt.subtotal,
        "tax": receipt.tax, "total": receipt.total,
        "line_sum_ok": flags["line_sum_ok"], "total_ok": flags["total_ok"],
        "tax_ok": flags["tax_ok"], "anomaly": flags["anomaly"], "category": category,
    }

    if item_rows:
        items = pd.concat([items, pd.DataFrame(item_rows)], ignore_index=True)
        items.to_csv(DATA / "items.csv", index=False)
    receipts = pd.concat([receipts, pd.DataFrame([receipt_row])], ignore_index=True)
    receipts.to_csv(DATA / "receipts.csv", index=False)
    return new_id


# ---------------------------------------------------------------------------
# GET /api/dashboard
# ---------------------------------------------------------------------------
@app.get("/api/dashboard")
def api_dashboard():
    receipts = load_receipts()
    items = load_items()
    if receipts.empty:
        return ok({"empty": True})

    n_anomalies = int(receipts["anomaly"].sum()) if "anomaly" in receipts.columns else 0
    kpis = {
        "n_receipts": int(len(receipts)),
        "n_items": int(len(items)),
        "total_spend": float(receipts["total"].fillna(0).sum()),
        "n_anomalies": n_anomalies,
    }

    by_category = []
    if "category" in items.columns:
        grouped = items.groupby("category")["line_price"].sum().sort_values(ascending=False)
        by_category = [{"category": str(c), "total": float(v)} for c, v in grouped.items()]

    totals = receipts["total"].dropna().to_numpy()
    distribution = []
    if len(totals):
        counts, edges = np.histogram(totals, bins=10)
        distribution = [{"range": f"{int(edges[i]):,}–{int(edges[i+1]):,}".replace(",", " "),
                         "count": int(counts[i])} for i in range(len(counts))]

    anomalies = []
    if n_anomalies:
        for _, row in receipts[receipts["anomaly"] == True].iterrows():  # noqa: E712
            rule, la, va, lb, vb = failing_rule(row)
            anomalies.append({
                "receipt_id": int(row["receipt_id"]), "rule": rule,
                "a_label": la, "a_value": va, "b_label": lb, "b_value": vb,
            })

    return ok({"empty": False, "kpis": kpis, "by_category": by_category,
               "distribution": distribution, "anomalies": anomalies})


# ---------------------------------------------------------------------------
# GET /api/accounting?period=
# ---------------------------------------------------------------------------
@app.get("/api/accounting")
def api_accounting(period: str = "Mois en cours", payment_mode: str = "cash", country: str = "CI"):
    receipts = load_receipts()
    if receipts.empty:
        return ok({"empty": True})

    vat_records, journal_groups = [], []
    for _, row in receipts.iterrows():
        merchant = _nan(row.get("merchant"))
        r = Receipt(items=[], subtotal=_nan(row.get("subtotal")), tax=_nan(row.get("tax")),
                    total=_nan(row.get("total")), receipt_id=row["receipt_id"])
        recoverable, reason = vat_recoverable(r, merchant=merchant)
        vat_records.append({"tax": r.tax or 0, "recoverable": recoverable, "reason": reason})
        try:
            entry = journal_entry(r, category=_nan(row.get("category")),
                                  payment_mode=payment_mode, country=country, merchant=merchant)
            journal_groups.append({
                "receipt_id": int(row["receipt_id"]),
                "balanced": is_balanced(entry),
                "lines": entry,
            })
        except (ValueError, KeyError):
            continue

    summary = vat_summary(vat_records)
    report = expense_report(receipts, period)
    return ok({"empty": False, "period": period, "vat": summary,
               "report": report, "journal": journal_groups, "disclaimer": DISCLAIMER})


# ---------------------------------------------------------------------------
# POST /api/search
# ---------------------------------------------------------------------------
class SearchPayload(BaseModel):
    question: str


@app.post("/api/search")
def api_search(payload: SearchPayload):
    question = (payload.question or "").strip()
    if not question:
        return error("Question vide.", 400)

    encoder, index, summaries = get_search()
    if encoder is None:
        return ok({"search_available": False, "llm_used": False, "answer": None,
                   "sources": [], "note": "Recherche sémantique indisponible "
                   "(FAISS / sentence-transformers non installés)."})

    from src.semantic import search
    results = search(question, encoder, index, summaries, k=5)
    sources = [{"text": t, "score": float(s)} for t, s in results]

    answer, llm_used = None, False
    if sources and os.environ.get("GROQ_API_KEY"):
        try:
            from src.llm import init_llm, answer_question
            init_llm(backend="groq", api_key=os.environ["GROQ_API_KEY"])
            answer = answer_question(question, [s["text"] for s in sources])
            llm_used = True
        except Exception:
            answer, llm_used = None, False   # degradation : sources seules

    return ok({"search_available": True, "llm_used": llm_used,
               "answer": answer, "sources": sources})


# ---------------------------------------------------------------------------
# GET /api/technical
# ---------------------------------------------------------------------------
def _csv_records(name):
    try:
        return pd.read_csv(DATA / name).to_dict("records")
    except FileNotFoundError:
        return []


@app.get("/api/technical")
def api_technical():
    return ok({
        "results": _csv_records("results.csv"),
        "overfitting": _csv_records("overfitting.csv"),
        "loss_curve": _csv_records("loss_curve.csv"),
    })


# ---------------------------------------------------------------------------
# GET /api/config  (le front s'auto-configure : pays, comptes, dispo Groq)
# ---------------------------------------------------------------------------
@app.get("/api/config")
def api_config():
    return ok({
        "countries": {c: TAX_RATES[c] for c in TAX_RATES},
        "payment_modes": list(PAYMENT_ACCOUNTS.keys()),
        "chart_of_accounts": CHART_OF_ACCOUNTS,
        "groq_configured": bool(os.environ.get("GROQ_API_KEY")),
        "disclaimer": DISCLAIMER,
    })


# ---------------------------------------------------------------------------
# Filet de securite : toute erreur non geree -> JSON, jamais un traceback HTML
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def any_error(request, exc):
    return JSONResponse({"error": "Erreur interne. Réessayez ; si le problème "
                         "persiste, vérifiez les logs du serveur."}, status_code=500)


# ---------------------------------------------------------------------------
# Front statique (monte en DERNIER pour ne pas masquer /api/*)
# ---------------------------------------------------------------------------
if WEB.exists():
    app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
