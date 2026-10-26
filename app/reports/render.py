"""Report exports. Every value that reaches HTML is escaped: brand and competitor names are user input."""

from html import escape

from fpdf import FPDF

LIGHT = "#f7f7f7"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{round(value * 100)}%"


def _position(value: float | None) -> str:
    return "n/a" if value is None else f"#{value:g}"


def render_html(content: dict, title: str) -> str:
    v = content["visibility"]
    stats = [
        ("Mention rate", _pct(v["mention_rate"])),
        ("Recommendation rate", _pct(v["recommendation_rate"])),
        ("Share of voice", _pct(v["share_of_voice"])),
        ("Citation rate", _pct(v["citation_rate"])),
    ]
    tiles = "".join(
        f'<div class="tile"><div class="label">{escape(label)}</div><div class="value">{escape(value)}</div></div>'
        for label, value in stats
    )
    summary = "".join(f"<li>{escape(line)}</li>" for line in content["summary"])
    rows = "".join(
        f"<tr><td>{escape(c['name'])}{' (you)' if c['is_you'] else ''}</td><td>{_pct(c['mention_rate'])}</td>"
        f"<td>{_pct(c['recommendation_rate'])}</td><td>{_pct(c['share_of_voice'])}</td>"
        f"<td>{_position(c['average_position'])}</td></tr>"
        for c in content["competitors"]
    )
    effort = {"S": "quick win", "M": "a few hours", "L": "a bigger project"}
    week = content.get("this_week")  # reports made before the weekly plan existed only have top_opportunities
    actions = "".join(
        f"<li><strong>{escape(o['title'])}</strong>{' (done)' if o['status'] == 'completed' else ''}"
        f" <span style=\"color:#666\">· {effort.get(o['effort'] or '', '')}</span>"
        f"<ul>{''.join(f'<li>{escape(step)}</li>' for step in o['steps'])}</ul></li>"
        for o in week
    ) if week else "".join(
        f"<li><strong>{escape(o['title'])}</strong><br>{escape(o['recommended_action'])}</li>"
        for o in content["top_opportunities"]
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<style>
body{{font-family:system-ui,sans-serif;background:{LIGHT};color:#111;margin:0;padding:32px 16px}}
main{{max-width:760px;margin:0 auto;background:#fff;border:1px solid #e5e5e5;border-radius:12px;padding:32px}}
h1{{font-size:24px;margin:0 0 4px}} h2{{font-size:16px;margin:28px 0 8px}} .sub{{color:#737373;margin:0 0 24px}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}}
.tile{{border:1px solid #e5e5e5;border-radius:8px;padding:12px}} .label{{color:#737373;font-size:12px}}
.value{{font-size:26px;font-weight:600}} table{{width:100%;border-collapse:collapse;font-size:14px}}
th,td{{text-align:left;padding:8px;border-bottom:1px solid #eee}} li{{margin-bottom:8px}}
</style></head><body><main>
<h1>{escape(title)}</h1><p class="sub">{escape(content['website'])} &middot; {escape(content['category'])}</p>
<div class="tiles">{tiles}</div>
<h2>Summary</h2><ul>{summary}</ul>
<h2>Competitors</h2>
<table><tr><th>Brand</th><th>Mention</th><th>Recommended</th><th>Share of voice</th><th>Avg. position</th></tr>{rows}</table>
<h2>This week&#39;s 3 actions</h2><ol>{actions or '<li>No open opportunities.</li>'}</ol>
</main></body></html>"""


def _latin1(text: str) -> str:
    # The built-in PDF fonts are Latin-1 only; replace anything else instead of crashing.
    return text.encode("latin-1", "replace").decode("latin-1")


def render_pdf(content: dict, title: str) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.multi_cell(0, 10, _latin1(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 6, _latin1(f"{content['website']} - {content['category']}"), new_x="LMARGIN", new_y="NEXT")

    def heading(text: str) -> None:
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 12)
        pdf.multi_cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)

    v = content["visibility"]
    heading("Visibility")
    for label, key in (("Mention rate", "mention_rate"), ("Recommendation rate", "recommendation_rate"),
                       ("Share of voice", "share_of_voice"), ("Citation rate", "citation_rate")):
        pdf.multi_cell(0, 6, f"{label}: {_pct(v[key])}", new_x="LMARGIN", new_y="NEXT")
    heading("Summary")
    for line in content["summary"]:
        pdf.multi_cell(0, 6, _latin1(f"- {line}"), new_x="LMARGIN", new_y="NEXT")
    heading("Competitors")
    for c in content["competitors"]:
        name = c["name"] + (" (you)" if c["is_you"] else "")
        pdf.multi_cell(
            0, 6, _latin1(f"{name}: mention {_pct(c['mention_rate'])}, recommended {_pct(c['recommendation_rate'])}, "
                          f"share of voice {_pct(c['share_of_voice'])}"),
            new_x="LMARGIN", new_y="NEXT",
        )
    heading("What to do next")
    for o in content["top_opportunities"]:
        pdf.multi_cell(0, 6, _latin1(f"- {o['title']}: {o['recommended_action']}"), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
