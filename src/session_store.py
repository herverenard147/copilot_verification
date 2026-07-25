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

PERSISTANCE LEGERE (optionnelle) : si init_persistence(path) est appele (par
api.py au demarrage d'un vrai serveur), les reçus valides sont sauvegardes dans
un fichier JSON HORS DEPOT (.local_state/), et recharges au demarrage suivant.
JAMAIS dans data/*.csv (corpus CORD intouchable). Le mode demo n'est pas
persiste. Sans init_persistence (ex. tests via TestClient sans context manager),
aucune I/O disque -- comportement historique.
"""
import json
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


def _flag(value):
    """Drapeau de controle -> True / False / None (gere le NaN pandas et numpy).
    Pur formatage d'affichage : aucun calcul, aucun seuil modifie."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return bool(value)


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
        _save()   # persiste l'etat vidé (retire cette session du fichier)

    # -- ecriture (memoire seule) --------------------------------------------
    def add_receipt(self, receipt, category, flags, merchant=None):
        """Ajoute un recu valide a la session. Renvoie son id local."""
        rid = self._next_id
        self._next_id += 1
        for it in receipt.items:
            self.items.append({
                "receipt_id": rid, "name": it.get("name"), "quantity": it.get("quantity"),
                "unit_price": it.get("unit_price"), "line_price": it.get("line_price"),
                # categorie PAR article si presente, sinon celle du recu (retro-compat)
                "category": it.get("category") or category,
            })
        self.receipts.append({
            "receipt_id": rid, "n_items": len(receipt.items),
            "items_sum": receipt.items_sum(), "subtotal": receipt.subtotal,
            "tax": receipt.tax, "total": receipt.total,
            "line_sum_ok": flags["line_sum_ok"], "total_ok": flags["total_ok"],
            "tax_ok": flags["tax_ok"], "anomaly": flags["anomaly"],
            "category": category, "merchant": merchant,
        })
        _save()   # persiste apres chaque reçu validé (si la persistance est active)
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

        receipts_list = [{
            "receipt_id": int(r["receipt_id"]),
            "category": r.get("category"),
            "total": _nan(r.get("total")),
            "n_items": int(r.get("n_items") or 0),
            "anomaly": bool(r.get("anomaly")) if r.get("anomaly") is not None else False,
            # drapeaux de controle EXPOSES pour l'affichage (badge "N points a
            # verifier") -- pur formatage, aucun calcul ni seuil touche.
            "line_sum_ok": _flag(r.get("line_sum_ok")),
            "total_ok": _flag(r.get("total_ok")),
            "tax_ok": _flag(r.get("tax_ok")),
        } for r in self.receipts]

        return {"empty": False, "kpis": kpis, "by_category": by_category,
                "distribution": distribution, "anomalies": anomalies,
                "receipts": receipts_list}

    def get_receipt(self, receipt_id):
        """Ligne de recu + ses articles (pour l'ecran de detail). (None, []) si absent."""
        rid = int(receipt_id)
        row = next((r for r in self.receipts if int(r["receipt_id"]) == rid), None)
        if row is None:
            return None, []
        items = [it for it in self.items if int(it["receipt_id"]) == rid]
        return row, items

    def get_accounting_data(self, period, payment_mode, country):
        receipts = self.receipts_df()
        if receipts.empty:
            return {"empty": True}

        # articles par recu (avec leur categorie individuelle) pour l'ecriture
        # multi-comptes -- voir journal_entry / _charge_lines.
        items_by_id = {}
        for it in self.items:
            items_by_id.setdefault(int(it["receipt_id"]), []).append({
                "name": it.get("name"), "quantity": it.get("quantity"),
                "unit_price": it.get("unit_price"), "line_price": _nan(it.get("line_price")),
                "category": _nan(it.get("category")),
            })

        vat_records, journal_groups, receipts_list = [], [], []
        for _, row in receipts.iterrows():
            rid = int(row["receipt_id"])
            merchant = _nan(row.get("merchant"))
            r = Receipt(items=items_by_id.get(rid, []),
                        subtotal=_nan(row.get("subtotal")), tax=_nan(row.get("tax")),
                        total=_nan(row.get("total")), receipt_id=rid)
            recoverable, reason = vat_recoverable(r, merchant=merchant)
            vat_records.append({"tax": r.tax or 0, "recoverable": recoverable, "reason": reason})
            # Résumé cliquable + motif TVA, pour filtrer la liste par motif.
            receipts_list.append({
                "receipt_id": rid, "category": _nan(row.get("category")),
                "total": _nan(row.get("total")), "n_items": int(row.get("n_items") or 0),
                "anomaly": bool(row.get("anomaly")) if row.get("anomaly") is not None else False,
                "line_sum_ok": _flag(row.get("line_sum_ok")),
                "total_ok": _flag(row.get("total_ok")),
                "tax_ok": _flag(row.get("tax_ok")),
                "vat_reason": reason,
            })
            try:
                entry = journal_entry(r, category=_nan(row.get("category")),
                                      payment_mode=payment_mode, country=country, merchant=merchant)
                journal_groups.append({"receipt_id": rid,
                                       "balanced": is_balanced(entry), "lines": entry})
            except (ValueError, KeyError):
                continue

        return {"empty": False, "period": period, "vat": vat_summary(vat_records),
                "report": expense_report(receipts, period), "journal": journal_groups,
                "receipts": receipts_list, "disclaimer": DISCLAIMER}

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
    _save()


def reset_all():
    """Vide tout le registre (utilise par les tests). Ne touche pas au fichier."""
    _sessions.clear()


# ---------------------------------------------------------------------------
# Persistance legere HORS DEPOT (jamais data/*.csv). Desactivee par defaut :
# seul init_persistence() l'active (api.py au demarrage d'un vrai serveur).
# ---------------------------------------------------------------------------
from pathlib import Path   # noqa: E402  (import local a la persistance)

_state_file = None         # None = persistance desactivee (defaut, tests inclus)


def init_persistence(path):
    """Active la persistance vers `path` (hors depot) et recharge l'etat
    existant. Idempotent. Fichier absent/corrompu -> etat vide, jamais de crash."""
    global _state_file
    _state_file = Path(path)
    _load()


def disable_persistence():
    """Coupe la persistance (utilise par les tests pour ne rien ecrire)."""
    global _state_file
    _state_file = None


def _load():
    """Recharge les sessions depuis le fichier JSON. Tout probleme (absent,
    corrompu, schema inattendu) -> on repart d'un etat vide, sans exception."""
    if _state_file is None or not _state_file.exists():
        return
    try:
        raw = json.loads(_state_file.read_text(encoding="utf-8"))
        assert isinstance(raw, dict)
    except Exception:
        return
    for sid, data in raw.items():
        try:
            session = UserSession(sid, user_id=data.get("user_id"))
            session.receipts = list(data.get("receipts", []))
            session.items = list(data.get("items", []))
            session._next_id = int(data.get("next_id",
                                             max((int(r["receipt_id"]) for r in session.receipts),
                                                 default=-1) + 1))
            # demo_mode volontairement NON restaure (on ne rouvre pas 800 recus CORD)
            _sessions[sid] = session
        except Exception:
            continue   # une session illisible n'empeche pas de charger les autres


def _save():
    """Sauvegarde les sessions NON-DEMO et NON-VIDES. Ecriture atomique.
    La persistance ne doit JAMAIS casser le service : toute erreur est avalee."""
    if _state_file is None:
        return
    try:
        payload = {}
        for sid, session in _sessions.items():
            if session.demo_mode or not session.receipts:
                continue   # jamais les 800 recus CORD du mode demo, ni les sessions vides
            payload[sid] = {"user_id": session.user_id, "receipts": session.receipts,
                            "items": session.items, "next_id": session._next_id}
        _state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = _state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_state_file)   # remplacement atomique : jamais de fichier a moitie ecrit
    except Exception:
        pass
