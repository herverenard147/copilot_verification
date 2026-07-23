"""Le juge : compare des predictions a la verite terrain."""
from src.utils import clean_amount, ensure_list
from src.data_loader import merge_blocks


def get_amount(gt_parse, block, key):
    """Extrait un montant d'un JSON CORD-like. Ex: ('total','total_price')."""
    if not isinstance(gt_parse, dict):
        return None
    d = merge_blocks(gt_parse.get(block))
    vals = ensure_list(d.get(key))
    return clean_amount(vals[0]) if vals else None


def field_accuracy(preds, gts, block, key):
    """% de recus ou le montant predit == le vrai (sur ceux ou le vrai existe)."""
    hits, total = 0, 0
    for p, g in zip(preds, gts):
        truth = get_amount(g, block, key)
        if truth is None:
            continue
        total += 1
        if p is not None and get_amount(p, block, key) == truth:
            hits += 1
    return hits / total if total else None


def valid_json_rate(preds):
    """% de sorties exploitables (un dict non vide)."""
    ok = sum(1 for p in preds if isinstance(p, dict) and p)
    return ok / len(preds) if preds else None
