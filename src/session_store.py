"""Cloisonnement des donnees par session utilisateur.

Les CSV de data/ sont un CORPUS DE REFERENCE (CORD) : entrainement, evaluation,
clustering KMeans, index FAISS de reference. Ce ne sont PAS les depenses de
l'utilisateur. Ce module tient les recus que l'utilisateur depose et valide
pendant SA session ; le tableau de bord, la comptabilite et les questions
lisent ces donnees-la. Aucune ecriture disque HORS PERSISTANCE EXPLICITE : un
correcteur qui clone n'herite jamais des recus d'un autre.

AUTH : chaque UserSession porte un `user_id` (None si anonyme). En mode prod
(api.py), le registre est keye sur `user:{user_id}` au lieu du cookie anonyme.

DEUX MECANISMES DE PARTAGE DE L'ETAT, INDEPENDANTS :

1. PERSISTANCE SQLite (optionnelle, init_persistence(path)) : survit a un
   REDEMARRAGE du process. Fichier HORS DEPOT (.local_state/), jamais
   data/*.csv. Le mode demo n'est JAMAIS persiste ici (voir _save()).

2. CACHE REDIS PARTAGE (optionnel, init_redis(url)) : necessaire des qu'il y
   a PLUSIEURS instances derriere un load balancer -- sans lui, une session
   commencee sur l'instance A est invisible sur l'instance B (chacune a son
   propre dict _sessions en memoire), et le mode demo casse au premier
   routage vers une autre instance. Contrairement a la persistance SQLite,
   le mode demo PARTICIPE au cache Redis (ce n'est pas une question de
   survivre a un redemarrage, mais de rester coherent ENTRE deux requetes de
   la MEME session utilisateur qui atterrissent sur deux instances differentes).
   Si Redis est configure, il devient la SOURCE DE VERITE : get_session() y
   lit en premier. Sinon, repli integral sur le dict _sessions en memoire
   (comportement historique inchange -- aucune regression pour un usage
   mono-instance sans Redis).
"""
import json
import math
import time

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
        self.last_accessed = time.time()  # voir evict_idle_sessions()

    # -- etat -----------------------------------------------------------------
    def is_empty(self):
        return not self.receipts

    def clear(self):
        self.receipts, self.items = [], []
        self.demo_mode = False
        self._next_id = 0
        _save()   # persiste l'etat vidé (retire cette session du fichier)
        _redis_save(self)   # propage aux autres instances (no-op si Redis desactive)

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
        _redis_save(self)
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
        _redis_save(self)
        return True

    def delete_receipt(self, receipt_id):
        """Supprime un recu (ligne + articles). Renvoie True si supprime."""
        rid = int(receipt_id)
        n = len(self.receipts)
        self.receipts = [r for r in self.receipts if int(r["receipt_id"]) != rid]
        self.items = [it for it in self.items if int(it["receipt_id"]) != rid]
        _save()
        _redis_save(self)
        return len(self.receipts) < n

    def load_demo(self, receipts, items):
        """MODE DEMONSTRATION : peuple la session avec un corpus (copie
        defensive) et active le drapeau demo. Jamais persiste en SQLite (voir
        _save()), mais PARTAGE via Redis si configure : sinon le mode demo
        casse des que la requete suivante atterrit sur une autre instance."""
        self.clear()
        self.receipts = [dict(r) for r in receipts]
        self.items = [dict(i) for i in items]
        self.demo_mode = True
        self._next_id = max((int(r["receipt_id"]) for r in self.receipts), default=-1) + 1
        _redis_save(self)

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

        # Depenses par categorie : une barre par categorie reellement presente.
        # Les articles sans categorie (classifieur muet, ancien recu) sont
        # regroupes sous "Non categorise" plutot que SILENCIEUSEMENT ecartes --
        # sinon groupby(dropna=True) les supprime et le cadre parait vide alors
        # que des articles existent (bug observe : 1 recu, 6 articles -> vide).
        by_category = []
        if not items.empty and "category" in items.columns:
            cat = items["category"].where(items["category"].notna(), "Non catégorisé")
            cat = cat.replace("", "Non catégorisé")
            grouped = items.assign(category=cat).groupby("category")["line_price"] \
                .sum().sort_values(ascending=False)
            by_category = [{"category": str(c), "total": float(v)} for c, v in grouped.items()]

        # Repartition des totaux : histogramme adapte au nombre de valeurs
        # DISTINCTES. Avec un seul montant on affiche CE montant (une barre),
        # pas 10 tranches quasi identiques nees du binning force de numpy
        # (range +/-0.5 autour d'une valeur unique -> libelles "5 579-5 579").
        totals = receipts["total"].dropna().to_numpy()
        distribution = []
        if len(totals):
            distinct = np.unique(totals)
            if len(distinct) == 1:
                v = float(distinct[0])
                distribution = [{"range": f"{round(v):,}".replace(",", " "),
                                 "count": int(len(totals))}]
            else:
                nbins = min(10, len(distinct))
                counts, edges = np.histogram(totals, bins=nbins)
                distribution = [{"range": f"{round(edges[i]):,}–{round(edges[i + 1]):,}".replace(",", " "),
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

    def get_accounting_data(self, period, payment_mode, country, category_account_map=None):
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
                                      payment_mode=payment_mode, country=country, merchant=merchant,
                                      category_account_map=category_account_map)
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

# Purge des sessions inactives (fuite memoire sinon : _sessions ne retirait
# jamais rien tant que le process tournait). TTL genereux (24h) : c'est un
# frein, pas une politique de retention agressive.
IDLE_TTL_SECONDS = 24 * 60 * 60


def get_session(session_id, user_id=None):
    """Recupere (ou cree) la session.

    Si Redis est configure (init_redis) : c'est la SOURCE DE VERITE. On y lit
    a CHAQUE appel plutot que de faire confiance a un dict local qui peut etre
    perime (une autre instance a pu modifier cette session entre-temps) --
    necessaire des qu'il y a plusieurs instances derriere un load balancer,
    sinon une session commencee sur l'instance A est invisible sur B.

    Sinon : repli integral sur le dict _sessions en memoire du process
    (comportement historique, inchange -- aucune regression pour un usage
    mono-instance sans Redis, y compris en test)."""
    if _redis is not None:
        session = _redis_load(session_id, user_id=user_id)
        if session is None:
            session = UserSession(session_id, user_id=user_id)
            _redis_save(session)
        session.last_accessed = time.time()
        return session
    session = _sessions.get(session_id)
    if session is None:
        session = UserSession(session_id, user_id=user_id)
        _sessions[session_id] = session
    session.last_accessed = time.time()
    return session


def evict_idle_sessions(ttl_seconds=IDLE_TTL_SECONDS):
    """Retire du registre EN MEMOIRE les sessions inactives depuis plus de
    ttl_seconds -- MAIS SEULEMENT si les perdre ne coute rien : mode demo
    (jamais persiste, un clic recharge le corpus) ou session vide (rien a
    perdre). Une session avec de vrais reçus persistes n'est JAMAIS evincee
    ici : il n'existe pas (encore) de mecanisme pour la recharger a la demande
    depuis la base si elle redevient active -- l'evincer perdrait des
    donnees visibles par l'utilisateur tant que ce mecanisme n'existe pas.
    Renvoie le nombre de sessions evincees.

    Si Redis est configure, cette fonction est un NO-OP utile (le dict local
    _sessions n'est plus la source de verite, get_session() ne le peuple
    plus) : Redis applique sa propre expiration (TTL sur chaque cle, voir
    _redis_save), pas besoin de dupliquer cette logique."""
    now = time.time()
    to_evict = [sid for sid, s in _sessions.items()
               if (now - s.last_accessed) > ttl_seconds and (s.demo_mode or s.is_empty())]
    for sid in to_evict:
        del _sessions[sid]
    return len(to_evict)


def drop_session(session_id):
    _sessions.pop(session_id, None)
    _redis_drop(session_id)
    _save()


def reset_all():
    """Vide tout le registre (utilise par les tests). Ne touche pas au fichier.
    Si Redis est configure, purge aussi les cles copilote:session:* (scan
    cible, jamais un FLUSHALL -- la meme base Redis peut servir a autre chose)."""
    _sessions.clear()
    if _redis is not None:
        try:
            for key in _redis.scan_iter(match=f"{_REDIS_PREFIX}*"):
                _redis.delete(key)
        except Exception:
            pass


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


# ---------------------------------------------------------------------------
# Cache Redis PARTAGE (optionnel) -- necessaire des qu'il y a plusieurs
# instances derriere un load balancer. Desactive par defaut : seul
# init_redis() l'active (api.py au demarrage, si REDIS_URL est definie).
# JAMAIS bloquant : toute erreur Redis (indisponible, timeout, cle
# corrompue...) fait retomber silencieusement sur le comportement memoire
# locale existant -- une panne Redis degrade (perte du partage entre
# instances) mais ne casse jamais le service.
# ---------------------------------------------------------------------------
_redis = None                      # None = cache desactive (repli memoire locale)
_REDIS_PREFIX = "copilote:session:"


def init_redis(url):
    """Active le cache Redis partage. Ping immediat : si Redis n'est pas
    joignable, on repart en mode memoire locale plutot que d'echouer chaque
    requete plus tard."""
    global _redis
    try:
        import redis as redis_lib
        client = redis_lib.from_url(url, decode_responses=True, socket_connect_timeout=2)
        client.ping()
        _redis = client
    except Exception:
        _redis = None


def close_redis():
    global _redis
    if _redis is not None:
        try:
            _redis.close()
        except Exception:
            pass
    _redis = None


def _redis_key(session_id):
    return f"{_REDIS_PREFIX}{session_id}"


def _redis_save(session):
    """Ecrit l'etat complet de la session dans Redis (TTL = IDLE_TTL_SECONDS,
    coherent avec evict_idle_sessions -- Redis fait lui-meme l'eviction des
    sessions partagees inactives, pas besoin de dupliquer cette logique).
    Best-effort : ne leve jamais."""
    if _redis is None:
        return
    try:
        payload = json.dumps({
            "receipts": session.receipts, "items": session.items,
            "demo_mode": session.demo_mode, "next_id": session._next_id,
        }, ensure_ascii=False)
        _redis.set(_redis_key(session.session_id), payload, ex=IDLE_TTL_SECONDS)
    except Exception:
        pass


def _redis_load(session_id, user_id=None):
    """Reconstruit une UserSession depuis Redis, ou None si absente/erreur
    (l'appelant cree alors une session vide -- jamais de crash)."""
    if _redis is None:
        return None
    try:
        raw = _redis.get(_redis_key(session_id))
        if raw is None:
            return None
        data = json.loads(raw)
        session = UserSession(session_id, user_id=user_id)
        session.receipts = data.get("receipts", [])
        session.items = data.get("items", [])
        session.demo_mode = bool(data.get("demo_mode", False))
        session._next_id = int(data.get("next_id", 0))
        return session
    except Exception:
        return None


def _redis_drop(session_id):
    if _redis is None:
        return
    try:
        _redis.delete(_redis_key(session_id))
    except Exception:
        pass
