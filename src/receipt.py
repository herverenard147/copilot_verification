"""La classe Receipt : UN recu = UN objet, avec ses donnees et ses calculs."""
import math
import re

from src.utils import clean_amount, ensure_list
from src.data_loader import merge_blocks


# Numero de facture dans du texte DEJA extrait (pas une nouvelle extraction).
# Marqueur (facture / n° / no / number / numero / #) suivi d'un numero.
_INVOICE_NUMBER_RE = re.compile(
    r"(?:facture|invoice|num[ée]ro|number|n[°o]?|#)\s*[°:.#\-]?\s*(\d[\w/\-]*)",
    re.IGNORECASE,
)


def find_invoice_number(text):
    """Cherche un numero de facture dans du texte deja extrait (regex simple,
    insensible a la casse). Renvoie le numero (str) ou None si absent -- aucun
    echec : pas de numero = pas de numero affiche."""
    if not text:
        return None
    m = _INVOICE_NUMBER_RE.search(text)
    return m.group(1) if m else None


def filter_invoice_headers(items):
    """Post-traitement FACTURE (regles simples, PAS un modele appris).

    Retire les lignes du PREMIER TIERS de la liste extraite qui n'ont NI prix
    NI quantite. Sur une facture, l'en-tete (nom, adresse, email) est souvent
    capte comme des 'articles' sans montant. Heuristique volontairement simple :
    la position dans l'ordre de lecture sert de proxy du tiers vertical (Donut
    ne fournit aucune coordonnee), combinee a l'absence de montant.

    Le mode 'ticket de caisse' n'appelle JAMAIS cette fonction -> son
    comportement reste strictement identique. Limite assumee : une ligne
    d'en-tete a laquelle Donut a mal rattache un prix ne sera pas retiree
    (elle 'a un montant')."""
    if not items:
        return items
    cutoff = math.ceil(len(items) / 3)      # premier tiers, ordre de lecture
    return [it for i, it in enumerate(items)
            if not (i < cutoff
                    and it.get("line_price") is None
                    and it.get("unit_price") is None
                    and it.get("quantity") is None)]


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
