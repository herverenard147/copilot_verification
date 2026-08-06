"""Limitation de debit (rate limiting) par IP -- frein contre un flot de
requetes (legitime ou non) qui saturerait le serveur.

En mono-instance : compteur a fenetre glissante en memoire (meme style que
l'anti brute-force de src/auth.py).

En multi-instance (init_redis(url)) : le MEME compteur doit etre PARTAGE,
sinon un attaquant (ou un pic de trafic legitime mal reparti) contourne la
limite simplement en frappant des instances differentes -- chacune ne
verrait qu'une fraction du trafic reel. Implemente via un sorted set Redis
par (bucket, identifiant), verifie/incremente ATOMIQUEMENT par un script
Lua (sinon deux requetes concurrentes sur deux instances pourraient toutes
les deux passer le controle avant que l'une des deux n'incremente -- le
script Lua s'execute d'un bloc cote serveur Redis, jamais entrelace).

Sans REDIS_URL configuree (ou si Redis est injoignable), repli total et
silencieux sur le compteur en memoire locale (comportement historique).
"""
import threading
import time
import uuid

_lock = threading.Lock()
_hits = {}   # (bucket, identifiant) -> [timestamps des requetes recentes] (repli local)

# (requetes max, fenetre en secondes). "default" s'applique a TOUT /api/*
# (borne l'usage global) ; les autres bornent EN PLUS un endpoint couteux
# specifique (verifies tous les deux, voir api.py).
LIMITS = {
    "default": (120, 60),        # 120 requetes/min/IP sur l'API en general
    "extract": (10, 60),         # upload + extraction : couteux CPU/memoire
    "bilan_import": (10, 60),    # parsing de fichier : couteux
}

_redis = None
_REDIS_PREFIX = "copilote:ratelimit:"

# ZREMRANGEBYSCORE purge les entrees hors fenetre, ZCARD compte ce qui reste ;
# si sous la limite, ZADD enregistre CETTE requete et EXPIRE rafraichit le TTL
# de la cle -- le tout dans UN SEUL appel atomique cote serveur Redis.
_LUA_CHECK = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, ARGV[1] - ARGV[2])
local count = redis.call('ZCARD', KEYS[1])
if count >= tonumber(ARGV[3]) then
    return 0
end
redis.call('ZADD', KEYS[1], ARGV[1], ARGV[4])
redis.call('EXPIRE', KEYS[1], ARGV[2])
return 1
"""
_lua_script = None


def init_redis(url):
    """Active le partage Redis des compteurs. Ping immediat : si Redis n'est
    pas joignable, repli silencieux sur la memoire locale."""
    global _redis, _lua_script
    try:
        import redis as redis_lib
        client = redis_lib.from_url(url, decode_responses=True, socket_connect_timeout=2)
        client.ping()
        _redis = client
        _lua_script = client.register_script(_LUA_CHECK)
    except Exception:
        _redis, _lua_script = None, None


def close_redis():
    global _redis, _lua_script
    if _redis is not None:
        try:
            _redis.close()
        except Exception:
            pass
    _redis, _lua_script = None, None


def _check_local(bucket, identifier, max_requests, window):
    key = (bucket, identifier)
    now = time.time()
    with _lock:
        hits = [t for t in _hits.get(key, []) if now - t < window]
        if len(hits) >= max_requests:
            _hits[key] = hits
            return False
        hits.append(now)
        _hits[key] = hits
        return True


def check(bucket, identifier):
    """True si la requete est autorisee (et l'enregistre aussitot), False
    si la limite du bucket est deja atteinte pour cet identifiant (IP)."""
    max_requests, window = LIMITS.get(bucket, LIMITS["default"])
    if _redis is not None:
        try:
            key = f"{_REDIS_PREFIX}{bucket}:{identifier}"
            now = time.time()
            allowed = _lua_script(keys=[key], args=[now, window, max_requests, uuid.uuid4().hex])
            return bool(int(allowed))
        except Exception:
            pass   # Redis en panne en cours de route -> repli local, jamais un crash
    return _check_local(bucket, identifier, max_requests, window)


def reset_all():
    """Vide le registre local (tests uniquement). Ne purge pas Redis (voir
    les tests dedies, qui scannent/suppriment leurs propres cles)."""
    with _lock:
        _hits.clear()
