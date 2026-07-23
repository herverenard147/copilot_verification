"""Banc d'essai de l'extraction : 4 configurations par image.

Pour chaque photo de test_images/, on compare :
  (a) donut_brut         : Donut sur l'image brute
  (b) donut_pretraite    : Donut sur l'image prétraitée (redressement+CLAHE)
  (c) vision_seul        : LLM vision Groq seul (nécessite GROQ_API_KEY)
  (d) pipeline_complet   : prétraitement + routage automatique (= /api/extract :
                            Donut, puis fallback vision si sortie vide ou pays CI)

Pour chacune : moteur utilisé, nb d'articles, total extrait, les 4 chips
(lignes / total / taxe / équilibre), temps d'exécution, et l'erreur si il y en a.

Sortie : tableau lisible en console + data/bench_results.csv.

⚠️ Attente réaliste (à documenter, pas à masquer) :
  - photos 1 et 2 (domaine de Donut, mais mauvaise qualité) : le prétraitement
    DOIT améliorer (a) -> (b).
  - photo 3 (hors domaine : facture française en tableau) : Donut échouera,
    c'est attendu ; seul le fallback vision (c/d) peut produire quelque chose,
    et la réponse indiquera engine=llm_fallback.

Usage :
    python scripts/bench_extraction.py [--images DOSSIER] [--country CI|ID]
"""
import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from src.preprocess import preprocess_image
from src.receipt import Receipt
from src.rules import audit
from src.accounting import journal_entry, is_balanced

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
CHIP = {True: "✅", False: "❌", None: "➖"}
CONFIGS = ["donut_brut", "donut_pretraite", "vision_seul", "pipeline_complet"]


def load_donut():
    import torch
    from transformers import DonutProcessor, VisionEncoderDecoderModel
    name = "naver-clova-ix/donut-base-finetuned-cord-v2"
    processor = DonutProcessor.from_pretrained(name)
    model = VisionEncoderDecoderModel.from_pretrained(name)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    return processor, model.to(device), device


def _donut_extract(image, donut):
    """Image -> Receipt via Donut. Monkeypatchable pour les tests."""
    from src.extractor import extract
    processor, model, device = donut
    return Receipt.from_gt_parse(extract(image, model, processor, device))


def _vision_extract(image):
    """Image -> Receipt via LLM vision Groq. Monkeypatchable pour les tests."""
    from src.llm import extract_receipt_via_vision
    return Receipt.from_gt_parse(extract_receipt_via_vision(image))


def chips_of(receipt, country):
    """Les 4 chips affichés par le front : lignes, total, taxe, équilibre."""
    flags = audit(receipt, country=country)
    try:
        entry = journal_entry(receipt, category=None, country=country)
        balanced = is_balanced(entry) if entry else None
    except (ValueError, KeyError):
        balanced = None
    return flags["line_sum_ok"], flags["total_ok"], flags["tax_ok"], balanced


def _empty(receipt):
    return (not receipt.items) and (receipt.total is None)


def run_config(config, base_img, pre_img, donut, country):
    """Execute une des 4 configurations, renvoie un dict de resultats + timing."""
    t0 = time.perf_counter()
    engine, receipt, err = config.split("_")[0], Receipt([], None, None, None), None
    try:
        if config == "donut_brut":
            engine, receipt = "donut", _donut_extract(base_img, donut)
        elif config == "donut_pretraite":
            engine, receipt = "donut", _donut_extract(pre_img, donut)
        elif config == "vision_seul":
            if not os.environ.get("GROQ_API_KEY"):
                raise RuntimeError("GROQ_API_KEY absente")
            engine, receipt = "llm_fallback", _vision_extract(base_img)
        elif config == "pipeline_complet":
            engine, receipt = "donut", _donut_extract(pre_img, donut)
            if (_empty(receipt) or country == "CI") and os.environ.get("GROQ_API_KEY"):
                try:
                    vr = _vision_extract(pre_img)
                    if vr.items or vr.total is not None:
                        engine, receipt = "llm_fallback", vr
                except Exception:
                    pass  # on garde Donut, le pipeline reel fait pareil
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"[:60]
        engine = "—"
    dt = time.perf_counter() - t0

    ls, to, tx, bal = chips_of(receipt, country)
    return {
        "config": config, "moteur": engine,
        "n_articles": len(receipt.items), "total": receipt.total,
        "chip_lignes": ls, "chip_total": to, "chip_taxe": tx, "chip_equilibre": bal,
        "temps_s": round(dt, 2), "erreur": err,
    }


