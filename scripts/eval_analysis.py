"""How accurate is our answer analysis? Score it against answers a person has labelled.

    cd backend && .venv/bin/python -m scripts.eval_analysis labelling.jsonl              # runs the analysis model (paid AI calls)
    cd backend && .venv/bin/python -m scripts.eval_analysis labelling.jsonl --model openai/gpt-5.4-mini
    cd backend && .venv/bin/python -m scripts.eval_analysis labelling.jsonl --dry-run    # scores the verdicts already stored, no AI calls

The input is the file written by scripts.export_answers_for_labelling, with labels filled in. A brand counts as labelled once
its "mentioned" is true or false. Then "recommended" must be true or false, and for a mentioned brand "sentiment" must be
"positive", "neutral" or "negative" ("position" is its rank in a numbered list, or null).
"""

import argparse
import json
from pathlib import Path

FIELDS = ("mentioned", "recommended", "position", "sentiment")
SENTIMENTS = ("positive", "neutral", "negative")
RECOMMENDED_MIN_ACCURACY = 0.90
FALLBACK_MODEL = "openai/gpt-5.4-mini"


def usable_label(label: dict) -> dict | None:
    """The label as the analysis would report it, None while it is not labelled, ValueError while it is half filled in."""
    mentioned = label.get("mentioned")
    if mentioned is None:
        return None
    if not mentioned:  # an absent brand is not recommended, ranked or described
        return {"mentioned": False, "recommended": False, "position": None, "sentiment": None}
    recommended, position, sentiment = label.get("recommended"), label.get("position"), label.get("sentiment")
    if not isinstance(recommended, bool):
        raise ValueError('"recommended" must be true or false')
    if position is not None and (not isinstance(position, int) or isinstance(position, bool) or position < 1):
        raise ValueError('"position" must be a number from 1 or null')
    if sentiment not in SENTIMENTS:
        raise ValueError('"sentiment" must be "positive", "neutral" or "negative"')
    return {"mentioned": True, "recommended": recommended, "position": position, "sentiment": sentiment}


def _positive(value) -> bool:
    return value is not None and value is not False


def score(items: list[dict]) -> dict:
    """items: [{"id", "brand", "label": usable_label(...), "predicted": {"mentioned", ...}}].

    Per field: accuracy = exact matches / items. "Positive" means true for mentioned and recommended, and any value for
    position and sentiment. Precision = right positives / predicted positives, recall = right positives / labelled positives
    (None when there are none). Also returns every disagreement."""
    fields: dict[str, dict] = {}
    disagreements: list[dict] = []
    for field in FIELDS:
        matches = predicted_pos = labelled_pos = right_pos = 0
        for item in items:
            want, got = item["label"][field], item["predicted"].get(field)
            matches += want == got
            predicted_pos += _positive(got)
            labelled_pos += _positive(want)
            right_pos += _positive(want) and want == got
            if want != got:
                disagreements.append({"id": item["id"], "brand": item["brand"], "field": field, "labelled": want, "predicted": got})
        fields[field] = {
            "n": len(items),
            "accuracy": matches / len(items) if items else None,
            "precision": right_pos / predicted_pos if predicted_pos else None,
            "recall": right_pos / labelled_pos if labelled_pos else None,
        }
    return {"fields": fields, "disagreements": disagreements}


def predictions_from_result(result: dict) -> dict[str, dict]:
    """ResponseAnalysisService.analyze() output as {tracked name: verdict}."""
    brand = {
        "mentioned": result["mention"]["mentioned"], "recommended": result["recommendation"]["recommended"],
        "position": result["position"]["position"], "sentiment": result["sentiment"]["sentiment"],
    }
    found = {result["mention"]["brand_name"]: brand}
    for c in result["competitors"]:
        found[c["competitor_name"]] = {f: c[f] for f in FIELDS}
    return found


