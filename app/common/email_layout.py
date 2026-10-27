"""The one HTML layout every SeenLens email uses: wordmark, card with a lime top edge, optional stats and list, one button.

Tables and inline styles only, so it renders the same in Gmail, Outlook and Apple Mail; the <style> block only adds
dark mode where the client supports it. Shape rule: the card is 16px, the button is a pill. Every value is escaped here.
"""

from html import escape

INK = "#171717"
MUTED = "#57534e"
FAINT = "#a8a29e"
LINE = "#e7e5e4"
PAGE = "#f5f5f4"
MARK = "#d7f36b"  # the app's lime, used once: the card's top edge
FONT = "Geist,-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"

DARK = """
@media (prefers-color-scheme: dark) {
  .bg { background:#0c0c0b !important; }
  .card { background:#171716 !important; border-left-color:#2a2a28 !important; border-right-color:#2a2a28 !important; border-bottom-color:#2a2a28 !important; }
  .ink { color:#f5f5f4 !important; }
  .muted { color:#a8a29e !important; }
  .rule { border-color:#2a2a28 !important; }
  .btn { background:#f5f5f4 !important; color:#171717 !important; }
}
@media (max-width:600px) {
  .pad { padding:28px 22px !important; }
  .btn { display:block !important; text-align:center !important; }
}
"""


def email_html(
    *,
    heading: str,
    paragraphs: list[str],
    button: tuple[str, str] | None = None,
    eyebrow: str | None = None,
    stats: list[tuple[str, str]] | None = None,
    items: list[str] | None = None,
    footer: str = "",
    preheader: str = "",
) -> str:
    """`button`: (label, url). `eyebrow`: who this is about (the workspace). `stats`: up to 3 (value, label).
    `items`: a short list, e.g. the questions a competitor took."""
    context = f'<td align="right" class="muted" style="font-size:13px;color:{MUTED}">{escape(eyebrow)}</td>' if eyebrow else ""
    body = "".join(
        f'<p class="muted" style="margin:0 0 16px;font-size:15px;line-height:1.65;color:{MUTED}">{escape(p)}</p>' for p in paragraphs
    )

    stats_html = ""
    if stats:
        shown = stats[:3]
        cells = "".join(
            f'<td width="{100 // len(shown)}%" valign="top" class="rule" style="padding:2px 0 2px {0 if i == 0 else 18}px;'
            f'{"" if i == 0 else f"border-left:1px solid {LINE};"}">'
            f'<div class="ink" style="font-size:30px;line-height:1.1;font-weight:700;letter-spacing:-0.03em;color:{INK}">{escape(value)}</div>'
            f'<div class="muted" style="margin-top:4px;font-size:13px;color:{MUTED}">{escape(label)}</div></td>'
            for i, (value, label) in enumerate(shown)
        )
        stats_html = (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="rule" '
            f'style="margin:8px 0 26px;border-top:1px solid {LINE};border-bottom:1px solid {LINE}"><tr><td style="padding:18px 0">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>{cells}</tr></table></td></tr></table>'
        )

    items_html = ""
    if items:
        rows = "".join(
            f'<tr><td width="26" valign="top" class="muted rule" style="padding:12px 0;font-size:13px;line-height:21px;font-weight:600;color:{FAINT};'
            f'{"" if i == 0 else f"border-top:1px solid {LINE};"}">{i}</td>'
            f'<td class="ink rule" style="padding:12px 0;font-size:14px;line-height:21px;color:{INK};'
            f'{"" if i == 0 else f"border-top:1px solid {LINE};"}">{escape(item)}</td></tr>'
            for i, item in enumerate(items, 1)
        )
        items_html = f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 26px">{rows}</table>'

    button_html = fallback = ""
    if button:
        label, url = escape(button[0]), escape(button[1])
        button_html = (
            f'<a href="{url}" class="btn" style="display:inline-block;background:{INK};color:#ffffff;text-decoration:none;'
            f'font-size:15px;font-weight:600;line-height:1;padding:15px 24px;border-radius:999px">{label}</a>'
        )
        fallback = (
            f'<p class="muted" style="margin:14px 0 0;font-size:12px;line-height:1.5;color:{FAINT}">'
            f'If the button does not work, open <a href="{url}" style="color:{FAINT};word-break:break-all">{url}</a></p>'
        )

    footer_html = f'<p class="muted" style="margin:0;font-size:12px;line-height:1.6;color:{FAINT}">{escape(footer)}</p>' if footer else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark">
<title>{escape(heading)}</title><style>{DARK}</style></head>
<body class="bg" style="margin:0;padding:0;background:{PAGE};font-family:{FONT};color:{INK};-webkit-font-smoothing:antialiased">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent">{escape(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="bg" style="background:{PAGE}"><tr><td align="center" style="padding:40px 16px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px">
<tr><td style="padding:0 2px 18px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
<td><table role="presentation" cellpadding="0" cellspacing="0"><tr>
<td width="22" height="22" style="background:{INK};border-radius:6px" align="center" valign="middle">
<div style="width:8px;height:8px;border-radius:2px;background:{MARK};font-size:0;line-height:0">&nbsp;</div></td>
<td class="ink" style="padding-left:8px;font-size:16px;font-weight:700;letter-spacing:-0.02em;color:{INK}">SeenLens</td>
</tr></table></td>{context}</tr></table></td></tr>
<tr><td class="card" style="background:#ffffff;border:1px solid {LINE};border-top:3px solid {MARK};border-radius:16px">
<div class="pad" style="padding:36px 36px 34px">
<h1 class="ink" style="margin:0 0 14px;font-size:26px;line-height:1.2;font-weight:700;letter-spacing:-0.025em;color:{INK}">{escape(heading)}</h1>
{body}{stats_html}{items_html}{button_html}{fallback}
</div></td></tr>
<tr><td style="padding:20px 4px 0">{footer_html}</td></tr>
</table></td></tr></table>
</body></html>"""
