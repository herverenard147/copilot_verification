# a lancer une fois, exporte 3 images CORD en pleine resolution
from datasets import load_dataset
ds = load_dataset("naver-clova-ix/cord-v2")
for i in [10, 45, 80, 90, 20, 79]:   # indices "neufs", hors ceux deja evalues
    ds["test"][i]["image"].save(f"test_images/indonesien_haute_res_{i}.jpg")