def bench(images_dir, country="CI"):
    paths = sorted(p for p in Path(images_dir).iterdir() if p.suffix.lower() in IMAGE_EXTS)
    if not paths:
        print(f"Aucune image dans {images_dir}/ (extensions : {sorted(IMAGE_EXTS)}).")
        return []

    if not os.environ.get("GROQ_API_KEY"):
        print("ℹ️  GROQ_API_KEY absente : les configs 'vision_seul' et le fallback "
              "de 'pipeline_complet' seront marqués indisponibles.")
    print(f"Chargement de Donut… ({len(paths)} image(s) × 4 configurations)")
    donut = load_donut()

    rows = []
    for path in paths:
        try:
            base = Image.open(path).convert("RGB")
        except Exception:
            print(f"⚠️  {path.name} : illisible, ignorée.")
            continue
        pre, _ = preprocess_image(base)
        for config in CONFIGS:
            r = run_config(config, base, pre, donut, country)
            r["image"] = path.name
            rows.append(r)

    _print_table(rows)
    _save_csv(rows)
    _interpret(rows)
    return rows


def _print_table(rows):
    hdr = (f"{'image':<26}{'config':<18}{'moteur':<13}{'art.':>5}{'total':>13}"
           f"   {'chips (L/T/Tx/Éq)':<18}{'temps':>7}  erreur")
    print("\n" + hdr)
    print("-" * len(hdr))
    for r in rows:
        chips = f"{CHIP[r['chip_lignes']]}{CHIP[r['chip_total']]}{CHIP[r['chip_taxe']]}{CHIP[r['chip_equilibre']]}"
        total = "—" if r["total"] is None else f"{r['total']:,.0f}".replace(",", " ")
        err = r["erreur"] or ""
        print(f"{r['image'][:25]:<26}{r['config']:<18}{r['moteur']:<13}"
              f"{r['n_articles']:>5}{total:>13}   {chips:<18}{r['temps_s']:>6}s  {err}")


def _save_csv(rows):
    import pandas as pd
    cols = ["image", "config", "moteur", "n_articles", "total", "chip_lignes",
            "chip_total", "chip_taxe", "chip_equilibre", "temps_s", "erreur"]
    out = Path("data/bench_results.csv")
    pd.DataFrame(rows)[cols].to_csv(out, index=False)
    print(f"\n💾 Résultats sauvegardés dans {out}")


def _interpret(rows):
    """Compare donut_brut vs donut_pretraite par image (le prétraitement aide-t-il ?)."""
    by_image = {}
    for r in rows:
        by_image.setdefault(r["image"], {})[r["config"]] = r
    print("\n=== Interprétation (Donut brut → prétraité) ===")
    for img, cfgs in by_image.items():
        a, b = cfgs.get("donut_brut"), cfgs.get("donut_pretraite")
        if not a or not b:
            continue
        delta = b["n_articles"] - a["n_articles"]
        verdict = ("gain" if delta > 0 else ("perte" if delta < 0 else "aucun changement"))
        print(f"{img:<26} articles {a['n_articles']} → {b['n_articles']}  ({verdict})")
    print("Note : sur une facture hors domaine, seule une config vision (c/d) peut "
          "produire un résultat ; l'échec de Donut y est attendu et documenté.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Banc d'essai extraction (4 configurations).")
    ap.add_argument("--images", default="test_images", help="dossier d'images (défaut: test_images/)")
    ap.add_argument("--country", default="CI", help="pays pour l'audit et le routage (CI/ID)")
    args = ap.parse_args()

    if not Path(args.images).is_dir():
        print(f"Dossier '{args.images}/' introuvable. Déposez-y vos photos de reçus, "
              f"puis relancez :  python scripts/bench_extraction.py --images {args.images}")
        sys.exit(0)
    bench(args.images, country=args.country)
