"""Generate an animated demo GIF for the mio-cua README.

Focused-zoom animation: crops the REAL "New repository" form area from a real
artifact screenshot, then animates a story using ACTUAL element coordinates
from that task's observation JSON:

  Perceive -> "Repository name" field highlights, cursor sweeps in
  Decide   -> thinking text over the field
  Act      -> types "mio-cua" into the focused field (character by character)
  Verify   -> Scene Diff: the field accepted the text
  Result   -> cursor moves to and clicks "Create repository"

By zooming into the form region, the cursor/highlight/typing are clearly
visible instead of being lost in a full-page screenshot. Safe: reads only the
artifact PNG/JSON; touches nothing on the real desktop.
"""
import glob
import json
import os

from PIL import Image, ImageDraw, ImageFont

ARTIFACTS = os.path.expanduser("~/.mio_cua/artifacts")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "promo", "demo.gif")

# Real coordinates from the task's observation JSON (screen px, full page)
REPO_NAME_BOX = (1064, 332, 560, 31)
CREATE_BTN = (1488, 877, 137, 32)
DESC_BOX = (922, 442, 702, 31)

# Crop box around the form (repo name -> description -> create button) + padding
CROP = (820, 250, 1700, 960)
CAP_H = 110
PAD = 22
TYPED = "mio-cua"
SWEEP_STEPS = 6
TYPING_HOLD = 500          # ms per typed char


def _font(size):
    for name in ("segoeuib.ttf", "segoeui.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _load_crop() -> Image.Image:
    files = sorted(glob.glob(os.path.join(ARTIFACTS, "*.png")), key=os.path.basename)
    overlay = [f for f in files if not f.endswith(".raw.png")]
    if not overlay:
        raise SystemExit(f"no artifact screenshots under {ARTIFACTS}")
    img = Image.open(overlay[0]).convert("RGB")
    return img.crop(CROP)


def _to_local(b):
    """Translate an absolute screen bbox into the cropped image's local coords."""
    x, y, w, h = b
    return (x - CROP[0], y - CROP[1], w, h)


def _center(b):
    x, y, w, h = b
    return (x + w / 2, y + h / 2)


def _interp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _cursor(frame, pos):
    d = ImageDraw.Draw(frame)
    x, y = int(pos[0]), int(pos[1])
    d.line([(x, y), (x, y + 14), (x + 6, y + 8), (x + 11, y + 14)], fill=(20, 20, 20), width=2)
    d.line([(x, y), (x, y + 14), (x + 6, y + 8), (x + 11, y + 14)], fill=(255, 255, 255), width=1)


def _highlight(frame, bbox, color=(255, 200, 40), width=4):
    d = ImageDraw.Draw(frame)
    x, y, w, h = bbox
    d.rectangle([x - width // 2, y - width // 2, x + w + width // 2, y + h + width // 2],
                outline=color, width=width)


def _caption(frame, step_no, title, body):
    d = ImageDraw.Draw(frame)
    w, h = frame.size
    d.rectangle([0, h - CAP_H, w, h], fill=(16, 20, 28))
    d.rectangle([0, h - CAP_H, w, h - CAP_H + 3], fill=(52, 152, 219))
    ft = _font(28)
    fb = _font(20)
    d.text((PAD, h - CAP_H + 14), f"{step_no}. {title}", font=ft, fill=(255, 255, 255))
    for j, ln in enumerate(body.split("\n")):
        d.text((PAD, h - CAP_H + 58 + j * 25), ln, font=fb, fill=(200, 214, 229))


def _canvas():
    base = _load_crop()
    w, h = base.size
    out = Image.new("RGB", (w, h + CAP_H), (10, 12, 16))
    out.paste(base, (0, 0))
    return out


def _base_frame(step_no, title, body, highlights=(), cursor=None, typed=""):
    c = _canvas()
    for b in highlights:
        _highlight(c, _to_local(b))
    if cursor:
        _cursor(c, cursor)
    if typed:
        d = ImageDraw.Draw(c)
        x0, y0, wb, hb = _to_local(REPO_NAME_BOX)
        d.text((x0 + 14, y0 + (hb - 22) // 2), typed, font=_font(22), fill=(0, 0, 0))
    _caption(c, step_no, title, body)
    return c


def main():
    frames = []
    durations = []

    field_center = _center(_to_local(REPO_NAME_BOX))
    btn_center = _center(_to_local(CREATE_BTN))
    desc_center = _center(_to_local(DESC_BOX))
    start = (30, 60)

    # 1. Perceive: cursor sweeps in while fields highlight
    targets = [start, desc_center, field_center]
    for i in range(SWEEP_STEPS):
        a = targets[min(i, len(targets) - 1)]
        b = targets[min(i + 1, len(targets) - 1)]
        pos = _interp(a, b, (i % 2) / 2)
        f = _base_frame(1, "Perceive",
                        "OCR + UIA fuse the screen into a Scene Graph\n\"Repository name\" / \"Create repository\" found",
                        highlights=(DESC_BOX, REPO_NAME_BOX), cursor=pos)
        frames.append(f)
        durations.append(220)

    # 2. Decide: focus the name field, thinking
    f = _base_frame(2, "Decide",
                    "LLM picks a VERIFIED action candidate\nclick \"Repository name\" -> type \"mio-cua\"",
                    highlights=(REPO_NAME_BOX,), cursor=field_center)
    frames += [f, f.copy(), f.copy()]
    durations += [1200, 200, 200]

    # 3. Act: typing effect
    for k in range(1, len(TYPED) + 1):
        f = _base_frame(3, "Act",
                        f'types "{TYPED[:k]}{"|" if k < len(TYPED) else ""}" into the focused field\nreal keyboard input',
                        highlights=(REPO_NAME_BOX,), cursor=field_center, typed=TYPED[:k])
        frames.append(f)
        durations.append(TYPING_HOLD)

    # 4. Verify: field accepted (typed text persists)
    f = _base_frame(4, "Verify",
                    "Scene Diff confirms the field accepted the text\nno stale scene — re-perceive before acting",
                    highlights=(REPO_NAME_BOX,), cursor=field_center, typed=TYPED)
    frames.append(f)
    durations.append(1300)

    # 5. Result: cursor moves to Create repository and clicks (text stays)
    for i in range(5):
        pos = _interp(field_center, btn_center, (i + 1) / 5)
        f = _base_frame(5, "Result",
                        "cursor moves to \"Create repository\"\nfive scenarios verified on real Windows 11",
                        highlights=(REPO_NAME_BOX,), cursor=pos, typed=TYPED)
        frames.append(f)
        durations.append(220)
    f = _base_frame(5, "Result",
                    "click lands on \"Create repository\"\nfive scenarios verified on real Windows 11",
                    highlights=(CREATE_BTN,), cursor=btn_center, typed=TYPED)
    frames.append(f)
    durations.append(1400)

    frames[0].save(OUT, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)
    print(f"wrote {OUT} ({len(frames)} frames, {os.path.getsize(OUT)/1024:.0f} KB, {frames[0].size})")


if __name__ == "__main__":
    main()
