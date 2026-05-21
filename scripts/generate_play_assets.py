#!/usr/bin/env python3
"""Generate Google Play listing bitmaps under android/fastlane/metadata/.../images/."""

from __future__ import annotations

import math
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Brand (distinct from sibling gpx-link blue)
TEAL = (0x0D, 0x94, 0x88)
WHITE = (255, 255, 255)
SLATE_L = (0x0F, 0x17, 0x2A)
SLATE_R = (0x13, 0x4E, 0x4A)

_REPO = Path(__file__).resolve().parent.parent
OUT_DIR = _REPO / "android/fastlane/metadata/android/en-US/images"
SHOT_DIR = OUT_DIR / "phoneScreenshots"


def try_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for p in candidates:
        fp = Path(p)
        if fp.is_file():
            return ImageFont.truetype(str(fp), size=size)
    return ImageFont.load_default()


def draw_pin(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    scale: float,
    fill,
    outline=None,
) -> None:
    """Simple map-pin silhouette (symmetric teardrop)."""
    r = 12 * scale
    stem_h = 28 * scale
    tip_y = cy + stem_h
    tip_x = cx
    pin_outline = outline or fill
    base_l = (cx - r * 0.85, cy + r * 0.35)
    base_r = (cx + r * 0.85, cy + r * 0.35)
    draw.polygon([base_l, base_r, (tip_x, tip_y)], fill=fill, outline=pin_outline)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill, outline=pin_outline)
    hole_r = r * 0.38
    draw.ellipse(
        (cx - hole_r, cy - hole_r, cx + hole_r, cy + hole_r),
        fill=WHITE if fill == TEAL else TEAL,
        outline=None,
    )


def gen_icon_512() -> Image.Image:
    w = h = 512
    img = Image.new("RGBA", (w, h), WHITE + (255,))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=112, fill=WHITE)
    draw_pin(draw, w / 2, h / 2 - 18, scale=11.2, fill=TEAL)
    return img.convert("RGB")


def gen_feature_1024_500() -> Image.Image:
    w, h = 1024, 500
    img = Image.new("RGB", (w, h))
    px = img.load()
    for x in range(w):
        t = x / (w - 1)
        r = int(SLATE_L[0] + (SLATE_R[0] - SLATE_L[0]) * t)
        g = int(SLATE_L[1] + (SLATE_R[1] - SLATE_L[1]) * t)
        b = int(SLATE_L[2] + (SLATE_R[2] - SLATE_L[2]) * t)
        for y in range(h):
            px[x, y] = (r, g, b)
    draw = ImageDraw.Draw(img)
    title_font = try_font(48)
    sub_font = try_font(22)

    # Google Play renders feature graphics in several card formats and may crop
    # the left/right edges. Keep all meaningful content inside the central area.
    def centered_text(y: int, text: str, font, fill) -> None:
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        x = (w - (right - left)) / 2 - left
        draw.text((x, y - top), text, font=font, fill=fill)

    draw_pin(draw, w / 2, 138, scale=3.9, fill=TEAL, outline=(0x0F, 0x76, 0x6E))
    centered_text(254, "GPX POI Enricher", title_font, WHITE)
    centered_text(332, "Maps → GPX  ·  OSM POIs", sub_font, (0xCC, 0xFB, 0xF1))
    return img


def fake_map_base(im: Image.Image, x0: int, y0: int, x1: int, y1: int) -> None:
    draw = ImageDraw.Draw(im)
    draw.rectangle((x0, y0, x1, y1), fill=(0xF0, 0xFD, 0xFA))
    step = 48
    for gx in range(x0, x1, step):
        draw.line((gx, y0, gx, y1), fill=(0xCC, 0xFB, 0xF1), width=1)
    for gy in range(y0, y1, step):
        draw.line((x0, gy, x1, gy), fill=(0xCC, 0xFB, 0xF1), width=1)
    park = (0xA7, 0xF3, 0xD0)
    draw.rounded_rectangle(
        (x0 + 80, y0 + 120, x0 + 280, y0 + 420),
        radius=24,
        fill=park,
    )
    sand = (0xFE, 0xE8, 0xCC)
    draw.rounded_rectangle(
        (x0 + 320, y0 + 60, x0 + 520, y0 + 200),
        radius=20,
        fill=sand,
    )


def screenshot_main() -> Image.Image:
    w, h = 1080, 1920
    img = Image.new("RGB", (w, h), (0xFA, 0xFA, 0xFA))
    draw = ImageDraw.Draw(img)
    status_h = 72
    draw.rectangle((0, 0, w, status_h), fill=SLATE_L)
    tb_h = 144
    draw.rectangle((0, status_h, w, status_h + tb_h), fill=TEAL)
    title_font = try_font(38)
    draw.text((40, status_h + 46), "GPX POI Enricher", font=title_font, fill=WHITE)
    body_top = status_h + tb_h
    split = int(w * 0.35)
    draw.rectangle((0, body_top, split, h), fill=WHITE)
    draw.line((split, body_top, split, h), fill=(0xE5, 0xE7, 0xEB), width=2)
    fake_map_base(img, split + 2, body_top, w - 1, h - 1)
    poly = [
        (split + 180, body_top + 280),
        (split + 420, body_top + 520),
        (split + 720, body_top + 380),
        (split + 620, body_top + 900),
        (split + 340, body_top + 820),
    ]
    draw.line(poly + [poly[0]], fill=TEAL, width=10)
    for px, py in poly:
        r = 14
        draw.ellipse((px - r, py - r, px + r, py + r), fill=TEAL, outline=WHITE)
    row_font = try_font(28)
    for i, name in enumerate(["route.gpx", "camping.yaml"]):
        y = body_top + 40 + i * 120
        outline_ul = (0xE5, 0xE7, 0xEB)
        draw.rounded_rectangle(
            (16, y, split - 16, y + 96),
            radius=12,
            outline=outline_ul,
            width=2,
        )
        draw.rectangle((36, y + 36, 68, y + 68), outline=TEAL, width=3)
        draw.line((44, y + 48, 60, y + 48), fill=TEAL, width=3)
        draw.line((52, y + 40, 52, y + 56), fill=TEAL, width=3)
        draw.text((88, y + 28), name, font=row_font, fill=(0x11, 0x18, 0x27))
    cap_font = try_font(24)
    draw.rectangle((0, h - 56, w, h), fill=SLATE_L)
    muted = (0x64, 0x74, 0x8B)
    draw.text(
        (split + 40, body_top + 36),
        "Map + profiles",
        font=cap_font,
        fill=muted,
    )
    return img


