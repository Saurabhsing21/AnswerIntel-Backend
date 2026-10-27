"""The PDF report: a cover with the verdict, then visibility, competitors, questions, sources, actions and methodology.

Drawn with fpdf2 and the bundled Geist font (OFL, see fonts/LICENSE.TXT), so any brand or question text renders.
Reports saved before a section existed simply skip it.
"""

import logging
from datetime import datetime
from pathlib import Path

from fpdf import FPDF

FONTS = Path(__file__).parent / "fonts"
logging.getLogger("fontTools").setLevel(logging.WARNING)  # font subsetting logs every PDF at INFO
INK = (23, 23, 23)
MUTED = (100, 100, 100)
FAINT = (160, 160, 160)
LINE = (229, 229, 229)
SURFACE = (250, 250, 249)
MARK = (215, 243, 107)
MARK_STRONG = (168, 201, 58)
UP = (22, 128, 61)
DOWN = (200, 40, 40)
AMBER = (180, 120, 10)
STATUS = {  # question result -> (label, text colour, fill)
    "won": ("Recommended", (22, 101, 52), (220, 252, 231)),
    "shared": ("Sometimes", (133, 77, 14), (254, 243, 199)),
    "mentioned": ("Mentioned only", (71, 85, 105), (241, 245, 249)),
    "absent": ("Missing", (153, 27, 27), (254, 226, 226)),
}
SECTIONS = ["Visibility in AI answers", "Competitive landscape", "Results by buyer question",
            "Sources AI relies on", "Recommended actions", "Methodology and data"]
IMPACT = {"high": DOWN, "medium": AMBER, "low": MUTED}
EFFORT = {"S": "Quick win", "M": "A few hours", "L": "Bigger project"}
SOURCE_TYPES = {
    "brand_website": "Your site", "competitor_website": "Competitor site", "review_site": "Review site",
    "comparison": "Comparison", "news": "News", "blog": "Blog", "reddit": "Reddit", "forum": "Forum",
    "directory": "Directory", "video": "Video", "other": "Other",
}


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{round(value * 100)}%"


def _pts(delta: float | None) -> str:
    if delta is None:
        return "first scan"
    pts = round(delta * 100)
    return "no change" if pts == 0 else f"{'+' if pts > 0 else '-'}{abs(pts)} pts"


def _date(value: str | None, with_time: bool = False) -> str:
    if not value:
        return "n/a"
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)[:10]
    return moment.strftime("%d %b %Y, %H:%M %Z" if with_time else "%d %b %Y").strip().rstrip(",")


