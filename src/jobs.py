"""File d'attente pour les taches longues (extraction Donut).

Sort l'inference du chemin de requete HTTP : POST /api/extract renvoie un
job_id immediatement (apres les controles rapides -- fichier, image,
resolution), le front interroge GET /api/extract/status/{id} jusqu'a "done".

Le pool de workers est BORNE (MAX_WORKERS) : ca sert aussi d'optimisation,
pas seulement de decouplage. Plusieurs inferences Donut lancees en parallele
se disputent les memes coeurs CPU et sont, au total, plus lentes que les
memes inferences traitees les unes apres les autres a pleine vitesse
mono-tache. Serialiser (ou limiter a quelques workers) evite cette
contention.

SCALING HORIZONTAL -- deux choses SEPAREES :
1. Le STATUT/RESULTAT d'un job (init_redis(url)) : PARTAGE via Redis si
   configure. Necessaire parce qu'un load balancer peut router la requete
   de SOUMISSION vers l'instance A et celle de POLLING vers l'instance B --
   sans partage, B repondrait "job introuvable" alors que A travaille dessus.
2. L'EXECUTION du travail : reste LOCALE a l'instance qui a recu la
   soumission (ThreadPoolExecutor local, jamais deplacee). Distribuer le
   calcul lui-meme entre instances demanderait de serialiser l'image sur le
   reseau via une vraie file de taches partagee (Celery/RQ + un backend de
   stockage d'images) -- hors scope ici, la charge de calcul n'est donc PAS
   repartie entre instances, seule la VISIBILITE du resultat l'est.

Sans REDIS_URL configuree (ou si Redis est injoignable), repli total et
silencieux sur le dict en memoire du process (comportement historique,
inchange -- aucune regression en mono-instance).
"""
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

MAX_WORKERS = 1              # serialise les inferences Donut (evite la contention CPU)
JOB_TTL_SECONDS = 30 * 60    # purge les jobs termines (done/error) plus vieux que ca

_executor = None
_jobs = {}   # job_id -> {"status", "result", "error", "created_at"} (repli memoire locale)
_lock = threading.Lock()

_redis = None                  # None = cache partage desactive (repli memoire locale)
_REDIS_PREFIX = "copilote:job:"


def init_redis(url):
    """Active le partage Redis du statut des jobs. Ping immediat : si Redis
    n'est pas joignable, repli silencieux sur la memoire locale."""
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


def _redis_key(job_id):
    return f"{_REDIS_PREFIX}{job_id}"


def _redis_set(job_id, state):
    """Best-effort : ne leve jamais. `state` doit deja etre JSON-safe (voir
    api.py, to_jsonable() applique au resultat avant qu'il arrive ici)."""
    if _redis is None:
        return
    try:
        _redis.set(_redis_key(job_id), json.dumps(state, ensure_ascii=False), ex=JOB_TTL_SECONDS)
    except Exception:
        pass


def _redis_get(job_id):
    if _redis is None:
        return None
    try:
        raw = _redis.get(_redis_key(job_id))
        return json.loads(raw) if raw is not None else None
    except Exception:
        return None


def _get_executor():
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="job-worker")
    return _executor


def submit(fn, *args, **kwargs):
    """Soumet fn(*args, **kwargs) en tache de fond, EXECUTEE SUR CETTE
    INSTANCE (voir docstring du module). Renvoie un job_id immediatement (la
    fonction n'a pas encore commence a s'executer). fn doit renvoyer un
    resultat deja JSON-safe (voir to_jsonable() cote appelant) : le cache
    Redis, s'il est actif, le serialise tel quel."""
    job_id = uuid.uuid4().hex
    created_at = time.time()
    state = {"status": "pending", "result": None, "error": None, "created_at": created_at}
    with _lock:
        _jobs[job_id] = dict(state)
    _redis_set(job_id, state)

    def _run():
        with _lock:
            if job_id in _jobs:
                _jobs[job_id]["status"] = "running"
        _redis_set(job_id, {"status": "running", "result": None, "error": None, "created_at": created_at})
        try:
            result = fn(*args, **kwargs)
            with _lock:
                if job_id in _jobs:
                    _jobs[job_id]["status"] = "done"
                    _jobs[job_id]["result"] = result
            _redis_set(job_id, {"status": "done", "result": result, "error": None, "created_at": created_at})
        except Exception as exc:
            with _lock:
                if job_id in _jobs:
                    _jobs[job_id]["status"] = "error"
                    _jobs[job_id]["error"] = str(exc)
            _redis_set(job_id, {"status": "error", "result": None, "error": str(exc), "created_at": created_at})

    _get_executor().submit(_run)
    _purge_old()
    return job_id


def get_status(job_id):
    """Etat du job, ou None si inconnu/expire/jamais existe. Lit Redis en
    priorite si configure (source de verite partagee entre instances) --
    sinon repli sur le dict local (comportement historique)."""
    if _redis is not None:
        return _redis_get(job_id)
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
