"""Cloisonnement des donnees par session utilisateur (EN MEMOIRE uniquement).

Les CSV de data/ sont un CORPUS DE REFERENCE (CORD) : entrainement, evaluation,
clustering KMeans, index FAISS de reference. Ce ne sont PAS les depenses de
l'utilisateur. Ce module tient les recus que l'utilisateur depose et valide
pendant SA session ; le tableau de bord, la comptabilite et les questions
lisent ces donnees-la. Aucune ecriture disque : un correcteur qui clone
n'herite jamais des recus d'un autre.

Prevu pour l'authentification future : chaque UserSession porte un `user_id`
(None pour l'instant). Le jour ou l'auth arrive, il suffira de keyer le
registre sur `user_id` au lieu du `session_id` -- voir get_session() -- sans
toucher au reste du code.
"""
import math

import numpy as np
import pandas as pd

from src.receipt import Receipt
from src.accounting import (
    journal_entry, is_balanced, vat_recoverable, vat_summary, expense_report,
    DISCLAIMER,
)

RECEIPT_COLUMNS = ["receipt_id", "n_items", "items_sum", "subtotal", "tax",
                   "total", "line_sum_ok", "total_ok", "tax_ok", "anomaly",
                   "category", "merchant"]
ITEM_COLUMNS = ["receipt_id", "name", "quantity", "unit_price", "line_price", "category"]


def _nan(value):
    """NaN pandas / None -> None (NaN est truthy et casserait la logique 3 etats)."""
    return None if value is None or (isinstance(value, float) and math.isnan(value)) else value


def _is_false(value):
    return value is False or value == False  # noqa: E712  (couvre numpy.bool_)


def _failing_rule(row):
    """Quelle regle a echoue en premier + les deux valeurs a comparer.
    Meme logique que l'affichage du front, pour rester coherent."""
    if _is_false(row.get("line_sum_ok")):
        return ("Somme des lignes ≠ sous-total", "Somme des lignes",
                _nan(row.get("items_sum")), "Sous-total déclaré", _nan(row.get("subtotal")))
    if _is_false(row.get("total_ok")):
        subtotal_plus_tax = (_nan(row.get("subtotal")) or 0) + (_nan(row.get("tax")) or 0)
        return ("Sous-total + taxe ≠ total", "Sous-total + taxe",
                subtotal_plus_tax, "Total déclaré", _nan(row.get("total")))
    if _is_false(row.get("tax_ok")):
        return ("Taux de taxe suspect", "Taxe déclarée",
                _nan(row.get("tax")), "Sous-total déclaré", _nan(row.get("subtotal")))
    return ("Anomalie non classée", None, None, None, None)


