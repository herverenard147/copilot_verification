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
    apply_account_overrides, DISCLAIMER,
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
    def _item_rows(self, rid, receipt, category):
        return [{
            "receipt_id": rid, "name": it.get("name"), "quantity": it.get("quantity"),
            "unit_price": it.get("unit_price"), "line_price": it.get("line_price"),
            # categorie PAR article si presente, sinon celle du recu (retro-compat)
            "category": it.get("category") or category,
        } for it in receipt.items]

    def _receipt_row(self, rid, receipt, category, flags, merchant, doc_type,
                     invoice_number, account_overrides, image_data):
        return {
            "receipt_id": rid, "n_items": len(receipt.items),
            "items_sum": receipt.items_sum(), "subtotal": receipt.subtotal,
            "tax": receipt.tax, "total": receipt.total,
            "line_sum_ok": flags["line_sum_ok"], "total_ok": flags["total_ok"],
            "tax_ok": flags["tax_ok"], "anomaly": flags["anomaly"],
            "category": category, "merchant": merchant, "doc_type": doc_type,
            "invoice_number": invoice_number, "account_overrides": account_overrides,
            # miniature base64 du recu (affichage detail). None pour la demo /
            # les anciens recus -> le front affiche un espace reserve.
            "image_data": image_data,
        }

    def add_receipt(self, receipt, category, flags, merchant=None, doc_type="ticket",
                    invoice_number=None, account_overrides=None, image_data=None):
        """Ajoute un recu valide a la session. Renvoie son id local."""
        rid = self._next_id
        self._next_id += 1
        self.items.extend(self._item_rows(rid, receipt, category))
        self.receipts.append(self._receipt_row(rid, receipt, category, flags, merchant,
                                               doc_type, invoice_number, account_overrides,
                                               image_data))
        _save()   # persiste apres chaque reçu validé (si la persistance est active)
        return rid

    def update_receipt(self, receipt_id, receipt, category, flags, merchant=None,
                       doc_type="ticket", invoice_number=None, account_overrides=None,
                       image_data=None):
        """Remplace un recu existant (memes id) par des donnees recalculees.
        Renvoie True si le recu existait, False sinon. Reutilise la meme logique
        de stockage que add_receipt (aucune duplication). Si image_data n'est pas
        fourni, on CONSERVE l'image existante (une modif ne perd pas la photo)."""
        rid = int(receipt_id)
        old = next((r for r in self.receipts if int(r["receipt_id"]) == rid), None)
        if old is None:
            return False
        if image_data is None:
            image_data = old.get("image_data")
        self.items = [it for it in self.items if int(it["receipt_id"]) != rid]
        self.items.extend(self._item_rows(rid, receipt, category))
        new_row = self._receipt_row(rid, receipt, category, flags, merchant, doc_type,
                                    invoice_number, account_overrides, image_data)
        self.receipts = [new_row if int(r["receipt_id"]) == rid else r for r in self.receipts]
        _save()
        return True

    def delete_receipt(self, receipt_id):
        """Supprime un recu (ligne + articles). Renvoie True si supprime."""
        rid = int(receipt_id)
        n = len(self.receipts)
        self.receipts = [r for r in self.receipts if int(r["receipt_id"]) != rid]
        self.items = [it for it in self.items if int(it["receipt_id"]) != rid]
        _save()
        return len(self.receipts) < n

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
                                  "a_label": la, "a_value": va, "b_label": lb, "b_value": vb,
                                  "doc_type": _nan(row.get("doc_type")) or "ticket",
                                  "invoice_number": _nan(row.get("invoice_number"))})

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
            "doc_type": r.get("doc_type") or "ticket",
            "invoice_number": r.get("invoice_number"),
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
            doc_type = _nan(row.get("doc_type")) or "ticket"
            invoice_number = _nan(row.get("invoice_number"))
            receipts_list.append({
                "receipt_id": rid, "category": _nan(row.get("category")),
                "total": _nan(row.get("total")), "n_items": int(row.get("n_items") or 0),
                "anomaly": bool(row.get("anomaly")) if row.get("anomaly") is not None else False,
                "line_sum_ok": _flag(row.get("line_sum_ok")),
                "total_ok": _flag(row.get("total_ok")),
                "tax_ok": _flag(row.get("tax_ok")),
                "vat_reason": reason,
                "doc_type": doc_type, "invoice_number": invoice_number,
            })
            try:
                entry = journal_entry(r, category=_nan(row.get("category")),
                                      payment_mode=payment_mode, country=country, merchant=merchant)
                # surcharge manuelle des comptes (Tache 4) appliquee au journal
                apply_account_overrides(entry, _nan(row.get("account_overrides")))
                journal_groups.append({"receipt_id": rid,
                                       "balanced": is_balanced(entry), "lines": entry,
                                       "doc_type": doc_type, "invoice_number": invoice_number})
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
# Persistance legere HORS DEPOT (jamais data/*.csv), via SQLite (stdlib, pas de
# dependance nouvelle). Desactivee par defaut : seul init_persistence() l'active
# (api.py au demarrage d'un vrai serveur ; TestClient sans context manager ne
# declenche pas le lifespan -> aucun .db pendant pytest). Schema minimal : UNE
# ligne par recu, donnees du recu en JSON dans la colonne `data`.
# ---------------------------------------------------------------------------
import sqlite3            # noqa: E402
import threading          # noqa: E402
from datetime import datetime, timezone   # noqa: E402
from pathlib import Path  # noqa: E402