def screenshot_poi_focus() -> Image.Image:
    w, h = 1080, 1920
    img = Image.new("RGB", (w, h), (0xFA, 0xFA, 0xFA))
    draw = ImageDraw.Draw(img)
    status_h = 72
    draw.rectangle((0, 0, w, status_h), fill=SLATE_L)
    tb_h = 144
    draw.rectangle((0, status_h, w, status_h + tb_h), fill=TEAL)
    draw.text((40, status_h + 46), "GPX POI Enricher", font=try_font(38), fill=WHITE)
    body_top = status_h + tb_h
    fake_map_base(img, 0, body_top, w - 1, h - 120)
    cx, cy = w // 2, body_top + (h - body_top) // 2 - 80
    for angle in range(0, 360, 55):
        rad = math.radians(angle)
        px = cx + 280 * math.cos(rad)
        py = cy + 280 * math.sin(rad)
        draw.line((cx, cy, px, py), fill=TEAL, width=8)
    chip_y = h - 280
    chip_outline = (0xE5, 0xE7, 0xEB)
    draw.rounded_rectangle(
        (80, chip_y, w - 80, chip_y + 72),
        radius=36,
        fill=(0xFF, 0xFF, 0xFF),
        outline=chip_outline,
        width=2,
    )
    draw.text(
        (120, chip_y + 22),
        "Enrich with OSM POIs along your track",
        font=try_font(26),
        fill=(0x47, 0x4F, 0x5E),
    )
    draw_pin(draw, cx, cy - 40, scale=14, fill=TEAL)
    draw.rectangle((0, h - 56, w, h), fill=SLATE_L)
    return img


def screenshot_maps_flow() -> Image.Image:
    w, h = 1080, 1920
    img = Image.new("RGB", (w, h), (0xFA, 0xFA, 0xFA))
    draw = ImageDraw.Draw(img)
    status_h = 72
    draw.rectangle((0, 0, w, status_h), fill=SLATE_L)
    tb_h = 144
    draw.rectangle((0, status_h, w, status_h + tb_h), fill=TEAL)
    draw.text((40, status_h + 46), "GPX POI Enricher", font=try_font(38), fill=WHITE)
    body_top = status_h + tb_h
    sheet_top = body_top + 120
    sheet_outline = (0xE5, 0xE7, 0xEB)
    draw.rounded_rectangle(
        (40, sheet_top, w - 40, h - 200),
        radius=28,
        fill=WHITE,
        outline=sheet_outline,
        width=2,
    )
    ink = (0x11, 0x18, 0x27)
    draw.text((80, sheet_top + 48), "Maps URL → GPX", font=try_font(36), fill=ink)
    hint_font = try_font(26)
    draw.text(
        (80, sheet_top + 110),
        "Paste a directions link; build a routed track for POI enrichment.",
        font=hint_font,
        fill=(0x64, 0x74, 0x8B),
    )
    chip_y = sheet_top + 220
    draw.rounded_rectangle(
        (72, chip_y, w - 72, chip_y + 88),
        radius=16,
        fill=(0xF0, 0xFD, 0xFA),
        outline=sheet_outline,
    )
    draw.text((104, chip_y + 28), "https://maps.app.goo.gl/…", font=try_font(28), fill=ink)
    fab_r = 56
    fx, fy = w - fab_r - 64, h - fab_r - 180
    draw.ellipse((fx - fab_r, fy - fab_r, fx + fab_r, fy + fab_r), fill=TEAL)
    draw.line((fx - 28, fy, fx + 28, fy), fill=WHITE, width=8)
    draw.line((fx, fy - 28, fx, fy + 28), fill=WHITE, width=8)
    draw.rectangle((0, h - 56, w, h), fill=SLATE_L)
    return img


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SHOT_DIR.mkdir(parents=True, exist_ok=True)

    icon = gen_icon_512()
    icon_path = OUT_DIR / "icon.png"
    icon.save(icon_path, "PNG", optimize=True)
    print(f"Wrote {icon_path}")

    feat = gen_feature_1024_500()
    feat_path = OUT_DIR / "featureGraphic.png"
    feat.save(feat_path, "PNG", optimize=True)
    print(f"Wrote {feat_path}")

    shots = [
        ("01-main.png", screenshot_main()),
        ("02-poi-focus.png", screenshot_poi_focus()),
        ("03-maps-url.png", screenshot_maps_flow()),
    ]
    for name, im in shots:
        p = SHOT_DIR / name
        im.save(p, "PNG", optimize=True)
        print(f"Wrote {p}")

    first_phone = shots[0][0]
    src = SHOT_DIR / first_phone
    for sub in ("sevenInchScreenshots", "tenInchScreenshots"):
        dest_dir = OUT_DIR / sub
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / first_phone
        shutil.copy2(src, dest)
        print(f"Wrote {dest} (same image as phone {first_phone} for {sub})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