class ReportPDF(FPDF):
    def __init__(self, brand: str, subtitle: str):
        super().__init__(format="A4")
        self.brand, self.subtitle = brand, subtitle
        for style, name in (("", "Regular"), ("B", "SemiBold")):
            self.add_font("Geist", style, str(FONTS / f"Geist-{name}.ttf"))
        self.add_font("GeistBold", "", str(FONTS / "Geist-Bold.ttf"))
        # Geist has no Devanagari: Hindi questions and brand names fall back to Noto, shaped by HarfBuzz.
        self.add_font("Noto", "", str(FONTS / "NotoSansDevanagari-Regular.ttf"))
        self.add_font("Noto", "B", str(FONTS / "NotoSansDevanagari-SemiBold.ttf"))
        self.set_fallback_fonts(["Noto"], exact_match=False)
        self.set_text_shaping(True)
        self.set_margins(18, 22, 18)
        self.set_auto_page_break(True, margin=20)
        self.alias_nb_pages()

    # Every page after the cover carries the report name and page numbers.
    def header(self):
        if self.page_no() == 1:
            return
        self.set_y(10)
        self.font(8, color=MUTED)
        self.cell(0, 5, f"{self.brand}  ·  AI visibility report", new_x="LMARGIN")
        self.set_x(self.l_margin)
        self.cell(0, 5, self.subtitle, align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*LINE)
        self.line(self.l_margin, 16.5, self.w - self.r_margin, 16.5)
        self.set_y(22)

    def footer(self):
        self.set_y(-13)
        self.font(7.5, color=FAINT)
        self.cell(0, 5, f"Confidential. Prepared by SeenLens for {self.brand}.")
        self.set_x(self.l_margin)
        self.cell(0, 5, f"Page {self.page_no()} of {{nb}}", align="R")

    def multi_cell(self, *args, **kwargs):
        kwargs.setdefault("align", "L")  # justified text leaves gaps in short report lines
        return super().multi_cell(*args, **kwargs)

    # Helpers
    @property
    def width(self) -> float:
        return self.w - self.l_margin - self.r_margin

    def font(self, size: float, bold: bool = False, color=INK, heavy: bool = False):
        self.set_font("GeistBold" if heavy else "Geist", "B" if bold and not heavy else "", size)
        self.set_text_color(*color)

    def section(self, number: int, title: str, lead: str = ""):
        if self.get_y() > self.h - 70:
            self.add_page()
        self.ln(4)
        self.font(8, bold=True, color=MARK_STRONG)
        self.cell(0, 5, f"{number:02d}", new_x="LMARGIN", new_y="NEXT")
        self.font(16, heavy=True)
        self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        if lead:
            self.font(9.5, color=MUTED)
            self.multi_cell(0, 5, lead, new_x="LMARGIN", new_y="NEXT")
        self.ln(3)

    def pill(self, x: float, y: float, text: str, fg, bg, size: float = 7.5) -> float:
        self.font(size, bold=True, color=fg)
        w = self.get_string_width(text) + 5
        self.set_fill_color(*bg)
        self.rect(x, y, w, 5, style="F", round_corners=True, corner_radius=2.5)
        self.set_xy(x, y)
        self.cell(w, 5, text, align="C")
        return w

    def bar(self, x: float, y: float, w: float, value: float | None, color=INK, h: float = 2.4):
        self.set_fill_color(*LINE)
        self.rect(x, y, w, h, style="F", round_corners=True, corner_radius=h / 2)
        if value:
            self.set_fill_color(*color)
            self.rect(x, y, max(h, w * min(value, 1)), h, style="F", round_corners=True, corner_radius=h / 2)

    def table_header(self, columns: list[tuple[str, float, str]]):
        self.set_fill_color(*SURFACE)
        self.set_draw_color(*LINE)
        self.font(7.5, bold=True, color=MUTED)
        y = self.get_y()
        self.rect(self.l_margin, y, self.width, 7, style="F")
        for label, w, align in columns:
            self.cell(w, 7, label.upper(), align=align)
        self.ln(7)

    def row_rule(self):
        self.set_draw_color(*LINE)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())


