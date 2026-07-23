"""Le pont vers Donut : une image entre, un JSON sort."""
import re
import torch


def extract(image, model, processor, device="cuda"):
    """Image de recu (PIL) -> dict structure (menu, totaux...)."""
    # 1. Preparer l'image comme le modele l'attend
    pixel_values = processor(image, return_tensors="pt").pixel_values

    # 2. Le "prompt de tache" : dit a Donut quel format produire
    task = "<s_cord-v2>"
    decoder_input_ids = processor.tokenizer(
        task, add_special_tokens=False, return_tensors="pt"
    ).input_ids

    # 3. Generation, token par token
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

    # 4. Nettoyer la sequence et la convertir en JSON
    seq = processor.batch_decode(outputs.sequences)[0]
    seq = seq.replace(processor.tokenizer.eos_token, "")
    seq = seq.replace(processor.tokenizer.pad_token, "")
    seq = re.sub(r"<.*?>", "", seq, count=1).strip()  # retire le prompt
    return processor.token2json(seq)
