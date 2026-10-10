r"""
Generate the fictional sample case for the demo (Mak Teh Sambal).

    .venv\Scripts\python scripts/make_sample_case.py

Writes sample_case/pile/ (the files the owner drops in) and
sample_case/kept_back/ (the supplier's live reply and the owner's clearer
copy). Every file is drawn here, so the case is the same on every machine.
Real photos can replace the site pictures later; keep the same file names.

The case is tuned for three demo moments (see sample_case/ANSWER_KEY.md):
  1. Waiting on a supplier: no cooking-oil certificate, only the invoice.
  2. Not sure: the ikan bilis certificate is an unreadable scan.
  3. Conflict: the store shelf shows Cap Merpati Hijau oil, not the declared MURNI.
"""

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "sample_case"
PILE = OUT / "pile"
KEPT = OUT / "kept_back"

FONT_DIR = Path("C:/Windows/Fonts")
INK = (34, 34, 38)
GREY = (110, 110, 118)
LINE = (200, 200, 205)
PAPER = (252, 251, 247)
SAMPLE_RED = (196, 40, 40)


def font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    name = ("consolab.ttf" if bold else "consola.ttf") if mono else ("arialbd.ttf" if bold else "arial.ttf")
    try:
        return ImageFont.truetype(str(FONT_DIR / name), size)
    except OSError:
        return ImageFont.load_default(size)


# ── the case ─────────────────────────────────────────────────────────

COMPANY = {
    "name": "Mak Teh Sambal Sdn Bhd",
    "reg_no": "202301099999 (1500999-X)",
    "address": "Lot 7, Jalan Perusahaan 3/2, Seksyen 15, 40200 Shah Alam, Selangor",
    "owner": "Siti Rahmah binti Yusof (Mak Teh)",
    "supervisor": "Nurul Ain binti Hassan",
}

SUPPLIERS = [
    # name, contact, phone, supplies, brand
    ("Syarikat Cili Maju", "Encik Halim", "+60 11-0000 0101", "Dried chilli", "CILI MAJU"),
    ("Minyak Murni Sdn Bhd", "Puan Aishah", "+60 11-0000 0202", "Palm cooking oil, 17 kg tin", "MURNI"),
    ("Bawang Segar Enterprise", "Encik Kumar", "+60 11-0000 0303", "Shallot paste, garlic paste", "BAWANG SEGAR"),
    ("Hasil Laut Kuala", "Puan Zainab", "+60 11-0000 0404", "Ikan bilis (dried anchovies)", "HASIL LAUT"),
    ("Gula Manis Sdn Bhd", "Encik Lim", "+60 11-0000 0505", "Fine sugar, 1 kg bag", "GULA MANIS"),
]

JAKIM = "Jabatan Kemajuan Islam Malaysia (JAKIM)"
JAIS = "Jabatan Agama Islam Selangor (JAIS)"

CERTS = {
    "chilli": dict(holder="Syarikat Cili Maju", products=["Cili Kering (Dried Chilli) - jenama CILI MAJU"],
                   number="SAMPLE-HC-CM-2025-0412", issued="1 Sep 2025", expiry="31 Aug 2027", issuer=JAKIM),
    "shallot_garlic": dict(holder="Bawang Segar Enterprise",
                           products=["Pes Bawang Merah (Shallot Paste) - jenama BAWANG SEGAR",
                                     "Pes Bawang Putih (Garlic Paste) - jenama BAWANG SEGAR"],
                           number="SAMPLE-HC-BS-2025-0733", issued="1 Mar 2025", expiry="28 Feb 2027", issuer=JAKIM),
    "ikan_bilis": dict(holder="Hasil Laut Kuala", products=["Ikan Bilis Kering (Dried Anchovies) - jenama HASIL LAUT"],
                       number="SAMPLE-JAIS-HLK-2025-0158", issued="1 Oct 2025", expiry="30 Sep 2027", issuer=JAIS),
    "sugar": dict(holder="Gula Manis Sdn Bhd", products=["Gula Pasir Halus (Fine Sugar) - jenama GULA MANIS"],
                  number="SAMPLE-HC-GM-2024-0961", issued="1 Apr 2024", expiry="31 Mar 2027", issuer=JAKIM),
    # kept back: arrives as the supplier's live reply
    "oil": dict(holder="Minyak Murni Sdn Bhd", products=["Minyak Masak Sawit (Palm Cooking Oil) - jenama MURNI"],
                number="SAMPLE-HC-MM-2025-0587", issued="1 Jul 2025", expiry="30 Jun 2027", issuer=JAKIM),
}


