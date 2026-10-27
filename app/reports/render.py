"""Report exports. Every value that reaches HTML is escaped: brand and competitor names are user input."""

from html import escape

LIGHT = "#f7f7f7"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{round(value * 100)}%"


def _position(value: float | None) -> str:
    return "n/a" if value is None else f"#{value:g}"


def _bar(value: float | None, color: str = "#171717") -> str:
    width = round(min(max(value or 0, 0), 1) * 100)
    return f'<span class="bar"><span style="width:{width}%;background:{color}"></span></span>'


def render_html(content: dict, title: str) -> str:
    """The web and email version of the PDF report: same sections, same order. Older reports skip what they lack."""
    from app.reports.pdf import EFFORT, SOURCE_TYPES, STATUS, _date, _pts

    v, meta = content["visibility"], content.get("meta") or {}
    deltas, margins = v.get("deltas") or {}, v.get("margins") or {}
    tiles = "".join(
        f'<div class="tile"><div class="label">{label}</div><div class="value">{_pct(v.get(key))}</div>'
        f'<div class="hint">{escape(_pts(deltas.get(key)))}{f" · ±{round(margins[key] * 100)} pts" if margins.get(key) else ""}</div></div>'
        for label, key in (("Mentioned", "mention_rate"), ("Recommended", "recommendation_rate"),
                           ("Share of voice", "share_of_voice"), ("Cited", "citation_rate"))
    )
    summary = "".join(f"<li>{escape(line)}</li>" for line in content.get("summary") or [])
    scope = "".join(
        f"<div><dt>{k}</dt><dd>{escape(str(val))}</dd></div>"
        for k, val in (("AI engines", ", ".join(meta.get("engines") or [])), ("Buyer questions", meta.get("questions")),
                       ("AI answers analysed", meta.get("answers")), ("Scan completed", _date(meta.get("scan_completed_at"))))
        if val not in (None, "")
    )
    engines = "".join(
        f"<tr><td><b>{escape(e['name'])}</b></td><td class=r>{e.get('responses', '')}</td>"
        f"<td>{_bar(e.get('mention_rate'))} {_pct(e.get('mention_rate'))}</td>"
        f"<td>{_bar(e.get('recommendation_rate'), '#a8c93a')} {_pct(e.get('recommendation_rate'))}</td></tr>"
        for e in content.get("engines") or []
    )
    competitors = "".join(
        f"<tr{' class=you' if c.get('is_you') else ''}><td><b>{escape(c['name'])}</b>{' (you)' if c.get('is_you') else ''}</td>"
        f"<td class=r>{_pct(c.get('mention_rate'))}</td><td class=r>{_pct(c.get('recommendation_rate'))}</td>"
        f"<td class=r>{_position(c.get('average_position'))}</td>"
        f"<td>{_bar(c.get('share_of_voice'), '#a8c93a' if c.get('is_you') else '#171717')} {_pct(c.get('share_of_voice'))}</td></tr>"
        for c in sorted(content.get("competitors") or [], key=lambda r: r.get("share_of_voice") or 0, reverse=True)
    )
    questions = "".join(
        f"<tr><td>{escape(q['text'])}</td><td><span class=pill style=\"color:rgb{STATUS[q['status']][1]};background:rgb{STATUS[q['status']][2]}\">"
        f"{STATUS[q['status']][0]}</span></td><td class=r><b>{q['recommended_on']}/{q['engines']}</b></td>"
        f"<td class=muted>{escape(', '.join(q['winners'])) or '–'}</td></tr>"
        for q in content.get("questions") or []
    )
    sources = "".join(
        f"<tr><td><b>{escape(s['domain'])}</b></td><td class=muted>{SOURCE_TYPES.get(s.get('source_type') or 'other', 'Other')}</td>"
        f"<td class=r>{s['citations']}</td><td class=muted>{escape(s.get('owner') or 'Independent')}</td>"
        f"<td class=r style=\"color:{'#16803d' if s['with_you'] else '#c82828'}\"><b>{'Yes' if s['with_you'] else 'No'}</b></td></tr>"
        for s in content.get("sources") or []
    )
    def action(a: dict) -> str:
        effort = f"<span class=tag>{EFFORT[a['effort']]}</span>" if a.get("effort") in EFFORT else ""
        steps = "".join(f"<li>{escape(step)}</li>" for step in (a.get("steps") or [a.get("recommended_action")]) if step)
        return (
            f"<li><b>{escape(a['title'])}</b> <span class=tag>{escape((a.get('impact') or 'medium').capitalize())} impact</span>{effort}"
            f"<p class=muted>{escape(a.get('description') or '')}</p><ul>{steps}</ul></li>"
        )

    actions = "".join(action(a) for a in content.get("top_opportunities") or [])

    def section(n: int, name: str, lead: str, body: str) -> str:
        return f'<section><p class=num>{n:02d}</p><h2>{name}</h2><p class=lead>{lead}</p>{body}</section>' if body else ""

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<style>
body{{margin:0;background:#f5f5f4;color:#171717;font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}}
main{{max-width:860px;margin:0 auto;background:#fff;min-height:100vh}}
header{{background:#171717;color:#fff;padding:40px 48px 36px}} .logo{{font-weight:600;display:flex;gap:8px;align-items:center}}
.logo i{{width:14px;height:14px;border-radius:4px;background:#d7f36b;display:inline-block}}
.kicker{{color:#d7f36b;font-size:12px;font-weight:600;letter-spacing:.08em;margin:28px 0 4px}}
h1{{font-size:38px;margin:0;letter-spacing:-.02em}} header p{{color:#bdbdbd;margin:6px 0 0}}
.wrap{{padding:32px 48px 48px}} .tiles{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:-56px}}
.tile{{background:#fff;border:1px solid #e5e5e5;border-radius:14px;padding:14px}} .label{{font-size:12px;color:#646464;font-weight:600}}
.value{{font-size:30px;font-weight:700;letter-spacing:-.02em}} .hint{{font-size:12px;color:#8a8a8a}}
h3{{font-size:17px;margin:28px 0 8px}} ul{{padding-left:20px}} li{{margin:4px 0}}
dl{{display:grid;grid-template-columns:1fr 1fr;gap:10px 24px;background:#fafaf9;border:1px solid #e5e5e5;border-radius:14px;padding:16px 20px;margin:20px 0 0}}
dt{{font-size:11px;font-weight:600;color:#646464;text-transform:uppercase;letter-spacing:.04em}} dd{{margin:0}}
section{{margin-top:40px}} .num{{color:#a8c93a;font-weight:600;font-size:12px;margin:0}} h2{{font-size:22px;margin:0;letter-spacing:-.01em}}
.lead,.muted{{color:#646464}} .lead{{margin:4px 0 14px}}
table{{width:100%;border-collapse:collapse;font-size:14px}} th{{background:#fafaf9;color:#646464;font-size:11px;text-transform:uppercase;letter-spacing:.04em;text-align:left;padding:9px 10px}}
td{{padding:10px;border-bottom:1px solid #e5e5e5;vertical-align:top}} .r{{text-align:right}} tr.you td{{background:#f7fce7}}
.bar{{display:inline-block;width:120px;height:7px;border-radius:9px;background:#e5e5e5;overflow:hidden;vertical-align:middle;margin-right:6px}} .bar span{{display:block;height:100%}}
.pill,.tag{{display:inline-block;font-size:12px;font-weight:600;padding:2px 9px;border-radius:999px}} .tag{{background:#f5f5f4;color:#646464;margin-left:6px}}
ol>li{{margin:0 0 18px}} footer{{color:#a3a3a3;font-size:12px;border-top:1px solid #e5e5e5;margin-top:40px;padding-top:16px}}
@media (max-width:640px){{header,.wrap{{padding-left:20px;padding-right:20px}} .tiles{{grid-template-columns:1fr 1fr}} .bar{{width:60px}}}}
</style></head><body><main>
<header><div class=logo><i></i>SeenLens</div><p class=kicker>AI VISIBILITY REPORT</p><h1>{escape(content['brand'])}</h1>
<p>{escape(content['website'].split("://")[-1].rstrip("/"))} &middot; {escape(content['category'])}{f" &middot; {escape(meta['country'])}" if meta.get('country') else ''}</p></header>
<div class=wrap><div class=tiles>{tiles}</div>
<h3>Executive summary</h3><ul>{summary}</ul>{f"<dl>{scope}</dl>" if scope else ""}
{section(1, "Visibility by AI engine", "How often each engine names and recommends you.", f"<table><tr><th>Engine</th><th class=r>Answers</th><th>Mentioned</th><th>Recommended</th></tr>{engines}</table>" if engines else "")}
{section(2, "Competitive landscape", "Every tracked brand in the same answers.", f"<table><tr><th>Brand</th><th class=r>Mentioned</th><th class=r>Recommended</th><th class=r>Avg. rank</th><th>Share of voice</th></tr>{competitors}</table>" if competitors else "")}
{section(3, "Results by buyer question", "Whether the engines recommended you, and who they recommended alongside or instead.", f"<table><tr><th>Question</th><th>Result</th><th class=r>Picked</th><th>Also recommended</th></tr>{questions}</table>" if questions else "")}
{section(4, "Sources AI relies on", "The websites the engines cited in this scan.", f"<table><tr><th>Website</th><th>Type</th><th class=r>Citations</th><th>Owner</th><th class=r>Names you</th></tr>{sources}</table>" if sources else "")}
{section(5, "Recommended actions", "Ranked by expected impact on how often AI recommends you.", f"<ol>{actions}</ol>" if actions else "<p class=muted>No open gaps were found in this scan.</p>")}
<footer>Scan {escape(str(meta.get("scan_id", "")))} &middot; generated {escape(_date(meta.get("generated_at"), True))}. AI answers vary between runs, users and over time; rates carry the margin of error shown.
Confidential. Prepared by SeenLens for {escape(content['brand'])}.</footer>
</div></main></body></html>"""
