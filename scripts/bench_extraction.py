"""Banc d'essai de l'extraction : 4 configurations par image, avec CONTROLE DE
PLAUSIBILITE (bugs E10/E11).

Pour chaque photo de test_images/, on compare :
  (a) donut_brut         : Donut sur l'image brute
  (b) donut_pretraite    : Donut sur l'image prétraitée (redressement+CLAHE)
  (c) vision_seul        : LLM vision Groq seul (nécessite GROQ_API_KEY)
  (d) pipeline_complet   : prétraitement + routage automatique (= /api/extract :
                            Donut, puis fallback vision si sortie vide ou pays CI)

GARDE-FOU DE RESOLUTION (E10) : une image sous ~0.3 Mpx est REJETEE avant toute
extraction. En dessous, il n'y a plus assez de pixels pour lire : le modèle
génère du texte plausible sur du flou (idéogrammes, prix inventés). Le premier
bench utilisait des vignettes (0.04-0.15 Mpx) : ses conclusions sont nulles.

CONTROLE DE PLAUSIBILITE (E11) : compter les articles récompensait
l'hallucination. On ajoute donc une colonne `plausible` par résultat, False si :
  - beaucoup d'articles sur une image basse résolution (invraisemblable),
  - la magnitude total/lignes est aberrante (R9, check_magnitude),
  - des caractères hors jeu attendu (CJK, symboles) apparaissent dans les noms.
Un crop qui "extrait 7 articles" faits d'idéogrammes est PIRE que 0 article honnête.

Sortie : tableau lisible en console + data/bench_results.csv.

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

from src.preprocess import preprocess_image, resolution_info, MIN_PIXELS
from src.receipt import Receipt
from src.rules import audit, check_magnitude
from src.accounting import journal_entry, is_balanced

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
CHIP = {True: "✅", False: "❌", None: "➖"}
PLAUSIBLE_LABEL = {True: "oui", False: "NON (hallu?)", None: "—"}
CONFIGS = ["donut_brut", "donut_pretraite", "vision_seul", "pipeline_complet"]

# Plages Unicode qui n'ont RIEN a faire sur un recu indonesien/ivoirien : leur
# presence dans un nom d'article trahit une hallucination du modele generatif.
_SUSPICIOUS_RANGES = [
    (0x3000, 0x303F),   # ponctuation CJK
    (0x3040, 0x30FF),   # hiragana / katakana
    (0x3400, 0x4DBF),   # CJK extension A
    (0x4E00, 0x9FFF),   # CJK unifie (ideogrammes)
    (0xAC00, 0xD7AF),   # hangul
    (0xF900, 0xFAFF),   # CJK compatibilite
]


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
    """Les chips affiches : lignes, total, taxe, magnitude, equilibre."""
    flags = audit(receipt, country=country)
    try:
        entry = journal_entry(receipt, category=None, country=country)
        balanced = is_balanced(entry) if entry else None
    except (ValueError, KeyError):
        balanced = None
    return {
        "line_sum_ok": flags["line_sum_ok"], "total_ok": flags["total_ok"],
        "tax_ok": flags["tax_ok"], "magnitude_ok": flags["magnitude_ok"],
        "balanced": balanced,
    }


def _has_suspicious_chars(names):
    for name in names:
        for ch in str(name or ""):
            code = ord(ch)
            if any(lo <= code <= hi for lo, hi in _SUSPICIOUS_RANGES):
                return True
    return False


def assess_plausibility(receipt, n_articles, source_mpx):
    """Le resultat ressemble-t-il a une vraie lecture ? Renvoie (plausible,
    motifs). plausible=None si aucun resultat (rien a juger)."""
    if n_articles == 0 and receipt.total is None:
        return None, []
    reasons = []
    if source_mpx < (MIN_PIXELS / 1e6) and n_articles > 3:
        reasons.append("beaucoup d'articles sur image basse résolution")
    if check_magnitude(receipt) is False:
        reasons.append("magnitude total/lignes aberrante")
    if _has_suspicious_chars(it.get("name") for it in receipt.items):
        reasons.append("caractères hors jeu attendu (CJK/symboles)")
    return (len(reasons) == 0), reasons


def _empty(receipt):
    return (not receipt.items) and (receipt.total is None)


def run_config(config, base_img, pre_img, donut, country, source_mpx):
    """Execute une des 4 configurations, renvoie un dict de resultats + timing
    + plausibilite."""
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

    c = chips_of(receipt, country)
    plausible, motifs = assess_plausibility(receipt, len(receipt.items), source_mpx)
    return {
        "config": config, "moteur": engine, "megapixels": source_mpx,
        "n_articles": len(receipt.items), "total": receipt.total,
        "chip_lignes": c["line_sum_ok"], "chip_total": c["total_ok"],
        "chip_taxe": c["tax_ok"], "chip_magnitude": c["magnitude_ok"],
        "chip_equilibre": c["balanced"],
        "plausible": plausible, "plausible_motifs": "; ".join(motifs),
        "temps_s": round(dt, 2), "erreur": err,
    }


def _rejected_row(name, res):
    """Ligne unique pour une image rejetee par le garde-fou de resolution :
    pas d'extraction du tout -> impossible d'halluciner (c'est le but)."""
    return {
        "image": name, "config": "(rejeté)", "moteur": "rejeté",
        "megapixels": res["megapixels"], "n_articles": 0, "total": None,
        "chip_lignes": None, "chip_total": None, "chip_taxe": None,
        "chip_magnitude": None, "chip_equilibre": None,
        "plausible": None, "plausible_motifs": "",
        "temps_s": 0.0,
        "erreur": (f"résolution {res['megapixels']} Mpx < {res['min_megapixels']} "
                   f"(rejeté avant extraction)"),
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

        res = resolution_info(base)
        if not res["ok"]:
            # Garde-fou E10 : trop basse resolution -> rejet, PAS d'extraction.
            print(f"🚫 {path.name} : {res['megapixels']} Mpx < seuil — rejetée (pas halluciné).")
            rows.append(_rejected_row(path.name, res))
            continue

        pre, _ = preprocess_image(base)
        for config in CONFIGS:
            r = run_config(config, base, pre, donut, country, res["megapixels"])
            r["image"] = path.name
            rows.append(r)

    _print_table(rows)
    _save_csv(rows)
    _interpret(rows)
    return rows


def _print_table(rows):
    hdr = (f"{'image':<26}{'config':<17}{'moteur':<12}{'Mpx':>6}{'art.':>5}{'total':>13}"
           f"  {'L/T/Tx/Mg/Éq':<13}{'plausible':<14}{'temps':>7}  erreur")
    print("\n" + hdr)
    print("-" * len(hdr))
    for r in rows:
        chips = (f"{CHIP[r['chip_lignes']]}{CHIP[r['chip_total']]}{CHIP[r['chip_taxe']]}"
                 f"{CHIP[r['chip_magnitude']]}{CHIP[r['chip_equilibre']]}")
        total = "—" if r["total"] is None else f"{r['total']:,.0f}".replace(",", " ")
        plausible = PLAUSIBLE_LABEL[r["plausible"]]
        print(f"{r['image'][:25]:<26}{r['config']:<17}{r['moteur']:<12}"
              f"{r['megapixels']:>6}{r['n_articles']:>5}{total:>13}  {chips:<13}"
              f"{plausible:<14}{r['temps_s']:>6}s  {r['erreur'] or ''}")


def _save_csv(rows):
    import pandas as pd
    cols = ["image", "config", "moteur", "megapixels", "n_articles", "total",
            "chip_lignes", "chip_total", "chip_taxe", "chip_magnitude",
            "chip_equilibre", "plausible", "plausible_motifs", "temps_s", "erreur"]
    out = Path("data/bench_results.csv")
    pd.DataFrame(rows)[cols].to_csv(out, index=False)
    print(f"\n💾 Résultats sauvegardés dans {out}")


def _interpret(rows):
    """Interpretation HONNETE, par image : le pretraitement aide-t-il DANS le
    domaine, et le resultat est-il une vraie lecture ou une hallucination ?"""
    by_image = {}
    for r in rows:
        by_image.setdefault(r["image"], []).append(r)

    print("\n=== Interprétation honnête (E10/E11) ===")
    for img, results in by_image.items():
        if any(r["config"] == "(rejeté)" for r in results):
            print(f"{img:<26} 🚫 rejetée (résolution insuffisante) — rejet propre, PAS d'hallucination.")
            continue

        a = next((r for r in results if r["config"] == "donut_brut"), None)
        b = next((r for r in results if r["config"] == "donut_pretraite"), None)

        # verdict hallucination : au moins une config non-plausible ?
        hallu = [r for r in results if r["plausible"] is False]
        verdict = ""
        if hallu:
            motifs = "; ".join(sorted({m for r in hallu for m in (r["plausible_motifs"].split("; ") if r["plausible_motifs"] else [])}))
            verdict = f" ⚠️ HALLUCINATION PROBABLE ({motifs})"

        if a and b:
            da = b["n_articles"] - a["n_articles"]
            # un gain d'articles ne compte QUE si le resultat prétraité reste plausible
            if b["plausible"] is False:
                pretr = "prétraitement NON concluant (résultat non plausible)"
            elif da > 0:
                pretr = f"prétraitement +{da} article(s) plausible(s)"
            elif da < 0:
                pretr = f"prétraitement {da} article(s)"
            else:
                pretr = "prétraitement sans effet sur le nb d'articles"
            print(f"{img:<26} {pretr}{verdict}")
        else:
            print(f"{img:<26}{verdict or ' (pas de comparaison brut/prétraité)'}")

    print("\nRappel méthodo : le nombre d'articles seul ne mesure RIEN sans le "
          "contrôle de plausibilité — compter des idéogrammes inventés récompenserait "
          "l'hallucination (E11). Un résultat non plausible n'est pas une extraction.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Banc d'essai extraction (4 configurations + plausibilité).")
    ap.add_argument("--images", default="test_images", help="dossier d'images (défaut: test_images/)")
    ap.add_argument("--country", default="CI", help="pays pour l'audit et le routage (CI/ID)")
    args = ap.parse_args()

    if not Path(args.images).is_dir():
        print(f"Dossier '{args.images}/' introuvable. Déposez-y vos photos de reçus, "
              f"puis relancez :  python scripts/bench_extraction.py --images {args.images}")
        sys.exit(0)
    bench(args.images, country=args.country)
