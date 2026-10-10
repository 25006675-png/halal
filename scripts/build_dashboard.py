r"""
Build the dashboard from the design template.

    .venv\Scripts\python scripts/build_dashboard.py

Reads GreenHalalReady.html (the landing page and its live-demo dashboard, as
designed) and writes dashboard/index.html with the live layer added:
  - dashboard/live.js goes inside the template's script, before its routing
    code, so it can extend the template's Dashboard class
  - "Live demo" (#demo) opens LiveDashboard (real backend) instead of the
    scripted Dashboard; the landing page's preview stays scripted
  - dashboard/live.css goes after the template's styles
Run it again whenever the template or the live layer changes.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "GreenHalalReady.html"
OUT = ROOT / "dashboard" / "index.html"
ROUTING = "/* Routing between the site and the live demo (#demo) */"
OPEN = "if (!fullDash) fullDash = new Dashboard(view, {});"


def main():
    html = TEMPLATE.read_text(encoding="utf-8")
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