def report(result: dict, model: str | None) -> str:
    def cell(v):
        return "-" if v is None else f"{v:.1%}"

    lines = [f"Analysis accuracy ({model or 'stored verdicts'})", f"{'field':<12}{'n':>6}{'accuracy':>11}{'precision':>11}{'recall':>9}"]
    for field, s in result["fields"].items():
        lines.append(f"{field:<12}{s['n']:>6}{cell(s['accuracy']):>11}{cell(s['precision']):>11}{cell(s['recall']):>9}")
    lines += ["", f"Disagreements: {len(result['disagreements'])}"]
    lines += [
        f"  answer {d['id']} | {d['brand']} | {d['field']}: labelled {d['labelled']!r}, analysis said {d['predicted']!r}"
        for d in result["disagreements"]
    ]
    recommended = result["fields"]["recommended"]["accuracy"]
    if recommended is not None and recommended < RECOMMENDED_MIN_ACCURACY:
        lines += ["", f"recommended accuracy is below {RECOMMENDED_MIN_ACCURACY:.0%}: switch ANALYSIS_MODEL to {FALLBACK_MODEL} "
                  "and re-check the credit weights (docs/analysis-accuracy.md)."]
    return "\n".join(lines)


def _stored(session, response_id: int) -> dict[str, dict]:
    from sqlalchemy import select

    from app.analysis.models import CompetitorObservation, Mention
    from app.competitors.models import Competitor

    found = {}
    mention = session.scalar(select(Mention).where(Mention.ai_response_id == response_id))
    if mention:
        found[mention.brand_name] = {f: getattr(mention, f) for f in FIELDS}
    for obs, name in session.execute(
        select(CompetitorObservation, Competitor.name)
        .join(Competitor, Competitor.id == CompetitorObservation.competitor_id)
        .where(CompetitorObservation.ai_response_id == response_id)
    ):
        found[name] = {f: getattr(obs, f) for f in FIELDS}
    return found


def _analysed(row: dict) -> dict[str, dict] | None:
    from app.analysis.base import AnalysisContext
    from app.analysis.service import ResponseAnalysisService

    context = AnalysisContext(
        brand_name=row["brand"], aliases=row.get("aliases") or [], prompt=row.get("prompt", ""),
        competitors=[{"id": i, "name": c["name"], "aliases": c.get("aliases") or []} for i, c in enumerate(row["competitors"])],
    )
    result = ResponseAnalysisService(use_llm=True).analyze(row["answer"], context)
    return predictions_from_result(result) if result["method"] == "llm" else None  # None: the AI call failed and rules answered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("labelled", help="the labelled JSONL file")
    parser.add_argument("--model", help="analysis model to test (default: ANALYSIS_MODEL from settings)")
    parser.add_argument("--dry-run", action="store_true", help="score the verdicts already stored; makes no AI calls")
    args = parser.parse_args(argv)

    from app.common.config import settings

    if args.model:
        settings.analysis_model = args.model
    model = None if args.dry_run else settings.analysis_model
    session = None
    if args.dry_run:
        from app.common.database import SessionLocal

        session = SessionLocal()

    items, skipped, failed = [], [], 0
    try:
        for line in Path(args.labelled).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            labelled = {}
            for name, label in row["labels"].items():
                try:
                    if (usable := usable_label(label)) is not None:
                        labelled[name] = usable
                except ValueError as exc:
                    skipped.append(f"answer {row['response_id']} | {name}: {exc}")
            if not labelled:
                continue
            predicted = _stored(session, row["response_id"]) if session else _analysed(row)
            if predicted is None:
                failed += 1
                continue
            for name, label in labelled.items():
                if name in predicted:
                    items.append({"id": row["response_id"], "brand": name, "label": label, "predicted": predicted[name]})
                else:
                    skipped.append(f"answer {row['response_id']} | {name}: no stored verdict")
    finally:
        if session:
            session.close()

    print(report(score(items), model))
    if skipped:
        print("\nSkipped:\n" + "\n".join(f"  {s}" for s in skipped))
    if failed:
        print(f"\n{failed} answers were left out because the AI call failed (check OPENROUTER_API_KEY and the model name).")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
