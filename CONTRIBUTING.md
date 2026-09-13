# Contributing

Thanks for considering a contribution! This started as a college mini-project
and is now open for improvements.

## Ways to contribute

- **Bug fixes** — open an issue first if the fix isn't obvious, otherwise just send a PR.
- **New fraud patterns** — add a new subtype to `scripts/generate_dataset.py` and retrain.
- **Model improvements** — new features, better weighting between Random Forest
  and Isolation Forest, or an entirely new model, as long as `scripts/train_models.py`
  still writes evaluation metrics to `models/evaluation_report.md`.
- **Frontend/UX** — `frontend/index.html` is intentionally dependency-free; keep it that way
  unless there's a good reason to add a build step.
- **Documentation** — clarifications, typo fixes, and better setup instructions are always welcome.

## Development setup

```bash
git clone <your-fork-url>
cd upi-fraud-project/backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Open `frontend/index.html` in a browser separately — no build step required.

## Before submitting a PR

- Run `python -m py_compile` on any Python file you changed (or let CI catch it).
- If you touched the dataset generator or training script, re-run both and update
  `models/evaluation_report.md` with the new numbers.
- Keep PRs focused — one fix or feature per PR is easier to review.

## Code of conduct

Be respectful. Assume good intent. Disagree about code, not people.
