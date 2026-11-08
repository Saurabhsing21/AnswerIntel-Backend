"""Pick random stored answers and write them to a JSONL file for a person to label.

    cd backend && .venv/bin/python -m scripts.export_answers_for_labelling --n 200 --out labelling.jsonl

Each line holds one answer, the brand and competitor names to judge, and an empty label for each. Fill the labels from
the answer text alone, then score them with scripts.eval_analysis (see docs/analysis-accuracy.md).
"""

import argparse
import json
from pathlib import Path

from sqlalchemy import func, select

# What a person fills in for one brand. null everywhere = not labelled yet.
EMPTY_LABEL = {"mentioned": None, "recommended": None, "position": None, "sentiment": None}


def labelling_row(response_id: int, engine: str | None, prompt: str, answer: str, brand: str, aliases: list[str], competitors: list[dict]) -> dict:
    """`competitors`: [{"name", "aliases"}]. Labels are keyed by the tracked name, brand first."""
    names = [brand, *[c["name"] for c in competitors]]
    return {
        "response_id": response_id,
        "engine": engine,
        "prompt": prompt,
        "answer": answer,
        "brand": brand,
        "aliases": aliases,
        "competitors": competitors,
        "labels": {name: dict(EMPTY_LABEL) for name in names},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=200, help="how many answers to export (default 200)")
    parser.add_argument("--out", default="labelling.jsonl", help="file to write (default labelling.jsonl)")
    parser.add_argument("--force", action="store_true", help="overwrite the file if it exists (it may hold labels)")
    args = parser.parse_args(argv)

    out = Path(args.out)
    if out.exists() and not args.force:
        print(f"{out} already exists and may hold labels. Pick another --out or pass --force.")
        return 1

    from app.analysis.models import Mention
    from app.common.database import SessionLocal
    from app.competitors.models import Competitor
    from app.projects.models import Project
    from app.providers.response_model import AIResponseRecord
    from app.scans.models import Scan

    rows = []
    with SessionLocal() as session:
        picked = session.execute(
            select(AIResponseRecord, Project)
            .join(Scan, Scan.id == AIResponseRecord.scan_id)
            .join(Project, Project.id == Scan.project_id)
            .where(AIResponseRecord.id.in_(select(Mention.ai_response_id)), AIResponseRecord.response_text != "")
            .order_by(func.random())
            .limit(args.n)
        ).all()
        for record, project in picked:
            competitors = session.scalars(select(Competitor).where(Competitor.project_id == project.id).order_by(Competitor.id)).all()
            rows.append(labelling_row(
                record.id, record.engine, record.prompt, record.response_text, project.brand_name.strip(), project.aliases or [],
                [{"name": c.name, "aliases": c.aliases or []} for c in competitors],
            ))

    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"Wrote {len(rows)} answers to {out}. Fill in every \"labels\" entry, then run scripts.eval_analysis.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
