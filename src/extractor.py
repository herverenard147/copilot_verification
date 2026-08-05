"""Le pont vers Donut : une image entre, un JSON sort.

Donut "lit" l'image avec un encodeur visuel, puis ECRIT le resultat comme un
texte, token par token, dans un format special que token2json reconvertit en
dictionnaire. Pas besoin d'OCR : le modele lit et structure d'un seul geste.
"""
import re

import torch

# Borne la generation a un nombre de tokens realiste pour un reçu (le JSON
# structure d'un vrai CORD tient largement en dessous). Sans ca, max_length
# vaut model.decoder.config.max_position_embeddings (~768) : sur une image
# de mauvaise qualite ou le modele n'emet pas l'EOS rapidement (hallucination,
# voir E11 dans le journal d'erreurs), la generation va jusqu'au bout de
# cette limite -- ce plafond borne le pire cas de latence sans affecter les
# extractions normales, qui terminent bien avant.
MAX_GENERATION_LENGTH = 512


def extract(image, model, processor, device="cuda"):
    """Image de recu (PIL) -> dict structure (menu, totaux...)."""
    pixel_values = processor(image, return_tensors="pt").pixel_values

    task = "<s_cord-v2>"           # prompt de tache : quel format produire
    decoder_input_ids = processor.tokenizer(
        task, add_special_tokens=False, return_tensors="pt"
    ).input_ids

    max_length = min(MAX_GENERATION_LENGTH, model.decoder.config.max_position_embeddings)
    # torch.no_grad() explicite : generate() le fait deja en interne, mais le
    # rendre explicite ici documente l'intention et protege si du code futur
    # s'ajoute autour de l'appel (aucun cout, jamais de regression possible).
    with torch.no_grad():
        outputs = model.generate(
            pixel_values.to(device),
            decoder_input_ids=decoder_input_ids.to(device),
            max_length=max_length,
            pad_token_id=processor.tokenizer.pad_token_id,
            eos_token_id=processor.tokenizer.eos_token_id,
            use_cache=True,
            bad_words_ids=[[processor.tokenizer.unk_token_id]],
            return_dict_in_generate=True,
        )

    seq = processor.batch_decode(outputs.sequences)[0]
    seq = seq.replace(processor.tokenizer.eos_token, "")
    seq = seq.replace(processor.tokenizer.pad_token, "")
    seq = re.sub(r"<.*?>", "", seq, count=1).strip()
    return processor.token2json(seq)
