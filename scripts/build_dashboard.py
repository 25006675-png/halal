r"""
Build the dashboard from the design template.

    .venv\Scripts\python scripts/build_dashboard.py

Reads index.html (the landing page and its live-demo dashboard, as
designed) and writes dashboard/index.html with the live layer added:
  - the template is a page fragment, so it is wrapped in a document shell
  - dashboard/live.js goes inside the template's script, before its routing
    code, so it can extend the template's Dashboard class
  - "Live demo" (#demo) opens LiveDashboard (real backend) instead of the
    scripted Dashboard; the landing page's preview stays scripted
  - dashboard/live.css goes after the template's styles
Run it again whenever the template or the live layer changes.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "index.html"
# index.html has no <!doctype>/<head>; without this shell the browser renders it in quirks mode
SHELL = ('<!doctype html><html><head><meta charset=utf8><meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">'
         '<style>:root{color-scheme:light;box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}'
         'html{scroll-padding-top:env(safe-area-inset-top,0px)}body{margin:0;padding:0;font:14px -apple-system,BlinkMacSystemFont,sans-serif;background:#fff;color:#000}'
         'img{max-width:100%}[hidden]:not([hidden=until-found i]){display:none!important}</style></head><body>\n')
OUT = ROOT / "dashboard" / "index.html"
ROUTING = "/* Routing between the site and the live demo (#demo) */"
OPEN = "if (!fullDash) fullDash = new Dashboard(view, {});"


def main():
    html = TEMPLATE.read_text(encoding="utf-8")
    if "</head>" not in html:
        html = SHELL + html + "\n</body></html>\n"
    live_js = (ROOT / "dashboard" / "live.js").read_text(encoding="utf-8")
    live_css = (ROOT / "dashboard" / "live.css").read_text(encoding="utf-8")
    for marker in (ROUTING, OPEN, "</head>"):
        if html.count(marker) != 1:
            raise SystemExit(f"Template changed: expected one {marker!r}")
    html = html.replace(ROUTING, live_js + "\n\n" + ROUTING)
    html = html.replace(OPEN, "if (!fullDash) fullDash = new LiveDashboard(view, {});")
    html = html.replace("</head>", "<style>\n" + live_css + "</style>\n</head>")
    OUT.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} ({len(html) // 1024} KB)")


if __name__ == "__main__":
    main()