def _cover(pdf: ReportPDF, content: dict, title: str, period: str):
    meta = content.get("meta") or {}
    v = content["visibility"]
    pdf.add_page()
    # Brand band
    pdf.set_fill_color(*INK)
    pdf.rect(0, 0, pdf.w, 92, style="F")
    pdf.set_fill_color(*MARK)
    pdf.rect(pdf.l_margin, 20, 7, 7, style="F", round_corners=True, corner_radius=2)
    pdf.set_xy(pdf.l_margin + 10, 19.5)
    pdf.font(12, bold=True, color=(255, 255, 255))
    pdf.cell(0, 8, "SeenLens")
    pdf.set_xy(pdf.l_margin, 40)
    pdf.font(9, bold=True, color=MARK)
    pdf.cell(0, 5, "AI VISIBILITY REPORT", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    pdf.font(28, heavy=True, color=(255, 255, 255))
    pdf.multi_cell(0, 12, content["brand"], new_x="LMARGIN", new_y="NEXT")
    pdf.font(10, color=(200, 200, 200))
    where = "  ·  ".join(x for x in (content["website"].replace("https://", "").rstrip("/"), content["category"], meta.get("country")) if x)
    pdf.cell(0, 6, where, new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"{period}   ·   Generated {_date(meta.get('generated_at'))}", new_x="LMARGIN", new_y="NEXT")

    # Headline numbers
    pdf.set_y(102)
    deltas, margins = v.get("deltas") or {}, v.get("margins") or {}
    tiles = [
        ("Mentioned", v["mention_rate"], "mention_rate", "of AI answers name you"),
        ("Recommended", v["recommendation_rate"], "recommendation_rate", "of AI answers pick you"),
        ("Share of voice", v["share_of_voice"], "share_of_voice", "of all brand mentions"),
        ("Cited", v["citation_rate"], "citation_rate", "of answers cite your site"),
    ]
    gap, w = 4, (pdf.width - 12) / 4
    y = pdf.get_y()
    for i, (label, value, key, hint) in enumerate(tiles):
        x = pdf.l_margin + i * (w + gap)
        pdf.set_draw_color(*LINE)
        pdf.set_fill_color(255, 255, 255)
        pdf.rect(x, y, w, 34, style="DF", round_corners=True, corner_radius=3)
        pdf.set_xy(x + 4, y + 4)
        pdf.font(8, bold=True, color=MUTED)
        pdf.cell(w - 8, 4, label)
        pdf.set_xy(x + 4, y + 10)
        pdf.font(22, heavy=True)
        pdf.cell(w - 8, 10, _pct(value))
        change = _pts(deltas.get(key))
        pdf.set_xy(x + 4, y + 21)
        pdf.font(7.5, bold=True, color=UP if change.startswith("+") else DOWN if change.startswith("-") else MUTED)
        margin = margins.get(key)
        pdf.cell(w - 8, 4, change + (f"   ±{round(margin * 100)} pts" if margin else ""))
        pdf.set_xy(x + 4, y + 26)
        pdf.font(7, color=FAINT)
        pdf.cell(w - 8, 4, hint)
    pdf.set_y(y + 42)

    # Executive summary
    pdf.font(13, heavy=True)
    pdf.cell(0, 7, "Executive summary", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    for line in content.get("summary") or []:
        y = pdf.get_y()
        pdf.set_fill_color(*MARK_STRONG)
        pdf.rect(pdf.l_margin, y + 1.8, 1.6, 1.6, style="F")
        pdf.set_x(pdf.l_margin + 5)
        pdf.font(10)
        pdf.multi_cell(pdf.width - 5, 5.4, line, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1.5)

    # Scope box
    if meta:
        pdf.ln(4)
        y = pdf.get_y()
        pdf.set_fill_color(*SURFACE)
        pdf.set_draw_color(*LINE)
        pdf.rect(pdf.l_margin, y, pdf.width, 26, style="DF", round_corners=True, corner_radius=3)
        facts = [
            ("AI engines", ", ".join(meta.get("engines") or []) or "n/a"),
            ("Buyer questions", str(meta.get("questions", "n/a"))),
            ("AI answers analysed", str(meta.get("answers", "n/a"))),
            ("Scan completed", _date(meta.get("scan_completed_at"))),
        ]
        col = pdf.width / 2
        for i, (k, val) in enumerate(facts):
            pdf.set_xy(pdf.l_margin + 5 + (i % 2) * col, y + 4 + (i // 2) * 10)
            pdf.font(7.5, bold=True, color=MUTED)
            pdf.cell(col - 8, 4, k.upper(), new_x="LEFT", new_y="NEXT")
            pdf.font(9.5)
            pdf.cell(col - 8, 5, val[:70])
        pdf.set_y(y + 30)

    # Contents
    pdf.ln(4)
    pdf.font(7.5, bold=True, color=MUTED)
    pdf.cell(0, 5, "IN THIS REPORT", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    for i, name in enumerate(SECTIONS, 1):
        pdf.font(9.5, bold=True, color=MARK_STRONG)
        pdf.cell(9, 6.5, f"{i:02d}")
        pdf.font(9.5)
        pdf.cell(0, 6.5, name, new_x="LMARGIN", new_y="NEXT")
        pdf.row_rule()


def _visibility(pdf: ReportPDF, content: dict):
    v = content["visibility"]
    pdf.add_page()
    pdf.section(1, "Visibility in AI answers", "How often the AI engines name and recommend you, with the change since the previous scan and the margin of error for this sample size.")
    cols = [("Metric", 44, "L"), ("Value", 18, "R"), ("Change", 24, "R"), ("Margin (95%)", 26, "R"), ("   What it measures", pdf.width - 112, "L")]
    pdf.table_header(cols)
    deltas, margins = v.get("deltas") or {}, v.get("margins") or {}
    rows = [
        ("Mention rate", "mention_rate", "Answers that name your brand"),
        ("Recommendation rate", "recommendation_rate", "Answers that suggest you as a pick"),
        ("Share of voice", "share_of_voice", "Your share of all brand mentions"),
        ("Citation rate", "citation_rate", "Answers that link to your website"),
        ("Positive sentiment", "positive_sentiment_rate", "Mentions that speak well of you"),
    ]
    for label, key, meaning in rows:
        pdf.font(9.5, bold=True)
        pdf.cell(44, 8, label)
        pdf.font(9.5)
        pdf.cell(18, 8, _pct(v.get(key)), align="R")
        change = _pts(deltas.get(key))
        pdf.set_text_color(*(UP if change.startswith("+") else DOWN if change.startswith("-") else MUTED))
        pdf.cell(24, 8, change, align="R")
        pdf.set_text_color(*MUTED)
        pdf.cell(26, 8, f"±{round(margins[key] * 100)} pts" if margins.get(key) else "–", align="R")
        pdf.font(8.5, color=MUTED)
        pdf.cell(0, 8, "   " + meaning, new_x="LMARGIN", new_y="NEXT")
        pdf.row_rule()
    if v.get("average_position"):
        pdf.ln(2)
        pdf.font(8.5, color=MUTED)
        pdf.multi_cell(0, 4.6, f"When AI ranks options in a list, you appear at position {v['average_position']:.1f} on average (1 is the top).", new_x="LMARGIN", new_y="NEXT")

    engines = content.get("engines") or []
    if engines:
        pdf.ln(5)
        pdf.font(11.5, heavy=True)
        pdf.cell(0, 7, "By AI engine", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
        cols = [("Engine", 40, "L"), ("Answers", 20, "R"), ("Mentioned", (pdf.width - 60) / 2, "L"), ("Recommended", (pdf.width - 60) / 2, "L")]
        pdf.table_header(cols)
        half = (pdf.width - 60) / 2
        for e in engines:
            y = pdf.get_y()
            pdf.font(9.5, bold=True)
            pdf.cell(40, 9, e["name"])
            pdf.font(9.5, color=MUTED)
            pdf.cell(20, 9, str(e.get("responses", "")), align="R")
            for i, key in enumerate(("mention_rate", "recommendation_rate")):
                x = pdf.l_margin + 60 + i * half + 4
                pdf.bar(x, y + 3.3, half - 22, e.get(key), INK if i == 0 else MARK_STRONG)
                pdf.set_xy(x + half - 20, y)
                pdf.font(9, bold=True)
                pdf.cell(14, 9, _pct(e.get(key)), align="R")
            pdf.set_y(y + 9)
            pdf.row_rule()

    trend = content.get("trend") or []
    if len(trend) > 1:
        pdf.ln(5)
        pdf.font(11.5, heavy=True)
        pdf.cell(0, 7, "Trend across scans", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
        w = (pdf.width - 40) / 3
        pdf.table_header([("Scan date", 40, "L"), ("Mentioned", w, "R"), ("Recommended", w, "R"), ("Share of voice", w, "R")])
        pdf.font(9.5)
        for t in trend[-8:]:
            pdf.cell(40, 7.5, _date(t.get("date")))
            for key in ("mention_rate", "recommendation_rate", "share_of_voice"):
                pdf.cell(w, 7.5, _pct(t.get(key)), align="R")
            pdf.ln(7.5)
            pdf.row_rule()


def _competitors(pdf: ReportPDF, content: dict):
    rows = content.get("competitors") or []
    if not rows:
        return
    pdf.section(2, "Competitive landscape", "Every tracked brand in the same answers. Share of voice is each brand's slice of all brand mentions.")
    rest = pdf.width - 50 - 22 - 26 - 22
    pdf.table_header([("Brand", 50, "L"), ("Mentioned", 22, "R"), ("Recommended", 26, "R"), ("Avg. rank", 22, "R"), ("Share of voice", rest, "L")])
    for c in sorted(rows, key=lambda r: r.get("share_of_voice") or 0, reverse=True):
        y = pdf.get_y()
        if c.get("is_you"):
            pdf.set_fill_color(247, 252, 231)
            pdf.rect(pdf.l_margin, y, pdf.width, 9, style="F")
        pdf.font(9.5, bold=True)
        pdf.cell(50, 9, c["name"] + ("  (you)" if c.get("is_you") else ""))
        pdf.font(9.5)
        pdf.cell(22, 9, _pct(c.get("mention_rate")), align="R")
        pdf.cell(26, 9, _pct(c.get("recommendation_rate")), align="R")
        pdf.cell(22, 9, f"#{c['average_position']:.1f}" if c.get("average_position") else "–", align="R")
        x = pdf.l_margin + 120 + 4
        pdf.bar(x, y + 3.3, rest - 22, c.get("share_of_voice"), MARK_STRONG if c.get("is_you") else INK)
        pdf.set_xy(x + rest - 20, y)
        pdf.font(9, bold=True)
        pdf.cell(14, 9, _pct(c.get("share_of_voice")), align="R")
        pdf.set_y(y + 9)
        pdf.row_rule()


def _questions(pdf: ReportPDF, content: dict):
    questions = content.get("questions") or []
    if not questions:
        return
    pdf.section(3, "Results by buyer question", "Each question was put to every engine. The result shows whether the engines recommended you, and who they recommended alongside or instead of you.")
    counts = {k: sum(q["status"] == k for q in questions) for k in STATUS}
    x = pdf.l_margin
    y = pdf.get_y()
    for key, (label, fg, bg) in STATUS.items():
        x += pdf.pill(x, y, f"{label}: {counts[key]}", fg, bg, 8) + 3
    pdf.set_y(y + 9)
    qw, rw, ew = pdf.width - 32 - 18 - 48, 32, 18
    pdf.table_header([("Question", qw, "L"), ("Result", rw, "L"), ("Picked", ew, "R"), ("Also recommended", 48, "L")])
    for q in questions:
        pdf.font(9)
        lines = pdf.multi_cell(qw - 3, 4.6, q["text"], dry_run=True, output="LINES")
        h = max(9, len(lines) * 4.6 + 4)
        if pdf.get_y() + h > pdf.h - 22:
            pdf.add_page()
        y = pdf.get_y()
        pdf.set_xy(pdf.l_margin, y + 2)
        pdf.multi_cell(qw - 3, 4.6, q["text"])
        label, fg, bg = STATUS[q["status"]]
        pdf.pill(pdf.l_margin + qw, y + 2, label, fg, bg)
        pdf.set_xy(pdf.l_margin + qw + rw, y)
        pdf.font(9, bold=True)
        pdf.cell(ew, 9, f"{q['recommended_on']}/{q['engines']}", align="R")
        pdf.set_xy(pdf.l_margin + qw + rw + ew + 3, y + 2)
        pdf.font(8.5, color=MUTED)
        pdf.multi_cell(45, 4.6, ", ".join(q["winners"]) or "–")
        pdf.set_y(y + h)
        pdf.row_rule()


def _sources(pdf: ReportPDF, content: dict):
    sources = content.get("sources")
    if sources is None:
        return
    pdf.section(4, "Sources AI relies on", "The websites the engines cited in this scan. Being present on these sites is one of the strongest levers for being recommended.")
    if not sources:
        pdf.font(9.5, color=MUTED)
        pdf.multi_cell(0, 5, "The engines in this scan answered from their own knowledge and cited no websites. Web-search engines such as ChatGPT Search, Perplexity and Gemini add cited sources.", new_x="LMARGIN", new_y="NEXT")
        return
    pdf.table_header([("Website", 62, "L"), ("Type", 34, "L"), ("Citations", 22, "R"), ("Owner", 36, "L"), ("Names you", pdf.width - 154, "R")])
    for s in sources:
        pdf.font(9.5, bold=True)
        pdf.cell(62, 8, s["domain"][:40])
        pdf.font(9, color=MUTED)
        pdf.cell(34, 8, SOURCE_TYPES.get(s.get("source_type") or "other", "Other"))
        pdf.font(9.5)
        pdf.cell(22, 8, str(s["citations"]), align="R")
        pdf.font(9, color=MUTED)
        pdf.cell(36, 8, "   " + (s.get("owner") or "Independent"))
        pdf.font(9, bold=True, color=UP if s["with_you"] else DOWN)
        pdf.cell(0, 8, "Yes" if s["with_you"] else "No", align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.row_rule()


def _actions(pdf: ReportPDF, content: dict):
    actions = content.get("top_opportunities") or []
    pdf.section(5, "Recommended actions", "Ranked by expected impact on how often AI recommends you. Each comes from the answers and sources in this scan.")
    if not actions:
        pdf.font(9.5, color=MUTED)
        pdf.multi_cell(0, 5, "No open gaps were found in this scan: you are recommended wherever a competitor is. Keep tracking weekly to catch changes early.", new_x="LMARGIN", new_y="NEXT")
        return
    for i, a in enumerate(actions[:6], 1):
        if pdf.get_y() > pdf.h - 60:
            pdf.add_page()
        y = pdf.get_y()
        pdf.set_fill_color(*INK)
        pdf.rect(pdf.l_margin, y, 7, 7, style="F", round_corners=True, corner_radius=2)
        pdf.set_xy(pdf.l_margin, y)
        pdf.font(9, bold=True, color=(255, 255, 255))
        pdf.cell(7, 7, str(i), align="C")
        pdf.set_xy(pdf.l_margin + 10, y)
        pdf.font(10.5, bold=True)
        pdf.multi_cell(pdf.width - 10, 5.5, a["title"], new_x="LMARGIN", new_y="NEXT")
        x, ty = pdf.l_margin + 10, pdf.get_y() + 1
        impact = (a.get("impact") or "medium").lower()
        x += pdf.pill(x, ty, f"{impact.capitalize()} impact", IMPACT.get(impact, MUTED), SURFACE) + 2
        if a.get("effort"):
            pdf.pill(x, ty, EFFORT.get(a["effort"], a["effort"]), MUTED, SURFACE)
        pdf.set_y(ty + 7)
        pdf.set_x(pdf.l_margin + 10)
        pdf.font(9.2, color=MUTED)
        pdf.multi_cell(pdf.width - 10, 4.8, a.get("description") or "", new_x="LMARGIN", new_y="NEXT")
        for step in a.get("steps") or [a.get("recommended_action")]:
            if not step:
                continue
            sy = pdf.get_y()
            pdf.set_fill_color(*MARK_STRONG)
            pdf.rect(pdf.l_margin + 12, sy + 1.9, 1.4, 1.4, style="F")
            pdf.set_x(pdf.l_margin + 16)
            pdf.font(9.2)
            pdf.multi_cell(pdf.width - 16, 4.8, step, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)


def _methodology(pdf: ReportPDF, content: dict):
    meta = content.get("meta") or {}
    pdf.add_page()
    pdf.section(6, "Methodology and data", "How these numbers were produced, so they can be checked and compared over time.")
    facts = [
        ("Scan ID", str(meta.get("scan_id", "n/a"))),
        ("Scan run", f"{_date(meta.get('scan_started_at'), True)}  to  {_date(meta.get('scan_completed_at'), True)}"),
        ("AI engines", ", ".join(meta.get("engines") or []) or "n/a"),
        ("Buyer questions asked", str(meta.get("questions", "n/a"))),
        ("AI answers analysed", f"{meta.get('answers', 'n/a')}" + (f" ({meta['failed_runs']} could not be collected)" if meta.get("failed_runs") else "")),
        ("Market", meta.get("country") or "n/a"),
        ("Scans in trend", str(meta.get("scans_in_trend", "n/a"))),
        ("Report generated", _date(meta.get("generated_at"), True)),
    ]
    for k, val in facts:
        pdf.font(9, bold=True, color=MUTED)
        pdf.cell(52, 7, k)
        pdf.font(9.5)
        pdf.multi_cell(0, 7, val, new_x="LMARGIN", new_y="NEXT")
        pdf.row_rule()

    blocks = [
        ("How answers are collected",
         "Each buyer question is sent to each AI engine as a fresh conversation, the way a buyer would ask it, with no "
         "brand prompting. Web-search engines answer with live search results; the others answer from what the model learned."),
        ("How answers are read",
         "Every answer is analysed for each tracked brand: whether it is named, whether it is recommended as a pick, its rank "
         "in any list, the tone used, and which websites are cited. A brand counts as mentioned only if its name appears in the text."),
        ("Margin of error",
         "Rates are reported with a 95% margin of error based on the number of answers. Changes smaller than the margin may be "
         "normal variation between runs rather than a real shift; the trend over several scans is more reliable than one scan."),
        ("Limitations",
         "AI answers vary between runs, users, locations and over time, and engines update their models without notice. "
         "Results reflect the questions and engines listed above on the dates shown, not every possible conversation."),
    ]
    pdf.ln(5)
    for heading, text in blocks:
        pdf.font(10.5, heavy=True)
        pdf.cell(0, 6, heading, new_x="LMARGIN", new_y="NEXT")
        pdf.font(9.2, color=MUTED)
        pdf.multi_cell(0, 4.9, text, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)
    pdf.ln(2)
    pdf.font(8, color=FAINT)
    pdf.multi_cell(0, 4.2, "This report is provided for information. It describes observed AI answers and is not a guarantee of future results.", new_x="LMARGIN", new_y="NEXT")


def render_pdf(content: dict, title: str, period: str = "") -> bytes:
    pdf = ReportPDF(content["brand"], period or title)
    _cover(pdf, content, title, period)
    _visibility(pdf, content)
    _competitors(pdf, content)
    pdf.add_page()
    _questions(pdf, content)
    _sources(pdf, content)
    _actions(pdf, content)
    _methodology(pdf, content)
    return bytes(pdf.output())
