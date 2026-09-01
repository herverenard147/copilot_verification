"""Authentification : hachage de mot de passe (argon2id) et jetons de session
signes (cookie distinct du cookie de session anonyme historique de
src/session_store.py). Aucun mot de passe n'est jamais stocke ni logue en
clair -- seul `password_hash` (sortie d'argon2) va en base.

Cle de signature des jetons : AUTH_SECRET_KEY doit etre definie en production
(variable d'environnement, jamais en dur dans le code). A defaut, une cle
aleatoire est generee au demarrage du process : les sessions ne survivent
alors pas a un redemarrage, ce qui est le comportement de secours le moins
risque (jamais une cle fixe partagee/predictible).

Anti brute-force : MAX_ATTEMPTS echecs par email sur LOCKOUT_WINDOW verrouille
temporairement les tentatives suivantes. En mono-instance : memoire process
(non persiste -- suffisant comme frein, pas concu pour resister a un
redemarrage cible). En multi-instance (init_redis(url)) : le compteur
d'echecs DOIT etre partage, sinon un attaquant contourne le verrou en
repartissant ses tentatives entre plusieurs instances derriere le load
balancer -- chacune ne verrait qu'une fraction des echecs reels."""
import os
import time

from argon2 import PasswordHasher
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from src.db import get_db
from src.models import User
from src.corrections import set_consent

_hasher = PasswordHasher()
_FALLBACK_SECRET = os.urandom(32).hex()

AUTH_COOKIE = "auth_token"
SESSION_MAX_AGE = 60 * 60 * 24 * 14  # 14 jours

MAX_ATTEMPTS = 5
LOCKOUT_WINDOW = 15 * 60  # secondes
_FAILED_LOGINS = {}  # email normalise -> [timestamps des echecs recents] (repli local)

_redis = None
_REDIS_PREFIX = "copilote:loginfail:"


def init_redis(url):
    """Active le partage Redis du compteur d'echecs. Ping immediat : si
    Redis n'est pas joignable, repli silencieux sur la memoire locale."""
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


def _redis_key(email):
    return f"{_REDIS_PREFIX}{email}"

# Bornes larges mais reelles : empechent un candidat enorme de forcer un
# hachage/verification argon2 couteux (DoS) ou un email demesure de finir
# tel quel en base (SQLite n'applique PAS la limite String(255) du modele,
# contrairement a un vrai serveur SQL -- voir src/models.py).
MAX_PASSWORD_LENGTH = 1024
MAX_EMAIL_LENGTH = 255


def _too_many_attempts(email):
    if _redis is not None:
        try:
            key = _redis_key(email)
            now = time.time()
            _redis.zremrangebyscore(key, 0, now - LOCKOUT_WINDOW)
            return _redis.zcard(key) >= MAX_ATTEMPTS
        except Exception:
            pass   # Redis en panne en cours de route -> repli local, jamais un crash
    now = time.time()
    recent = [t for t in _FAILED_LOGINS.get(email, []) if now - t < LOCKOUT_WINDOW]
    _FAILED_LOGINS[email] = recent
    return len(recent) >= MAX_ATTEMPTS


def _record_failure(email):
    if _redis is not None:
        try:
            now = time.time()
            key = _redis_key(email)
            _redis.zadd(key, {f"{now}:{os.urandom(4).hex()}": now})
            _redis.expire(key, LOCKOUT_WINDOW)
            return
        except Exception:
            pass
    _FAILED_LOGINS.setdefault(email, []).append(time.time())


def _clear_failures(email):
    if _redis is not None:
        try:
            _redis.delete(_redis_key(email))
            return
        except Exception:
            pass
    _FAILED_LOGINS.pop(email, None)


def _secret_key():
    return os.environ.get("AUTH_SECRET_KEY", _FALLBACK_SECRET)


def hash_password(plain):
    return _hasher.hash(plain)


def verify_password(plain, hashed):
    try:
        _hasher.verify(hashed, plain)
        return True
    except Exception:
        return False


