#!/usr/bin/env python3
"""AI pixel-art sprite pipeline: refs, prompt, gen (Codex), snap, sheet post-process."""
import argparse, os, re, shutil, subprocess, sys, tempfile
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
SNAPPER = "spritefusion-pixel-snapper"
GREEN = (0, 255, 0)


# ---------- helpers ----------
def is_green(a):
    """Chroma-green mask for an RGB(A) uint8 array (tolerant: AI + quantized greens drift)."""
    a = a.astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    m = (g > 120) & (g - np.maximum(r, b) > 70)
    if a.shape[-1] == 4:
        m |= a[..., 3] < 128
    return m


def label(mask, connectivity=8):
    """Connected components -> list of (ys, xs) index arrays. Pure python BFS; inputs are small."""
    h, w = mask.shape
    seen = np.zeros_like(mask, bool)
    nbrs = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    if connectivity == 8:
        nbrs += [(-1, -1), (-1, 1), (1, -1), (1, 1)]
    comps = []
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        seen[y0, x0] = True
        q, ys, xs = deque([(y0, x0)]), [], []
        while q:
            y, x = q.popleft()
            ys.append(y); xs.append(x)
            for dy, dx in nbrs:
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    q.append((ny, nx))
        comps.append((np.array(ys), np.array(xs)))
    return comps


def dilate(mask, r):
    out = mask.copy()
    for _ in range(r):
        m = out.copy()
        m[1:] |= out[:-1]; m[:-1] |= out[1:]; m[:, 1:] |= out[:, :-1]; m[:, :-1] |= out[:, 1:]
        out = m
    return out


