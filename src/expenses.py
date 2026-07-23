"""Construit la base de depenses a partir des recus CORD."""
import json
import pandas as pd

from src.receipt import Receipt
from src.rules import audit


def build_expense_db(split, limit=None):
    """Split HuggingFace -> (df_items, df_receipts) enrichis des audits."""
    items, receipts = [], []
    for i, ex in enumerate(split):
        if limit and i >= limit:
            break
        gt = json.loads(ex["ground_truth"])["gt_parse"]
        r = Receipt.from_gt_parse(gt, receipt_id=i)

        for it in r.items:
            items.append({"receipt_id": i, **it})

        flags = audit(r)
        receipts.append({
            "receipt_id": i,
            "n_items": len(r.items),
            "items_sum": r.items_sum(),
            "subtotal": r.subtotal,
            "tax": r.tax,
            "total": r.total,
            **flags,
        })
    return pd.DataFrame(items), pd.DataFrame(receipts)


def receipt_text(gt_full):
    """Reconstruit le texte brut d'un recu depuis valid_line."""
    words = []
    for line in gt_full.get("valid_line", []):
        words.extend(w["text"] for w in line.get("words", []))
    return " ".join(words)
