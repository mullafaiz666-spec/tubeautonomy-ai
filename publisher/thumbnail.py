#!/usr/bin/env python3
"""Generate a clean 1280x720 TubeVerse YouTube thumbnail locally."""
from __future__ import annotations

import argparse
import textwrap
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--output", default="thumbnail.jpg")
    parser.add_argument("--background", default=None)
    args = parser.parse_args()

    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

    width, height = 1280, 720
    if args.background and Path(args.background).is_file():
        image = Image.open(args.background).convert("RGB")
        scale = max(width / image.width, height / image.height)
        image = image.resize((int(image.width * scale), int(image.height * scale)))
        left = (image.width - width) // 2
        top = (image.height - height) // 2
        image = image.crop((left, top, left + width, top + height))
        image = image.filter(ImageFilter.GaussianBlur(2))
        image = ImageEnhance.Brightness(image).enhance(0.42)
    else:
        image = Image.new("RGB", (width, height), "#080b14")

    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 10), fill="#9b87f5")
    draw.rounded_rectangle((64, 64, 315, 116), radius=12, fill="#12192b", outline="#38415a", width=2)

    try:
        brand = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
        headline = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72)
        footer = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
    except OSError:
        brand = headline = footer = ImageFont.load_default()

    draw.text((88, 78), "TUBEVERSE AI", font=brand, fill="#b8a9ff")
    clean = " ".join(args.title.split())[:95]
    lines = textwrap.wrap(clean, width=24)[:4]
    y = 184
    for line in lines:
        draw.text((70, y), line, font=headline, fill="white", stroke_width=2, stroke_fill="#000000")
        y += 88
    draw.text((72, 650), "AUTONOMOUS VIDEO SYSTEM", font=footer, fill="#aab5c6")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "JPEG", quality=90, optimize=True)
    if output.stat().st_size > 2 * 1024 * 1024:
        image.save(output, "JPEG", quality=80, optimize=True)
    print({"output": str(output), "sizeBytes": output.stat().st_size})


if __name__ == "__main__":
    main()
