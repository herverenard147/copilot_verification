"""Pretraitement des photos de recus avant Donut.

Donut a ete entraine sur CORD : des scans PROPRES, droits, bien eclaires. En
production on recoit des photos de telephone : penchees, sombres, mal cadrees.
Cet ecart de distribution est probablement la premiere cause des mauvais
resultats sur photos reelles. On corrige donc l'image AVANT de la donner au
modele : redimensionnement, contraste (CLAHE), redressement (detection des
bords du ticket), conversion RGB propre.

Chaque etape est isolee et testable ; le redressement est enveloppe dans un
try/except car il peut echouer sur une image atypique (aucun bord franc) --
dans ce cas on renvoie l'image telle quelle plutot que de planter.
"""
import numpy as np
from PIL import Image

try:
    import cv2
    _HAS_CV2 = True
except ImportError:          # degradation : sans OpenCV, on fait le minimum via PIL
    _HAS_CV2 = False


TARGET_HEIGHT = 1280         # hauteur visee : assez grand pour Donut, pas trop lourd
MAX_UPSCALE = 2.0            # on n'agrandit jamais une petite image de plus de x2


def to_rgb(image):
    """Garantit une image PIL en mode RGB (Donut n'accepte que ca)."""
    if image.mode != "RGB":
        image = image.convert("RGB")
    return image


def smart_resize(image, target_height=TARGET_HEIGHT):
    """Redimensionne en gardant le RATIO, pour viser ~target_height de haut.

    On reduit une grande photo (gain de vitesse et de bruit) ; on agrandit une
    petite image mais sans exagerer (au-dela de x2 on n'invente que du flou)."""
    w, h = image.size
    if h == 0:
        return image
    scale = target_height / h
    scale = min(scale, MAX_UPSCALE)            # cap l'agrandissement
    new_w = max(1, round(w * scale))
    new_h = max(1, round(h * scale))
    return image.resize((new_w, new_h), Image.LANCZOS)


def enhance_contrast(image):
    """Ameliore le contraste local via CLAHE (sur le canal luminance L de LAB).

    CLAHE = Contrast Limited Adaptive Histogram Equalization : contrairement a
    une egalisation globale, il traite l'image par tuiles, ce qui rattrape les
    zones d'ombre d'une photo prise a la main sans surexposer le reste.
    Sans OpenCV, on retombe sur l'autocontraste PIL (moins fin mais utile)."""
    if not _HAS_CV2:
        from PIL import ImageOps
        return ImageOps.autocontrast(image, cutoff=1)

    arr = np.array(image)                       # RGB
    lab = cv2.cvtColor(arr, cv2.COLOR_RGB2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    lab = cv2.merge((l, a, b))
    out = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
    return Image.fromarray(out)


def _order_corners(pts):
    """Ordonne 4 points en (haut-gauche, haut-droit, bas-droit, bas-gauche)."""
    pts = pts.reshape(4, 2).astype("float32")
    ordered = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    ordered[0] = pts[np.argmin(s)]              # HG = plus petite somme x+y
    ordered[2] = pts[np.argmax(s)]              # BD = plus grande somme
    diff = np.diff(pts, axis=1)
    ordered[1] = pts[np.argmin(diff)]           # HD = plus petit y-x
    ordered[3] = pts[np.argmax(diff)]           # BG = plus grand y-x
    return ordered


def deskew(image):
    """Detecte les bords du ticket et le redresse a plat (perspective).

    Retourne (image, redresse: bool). Si aucun quadrilatere credible n'est
    trouve (ticket froisse, fond charge, pas de bord net), on renvoie l'image
    inchangee avec redresse=False -- mieux vaut ne rien faire que deformer."""
    if not _HAS_CV2:
        return image, False

    arr = np.array(image)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return image, False

    img_area = arr.shape[0] * arr.shape[1]
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < 0.25 * img_area:
        return image, False                     # le "ticket" occupe trop peu de place : peu fiable

    peri = cv2.arcLength(largest, True)
    approx = cv2.approxPolyDP(largest, 0.02 * peri, True)
    if len(approx) != 4:
        return image, False                     # pas un quadrilatere : on n'ose pas redresser

    corners = _order_corners(approx)
    (tl, tr, br, bl) = corners
    width = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    height = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    if width < 10 or height < 10:
        return image, False

    dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
                   dtype="float32")
    matrix = cv2.getPerspectiveTransform(corners, dst)
    warped = cv2.warpPerspective(arr, matrix, (width, height))
    return Image.fromarray(warped), True


def preprocess_image(image, target_height=TARGET_HEIGHT, do_deskew=True, do_clahe=True):
    """Chaine complete : RGB -> (redressement) -> redimensionnement -> (CLAHE).

    Renvoie (image_pretraitee, infos) ou infos = {"deskewed": bool,
    "size": (w, h)} pour tracer ce qui a ete applique (utile au banc d'essai).
    Robuste : chaque etape optionnelle est protegee, l'echec d'une etape ne
    fait pas echouer tout le pretraitement."""
    info = {"deskewed": False, "clahe": False}
    image = to_rgb(image)

    if do_deskew:
        try:
            image, info["deskewed"] = deskew(image)
        except Exception:
            info["deskewed"] = False            # on garde l'image non redressee

    image = smart_resize(image, target_height=target_height)

    if do_clahe:
        try:
            image = enhance_contrast(image)
            info["clahe"] = True
        except Exception:
            info["clahe"] = False

    image = to_rgb(image)
    info["size"] = image.size
    return image, info
