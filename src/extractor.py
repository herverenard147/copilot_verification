"""Le pont vers Donut : une image entre, un JSON sort.

Donut "lit" l'image avec un encodeur visuel, puis ECRIT le resultat comme un
texte, token par token, dans un format special que token2json reconvertit en
dictionnaire. Pas besoin d'OCR : le modele lit et structure d'un seul geste.
"""
import re


def extract(image, model, processor, device="cuda"):
    """Image de recu (PIL) -> dict structure (menu, totaux...)."""
    pixel_values = processor(image, return_tensors="pt").pixel_values

    task = "<s_cord-v2>"           # prompt de tache : quel format produire
    decoder_input_ids = processor.tokenizer(
        task, add_special_tokens=False, return_tensors="pt"
    ).input_ids

    outputs = model.generate(
        pixel_values.to(device),
        decoder_input_ids=decoder_input_ids.to(device),
        max_length=model.decoder.config.max_position_embeddings,
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
