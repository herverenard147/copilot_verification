# diagnostic_crop.py — à lancer depuis la racine du projet
import sys
sys.path.append(".")
from PIL import Image
import torch
from transformers import DonutProcessor, VisionEncoderDecoderModel
from src.extractor import extract

MODEL = "naver-clova-ix/donut-base-finetuned-cord-v2"
proc = DonutProcessor.from_pretrained(MODEL)
model = VisionEncoderDecoderModel.from_pretrained(MODEL)
device = "cuda" if torch.cuda.is_available() else "cpu"
model.to(device)

img = Image.open("test_images/receipt-shopping-mini-market-indonesia-260nw-2352129737.jpg").convert("RGB")  # ajuste le nom
W, H = img.size
print(f"Image d'origine : {W}x{H}\n")

variantes = {
    "1. Originale":            img,
    "2. Crop central 70%":     img.crop((int(W*.15), int(H*.15), int(W*.85), int(H*.85))),
    "3. Crop central 50%":     img.crop((int(W*.25), int(H*.25), int(W*.75), int(H*.75))),
    "4. Rotation -30°":        img.rotate(-30, expand=True, fillcolor=(255,255,255)),
    "5. Rotation +30°":        img.rotate(30, expand=True, fillcolor=(255,255,255)),
    "6. Crop 50% + rot -30°":  img.crop((int(W*.25), int(H*.25), int(W*.75), int(H*.75))
                                  ).rotate(-30, expand=True, fillcolor=(255,255,255)),
}

for nom, v in variantes.items():
    try:
        r = extract(v, model, processor=proc, device=device)
        menu = r.get("menu") if isinstance(r, dict) else None
        n = len(menu) if isinstance(menu, list) else (1 if menu else 0)
        print(f"{nom:26s} → {n} article(s)   {str(r)[:110]}")
    except Exception as e:
        print(f"{nom:26s} → ÉCHEC {type(e).__name__}")
