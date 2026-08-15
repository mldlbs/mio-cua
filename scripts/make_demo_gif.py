"""Generate a synthetic demo GIF for the mio-cua README.

Builds frames from REAL task-artifact screenshots (overlay PNGs the agent
produced during its verified Calculator run) plus caption overlays that tell
the story: Perceive -> Decide -> Act -> Verify -> Result.

Safe: does NOT touch the real desktop, moves nothing, only reads existing PNGs.
"""
import glob
import os

from PIL import Image, ImageDraw, ImageFont

ARTIFACTS = os.path.expanduser("~/.mio_cua/artifacts")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo.gif")

STEPS = [
    ("Perceive", "OCR + UIA fused into a Scene Graph\nevery element: text, type, bbox, state"),
    ("Decide", "LLM picks from VERIFIED action candidates\nno guessing coordinates"),
    ("Act", "real mouse/keyboard input\noverlay numbering maps to element ids"),
    ("Verify", "Scene Diff confirms the screen changed\ncalculator display 0 -> 7"),
    ("Result", "123 * 456 = 56088\nfive scenarios PASS on real Windows 11"),
]


def _font(size: int):
    for name in ("segoeuib.ttf", "segoeui.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _frames() -> list:
    files = sorted(
        glob.glob(os.path.join(ARTIFACTS, "*.png")),
        key=lambda p: os.path.basename(p),
    )
    frames = []
    # prefer overlay (numbered) shots; fall back to any raw png
    overlay = [f for f in files if not f.endswith(".raw.png")]
    if not overlay:
        overlay = files
    if not overlay:
        raise SystemExit(f"no artifact screenshots found under {ARTIFACTS}")
    base = Image.open(overlay[0]).convert("RGB")
    w, h = base.size
    cap_h = int(h * 0.14)
    for i, (title, body) in enumerate(STEPS):
        frame = base.copy()
        canvas = Image.new("RGB", (w, h + cap_h), (10, 12, 16))
        canvas.paste(frame, (0, 0))
        draw = ImageDraw.Draw(canvas)
        draw.rectangle([0, h, w, h + cap_h], fill=(16, 20, 28))
        draw.rectangle([0, h, w, h + 3], fill=(52, 152, 219))
        ft = _font(max(28, int(cap_h * 0.32)))
        fb = _font(max(22, int(cap_h * 0.22)))
        # title at left
        draw.text((28, h + int(cap_h * 0.12)), f"{i+1}. {title}", font=ft, fill=(255, 255, 255))
        # body text, right-aligned block
        lines = body.split("\n")
        for j, ln in enumerate(lines):
            draw.text((w - 28 - int(fb.size * 1.0 * len(ln) * 0.9), h + int(cap_h * 0.16) + j * int(fb.size * 1.25)),
                      ln, font=fb, fill=(200, 214, 229))
        frames.append(canvas)
    return frames


def main():
    frames = _frames()
    dur = 1800  # ms per frame
    frames[0].save(OUT, save_all=True, append_images=frames[1:], duration=dur, loop=0, optimize=False)
    kb = os.path.getsize(OUT) / 1024
    print(f"wrote {OUT} ({len(frames)} frames, {kb:.0f} KB)")


if __name__ == "__main__":
    main()