_db_path = None           # None = persistance desactivee (defaut, tests inclus)
_conn = None              # connexion SQLite du processus
_lock = threading.Lock()  # endpoints sync en threadpool -> serialise l'acces base

_SCHEMA = """CREATE TABLE IF NOT EXISTS receipts (
    session_id     TEXT    NOT NULL,
    receipt_id     INTEGER NOT NULL,
    data           TEXT    NOT NULL,   -- {"receipt": {...}, "items": [...]} en JSON
    doc_type       TEXT,
    invoice_number TEXT,
    created_at     TEXT,
    updated_at     TEXT,
    PRIMARY KEY (session_id, receipt_id))"""


def _open_and_prepare():
    """Ouvre la base et cree la table. True si OK, False sinon (corrompue…)."""
    global _conn
    try:
        _conn = sqlite3.connect(str(_db_path), check_same_thread=False)
        _conn.execute(_SCHEMA)
        _conn.commit()
        return True
    except Exception:
        _conn = None
        return False


def init_persistence(path):
    """Active la persistance SQLite vers `path` (hors depot) et recharge l'etat.
    Base absente -> creee. Corrompue -> recreee a neuf. Verrouillee/illisible ->
    demarrage a vide. JAMAIS de crash (meme garantie qu'avec le JSON)."""
    global _db_path
    if _conn is not None:
        disable_persistence()          # reouverture propre si deja initialisee
    _db_path = Path(path)
    try:
        _db_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        _db_path = None
        return
    if not _open_and_prepare():
        # corrompue : on repart d'une base neuve (comme le JSON qui ecrasait un
        # fichier corrompu au prochain save)
        try:
            _db_path.unlink()
        except Exception:
            pass
        if not _open_and_prepare():
            disable_persistence()      # illisible/verrouillee -> etat vide, pas de crash
            return
    _load()


def disable_persistence():
    """Coupe la persistance et ferme la connexion (tests + arret serveur)."""
    global _db_path, _conn
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
        _db_path, _conn = None, None


close_persistence = disable_persistence   # alias explicite pour l'arret du lifespan


def _load():
    """Recharge les sessions depuis la base. Tout probleme -> etat vide."""
    if _conn is None:
        return
    try:
        with _lock:
            rows = _conn.execute("SELECT session_id, receipt_id, data FROM receipts").fetchall()
    except Exception:
        return
    loaded = {}
    for sid, _rid, data_json in rows:
        try:
            blob = json.loads(data_json)
            session = loaded.get(sid) or UserSession(sid)
            session.receipts.append(blob["receipt"])
            session.items.extend(blob.get("items", []))
            loaded[sid] = session
        except Exception:
            continue   # une ligne illisible n'empeche pas de charger les autres
    for sid, session in loaded.items():
        session._next_id = max((int(r["receipt_id"]) for r in session.receipts), default=-1) + 1
        # demo_mode volontairement NON restaure (on ne rouvre pas 800 recus CORD)
        _sessions[sid] = session


def _save():
    """Reecrit l'etat persistable (sessions NON-demo, NON-vides) dans UNE seule
    transaction (atomique, comme le remplacement de fichier). created_at
    preserve. La persistance ne doit JAMAIS casser le service : erreurs avalees."""
    if _conn is None:
        return
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _lock:
            existing = {(sid, rid): cat for sid, rid, cat in
                        _conn.execute("SELECT session_id, receipt_id, created_at FROM receipts")}
            cur = _conn.cursor()
            cur.execute("DELETE FROM receipts")   # transaction implicite jusqu'au commit
            for sid, session in _sessions.items():
                if session.demo_mode or not session.receipts:
                    continue   # jamais le mode demo (800 recus CORD), ni les sessions vides
                items_by = {}
                for it in session.items:
                    items_by.setdefault(int(it["receipt_id"]), []).append(it)
                for r in session.receipts:
                    rid = int(r["receipt_id"])
                    blob = json.dumps({"receipt": r, "items": items_by.get(rid, [])},
                                      ensure_ascii=False)
                    created = existing.get((sid, rid), now)
                    cur.execute(
                        "INSERT INTO receipts (session_id, receipt_id, data, doc_type, "
                        "invoice_number, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (sid, rid, blob, r.get("doc_type"), r.get("invoice_number"), created, now))
            _conn.commit()
    except Exception:
        try:
            _conn.rollback()
        except Exception:
            pass
