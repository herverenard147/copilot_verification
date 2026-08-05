"""File d'attente en memoire pour les taches longues (extraction Donut).

Sort l'inference du chemin de requete HTTP : POST /api/extract renvoie un
job_id immediatement (apres les controles rapides -- fichier, image,
resolution), le front interroge GET /api/extract/status/{id} jusqu'a "done".

Le pool de workers est BORNE (MAX_WORKERS) : ca sert aussi d'optimisation,
pas seulement de decouplage. Plusieurs inferences Donut lancees en parallele
se disputent les memes coeurs CPU et sont, au total, plus lentes que les
memes inferences traitees les unes apres les autres a pleine vitesse
mono-tache. Serialiser (ou limiter a quelques workers) evite cette
contention.

LIMITE CONNUE, assumee et non traitee ici : ce registre est en memoire de
process, comme session_store.py. Il ne survit pas a un redemarrage et n'est
pas partage entre plusieurs instances -- pour un vrai scaling horizontal
(plusieurs containers), il faudrait le deplacer vers un backend partage
(Redis, une table). Etape suivante, pas faite dans ce chantier.
"""
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

MAX_WORKERS = 1              # serialise les inferences Donut (evite la contention CPU)
JOB_TTL_SECONDS = 30 * 60    # purge les jobs termines (done/error) plus vieux que ca

_executor = None
_jobs = {}   # job_id -> {"status", "result", "error", "created_at"}
_lock = threading.Lock()


def _get_executor():
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="job-worker")
    return _executor


def submit(fn, *args, **kwargs):
    """Soumet fn(*args, **kwargs) en tache de fond. Renvoie un job_id
    immediatement (la fonction n'a pas encore commence a s'executer)."""
    job_id = uuid.uuid4().hex
    with _lock:
        _jobs[job_id] = {"status": "pending", "result": None, "error": None,
                         "created_at": time.time()}

    def _run():
        with _lock:
            if job_id in _jobs:
                _jobs[job_id]["status"] = "running"
        try:
            result = fn(*args, **kwargs)
            with _lock:
                if job_id in _jobs:
                    _jobs[job_id]["status"] = "done"
                    _jobs[job_id]["result"] = result
        except Exception as exc:
            with _lock:
                if job_id in _jobs:
                    _jobs[job_id]["status"] = "error"
                    _jobs[job_id]["error"] = str(exc)

    _get_executor().submit(_run)
    _purge_old()
    return job_id


def get_status(job_id):
    """Copie de l'etat du job, ou None si inconnu/expire/jamais existe."""
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job is not None else None


def _purge_old():
    cutoff = time.time() - JOB_TTL_SECONDS
    with _lock:
        stale = [jid for jid, j in _jobs.items()
                if j["status"] in ("done", "error") and j["created_at"] < cutoff]
        for jid in stale:
            del _jobs[jid]


def reset_all():
    """Vide le registre (tests uniquement)."""
    with _lock:
        _jobs.clear()
