#!/usr/bin/env python3
"""Assemble the single-file page (dist/halalready.html) and a local preview with local fonts."""
import pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent
SRC = ROOT / "src"
DIST = ROOT / "dist"
DIST.mkdir(exist_ok=True)

head = (SRC / "head.html").read_text()
css = "\n".join((SRC / "css" / f).read_text() for f in ["base.css", "fx.css", "site.css", "dash.css"])
body = (SRC / "body.html").read_text()
js = "\n".join((SRC / "js" / f).read_text() for f in ["lib.js", "data.js", "fx.js", "dash.js", "site.js"])
js = "(() => {\n'use strict';\n" + js + "\n})();"

page = head + "<style>\n" + css + "\n</style>\n" + body + "\n<script>\n" + js + "\n</script>\n"
(DIST / "halalready.html").write_text(page)

local_fonts = """<style>
@font-face{font-family:"Plus Jakarta Sans";src:url("../fonts/PlusJakartaSans.ttf") format("truetype");font-weight:200 800;font-display:block}
@font-face{font-family:"Instrument Serif";src:url("../fonts/InstrumentSerif-Regular.ttf") format("truetype");font-weight:400;font-style:normal;font-display:block}
@font-face{font-family:"Instrument Serif";src:url("../fonts/InstrumentSerif-Italic.ttf") format("truetype");font-weight:400;font-style:italic;font-display:block}
@font-face{font-family:"Geist";src:url("../fonts/Geist.ttf") format("truetype");font-weight:100 900;font-display:block}
@font-face{font-family:"Archivo";src:url("../fonts/Archivo.ttf") format("truetype");font-weight:100 900;font-stretch:62% 125%;font-display:block}
@font-face{font-family:"IBM Plex Mono";src:url("../fonts/IBMPlexMono-Regular.ttf") format("truetype");font-weight:400;font-display:block}
@font-face{font-family:"IBM Plex Mono";src:url("../fonts/IBMPlexMono-Medium.ttf") format("truetype");font-weight:500;font-display:block}
@font-face{font-family:"IBM Plex Mono";src:url("../fonts/IBMPlexMono-SemiBold.ttf") format("truetype");font-weight:600;font-display:block}
</style>"""
preview_head = re.sub(r'<link rel="(?:preconnect|stylesheet)"[^>]*>\n?', "", head)
skeleton = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
            '<style>:root{color-scheme:light;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}'
            'body{margin:0;font:14px system-ui,sans-serif}img{max-width:100%}[hidden]{display:none!important}</style>'
            + local_fonts + '</head><body>')
preview = skeleton + preview_head + "<style>\n" + css + "\n</style>\n" + body + "\n<script>\n" + js + "\n</script>\n</body></html>"
(DIST / "preview.html").write_text(preview)
print("page bytes:", len(page.encode()), "| preview bytes:", len(preview.encode()))
