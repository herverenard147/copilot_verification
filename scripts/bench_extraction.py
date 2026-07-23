"""Banc d'essai de l'extraction : le pretraitement aide-t-il vraiment ?

Passe chaque image de test_images/ dans le pipeline, DEUX fois : image brute
vs image pretraitee (redressement + CLAHE + redimensionnement). Pour chaque
passage : moteur utilise, nombre d'articles extraits, total, et les chips de
controle. Sortie en tableau lisible + data/bench_results.csv.

Objectif : mesurer concretement l'apport du pretraitement (src/preprocess.py)
sur des photos reelles hors distribution CORD.

Usage :
    python scripts/bench_extraction.py [--images DOSSIER] [--fallback]

  --fallback : sur le passage pretraite, autorise le fallback vision Groq
               (necessite GROQ_API_KEY) quand Donut rend une sortie vide.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from src.preprocess import preprocess_image
from src.receipt import Receipt
from src.rules import audit

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
CHIP = {True: "✅", False: "❌", None: "➖"}


def load_donut():
    import torch
    from transformers import DonutProcessor, VisionEncoderDecoderModel
    name = "naver-clova-ix/donut-base-finetuned-cord-v2"
    processor = DonutProcessor.from_pretrained(name)
    model = VisionEncoderDecoderModel.from_pretrained(name)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    return processor, model.to(device), device


def run_once(image, donut, country, allow_fallback):
    """Un passage complet image -> (engine, receipt, flags)."""
    from src.extractor import extract
    processor, model, device = donut
    engine = "donut"
    try:
        prediction = extract(image, model, processor, device)
    except Exception:
        prediction = {}
    receipt = Receipt.from_gt_parse(prediction)

    incoherent = (not receipt.items) and (not receipt.total)
    if allow_fallback and incoherent and os.environ.get("GROQ_API_KEY"):
        try:
            from src.llm import extract_receipt_via_vision
            vision = extract_receipt_via_vision(image)
            vr = Receipt.from_gt_parse(vision)
            if vr.items or vr.total:
                receipt, engine = vr, "llm_fallback"
        except Exception:
            pass
    return engine, receipt, audit(receipt, country=country)


def bench(images_dir, country="CI", allow_fallback=False):
    paths = sorted(p for p in Path(images_dir).iterdir() if p.suffix.lower() in IMAGE_EXTS)
    if not paths:
        print(f"Aucune image dans {images_dir}/ (extensions : {sorted(IMAGE_EXTS)}).")
        return []

    print(f"Chargement de Donut… ({len(paths)} image(s) à traiter, 2 passages chacune)")
    donut = load_donut()
    rows = []

    for path in paths:
        try:
            base = Image.open(path).convert("RGB")
        except Exception:
            print(f"⚠️  {path.name} : illisible, ignorée.")
            continue

        # passage 1 : image BRUTE (juste RGB, aucun pretraitement)
        e1, r1, f1 = run_once(base, donut, country, allow_fallback=False)
        rows.append(_row(path.name, "brute", e1, r1, f1, {"deskewed": False, "clahe": False}))

        # passage 2 : image PRETRAITEE
        pre, info = preprocess_image(base)
        e2, r2, f2 = run_once(pre, donut, country, allow_fallback)
        rows.append(_row(path.name, "pretraitee", e2, r2, f2, info))

    _print_table(rows)
    _save_csv(rows)
    _summarize(rows)
    return rows


def _row(name, variant, engine, receipt, flags, info):
    return {
        "image": name, "variante": variant, "moteur": engine,
        "n_articles": len(receipt.items), "total": receipt.total,
        "deskew": info.get("deskewed"), "clahe": info.get("clahe"),
        "line_sum_ok": flags["line_sum_ok"], "total_ok": flags["total_ok"],
        "tax_ok": flags["tax_ok"], "anomalie": flags["anomaly"],
    }


def _print_table(rows):
    header = f"{'image':<22}{'variante':<12}{'moteur':<13}{'articles':>9}{'total':>14}   chips (lignes/total/taxe)"
    print("\n" + header)
    print("-" * len(header))
    for r in rows:
        chips = f"{CHIP[r['line_sum_ok']]} {CHIP[r['total_ok']]} {CHIP[r['tax_ok']]}"
        total = "—" if r["total"] is None else f"{r['total']:,.0f}".replace(",", " ")
        print(f"{r['image'][:21]:<22}{r['variante']:<12}{r['moteur']:<13}"
              f"{r['n_articles']:>9}{total:>14}   {chips}")


def _save_csv(rows):
    import pandas as pd
    out = Path("data/bench_results.csv")
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"\n💾 Résultats sauvegardés dans {out}")


def _summarize(rows):
    """Compare brute vs pretraitee : le pretraitement extrait-il plus ?"""
    brute = [r for r in rows if r["variante"] == "brute"]
    pre = [r for r in rows if r["variante"] == "pretraitee"]
    if not brute or not pre:
        return
    n_brute = sum(r["n_articles"] for r in brute)
    n_pre = sum(r["n_articles"] for r in pre)
    nonempty_brute = sum(1 for r in brute if r["n_articles"] or r["total"] is not None)
    nonempty_pre = sum(1 for r in pre if r["n_articles"] or r["total"] is not None)
    print("\n=== Synthèse (apport du prétraitement) ===")
    print(f"Articles extraits au total   : brute {n_brute}  →  prétraitée {n_pre}")
    print(f"Images avec extraction utile : brute {nonempty_brute}/{len(brute)}  →  "
          f"prétraitée {nonempty_pre}/{len(pre)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Banc d'essai extraction (brute vs prétraitée).")
    ap.add_argument("--images", default="test_images", help="dossier d'images (défaut: test_images/)")
    ap.add_argument("--country", default="CI", help="pays pour l'audit (CI/ID, défaut: CI)")
    ap.add_argument("--fallback", action="store_true", help="autoriser le fallback vision Groq")
    args = ap.parse_args()

    if not Path(args.images).is_dir():
        print(f"Dossier '{args.images}/' introuvable. Créez-le et déposez-y des photos de reçus, "
              f"puis relancez :  python scripts/bench_extraction.py --images {args.images}")
        sys.exit(0)
    bench(args.images, country=args.country, allow_fallback=args.fallback)
