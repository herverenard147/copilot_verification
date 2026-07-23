"""Transforme les recus CORD en DataFrame pandas exploitable."""
import json
import pandas as pd

from src.utils import clean_amount, ensure_list


def receipt_to_rows(gt_parse, receipt_id):
    """Un recu -> une liste de lignes plates, une par article achete."""
    rows = []
    for item in ensure_list(gt_parse.get("menu")):
        if not isinstance(item, dict):
            continue
        rows.append({
            "receipt_id": receipt_id,
            "item_name": item.get("nm"),
            "quantity": clean_amount(item.get("cnt")),
            "unit_price": clean_amount(item.get("unitprice")),
            "line_price": clean_amount(item.get("price")),
        })
    return rows


def merge_blocks(x):
    """CORD encode parfois sub_total/total comme UNE LISTE de blocs
    (ex: sous-total avant et apres remise). On fusionne en un seul dict ;
    en cas de doublon de cle, le dernier bloc gagne."""
    merged = {}
    for block in ensure_list(x):
        if isinstance(block, dict):
            merged.update(block)
    return merged


def totals_of(gt_parse):
    """Extrait subtotal, tax, total d'un recu."""
    total = merge_blocks(gt_parse.get("total"))
    sub = merge_blocks(gt_parse.get("sub_total"))

    def first(x):
        """Une VALEUR individuelle peut aussi etre une liste."""
        vals = ensure_list(x)
        return vals[0] if vals else None

    return {
        "subtotal": clean_amount(first(sub.get("subtotal_price"))),
        "tax": clean_amount(first(sub.get("tax_price"))),
        "total": clean_amount(first(total.get("total_price"))),
    }


def load_dataframes(split):
    """Split HuggingFace -> (df_items, df_receipts)."""
    all_items, all_receipts = [], []
    for i, ex in enumerate(split):
        gt = json.loads(ex["ground_truth"])["gt_parse"]
        all_items.extend(receipt_to_rows(gt, i))
        all_receipts.append({"receipt_id": i, **totals_of(gt)})
    return pd.DataFrame(all_items), pd.DataFrame(all_receipts)