def nn_fit(img, size, bg, k=None):
    """Integer nearest-neighbor upscale centered on bg: the largest that fits size x size, or k if given."""
    k = k or max(1, min(size // img.width, size // img.height))
    big = img.resize((img.width * k, img.height * k), Image.NEAREST)
    canvas = Image.new(img.mode, (size, size), bg)
    canvas.paste(big, ((size - big.width) // 2, (size - big.height) // 2))
    return canvas, k


def char_height(img):
    """Height in px of the non-background part of an image (chroma green / transparent = background)."""
    ys = np.nonzero((~is_green(np.asarray(img.convert("RGBA")))).any(1))[0]
    return int(ys.max() - ys.min() + 1)


def run_snapper(src, dst, pixel_size=None, colors=16):
    if not shutil.which(SNAPPER):
        sys.exit(f"{SNAPPER} not found. Install: brew install Hugo-Dz/tap/spritefusion-pixel-snapper")
    cmd = [SNAPPER, str(src), str(dst), str(colors)]
    if pixel_size:
        cmd += ["--pixel-size", str(pixel_size)]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode:
        sys.exit(f"snapper failed on {src}: {out.stderr.strip() or out.stdout.strip()}")
    m = re.search(r"Pixel size: ([\d.]+)", out.stdout)
    return float(m.group(1)) if m else pixel_size


# ---------- commands ----------
def cmd_refs(a):
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    for name, (w, h) in {"checker_1024.png": (1024, 1024), "poseboard_2048x1536.png": (2048, 1536)}.items():
        yy, xx = np.indices((h, w))
        px = np.where(((xx + yy) % 2 == 0)[..., None], 255, 0).astype(np.uint8).repeat(3, -1)
        Image.fromarray(px).save(out / name)
        print(out / name)
    for n in (8, 4):
        walk_guide(n).save(out / f"walkguide_{n}.png")
        print(out / f"walkguide_{n}.png")


NEAR, FAR = (230, 30, 30), (40, 80, 230)  # near-side limbs red, far-side blue (never green: chroma)


def walk_guide(n):
    """Stick-figure walk cycle facing left on a 4x3 board of 512 cells; n=8 full cycle, n=4 key poses."""
    from math import cos, pi, radians, sin
    from PIL import ImageDraw
    img = Image.new("RGB", (2048, 1536), "white")
    d = ImageDraw.Draw(img)
    L, W = 95, 16

    def limb(x, y, a, bend, col):
        # hanging limb; angle a from vertical, + = forward (-x, facing left); lower segment at a + bend
        kx, ky = x - L * sin(a), y + L * cos(a)
        ex, ey = kx - L * 0.9 * sin(a + bend), ky + L * 0.9 * cos(a + bend)
        d.line([(x, y), (kx, ky), (ex, ey)], fill=col, width=W, joint="curve")

    for c, i in enumerate(range(0, 8, 8 // n)):
        ph = 2 * pi * i / 8
        ox, oy = (c % 4) * 512, (c // 4) * 512
        hx, hy = ox + 256, oy + 290 + 10 * cos(2 * ph)  # hip dips at contact, rises at passing
        an = radians(28) * cos(ph)  # near thigh swing
        legs = [(-an, radians(45) * max(0, sin(ph)), FAR), (an, radians(45) * max(0, -sin(ph)), NEAR)]
        sx, sy = hx + 6, hy - 140
        # arms swing opposite their same-side leg; elbows flex forward, knees backward
        limb(sx, sy, an * 0.7, radians(20), FAR)
        limb(hx, hy, legs[0][0], -legs[0][1], FAR)
        d.line([(hx, hy), (sx, sy)], fill="black", width=W + 4)
        d.ellipse([sx - 42, sy - 100, sx + 30, sy - 28], fill="black")
        d.polygon([(sx - 40, sy - 70), (sx - 62, sy - 58), (sx - 40, sy - 48)], fill="black")  # nose = facing
        limb(hx, hy, legs[1][0], -legs[1][1], NEAR)
        limb(sx, sy, -an * 0.7, radians(20), NEAR)
    return img


def cmd_prompt(a):
    text = (HERE / "templates" / f"{a.kind}.txt").read_text()
    vals = {"CANVAS_W": "2048", "CANVAS_H": "1536", "COLS": "4", "ROWS": "3"}
    for kv in a.set or []:
        k, _, v = kv.partition("=")
        vals[k.strip()] = Path(v[1:]).read_text().strip() if v.startswith("@") else v
    for k, v in vals.items():
        text = text.replace("{" + k + "}", v)
    left = sorted(set(re.findall(r"\{([A-Z_]+)\}", text)))
    if left:
        sys.exit("missing --set for: " + ", ".join(left))
    if a.out:
        Path(a.out).write_text(text); print(a.out)
    else:
        print(text)


def cmd_gen(a):
    """Generate one image with Codex's built-in image tool; refuse anything not really generated."""
    if not shutil.which("codex"):
        sys.exit("codex CLI not installed. Generate manually and save as " + a.out)
    out = Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    prompt = Path(a.prompt).read_text() + (
        f"\n\n---\nUse your built-in image generation tool (image_gen) with the attached images as references, in that order. "
        f"Save the generated PNG exactly to: {out}\n"
        "If the built-in image generation tool is unavailable, do NOT create the image any other way "
        "(no scripts, no drawing code). Reply only IMAGE_GEN_UNAVAILABLE.")
    cmd = ["codex", "exec", "--skip-git-repo-check", "-s", "workspace-write", "-C", str(out.parent),
           "-c", 'model_provider="openai"']  # this machine's default provider is a proxy without image_gen
    for r in a.ref or []:
        cmd += ["-i", str(Path(r).resolve())]
    res = subprocess.run(cmd + ["--", prompt], capture_output=True, text=True)  # "--": -i is variadic and would swallow the prompt
    if "IMAGE_GEN_UNAVAILABLE" in res.stdout or not out.exists():
        sys.exit("Codex image generation unavailable in exec mode. Generate manually and save as " + str(out))
    w, h = Image.open(out).size
    if min(w, h) < 1024:
        sys.exit(f"{out} is {w}x{h}; expected >=1024 (likely not a real image_gen result). Regenerate manually.")
    print(out)


def cmd_snap(a):
    with tempfile.TemporaryDirectory() as t:
        native = Path(t) / "native.png"
        ps = run_snapper(a.input, native, a.pixel_size, a.colors)
        img = Image.open(native).convert("RGB")
        if a.native:
            img.save(a.native)
        big, k = nn_fit(img, a.size, GREEN)
        big.save(a.output)
    print(f"pixel_size={ps} native={img.width}x{img.height} scale=x{k} -> {a.output}")


def extract_frames(sheet, min_frac=0.08):
    """Split an AI pose-board into per-character crops (bbox), ordered row-major."""
    rgb = np.asarray(sheet.convert("RGB"))
    f = 4  # label on a 1/4 grid for speed
    small = ~is_green(rgb[::f, ::f])
    comps = label(dilate(small, 3))  # dilation glues detached weapon bits to their body
    labmap = np.zeros(small.shape, int)
    for i, c in enumerate(comps, 1):
        labmap[c] = i
    big = max((len(c[0]) for c in comps), default=0)
    keep = [i for i, c in enumerate(comps, 1) if big and len(c[0]) >= big * min_frac]
    if not keep:
        sys.exit("no characters found (is the background chroma green?)")
    H, W = rgb.shape[:2]
    labfull = labmap.repeat(f, 0).repeat(f, 1)[:H, :W]
    boxes = []
    for i in keep:
        ys, xs = comps[i - 1]
        boxes.append((i, ys.min() * f, xs.min() * f, (ys.max() + 1) * f, (xs.max() + 1) * f))
    rowh = np.median([b[3] - b[1] for b in boxes])
    boxes.sort(key=lambda b: (round(((b[1] + b[3]) / 2) / rowh), b[2]))
    crops = []
    for i, y0, x0, y1, x1 in boxes:
        y0, x0, y1, x1 = max(0, y0 - f), max(0, x0 - f), min(H, y1 + f), min(W, x1 + f)
        crop = rgb[y0:y1, x0:x1].copy()
        crop[labfull[y0:y1, x0:x1] != i] = GREEN  # blank neighbours bleeding into this bbox
        crops.append(Image.fromarray(crop))
    return crops


def clean(img, speck=3):
    """Green -> transparent, then drop tiny isolated pixel clusters (despeckle)."""
    a = np.asarray(img.convert("RGBA")).copy()
    a[is_green(a)] = 0
    solid = a[..., 3] > 0
    # despill: dark-green edge pixels (outline blended with the chroma bg) -> the sprite's own outline colour
    rgb = a[..., :3].astype(int)
    spill = solid & (rgb[..., 1] > rgb[..., 0] + 40) & (rgb[..., 1] > rgb[..., 2] + 40)
    dark = solid & ~spill & (rgb.max(-1) < 80)
    if spill.any() and dark.any():
        a[spill, :3] = np.median(rgb[dark], axis=0).astype(np.uint8)
    for ys, xs in label(solid):
        if len(ys) <= speck:
            a[ys, xs] = 0
    return Image.fromarray(a)


def anchor_point(img, mode="feet"):
    """Point that must coincide across frames; y is always the lowest solid row (ground contact).
    x: feet = median x of the bottom quarter (idle/attack/hurt/death);
       torso = median x of the 30-60% height band (walk/jump: legs swing, torso stays put)."""
    m = np.asarray(img)[..., 3] > 0
    ys, xs = np.nonzero(m)
    top, bot = ys.min(), ys.max()
    h = bot - top
    if mode == "torso":
        band = (ys >= top + h * 0.3) & (ys <= top + h * 0.6)
    else:
        band = ys >= bot - max(1, h // 4)
    return int(np.median(xs[band])), int(bot)


def align(frames, mode="feet"):
    """Place every frame on one canvas so anchors coincide (removes frame drift)."""
    pts = [anchor_point(f, mode) for f in frames]
    left = max(ax for ax, _ in pts); right = max(f.width - ax for f, (ax, _) in zip(frames, pts))
    up = max(ay for _, ay in pts); down = max(f.height - ay for f, (_, ay) in zip(frames, pts))
    out = []
    for f, (ax, ay) in zip(frames, pts):
        c = Image.new("RGBA", (left + right, up + down), (0, 0, 0, 0))
        c.paste(f, (left - ax, up - ay), f)
        out.append(c)
    return out


def cmd_sheet(a):
    """Input is an AI sheet (extract into OUT/raw) or a raw/ folder (rebuild after fixing/inserting frames)."""
    out, src = Path(a.out), Path(a.sheet)
    raw = out / "raw"
    if src.is_dir():
        files = sorted(src.glob("*.png"))
    else:
        if raw.exists() and any(raw.iterdir()):
            sys.exit(f"{raw} already has frames (may contain your fixes). Rebuild from it: "
                     f"sprite.py sheet {raw} {out} ...  or choose a new OUT folder.")
        raw.mkdir(parents=True, exist_ok=True)
        for i, c in enumerate(extract_frames(Image.open(src)), 1):
            c.save(raw / f"{i:02}.png")
        files = sorted(raw.glob("*.png"))
        print(f"extracted {len(files)} frames -> {raw}")
    if not files:
        sys.exit(f"no PNG frames in {src}")
    print("frames: " + ", ".join(f"{i}={f.name}" for i, f in enumerate(files, 1)))
    pick = [int(x) for x in a.pick.split(",")] if a.pick else list(range(1, len(files) + 1))
    bad = [i for i in pick if not 1 <= i <= len(files)]
    if bad:
        sys.exit(f"--pick out of range {bad}; have {len(files)} frames")
    chosen = [files[i - 1] for i in pick]

    ps, snapped = a.pixel_size, []
    ah = char_height(Image.open(a.match)) if a.match else None
    if ah and not ps:
        # Auto-detect is unreliable on AI sheets, and the snapper's output height is a step function of
        # pixel_size. So trial-snap one frame over a range and take the finest grid whose character is not
        # taller than the anchor; the --match step below enlarges the rest (enlarging loses no pixels).
        best = None
        with tempfile.TemporaryDirectory() as t:
            for p in np.arange(2.0, 12.01, 0.5):
                run_snapper(chosen[0], Path(t) / "t.png", float(p), a.colors)
                h = char_height(clean(Image.open(Path(t) / "t.png")))
                if h <= ah and (best is None or h > best[1]):
                    best = (float(p), h)
        if best:
            ps = best[0]
            print(f"pixel_size {ps} (character {best[1]}px vs anchor {ah}px)")
    with tempfile.TemporaryDirectory() as t:
        for n, f in enumerate(chosen):
            dst = Path(t) / f"{n}.png"
            ps = run_snapper(f, dst, ps, a.colors)  # first frame's size is reused for all
            snapped.append(clean(Image.open(dst)))
    print(f"snapped with pixel_size={ps}")

    heights = [f.getbbox()[3] - f.getbbox()[1] for f in snapped]
    med = float(np.median(heights))
    odd = [f.name for f, h in zip(chosen, heights) if abs(h - med) > med * 0.12]
    if odd:
        print(f"WARNING height outliers (check scale/pose) {odd}; heights={heights}")

    # The model draws every image at its own pixel density, so a sheet's character is rarely as many
    # pixels tall as the anchor's. --match rescales all frames by one factor to the anchor's height.
    k_fixed = a.scale
    if a.match:
        f = ah / med
        print(f"match: frames x{f:.3f} (character {med:.0f}px -> anchor {ah}px)")
        if not 0.8 <= f <= 1.25:
            print("WARNING match factor is large, pixels will look uneven; regenerate the sheet with a closer size")
        snapped = [x.resize((max(1, round(x.width * f)), max(1, round(x.height * f))), Image.NEAREST) for x in snapped]
        k_fixed = k_fixed or max(1, a.cell // (ah * 3 // 2 + 1))  # depends only on the anchor, so every sheet of a character shares it

    aligned = align(snapped, a.anchor)
    if k_fixed and any(max(x.width, x.height) * k_fixed > a.cell for x in aligned):
        print(f"WARNING frames x{k_fixed} are bigger than the {a.cell}px cell and will be cropped: raise --cell or lower --scale")
    (out / "frames").mkdir(parents=True, exist_ok=True)
    for old in (out / "frames").glob("*.png"):
        old.unlink()  # derived output only; stale frames would mislead
    cells = []
    for f, img in zip(chosen, aligned):
        cell, k = nn_fit(img, a.cell, (0, 0, 0, 0), k_fixed)
        cell.save(out / "frames" / f.name)
        cells.append(cell)
    cols = a.cols or len(cells)
    rows = -(-len(cells) // cols)
    sheet = Image.new("RGBA", (cols * a.cell, rows * a.cell), (0, 0, 0, 0))
    for i, c in enumerate(cells):
        sheet.paste(c, ((i % cols) * a.cell, (i // cols) * a.cell))
    sheet.save(out / "sheet.png")
    cells[0].save(out / "preview.gif", save_all=True, append_images=cells[1:], duration=1000 // a.fps,
                  loop=0, disposal=2)
    print(f"sheet {sheet.width}x{sheet.height} ({len(cells)} frames, {cols} cols, cell {a.cell}, x{k}) -> {out/'sheet.png'}")
    print(f"preview -> {out/'preview.gif'}")


def cmd_put(a):
    """Put a separately generated frame (fix / in-between) into raw/, rescaled so the character's
    height matches the --match frames (raw crops are smaller than a 1024 generation)."""
    def main_crop(path):
        return max(extract_frames(Image.open(path)), key=lambda c: c.width * c.height)

    def char_h(img):
        ys = np.nonzero(~is_green(np.asarray(img)))[0]
        return ys.max() - ys.min() + 1

    target_h = float(np.mean([char_h(main_crop(m)) for m in a.match]))  # read before a fix overwrites it
    crop = main_crop(a.input)
    s = target_h / char_h(crop)
    crop = crop.resize((max(1, round(crop.width * s)), max(1, round(crop.height * s))), Image.LANCZOS)
    canvas = Image.new("RGB", (crop.width + 8, crop.height + 8), GREEN)
    canvas.paste(crop, (4, 4))
    canvas.save(a.out)
    print(f"{a.input} -> {a.out} (scaled x{s:.3f} to height {target_h:.0f}px)")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    s = p.add_subparsers(dest="cmd", required=True)
    r = s.add_parser("refs", help="checker_1024, poseboard_2048x1536, walkguide_8, walkguide_4"); r.add_argument("out")
    r = s.add_parser("prompt", help="fill a template from templates/")
    r.add_argument("kind", choices=sorted(p.stem for p in (HERE / "templates").glob("*.txt")))
    r.add_argument("--set", action="append", help="KEY=VALUE or KEY=@file")
    r.add_argument("--out")
    r = s.add_parser("gen", help="generate via Codex built-in image tool")
    r.add_argument("prompt"); r.add_argument("out"); r.add_argument("--ref", action="append")
    r = s.add_parser("snap", help="pixel-snap one image and NN-upscale (anchors)")
    r.add_argument("input"); r.add_argument("output")
    r.add_argument("--size", type=int, default=1024); r.add_argument("--native")
    r.add_argument("--pixel-size", type=float); r.add_argument("--colors", type=int, default=16)
    r = s.add_parser("sheet", help="AI sheet (or raw/ folder) -> snapped, aligned, cleaned, packed sprite sheet")
    r.add_argument("sheet", help="AI sheet PNG, or OUT/raw folder to rebuild after put")
    r.add_argument("out")
    r.add_argument("--pick", help="1-based positions in the printed frame list, in order, e.g. 2,3,4,6")
    r.add_argument("--anchor", choices=["feet", "torso"], default="feet", help="torso for walk/jump")
    r.add_argument("--pixel-size", type=float, help="the sheet's OWN pixel grid (omit to auto-detect); not the anchor's, the model draws each image at its own density")
    r.add_argument("--match", help="anchor *_native.png: rescale every frame so the character is as tall as in the anchor")
    r.add_argument("--scale", type=int, help="fixed integer enlargement of the output cells (with --match it is derived from the anchor height)")
    r.add_argument("--colors", type=int, default=16)
    r.add_argument("--cell", type=int, default=256); r.add_argument("--cols", type=int)
    r.add_argument("--fps", type=int, default=10)
    r = s.add_parser("put", help="insert a fixed / in-between frame into raw/, scaled to match frames")
    r.add_argument("input"); r.add_argument("out")
    r.add_argument("--match", action="append", required=True, help="raw frame(s) whose height to match")
    a = p.parse_args(argv)
    {"refs": cmd_refs, "prompt": cmd_prompt, "gen": cmd_gen, "snap": cmd_snap, "sheet": cmd_sheet,
     "put": cmd_put}[a.cmd](a)


if __name__ == "__main__":
    main()
