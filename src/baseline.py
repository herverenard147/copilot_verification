"""La baseline : un mot + sa position -> son etiquette.

Le FEATURE ENGINEERING est ici : on transforme chaque mot en nombres qui
decrivent ce qu'un humain regarderait. Comment reperes-tu un prix sur un
ticket ? Il est A DROITE, fait de CHIFFRES, avec des VIRGULES. Ce sont les
features 1, 4 et 5.
"""
import json
import numpy as np


def featurize_word(text, cx, cy, img_w, img_h):
    """Un mot -> un vecteur de 8 nombres."""
    n = max(len(text), 1)
    digits = sum(c.isdigit() for c in text)
    return [
        cx / img_w,                            # position horizontale
        cy / img_h,                            # position verticale
        min(len(text), 20) / 20,               # longueur du mot
        digits / n,                            # proportion de chiffres
        ("," in text or "." in text) * 1.0,    # separateur de milliers ?
        text.isupper() * 1.0,                  # tout en majuscules ?
        text.isalpha() * 1.0,                  # que des lettres ?
        ("x" in text.lower()) * 1.0,           # "2x", marqueur de quantite
    ]


def word_center(quad):
    """Centre du quadrilatere entourant un mot."""
    xs = [quad["x1"], quad["x2"], quad["x3"], quad["x4"]]
    ys = [quad["y1"], quad["y2"], quad["y3"], quad["y4"]]
    return sum(xs) / 4, sum(ys) / 4


def build_word_dataset(split):
    """Split HF -> (X features, y etiquettes)."""
    X, y = [], []
    for ex in split:
        gt = json.loads(ex["ground_truth"])
        w, h = ex["image"].size
        for line in gt.get("valid_line", []):
            for word in line.get("words", []):
                cx, cy = word_center(word["quad"])
                X.append(featurize_word(word["text"], cx, cy, w, h))
                y.append(line["category"])
    return np.array(X), np.array(y)
