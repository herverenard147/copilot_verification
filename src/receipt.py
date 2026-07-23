"""La classe Receipt : UN recu = UN objet, avec ses donnees et ses calculs."""
from src.utils import clean_amount, ensure_list
from src.data_loader import merge_blocks


class Receipt:
    """Represente un recu normalise.

    Plutot que de trimballer des dictionnaires JSON bruts partout, on cree un
    objet qui SAIT calculer des choses sur lui-meme.
    """

    def __init__(self, items, subtotal=None, tax=None, total=None, receipt_id=None):
        self.receipt_id = receipt_id
        self.items = items
        self.subtotal = subtotal
        self.tax = tax
        self.total = total

    @classmethod
    def from_gt_parse(cls, gt_parse, receipt_id=None):
        """Construit un Receipt depuis un JSON CORD OU une sortie Donut.
        Meme moule pour les deux : c'est ce qui permet de comparer.

        NORMALISATION A LA FRONTIERE (bug E8) : token2json peut renvoyer une
        LISTE a la racine (plusieurs blocs detectes, typique d'une photo
        inclinee avec du fond), ou n'importe quoi d'autre. On normalise ICI,
        au point d'entree, une bonne fois -- plutot que de durcir chaque champ
        localement comme on l'a fait pour menu/sub_total/total. Un recu VIDE
        sort alors sans exception ; les regles repondront None ("non
        verifiable"), ce qui est le comportement correct."""
        if isinstance(gt_parse, list):
            gt_parse = merge_blocks(gt_parse)      # fusionne les blocs en un seul dict
        elif not isinstance(gt_parse, dict):
            gt_parse = {}                          # ni dict ni liste -> recu vide

        items = []
        for it in ensure_list(gt_parse.get("menu")):
            if not isinstance(it, dict):
                continue
            items.append({
                "name": it.get("nm"),
                "quantity": clean_amount(it.get("cnt")),
                "unit_price": clean_amount(it.get("unitprice")),
                "line_price": clean_amount(it.get("price")),
            })
        sub = merge_blocks(gt_parse.get("sub_total"))
        tot = merge_blocks(gt_parse.get("total"))

        def first(x):
            vals = ensure_list(x)
            return vals[0] if vals else None

        return cls(
            items=items,
            subtotal=clean_amount(first(sub.get("subtotal_price"))),
            tax=clean_amount(first(sub.get("tax_price"))),
            total=clean_amount(first(tot.get("total_price"))),
            receipt_id=receipt_id,
        )

    def items_sum(self):
        """Somme des prix de ligne connus."""
        prices = [it["line_price"] for it in self.items if it["line_price"] is not None]
        return sum(prices) if prices else None

    def __repr__(self):
        return (f"Receipt(id={self.receipt_id}, {len(self.items)} articles, "
                f"total={self.total})")