# ── drawing helpers ──────────────────────────────────────────────────

def page(w: int = 1100, h: int = 1500) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (w, h), PAPER)
    return img, ImageDraw.Draw(img)


def sample_band(d: ImageDraw.ImageDraw, w: int, text: str = "SAMPLE - FICTIONAL - FOR DEMONSTRATION ONLY"):
    d.rectangle([0, 0, w, 44], fill=SAMPLE_RED)
    d.text((w // 2, 22), text, font=font(22, True), fill="white", anchor="mm")


def watermark(img: Image.Image, text: str = "SAMPLE - FICTIONAL"):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.text((img.width // 2, img.height // 2), text, font=font(110, True), fill=(196, 40, 40, 38), anchor="mm")
    layer = layer.rotate(30, center=(img.width // 2, img.height // 2))
    img.paste(layer, (0, 0), layer)


def wrap(d: ImageDraw.ImageDraw, text: str, f, width: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        test = (cur + " " + word).strip()
        if d.textlength(test, font=f) <= width:
            cur = test
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def table(d: ImageDraw.ImageDraw, x: int, y: int, cols: list[int], rows: list[list[str]], size: int = 22,
          header: bool = True) -> int:
    f, fb = font(size), font(size, True)
    for r, row in enumerate(rows):
        cells = [wrap(d, str(c), fb if (header and r == 0) else f, cols[i] - 16) for i, c in enumerate(row)]
        h = max(len(c) for c in cells) * (size + 8) + 16
        cx = x
        for i, lines in enumerate(cells):
            if header and r == 0:
                d.rectangle([cx, y, cx + cols[i], y + h], fill=(236, 234, 228))
            d.rectangle([cx, y, cx + cols[i], y + h], outline=LINE, width=2)
            for k, line in enumerate(lines):
                d.text((cx + 8, y + 8 + k * (size + 8)), line, font=fb if (header and r == 0) else f, fill=INK)
            cx += cols[i]
        y += h
    return y


def leaf_mark(d: ImageDraw.ImageDraw, cx: int, cy: int, r: int, color):
    """A plain leaf-and-tick mark for fictional issuers (never resembles a real halal logo)."""
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=5)
    d.polygon([(cx - r * .45, cy + r * .1), (cx - r * .1, cy + r * .45), (cx + r * .5, cy - r * .4),
               (cx - r * .1, cy + r * .2)], fill=color)


# ── documents ────────────────────────────────────────────────────────

def certificate(key: str) -> Image.Image:
    c = CERTS[key]
    img, d = page()
    w = img.width
    sample_band(d, w)
    d.rectangle([40, 70, w - 40, img.height - 40], outline=(60, 110, 70), width=6)
    d.rectangle([54, 84, w - 54, img.height - 54], outline=(60, 110, 70), width=2)
    leaf_mark(d, w // 2, 190, 60, (60, 110, 70))
    d.text((w // 2, 290), c["issuer"].upper(), font=font(26, True), fill=INK, anchor="mm")
    d.text((w // 2, 360), "SIJIL PENGESAHAN HALAL", font=font(46, True), fill=(40, 90, 50), anchor="mm")
    d.text((w // 2, 410), "HALAL CERTIFICATE (SAMPLE, NOT A REAL CERTIFICATE)", font=font(22), fill=GREY, anchor="mm")
    y = 480
    rows = [["Perkara / Field", "Butiran / Details"],
            ["Nama Syarikat / Company", c["holder"]],
            ["Produk / Product(s)", "\n".join(c["products"])],
            ["No. Sijil / Certificate No.", c["number"]],
            ["Tarikh Dikeluarkan / Issued", c["issued"]],
            ["Sah Hingga / Valid Until", c["expiry"]],
            ["Dikeluarkan oleh / Issued by", c["issuer"]]]
    # products are listed one per row so each wraps cleanly
    flat = []
    for r in rows:
        if "\n" in r[1]:
            for i, p in enumerate(r[1].split("\n")):
                flat.append([r[0] if i == 0 else "", p])
        else:
            flat.append(r)
    y = table(d, 100, y, [340, 560], flat, size=24)
    d.text((100, y + 50), "Sijil ini sah bagi produk yang disenaraikan sahaja.", font=font(22), fill=INK)
    d.text((100, y + 82), "This certificate is valid only for the products listed above.", font=font(22), fill=GREY)
    d.line([680, y + 220, 1000, y + 220], fill=INK, width=2)
    d.text((840, y + 240), "Pengarah / Director (sample)", font=font(20), fill=GREY, anchor="mm")
    watermark(img)
    return img


def unreadable(img: Image.Image) -> Image.Image:
    """A bad phone scan: tiny, smeared, tilted and washed out. The layout shows; the details do not."""
    small = img.resize((img.width // 9, img.height // 9), Image.BILINEAR)
    small = small.filter(ImageFilter.GaussianBlur(1.6))
    big = small.resize(img.size, Image.BILINEAR).filter(ImageFilter.GaussianBlur(6))
    big = big.rotate(-4, resample=Image.BICUBIC, fillcolor=(205, 203, 196))
    grey = Image.new("RGB", big.size, (228, 226, 220))
    return Image.blend(big, grey, 0.35)


def ssm_registration() -> Image.Image:
    img, d = page()
    sample_band(d, img.width)
    d.text((550, 130), "SURUHANJAYA SYARIKAT (SAMPLE REGISTRY)", font=font(30, True), fill=INK, anchor="mm")
    d.text((550, 180), "Business Registration Information (fictional)", font=font(24), fill=GREY, anchor="mm")
    table(d, 100, 260, [340, 560], [
        ["Field", "Details"],
        ["Company name", COMPANY["name"]],
        ["Registration no.", COMPANY["reg_no"]],
        ["Type", "Private limited company (Sdn Bhd)"],
        ["Date of incorporation", "14 March 2023"],
        ["Business address", COMPANY["address"]],
        ["Nature of business", "Manufacture of sambal and chilli-based condiments"],
        ["Directors", COMPANY["owner"]],
    ], size=24)
    watermark(img)
    return img


def company_profile() -> Image.Image:
    img, d = page()
    sample_band(d, img.width)
    d.text((80, 100), "Company Profile", font=font(44, True), fill=INK)
    d.text((80, 160), COMPANY["name"], font=font(28, True), fill=SAMPLE_RED)
    body = ("Mak Teh Sambal makes two jarred sambals in a small factory unit in Shah Alam, Selangor. "
            "We want halal certification so we can supply a supermarket chain. "
            "Six production staff work one shift, Monday to Friday.")
    y = 220
    for line in wrap(d, body, font(24), 940):
        d.text((80, y), line, font=font(24), fill=INK)
        y += 34
    d.text((80, y + 20), "Products", font=font(30, True), fill=INK)
    d.text((100, y + 66), "1.  Sambal Tumis Mak Teh, 250 g glass jar", font=font(24), fill=INK)
    d.text((100, y + 102), "2.  Sambal Ikan Bilis Mak Teh, 250 g glass jar", font=font(24), fill=INK)
    y += 180
    d.text((80, y), "Organisation chart", font=font(30, True), fill=INK)
    boxes = [((550, y + 90), "Owner / Managing Director", COMPANY["owner"]),
             ((550, y + 250), "Halal Supervisor", COMPANY["supervisor"]),
             ((300, y + 410), "Production (4 staff)", "Cooking and filling"),
             ((800, y + 410), "Packing and store (2 staff)", "Labelling, receiving, store")]
    for (cx, cy), role, name in boxes:
        d.rounded_rectangle([cx - 210, cy - 50, cx + 210, cy + 50], 12, outline=INK, width=3, fill=(245, 243, 236))
        d.text((cx, cy - 16), role, font=font(22, True), fill=INK, anchor="mm")
        d.text((cx, cy + 18), name, font=font(20), fill=GREY, anchor="mm")
    d.line([550, y + 140, 550, y + 200], fill=INK, width=3)
    d.line([550, y + 300, 550, y + 330, ], fill=INK, width=3)
    d.line([300, y + 330, 800, y + 330], fill=INK, width=3)
    d.line([300, y + 330, 300, y + 360], fill=INK, width=3)
    d.line([800, y + 330, 800, y + 360], fill=INK, width=3)
    watermark(img)
    return img


def recipe(product: str, items: list[tuple[str, str, str]], steps: list[str]) -> Image.Image:
    img, d = page()
    sample_band(d, img.width)
    d.text((80, 100), "Resipi / Recipe", font=font(40, True), fill=INK)
    d.text((80, 160), product, font=font(30, True), fill=SAMPLE_RED)
    d.text((80, 205), "Batch size: 40 jars x 250 g.  Internal recipe card, " + COMPANY["name"], font=font(22), fill=GREY)
    y = table(d, 80, 260, [380, 300, 260], [["Ingredient", "Brand", "Amount per batch"]] + [list(i) for i in items],
              size=24)
    d.text((80, y + 40), "Method", font=font(28, True), fill=INK)
    y += 90
    for i, s in enumerate(steps, 1):
        for k, line in enumerate(wrap(d, s, font(23), 880)):
            d.text((80, y), (f"{i}. " if k == 0 else "    ") + line, font=font(23), fill=INK)
            y += 32
        y += 8
    watermark(img)
    return img


def supplier_list() -> Image.Image:
    img, d = page(1400, 1000)
    sample_band(d, img.width)
    d.text((70, 90), "Senarai Pembekal / Approved Supplier List", font=font(38, True), fill=INK)
    d.text((70, 145), COMPANY["name"] + "  -  updated 1 Oct 2026", font=font(22), fill=GREY)
    table(d, 70, 200, [330, 210, 250, 320, 220],
          [["Supplier", "Contact", "Phone (WhatsApp)", "Supplies", "Brand"]] + [list(s) for s in SUPPLIERS], size=23)
    watermark(img)
    return img


def invoice() -> Image.Image:
    img, d = page()
    sample_band(d, img.width)
    d.text((80, 100), "MINYAK MURNI SDN BHD", font=font(36, True), fill=(150, 110, 10))
    d.text((80, 150), "Lot 22, Kawasan Perindustrian Klang (fictional address)", font=font(20), fill=GREY)
    d.text((1020, 100), "INVOIS / INVOICE", font=font(34, True), fill=INK, anchor="ra")
    table(d, 600, 160, [200, 220], [["Invoice no.", "INV-MM-2026-0917"], ["Date", "12 Sep 2026"],
                                    ["Terms", "30 days"]], size=21, header=False)
    d.text((80, 300), "Bill to:", font=font(22, True), fill=INK)
    d.text((80, 332), COMPANY["name"], font=font(22), fill=INK)
    d.text((80, 362), COMPANY["address"][:52], font=font(20), fill=GREY)
    d.text((80, 388), COMPANY["address"][52:].strip(", "), font=font(20), fill=GREY)
    y = table(d, 80, 450, [460, 110, 170, 200], [
        ["Description", "Qty", "Unit price", "Amount (RM)"],
        ["Minyak Masak Sawit MURNI, tin 17 kg", "10", "RM 98.00", "980.00"],
        ["Delivery charge", "1", "RM 40.00", "40.00"],
    ], size=22)
    table(d, 620, y + 10, [120, 200], [["Total", "RM 1,020.00"]], size=24, header=False)
    d.text((80, y + 140), "Brand supplied: MURNI palm cooking oil (17 kg tin).", font=font(22), fill=INK)
    d.text((80, y + 176), "Halal certificate available on request.", font=font(22), fill=INK)
    d.text((80, y + 240), "Thank you for your business.", font=font(22), fill=GREY)
    watermark(img)
    return img


# ── site photos (flat drawings with readable labels) ─────────────────

def room(title_ms: str, title_en: str, wall=(232, 228, 216), floor=(196, 190, 178)) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (1600, 1000), wall)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 760, 1600, 1000], fill=floor)
    for x in range(0, 1600, 80):
        d.line([x, 760, x - 120, 1000], fill=(184, 178, 166), width=2)
    d.rounded_rectangle([560, 30, 1040, 130], 10, fill=(30, 70, 140))
    d.text((800, 64), title_ms, font=font(34, True), fill="white", anchor="mm")
    d.text((800, 104), title_en, font=font(22), fill=(220, 230, 245), anchor="mm")
    return img, d


def photo_caption(img: Image.Image, text: str):
    d = ImageDraw.Draw(img)
    d.rectangle([0, 960, 1600, 1000], fill=(0, 0, 0))
    d.text((20, 980), "SAMPLE - FICTIONAL  |  " + text, font=font(20), fill="white", anchor="lm")


def tin(d, x, y, brand, line2, color, text_color="white", w=150, h=190):
    d.rectangle([x, y, x + w, y + h], fill=color, outline=(60, 60, 60), width=3)
    d.ellipse([x, y - 14, x + w, y + 14], fill=tuple(min(255, c + 40) for c in color), outline=(60, 60, 60), width=3)
    d.rectangle([x + 8, y + 40, x + w - 8, y + 150], fill=(255, 255, 255) if text_color != "white" else
                tuple(max(0, c - 30) for c in color))
    lines = brand.split("\n")
    fs, step = (24, 26) if len(lines) == 1 else (18, 21)
    top = y + 62 if len(lines) == 1 else y + 54
    for i, ln in enumerate(lines):
        d.text((x + w // 2, top + i * step), ln, font=font(fs, True), fill=text_color, anchor="mm")
    d.text((x + w // 2, top + len(lines) * step + 2), line2, font=font(15, True), fill=text_color, anchor="mm")
    d.text((x + w // 2, y + 136), "17 KG", font=font(18, True), fill=text_color, anchor="mm")


def sack(d, x, y, brand, line2, color=(214, 196, 150), w=170, h=150):
    d.rounded_rectangle([x, y, x + w, y + h], 28, fill=color, outline=(120, 100, 60), width=3)
    d.text((x + w // 2, y + 55), brand, font=font(24, True), fill=(140, 30, 20), anchor="mm")
    d.text((x + w // 2, y + 90), line2, font=font(18, True), fill=(60, 40, 20), anchor="mm")


def tub(d, x, y, brand, line2, color=(240, 240, 236), w=130, h=110):
    d.rectangle([x, y, x + w, y + h], fill=color, outline=(90, 90, 90), width=3)
    d.rectangle([x - 6, y - 14, x + w + 6, y], fill=(200, 60, 40))
    d.text((x + w // 2, y + 38), brand, font=font(17, True), fill=INK, anchor="mm")
    d.text((x + w // 2, y + 66), line2, font=font(15), fill=INK, anchor="mm")


def shelf_frame(d, x0, x1, levels):
    for y in levels:
        d.rectangle([x0, y, x1, y + 16], fill=(150, 150, 158), outline=(90, 90, 96))
    d.rectangle([x0, levels[0] - 260, x0 + 14, 760], fill=(120, 120, 128))
    d.rectangle([x1 - 14, levels[0] - 260, x1, 760], fill=(120, 120, 128))


def store_photo() -> Image.Image:
    img, d = room("STOR BAHAN MENTAH", "Raw material store")
    shelf_frame(d, 60, 1540, [430, 740])
    # top shelf: declared MURNI oil, then two tins of an undeclared brand at the right end
    for i in range(5):
        tin(d, 90 + i * 170, 232, "MURNI", "Minyak Masak Sawit", (230, 180, 30), text_color=(90, 50, 0))
    tin(d, 1080, 232, "CAP\nMERPATI HIJAU", "Minyak Masak", (40, 130, 70))
    tin(d, 1250, 232, "CAP\nMERPATI HIJAU", "Minyak Masak", (40, 130, 70))
    # bottom shelf on a raised pallet: chilli, sugar, pastes, ikan bilis
    sack(d, 90, 584, "CILI MAJU", "Cili Kering 10 kg")
    sack(d, 280, 584, "CILI MAJU", "Cili Kering 10 kg")
    for i in range(3):
        d.rectangle([480 + i * 120, 620, 580 + i * 120, 734], fill=(250, 250, 250), outline=(90, 90, 90), width=3)
        d.text((530 + i * 120, 655), "GULA", font=font(20, True), fill=(30, 90, 170), anchor="mm")
        d.text((530 + i * 120, 680), "MANIS", font=font(20, True), fill=(30, 90, 170), anchor="mm")
        d.text((530 + i * 120, 708), "Gula Pasir 1kg", font=font(13), fill=INK, anchor="mm")
    tub(d, 870, 624, "BAWANG SEGAR", "Pes Bawang Merah")
    tub(d, 1020, 624, "BAWANG SEGAR", "Pes Bawang Putih")
    d.rectangle([1180, 610, 1380, 734], fill=(200, 170, 120), outline=(110, 80, 40), width=3)
    d.text((1280, 650), "HASIL LAUT", font=font(22, True), fill=(20, 60, 120), anchor="mm")
    d.text((1280, 684), "Ikan Bilis Kering", font=font(18), fill=INK, anchor="mm")
    d.text((1280, 710), "5 kg", font=font(18), fill=INK, anchor="mm")
    # pallet under the bottom shelf
    d.rectangle([60, 756, 1540, 772], fill=(160, 120, 70))
    photo_caption(img, "Site photo: raw material store, 10 Oct 2026, 09:12")
    return img


def processing_photo() -> Image.Image:
    img, d = room("KAWASAN PEMPROSESAN", "Processing area", wall=(236, 240, 240))
    for x in (120, 860):
        d.rectangle([x, 520, x + 620, 545], fill=(205, 210, 215), outline=(140, 145, 150), width=3)
        d.rectangle([x + 20, 545, x + 40, 760], fill=(170, 175, 180))
        d.rectangle([x + 580, 545, x + 600, 760], fill=(170, 175, 180))
    for x in (200, 470):
        d.ellipse([x, 440, x + 220, 530], fill=(70, 70, 75), outline=(40, 40, 40), width=3)
        d.rectangle([x + 60, 530, x + 160, 545], fill=(50, 50, 55))
    for i, label in enumerate(["Pes Cili", "Bawang Merah", "Bawang Putih"]):
        x = 900 + i * 190
        d.rectangle([x, 410, x + 160, 520], fill=(245, 248, 250), outline=(120, 130, 140), width=3)
        d.rectangle([x + 15, 440, x + 145, 490], fill="white", outline=(150, 150, 150))
        d.text((x + 80, 465), label, font=font(18, True), fill=INK, anchor="mm")
    d.rectangle([1250, 180, 1520, 360], fill="white", outline=(150, 150, 150), width=3)
    d.text((1385, 220), "Wajib pakai", font=font(22, True), fill=SAMPLE_RED, anchor="mm")
    d.text((1385, 255), "penutup rambut,", font=font(20), fill=INK, anchor="mm")
    d.text((1385, 285), "apron & sarung tangan", font=font(20), fill=INK, anchor="mm")
    d.text((1385, 325), "Hairnet, apron, gloves", font=font(17), fill=GREY, anchor="mm")
    photo_caption(img, "Site photo: processing area, 10 Oct 2026, 09:20")
    return img


def packing_photo() -> Image.Image:
    img, d = room("KAWASAN PEMBUNGKUSAN", "Packing area", wall=(238, 236, 230))
    d.rectangle([100, 520, 1500, 545], fill=(205, 210, 215), outline=(140, 145, 150), width=3)
    d.rectangle([130, 545, 150, 760], fill=(170, 175, 180))
    d.rectangle([1450, 545, 1470, 760], fill=(170, 175, 180))
    for i in range(10):
        x = 160 + i * 125
        name, color = (("Sambal Tumis", (190, 40, 30)) if i < 5 else ("Sambal Ikan Bilis", (150, 60, 20)))
        d.rectangle([x, 380, x + 95, 520], fill=color, outline=(60, 20, 10), width=3)
        d.rectangle([x - 4, 360, x + 99, 384], fill=(220, 180, 40))
        d.rectangle([x + 6, 420, x + 89, 490], fill=(255, 250, 235))
        d.text((x + 47, 440), "MAK TEH", font=font(15, True), fill=INK, anchor="mm")
        for k, part in enumerate(name.split(" ", 1)):
            d.text((x + 47, 458 + k * 16), part, font=font(12), fill=INK, anchor="mm")
    d.rectangle([1250, 190, 1520, 340], fill="white", outline=(150, 150, 150), width=3)
    d.text((1385, 230), "Semak label", font=font(22, True), fill=INK, anchor="mm")
    d.text((1385, 268), "& kod kelompok", font=font(20), fill=INK, anchor="mm")
    d.text((1385, 304), "Check label & batch code", font=font(16), fill=GREY, anchor="mm")
    photo_caption(img, "Site photo: packing area, 10 Oct 2026, 09:27")
    return img


def cleaning_photo() -> Image.Image:
    img, d = room("KAWASAN PENCUCIAN", "Cleaning area", wall=(228, 236, 238))
    d.rectangle([150, 470, 650, 560], fill=(205, 210, 215), outline=(120, 125, 130), width=4)
    d.rectangle([190, 485, 610, 545], fill=(170, 180, 190))
    d.line([400, 380, 400, 470], fill=(120, 120, 120), width=10)
    d.line([400, 380, 450, 380], fill=(120, 120, 120), width=10)
    d.rectangle([680, 400, 740, 470], fill=(80, 160, 210), outline=(40, 80, 120), width=3)
    d.text((710, 500), "Sabun", font=font(18, True), fill=INK, anchor="mm")
    d.text((710, 522), "tangan", font=font(16), fill=INK, anchor="mm")
    # chemicals in a closed, labelled cabinet, away from food
    d.rectangle([1050, 260, 1450, 740], fill=(190, 60, 50), outline=(110, 30, 20), width=4)
    d.line([1250, 270, 1250, 730], fill=(110, 30, 20), width=4)
    d.text((1250, 330), "BAHAN PENCUCI", font=font(28, True), fill="white", anchor="mm")
    d.text((1250, 370), "Cleaning chemicals only", font=font(20), fill="white", anchor="mm")
    d.text((1250, 405), "Jauhkan dari makanan", font=font(18), fill="white", anchor="mm")
    for x in (850, 900, 950):
        d.line([x, 300, x, 700], fill=(140, 110, 70), width=8)
        d.rectangle([x - 20, 700, x + 20, 740], fill=(90, 120, 200))
    photo_caption(img, "Site photo: cleaning area, 10 Oct 2026, 09:33")
    return img


def waste_photo() -> Image.Image:
    img, d = room("KAWASAN SISA", "Waste area (outside back door)", wall=(214, 214, 210))
    d.rectangle([80, 220, 380, 760], fill=(150, 150, 150), outline=(90, 90, 90), width=4)
    d.text((230, 260), "Pintu belakang", font=font(20, True), fill=INK, anchor="mm")
    for i, (label, color) in enumerate([("SISA AM", (40, 110, 60)), ("SISA AM", (40, 110, 60)),
                                       ("KITAR SEMULA", (40, 80, 160))]):
        x = 560 + i * 300
        d.rectangle([x, 470, x + 220, 750], fill=color, outline=(30, 30, 30), width=4)
        d.rectangle([x - 10, 440, x + 230, 475], fill=tuple(c - 20 for c in color), outline=(30, 30, 30), width=4)
        d.text((x + 110, 560), label, font=font(24, True), fill="white", anchor="mm")
        d.text((x + 110, 600), "Tertutup / lid closed", font=font(16), fill="white", anchor="mm")
    photo_caption(img, "Site photo: waste area, 10 Oct 2026, 09:38")
    return img


def photo_texture(img: Image.Image, seed: int) -> Image.Image:
    """A little noise and blur so the drawings read as phone photos, not diagrams. Labels stay sharp enough."""
    rnd = random.Random(seed)
    px = img.load()
    for _ in range(img.width * img.height // 40):
        x, y = rnd.randrange(img.width), rnd.randrange(img.height)
        r, g, b = px[x, y]
        n = rnd.randint(-14, 14)
        px[x, y] = (max(0, min(255, r + n)), max(0, min(255, g + n)), max(0, min(255, b + n)))
    return img.filter(ImageFilter.GaussianBlur(0.6))


# ── write everything ─────────────────────────────────────────────────

def main():
    PILE.mkdir(parents=True, exist_ok=True)
    KEPT.mkdir(parents=True, exist_ok=True)
    for old in list(PILE.glob("*.png")) + list(KEPT.glob("*.png")):
        old.unlink()

    tumis = [("Cili kering (dried chilli)", "CILI MAJU", "3 kg"),
             ("Minyak masak sawit (palm cooking oil)", "MURNI", "4 kg"),
             ("Pes bawang merah (shallot paste)", "BAWANG SEGAR", "2 kg"),
             ("Pes bawang putih (garlic paste)", "BAWANG SEGAR", "0.5 kg"),
             ("Gula (sugar)", "GULA MANIS", "1.2 kg")]
    bilis = tumis + [("Ikan bilis (dried anchovies)", "HASIL LAUT", "2 kg")]

    files = {
        "01_ssm_registration.png": ssm_registration(),
        "02_company_profile.png": company_profile(),
        "03_recipe_sambal_tumis.png": recipe("Sambal Tumis Mak Teh (250 g)", tumis, [
            "Soak and blend the dried chilli.",
            "Heat the oil; fry shallot and garlic paste until fragrant.",
            "Add the chilli and cook on low heat for 45 minutes, stirring.",
            "Add sugar, cook 10 more minutes, then fill hot into jars."]),
        "04_recipe_sambal_ikan_bilis.png": recipe("Sambal Ikan Bilis Mak Teh (250 g)", bilis, [
            "Fry the ikan bilis in part of the oil until crisp; set aside.",
            "Cook the sambal base as for Sambal Tumis.",
            "Fold the ikan bilis into the sambal and fill hot into jars."]),
        "05_supplier_list.png": supplier_list(),
        "06_certificate_cili_maju.png": certificate("chilli"),
        "07_certificate_bawang_segar.png": certificate("shallot_garlic"),
        "08_certificate_hasil_laut.png": unreadable(certificate("ikan_bilis")),
        "09_certificate_gula_manis.png": certificate("sugar"),
        "10_invoice_minyak_murni.png": invoice(),
        "11_photo_store.png": photo_texture(store_photo(), 11),
        "12_photo_processing.png": photo_texture(processing_photo(), 12),
        "13_photo_packing.png": photo_texture(packing_photo(), 13),
        "14_photo_cleaning.png": photo_texture(cleaning_photo(), 14),
        "15_photo_waste.png": photo_texture(waste_photo(), 15),
    }
    for name, img in files.items():
        img.save(PILE / name, optimize=True)

    certificate("oil").save(KEPT / "reply_certificate_minyak_murni.png", optimize=True)
    certificate("ikan_bilis").save(KEPT / "clear_copy_certificate_hasil_laut.png", optimize=True)
    print(f"Wrote {len(files)} files to {PILE.relative_to(ROOT)} and 2 to {KEPT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