class UserSession:
    """Les recus deposes/valides par UN utilisateur pendant SA session."""

    def __init__(self, session_id, user_id=None):
        self.session_id = session_id
        self.user_id = user_id           # reserve pour l'auth future (None pour l'instant)
        self.receipts = []               # list[dict], schema RECEIPT_COLUMNS
        self.items = []                  # list[dict], schema ITEM_COLUMNS
        self.demo_mode = False
        self._next_id = 0

    # -- etat -----------------------------------------------------------------
    def is_empty(self):
        return not self.receipts

    def clear(self):
        self.receipts, self.items = [], []
        self.demo_mode = False
        self._next_id = 0

    # -- ecriture (memoire seule) --------------------------------------------
    def add_receipt(self, receipt, category, flags, merchant=None):
        """Ajoute un recu valide a la session. Renvoie son id local."""
        rid = self._next_id
        self._next_id += 1
        for it in receipt.items:
            self.items.append({
                "receipt_id": rid, "name": it.get("name"), "quantity": it.get("quantity"),
                "unit_price": it.get("unit_price"), "line_price": it.get("line_price"),
                "category": category,
            })
        self.receipts.append({
            "receipt_id": rid, "n_items": len(receipt.items),
            "items_sum": receipt.items_sum(), "subtotal": receipt.subtotal,
            "tax": receipt.tax, "total": receipt.total,
            "line_sum_ok": flags["line_sum_ok"], "total_ok": flags["total_ok"],
            "tax_ok": flags["tax_ok"], "anomaly": flags["anomaly"],
            "category": category, "merchant": merchant,
        })
        return rid

    def load_demo(self, receipts, items):
        """MODE DEMONSTRATION : peuple la session avec un corpus (copie
        defensive) et active le drapeau demo. Les donnees restent en memoire."""
        self.clear()
        self.receipts = [dict(r) for r in receipts]
        self.items = [dict(i) for i in items]
        self.demo_mode = True
        self._next_id = max((int(r["receipt_id"]) for r in self.receipts), default=-1) + 1

    # -- DataFrames -----------------------------------------------------------
    def receipts_df(self):
        return pd.DataFrame(self.receipts, columns=RECEIPT_COLUMNS)

    def items_df(self):
        return pd.DataFrame(self.items, columns=ITEM_COLUMNS)

    # -- lectures agregees ----------------------------------------------------
    def get_dashboard_data(self):
        receipts = self.receipts_df()
        items = self.items_df()
        if receipts.empty:
            return {"empty": True}

        n_anomalies = int(receipts["anomaly"].fillna(False).astype(bool).sum())
        kpis = {
            "n_receipts": int(len(receipts)),
            "n_items": int(len(items)),
            "total_spend": float(receipts["total"].fillna(0).sum()),
            "n_anomalies": n_anomalies,
        }

        by_category = []
        if not items.empty and "category" in items.columns:
            grouped = items.groupby("category")["line_price"].sum().sort_values(ascending=False)
            by_category = [{"category": str(c), "total": float(v)} for c, v in grouped.items()]

        totals = receipts["total"].dropna().to_numpy()
        distribution = []
        if len(totals):
            counts, edges = np.histogram(totals, bins=10)
            distribution = [{"range": f"{int(edges[i]):,}–{int(edges[i + 1]):,}".replace(",", " "),
                             "count": int(counts[i])} for i in range(len(counts))]

        anomalies = []
        if n_anomalies:
            flagged = receipts[receipts["anomaly"].fillna(False).astype(bool)]
            for _, row in flagged.iterrows():
                rule, la, va, lb, vb = _failing_rule(row)
                anomalies.append({"receipt_id": int(row["receipt_id"]), "rule": rule,
                                  "a_label": la, "a_value": va, "b_label": lb, "b_value": vb})

        return {"empty": False, "kpis": kpis, "by_category": by_category,
                "distribution": distribution, "anomalies": anomalies}

    def get_accounting_data(self, period, payment_mode, country):
        receipts = self.receipts_df()
        if receipts.empty:
            return {"empty": True}

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
                journal_groups.append({"receipt_id": int(row["receipt_id"]),
                                       "balanced": is_balanced(entry), "lines": entry})
            except (ValueError, KeyError):
                continue

        return {"empty": False, "period": period, "vat": vat_summary(vat_records),
                "report": expense_report(receipts, period), "journal": journal_groups,
                "disclaimer": DISCLAIMER}

    def search_texts(self):
        """Un resume textuel par recu utilisateur, pour la recherche semantique."""
        names_by_id = {}
        for it in self.items:
            names_by_id.setdefault(it["receipt_id"], []).append(it.get("name") or "")
        texts = []
        for r in self.receipts:
            parts = [f"Reçu #{r['receipt_id']}"]
            names = ", ".join(n for n in names_by_id.get(r["receipt_id"], []) if n)
            if names:
                parts.append(f"articles : {names}")
            parts.append(f"catégorie : {r.get('category') or 'non catégorisé'}")
            total = _nan(r.get("total"))
            if total is not None:
                parts.append(f"total : {int(total)}")
            texts.append(" — ".join(parts))
        return texts


# ---------------------------------------------------------------------------
# Registre des sessions (memoire de processus)
# ---------------------------------------------------------------------------
_sessions = {}   # session_id -> UserSession


def get_session(session_id, user_id=None):
    """Recupere (ou cree) la session. AUTH FUTURE : quand un user_id existera,
    keyer `_sessions` sur user_id ici -- le reste du code passe deja par cette
    fonction, donc rien d'autre a changer."""
    session = _sessions.get(session_id)
    if session is None:
        session = UserSession(session_id, user_id=user_id)
        _sessions[session_id] = session
    return session


def drop_session(session_id):
    _sessions.pop(session_id, None)


def reset_all():
    """Vide tout le registre (utilise par les tests)."""
    _sessions.clear()