def verify_user_password(user_id, password):
    """Reverifie le mot de passe d'un compte deja identifie (ex. confirmation
    avant suppression de compte) -- pas une connexion, pas d'anti brute-force
    ici (l'utilisateur est deja authentifie par son cookie de session)."""
    if not password or len(password) > MAX_PASSWORD_LENGTH:
        return False
    with get_db() as s:
        user = s.get(User, user_id)
        if user is None or not user.is_active:
            return False
        return verify_password(password, user.password_hash)


def register_user(email, password):
    """Cree un compte. Leve ValueError (email invalide, deja pris, mot de
    passe trop court) plutot qu'une exception SQL brute -- message utilisable
    tel quel par l'API.

    Consentement "amelioration du modele par mes corrections" ACCORDE PAR
    DEFAUT a l'inscription (decision produit explicite) : le front DOIT
    prevenir l'utilisateur immediatement apres l'inscription (popup dediee,
    voir Connexion.jsx/App.jsx) avec un moyen immediat de le retirer -- ce
    n'est jamais un defaut silencieux."""
    email = (email or "").strip().lower()
    if not email or "@" not in email or len(email) > MAX_EMAIL_LENGTH:
        raise ValueError("Email invalide.")
    if not password or len(password) < 8 or len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError(f"Mot de passe invalide (8 à {MAX_PASSWORD_LENGTH} caractères).")
    with get_db() as s:
        if s.query(User).filter_by(email=email).first():
            raise ValueError("Un compte existe déjà avec cet email.")
        user = User(email=email, password_hash=hash_password(password))
        s.add(user)
        s.flush()
        user_id = user.id
    set_consent(user_id, "training_data", True)
    return user_id


MAX_PROFILE_FIELD_LENGTH = 255


def get_profile(user_id):
    """Email + champs de profil optionnels (nom, poste, entreprise) pour
    l'ecran Profil. None si le compte n'existe pas/plus."""
    with get_db() as s:
        user = s.get(User, user_id)
        if user is None:
            return None
        return {"email": user.email, "full_name": user.full_name,
                "job_title": user.job_title, "company": user.company}


def update_profile(user_id, full_name=None, job_title=None, company=None):
    """Met a jour les champs de profil optionnels. Chaine vide -> NULL
    (efface le champ) ; None -> champ inchange (permet une mise a jour
    partielle depuis l'API sans ecraser les autres champs)."""
    def _clean(v):
        if v is None:
            return None
        v = v.strip()
        if len(v) > MAX_PROFILE_FIELD_LENGTH:
            raise ValueError(f"Ce champ dépasse {MAX_PROFILE_FIELD_LENGTH} caractères.")
        return v or None
    with get_db() as s:
        user = s.get(User, user_id)
        if user is None:
            raise ValueError("Compte introuvable.")
        if full_name is not None:
            user.full_name = _clean(full_name)
        if job_title is not None:
            user.job_title = _clean(job_title)
        if company is not None:
            user.company = _clean(company)


def authenticate(email, password):
    """Renvoie l'id utilisateur si email/mot de passe corrects, sinon None.
    Meme reponse (None) que l'email soit inconnu, le mot de passe faux, ou le
    compte verrouille : ne revele jamais quels emails sont enregistres."""
    email = (email or "").strip().lower()
    if not password or len(password) > MAX_PASSWORD_LENGTH or len(email) > MAX_EMAIL_LENGTH:
        return None   # jamais hacher/verifier un candidat demesure (cout argon2)
    if _too_many_attempts(email):
        return None
    with get_db() as s:
        user = s.query(User).filter_by(email=email).first()
        valid = user is not None and user.is_active and verify_password(password, user.password_hash)
        if not valid:
            _record_failure(email)
            return None
        _clear_failures(email)
        return user.id


def issue_token(user_id):
    serializer = URLSafeTimedSerializer(_secret_key(), salt="auth-session")
    return serializer.dumps({"user_id": user_id})


def verify_token(token):
    """Renvoie user_id si le jeton est valide et non expire, sinon None."""
    if not token:
        return None
    serializer = URLSafeTimedSerializer(_secret_key(), salt="auth-session")
    try:
        data = serializer.loads(token, max_age=SESSION_MAX_AGE)
        return data.get("user_id")
    except (BadSignature, SignatureExpired):
        return None
