# Analysis accuracy check

Every stored answer is read by the analysis model (`ANALYSIS_MODEL`), which decides for each tracked brand whether it was
mentioned, recommended, at which rank, and how the answer talks about it. This check measures how often those verdicts
agree with a person reading the same answers. Run it before changing `ANALYSIS_MODEL`, the analysis prompt, or the credit
weights, and whenever mention or recommendation numbers look off.

## Steps

All commands run from `backend/`.

1. **Export answers.** Picks random stored answers (default 200) and writes one JSON line per answer, with the brand and
   competitor names and an empty label for each.

   ```bash
   .venv/bin/python -m scripts.export_answers_for_labelling --n 200 --out labelling.jsonl
   ```

   It refuses to overwrite an existing file (it may hold labels) unless you pass `--force`.

2. **Label them.** For every name under `labels`, read the `answer` and fill in:

   | field | value |
   |---|---|
   | `mentioned` | `true` if the answer names the brand (or one of its `aliases`), else `false` |
   | `recommended` | `true` if the answer tells the reader to choose it or lists it among its picks; a passing mention is `false` |
   | `position` | its number in an explicit numbered list, otherwise `null` |
   | `sentiment` | `"positive"`, `"neutral"` or `"negative"` for how the answer talks about that brand |

   Label from the answer text alone. If `mentioned` is `false`, leave the rest as `null`. A brand with `mentioned` left
   `null` is treated as not labelled and ignored. Label at least 100 answers; with fewer, one wrong label moves the
   percentages too much.

3. **Score the model.** This calls the analysis model once per labelled answer, so it costs money (about as much as
   analysing that many answers in a scan).

   ```bash
   .venv/bin/python -m scripts.eval_analysis labelling.jsonl                              # the model in ANALYSIS_MODEL
   .venv/bin/python -m scripts.eval_analysis labelling.jsonl --model openai/gpt-5.4-mini  # try another model
   .venv/bin/python -m scripts.eval_analysis labelling.jsonl --dry-run                    # the verdicts already stored, no AI calls
   ```

   It prints accuracy, precision and recall for `mentioned`, `recommended`, `position` and `sentiment`, then every
   disagreement (answer id, brand, field, what you labelled, what the analysis said). For `mentioned` and `recommended`,
   precision and recall are about the `true` value. For `position` and `sentiment` a verdict is a hit only when it equals
   your label exactly. Answers whose AI call failed are left out and counted, so a missing key cannot pass for an accurate
   run.

## Decision rule

If **`recommended` accuracy is below 90%**, switch `ANALYSIS_MODEL` to `openai/gpt-5.4-mini`, run step 3 again on the same
file, and re-check the credit weights (`backend/app/billing/plans.py` and `frontend/lib/billing/plans.ts`), because the
analysis call is part of what each answer costs us. Keep the new model only if its `recommended` accuracy is clearly higher.
The disagreement list shows what kind of mistake it makes (for example, calling a passing mention a recommendation); fixing
the prompt may be cheaper than changing the model.
