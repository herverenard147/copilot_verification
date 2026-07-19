# Receipt & Expense Copilot

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-in%20progress-yellow)

> Upload a receipt photo → structured, validated, queryable expenses.

## Table of contents

- [Overview](#overview)
- [Dataset](#dataset)
- [Approach](#approach)
- [Notions covered](#notions-covered)
- [Project structure](#project-structure)
- [Setup](#setup)
- [Ethics](#ethics)
- [Attribution](#attribution)

## Overview

This project turns a photo of a receipt into a clean, structured, and
queryable expense record. The pipeline is:

```
receipt image  →  extracted text  →  structured JSON  →  business rules
              →  expense database  →  natural-language Q&A
```

Everything is wrapped in a **Streamlit** app so a user can drop in a photo,
see the parsed line items, get validation feedback (e.g. totals that don't
add up, missing fields), and then ask questions about their spending in
plain language ("how much did I spend on drinks last week?").

## Dataset

We use **[CORD](https://github.com/clovaai/cord)** (Consolidated Receipt
Dataset), a public dataset of ~1,000 Indonesian receipts released under
**CC BY 4.0**.

Notes on the dataset:

- **Merchant name and date are not present** in the public labels — these
  fields are censored/removed from the released annotations, so any
  extraction of merchant/date has to come from a different source or model
  (or be left out of the structured schema entirely).
- **Number formatting**: amounts use a comma as a **thousands separator**,
  not a decimal separator. So a value written as `"25,000"` means
  **25000**, not 25.000. This matters a lot for any parsing/normalization
  step downstream.

## Approach

- **Donut** (`naver-clova-ix/donut-base-finetuned-cord-v2`), a pre-trained
  OCR-free document understanding model already fine-tuned on CORD, is used
  **as-is** — no additional fine-tuning is performed. It serves as the main
  image → structured JSON extractor.
- A small **hand-trained classifier** is built from scratch as a baseline,
  and its performance is compared against Donut's output. This comparison
  is used to reason about trade-offs between a heavyweight pre-trained
  model and a lightweight custom-trained one.

## Notions covered

This project is built to cover the following bootcamp notions:

- Python & Object-Oriented Programming
- Data wrangling & visualization
- Supervised machine learning & KMeans (clustering)
- A small neural network built from scratch
- Natural Language Processing (NLP)
- Using a pre-trained model (Donut)
- FAISS (vector similarity search)
- Prompt engineering
- Streamlit (interactive app)
- Ethics in ML/AI systems

## Project structure

```
copilot_verification/
├── src/            # Core source code (parsing, rules, models, app logic)
├── notebooks/       # Exploration, experiments, and analysis notebooks
├── data/             # Raw & processed data (git-ignored, kept locally)
├── tests/            # Unit / integration tests
├── app.py             # Streamlit application entry point
├── requirements.txt   # Python dependencies
├── .gitignore
└── README.md
```

## Setup

> Placeholder — instructions to be completed as the project takes shape.

```bash
# Clone the repository
git clone https://github.com/herverenard147/copilot_verification.git
cd copilot_verification

# TODO: create virtual environment, install requirements, run the app
```

## Ethics

- **Geographic bias**: CORD is composed entirely of Indonesian receipts, so
  any model trained or evaluated on it may not generalize well to receipts
  from other countries, currencies, or formatting conventions.
- **Censored fields**: merchant name and date are deliberately removed from
  the public dataset, which limits what can be responsibly inferred or
  displayed about a given receipt without additional user-provided context.
- **Explainability**: the business rules applied on top of the extracted
  data (validation, totals checking, categorization) are kept simple and
  transparent by design, so a user can understand *why* a receipt was
  flagged or how a number was computed, rather than relying on an opaque
  black-box decision.

## Attribution

This project uses the **CORD** dataset — Park, S. et al. (2019),
*"CORD: A Consolidated Receipt Dataset for Post-OCR Parsing"*, released
under **CC BY 4.0**.
