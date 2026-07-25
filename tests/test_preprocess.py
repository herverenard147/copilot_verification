"""Tests du pretraitement d'image. Lancer avec : pytest tests/ -q"""
import numpy as np
import pytest
from PIL import Image

from src.preprocess import (
    to_rgb, smart_resize, enhance_contrast, deskew, preprocess_image,
    TARGET_HEIGHT,
)


def make_image(w, h, mode="RGB", color=(120, 120, 120)):
    return Image.new(mode, (w, h), color)


def test_to_rgb_convertit_les_autres_modes():
    assert to_rgb(make_image(10, 10, mode="L", color=128)).mode == "RGB"
    assert to_rgb(make_image(10, 10, mode="RGBA", color=(1, 2, 3, 4))).mode == "RGB"


def test_smart_resize_garde_le_ratio():
    img = make_image(600, 1200)             # ratio 1:2
    out = smart_resize(img, target_height=1280)
    w, h = out.size
    assert abs(w / h - 0.5) < 0.01          # ratio preserve
    assert 1270 <= h <= 1290                # hauteur proche de la cible


def test_smart_resize_ne_suragrandit_pas():
    # une petite image ne doit pas etre agrandie de plus de x2
    out = smart_resize(make_image(100, 100), target_height=1280)
    assert out.size[1] <= 200


def test_enhance_contrast_preserve_dimensions_et_mode():
    img = make_image(64, 64)
    out = enhance_contrast(img)
    assert out.size == img.size
    assert out.mode == "RGB"


def test_deskew_renvoie_toujours_un_couple_valide():
    # image unie sans bord franc -> pas de redressement, image renvoyee telle quelle
    img = make_image(300, 400)
    out, deskewed = deskew(img)
    assert isinstance(deskewed, bool)
    assert out.mode == "RGB"


def test_deskew_detecte_un_ticket_rectangulaire():
    # fond noir, "ticket" blanc incline : on verifie juste que ca ne plante pas
    # et que la sortie reste une image RGB exploitable
    arr = np.zeros((400, 400, 3), dtype=np.uint8)
    arr[80:320, 120:280] = 255              # rectangle clair centre
    out, deskewed = deskew(Image.fromarray(arr))
    assert out.mode == "RGB"
    assert out.size[0] > 0 and out.size[1] > 0


def test_preprocess_image_bout_en_bout():
    img = make_image(800, 1600)
    out, info = preprocess_image(img)
    assert out.mode == "RGB"
    assert out.size[1] <= TARGET_HEIGHT + 20
    assert set(info) >= {"deskewed", "clahe", "size"}
    assert isinstance(info["deskewed"], bool)


def test_preprocess_image_sur_toute_petite_image_ne_plante_pas():
    out, info = preprocess_image(make_image(4, 4))
    assert out.mode == "RGB"
    assert out.size[0] >= 1 and out.size[1] >= 1


def test_preprocess_desactivation_des_etapes():
    out, info = preprocess_image(make_image(400, 500), do_deskew=False, do_clahe=False)
    assert info["deskewed"] is False
    assert info["clahe"] is False
