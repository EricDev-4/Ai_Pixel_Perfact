#!/usr/bin/env python3
"""AI pixel-art sprite pipeline: refs, prompt, gen (Codex), snap, sheet post-process."""
import argparse, base64, io, json, os, re, shutil, subprocess, sys, tempfile, time, urllib.error, urllib.request
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
SNAPPER = "spritefusion-pixel-snapper"
KEY = (255, 0, 255)  # chroma magenta: no ENDESGA 32 colour is keyed out (green #63c74d was)
CELL = 64  # runtime frame cell in dots (1 dot = 1 px in every saved file; the engine scales x2)
SRC_GRID = 1024 // CELL  # 16 px per dot on a 1024 single-frame generation
BOARD_GRID = 512 // CELL  # 8 px per dot on the 2048x1536 pose board (512 px cells)


# ---------- helpers ----------
def is_key(a):
    """Chroma-magenta mask for an RGB(A) uint8 array (tolerant: AI + quantized magentas drift)."""
    a = a.astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    m = (r > 120) & (b > 120) & (np.minimum(r, b) - g > 70)
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
    """Height in px of the non-background part of an image (chroma magenta / transparent = background)."""
    ys = np.nonzero((~is_key(np.asarray(img.convert("RGBA")))).any(1))[0]
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


def snap_grid(src, dst, grid, colors):
    """Snap at the generation grid; if the output size shows the model ignored it, fall back to auto-detect."""
    w, h = Image.open(src).size
    ps = run_snapper(src, dst, grid, colors)
    got = Image.open(dst).size
    want = (round(w / grid), round(h / grid))
    if max(abs(g - w_) / w_ for g, w_ in zip(got, want)) > 0.05:  # snapper adapts grid lines: a few % is normal
        ps = run_snapper(src, dst, None, colors)
        print(f"WARNING {Path(src).name}: grid {grid}px not honoured (got {got}, want {want}); "
              f"auto-detected pixel_size={ps} -> {Image.open(dst).size}. Dot size may differ from other assets.")
    return ps


# ---------- commands ----------
def cmd_refs(a):
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    for name, (w, h), g in (("checker_1024.png", (1024, 1024), SRC_GRID),
                            ("poseboard_2048x1536.png", (2048, 1536), BOARD_GRID)):
        yy, xx = np.indices((h, w))  # checker of g x g blocks = the dot grid the model must draw on
        px = np.where(((xx // g + yy // g) % 2 == 0)[..., None], 255, 0).astype(np.uint8).repeat(3, -1)
        Image.fromarray(px).save(out / name)
        print(out / name)
    for n in (8, 4):
        walk_guide(n).save(out / f"walkguide_{n}.png")
        print(out / f"walkguide_{n}.png")


NEAR, FAR = (230, 30, 30), (40, 80, 230)  # near-side limbs red, far-side blue (never magenta: chroma)


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
    b = int(vals.setdefault("BODY_DOTS", "32"))  # character fits in b x b dots (AGENTS.md size tiers)
    vals.update(BODY_PX=str(b * SRC_GRID), BODY_BOARD_PX=str(b * BOARD_GRID))
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
        ps = snap_grid(a.input, native, a.pixel_size, a.colors)
        img = Image.open(native).convert("RGB")
        if a.native:
            img.save(a.native)
        big, k = nn_fit(img, a.size, KEY)
        big.save(a.output)
    bb = clean(img).getbbox()
    size = (bb[2] - bb[0], bb[3] - bb[1]) if bb else (0, 0)
    print(f"pixel_size={ps} native={img.width}x{img.height} character={size[0]}x{size[1]} dots scale=x{k} -> {a.output}")
    if max(size) > 48:
        print("NOTE character is larger than 48 dots (character tier 28-48): allowed only for large tiers in AGENTS.md")


def cmd_up(a):
    """Integer NN enlargement of a native (1 dot = 1 px) frame, e.g. raw/05.png as a 1024 generation reference."""
    big, k = nn_fit(Image.open(a.input).convert("RGB"), a.size, KEY)
    big.save(a.output)
    print(f"x{k} -> {a.output}")


def cmd_idle(a):
    """Breathing idle made from the anchor alone (no generation, so face and hair never drift):
    everything above the waist row sinks 1 dot in the second half of the loop; legs stay put.
    Writes OUT/raw/NN.png (native, magenta background); then build with `sheet OUT/raw OUT ...`."""
    src = clean(Image.open(a.anchor))
    src = src.crop(src.getbbox())
    w, h = src.size
    waist = a.waist if a.waist is not None else round(h * 0.7)  # rows from the top that move; below stays
    raw = Path(a.out) / "raw"
    if raw.exists() and any(raw.iterdir()):
        sys.exit(f"{raw} already has frames; choose a new OUT folder or remove it")
    raw.mkdir(parents=True, exist_ok=True)
    top, legs = src.crop((0, 0, w, waist)), src.crop((0, waist, w, h))
    for i in range(a.frames):
        dy = 1 if i >= a.frames // 2 else 0  # first half neutral, second half exhaled
        fr = Image.new("RGBA", (w + 2, h + 2), (0, 0, 0, 0))
        fr.paste(legs, (1, 1 + waist), legs)
        fr.paste(top, (1, 1 + dy), top)  # sinking top covers the legs' first row: no gap
        bg = Image.new("RGB", fr.size, KEY)
        bg.paste(fr, (0, 0), fr)
        bg.save(raw / f"{i + 1:02}.png")
    print(f"idle: {a.frames} frames, rows 0-{waist - 1} of {h} sink 1 dot in frames {a.frames // 2 + 1}-{a.frames} -> {raw}")


PL_API = "https://api.pixellab.ai/v2"
PL_MAX = 256  # PixelLab animation input px per side (v3 also: w*h*frames <= 524288)


def pl_call(path, body=None):
    kf = Path.home() / ".config/pixellab/api_key"
    key = (os.environ.get("PIXELLAB_API_KEY") or (kf.read_text().strip() if kf.exists() else "")
           or sys.exit(f"set PIXELLAB_API_KEY or put the key in {kf} (pixellab.ai -> account -> API)"))
    req = urllib.request.Request(PL_API + path, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"PixelLab {path}: HTTP {e.code} {e.read().decode(errors='replace')[:500]}")


def b64png(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return {"type": "base64", "base64": base64.b64encode(buf.getvalue()).decode(), "format": "png"}


def pl_request(anchor, prompt, frames, model, canvas, seed=None, last_anchor=False):
    """-> (endpoint, body). The anchor native (1 dot = 1 px) sits at the bottom centre of a transparent
    canvas with room for the motion; frames come back at the input size, so the dot size is kept.
    PixelLab has no palette lock: colours are fixed afterwards by `sheet --table` + `check`."""
    if model == "v3" and (frames % 2 or not 4 <= frames <= 16):
        sys.exit("v3 needs an even frame count 4-16")
    if model == "pixminimax" and (frames % 4 or not 4 <= frames <= 40):
        sys.exit("pixminimax needs a frame count that is a multiple of 4, 4-40")
    src = clean(Image.open(anchor))
    src = src.crop(src.getbbox())
    side = max(canvas, src.width + 4, src.height + 4)
    if side > PL_MAX or (model == "v3" and side * side * frames > 524288):
        sys.exit(f"canvas {side}px x {frames} frames exceeds the PixelLab limit for {model}")
    bg = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    bg.paste(src, ((side - src.width) // 2, side - src.height - 2), src)
    body = {"first_frame": b64png(bg), "frame_count": frames, "no_background": True, "seed": seed or 0}
    if last_anchor:  # end on the anchor pose: attacks return to the start instead of stopping short
        body["last_frame"] = b64png(bg)
    body["action" if model == "v3" else "description"] = prompt
    return ("/animate-with-text-v3" if model == "v3" else "/animate-pixminimax"), body


def pl_frames(images, model):
    """last_response.images (base64, maybe data: URLs) -> RGB frames on magenta.
    pixminimax returns frame_count + 1 images; index 0 is the unchanged input."""
    out = []
    for im in images[1:] if model == "pixminimax" else images:
        fr = Image.open(io.BytesIO(base64.b64decode(im["base64"].split(",")[-1]))).convert("RGBA")
        bg = Image.new("RGB", fr.size, KEY)
        bg.paste(fr, (0, 0), fr)
        out.append(bg)
    return out


def cmd_animate(a):
    """Animate the anchor with PixelLab -> OUT/raw/NN.png (AI originals);
    then build with `sheet OUT/raw OUT --compare <anchor>`."""
    out = Path(a.out)
    raw = out / "raw"
    if raw.exists() and any(raw.iterdir()):
        sys.exit(f"{raw} already has frames; choose a new OUT folder or remove it")
    prompt = Path(a.prompt[1:]).read_text().strip() if a.prompt.startswith("@") else a.prompt
    path, body = pl_request(a.anchor, prompt, a.frames, a.model, a.canvas, a.seed, a.last_anchor)
    job = pl_call(path, body)["background_job_id"]
    print(f"submitted job {job} ({a.model}, {a.frames} frames); waiting (30-180 s)", flush=True)
    deadline = time.time() + a.timeout
    while (j := pl_call(f"/background-jobs/{job}"))["status"] not in ("completed", "failed"):
        if time.time() > deadline:
            sys.exit(f"timeout; the job keeps running: GET /background-jobs/{job}")
        time.sleep(4)
    if j["status"] != "completed":
        sys.exit(f"job {job} failed: {(j.get('last_response') or {}).get('detail')}")
    frames = pl_frames(j["last_response"]["images"], a.model)
    raw.mkdir(parents=True, exist_ok=True)
    for i, fr in enumerate(frames, 1):
        fr.save(raw / f"{i:02}.png")
    print(f"{len(frames)} frames {frames[0].width}x{frames[0].height}, cost {j.get('usage')} -> {raw}\n"
          f"next: sprite.py sheet {raw} {out} --compare {a.anchor}")



def extract_frames(sheet, min_frac=0.08, f=1, glue=1):
    """Split a pose-board into per-character crops (bbox), ordered row-major.
    f: label on a 1/f grid for speed (4 suits full-size AI images; native boards use 1);
    glue: dilation radius that joins detached weapon bits to their body."""
    rgb = np.asarray(sheet.convert("RGB"))
    small = ~is_key(rgb[::f, ::f])
    comps = label(dilate(small, glue))
    labmap = np.zeros(small.shape, int)
    for i, c in enumerate(comps, 1):
        labmap[c] = i
    big = max((len(c[0]) for c in comps), default=0)
    keep = [i for i, c in enumerate(comps, 1) if big and len(c[0]) >= big * min_frac]
    if not keep:
        sys.exit("no characters found (is the background chroma magenta #FF00FF?)")
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
        crop[labfull[y0:y1, x0:x1] != i] = KEY  # blank neighbours bleeding into this bbox
        crops.append(Image.fromarray(crop))
    return crops


def clean(img, speck=3):
    """Chroma magenta -> transparent, then drop tiny isolated pixel clusters (despeckle)."""
    a = np.asarray(img.convert("RGBA")).copy()
    a[is_key(a)] = 0
    solid = a[..., 3] > 0
    # despill: magenta-tinted edge pixels (outline blended with the chroma bg) -> the sprite's own outline colour.
    # Edge ring only, so purple/pink palette colours inside the sprite are left alone.
    rgb = a[..., :3].astype(int)
    edge = solid & dilate(~solid, 1)
    lo = np.minimum(rgb[..., 0], rgb[..., 2])
    spill = edge & (lo > 100) & (lo - rgb[..., 1] > 60)  # ENDESGA #ff0044 #68386c #b55088 stay untouched
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
    """Input is an AI sheet (snapped once at the board grid, frames extracted into OUT/raw as native
    1 dot = 1 px crops) or a raw/ folder (rebuild after fixing/inserting frames). No resizing anywhere:
    every frame keeps the dot size it was snapped at and is placed in a CELL x CELL cell."""
    out, src = Path(a.out), Path(a.sheet)
    raw = out / "raw"
    if src.is_dir():
        files = sorted(src.glob("*.png"))
    else:
        if raw.exists() and any(raw.iterdir()):
            sys.exit(f"{raw} already has frames (may contain your fixes). Rebuild from it: "
                     f"sprite.py sheet {raw} {out} ...  or choose a new OUT folder.")
        raw.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as t:
            native = Path(t) / "board.png"
            ps = snap_grid(src, native, a.pixel_size, a.colors)  # one grid + one colour set for the whole sheet
            board = Image.open(native).convert("RGB")
        print(f"snapped board with pixel_size={ps} -> {board.width}x{board.height} dots")
        for i, c in enumerate(extract_frames(board), 1):
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
    frames = [c.crop(c.getbbox()) for c in (clean(Image.open(f)) for f in chosen)]  # drop transparent margins

    heights = [f.getbbox()[3] - f.getbbox()[1] for f in frames]
    med = float(np.median(heights))
    odd = [f.name for f, h in zip(chosen, heights) if abs(h - med) > med * 0.12]
    if odd:
        print(f"WARNING height outliers (check pose) {odd}; heights={heights}")
    if a.compare:
        # Supporting check only (AGENTS.md): poses change height, so compare with the anchor, never resize.
        ah = char_height(Image.open(a.compare))
        print(f"height: frames median {med:.0f} dots vs anchor {ah} dots")
        if abs(med - ah) > 2:
            print("WARNING the sheet is drawn at a different scale than the anchor: regenerate or hand-fix (no resizing)")

    before = None
    if a.table:
        table = read_table(a.table)
        before = frames
        res = [apply_table(f, table) for f in frames]
        frames = [r[0] for r in res]
        missing = set().union(*(r[1] for r in res))
        if missing:
            print(f"WARNING {len(missing)} colours are not in {a.table} and were left unchanged: "
                  + " ".join(map(hexc, sorted(missing))) + "  -> add them to the table")
    elif a.ramps:
        tsv = out / "colors.tsv"
        if tsv.exists():
            print(f"{tsv} exists (may hold your edits); not overwritten")
        else:
            rows = propose_table(frames, read_ramps(a.ramps))
            write_table(tsv, rows)
            print(f"draft colour table ({len(rows)} colours, {sum(1 for r in rows if r[4])} ambiguous) -> {tsv}")

    aligned = align(frames, a.anchor)
    w, h = aligned[0].size
    ax, ay = anchor_point(aligned[0], a.anchor)  # identical for every aligned frame
    ox, oy = a.cell // 2 - ax, a.cell - 1 - ay  # anchor -> bottom centre of the cell
    if ox < 0 or oy < 0 or ox + w > a.cell or oy + h > a.cell:
        print(f"WARNING frames ({w}x{h} dots around the anchor) do not fit the {a.cell}x{a.cell} cell and are cropped")
    (out / "frames").mkdir(parents=True, exist_ok=True)
    for old in (out / "frames").glob("*.png"):
        old.unlink()  # derived output only; stale frames would mislead
    cells = []
    for f, img in zip(chosen, aligned):
        cell = Image.new("RGBA", (a.cell, a.cell), (0, 0, 0, 0))
        cell.paste(img, (ox, oy), img)
        cell.save(out / "frames" / f.name)
        cells.append(cell)
    cols = a.cols or len(cells)
    sheet = pack(cells, cols, a.cell)
    sheet.save(out / "sheet.png")
    k = 4  # preview only; game files stay 1 dot = 1 px and the engine scales x2
    big = [c.resize((c.width * k, c.height * k), Image.NEAREST) for c in cells]
    big[0].save(out / "preview.gif", save_all=True, append_images=big[1:], duration=1000 // a.fps, loop=0, disposal=2)
    print(f"sheet {sheet.width}x{sheet.height} dots ({len(cells)} frames, {cols} cols, cell {a.cell}) -> {out/'sheet.png'}")
    print(f"preview (x{k}, viewing only) -> {out/'preview.gif'}")
    if before is not None:
        bcells = []
        for img in align(before, a.anchor):  # same alpha as the remapped frames -> same placement
            c = Image.new("RGBA", (a.cell, a.cell), (0, 0, 0, 0)); c.paste(img, (ox, oy), img); bcells.append(c)
        palette = sorted({t for _, t in table.values()}, key=luma)
        (out / "palette.hex").write_text("".join(hexc(c)[1:] + "\n" for c in palette))
        print(f"character palette ({len(palette)} colours) -> {out / 'palette.hex'}")
        write_review(out, pack(bcells, cols, a.cell), sheet, table, palette)
        (out / "review" / "frames.txt").write_text("\n".join(f.name for f in chosen), encoding="utf-8")
        return cmd_check(argparse.Namespace(inputs=[str(out / "frames"), str(out / "sheet.png")],
                                            palette=str(out / "palette.hex"), max_colors=16))


def cmd_put(a):
    """Put a separately generated frame (fix / in-between, 1024 at the 16 px grid) into raw/ as a native
    crop. No resizing: the height is only compared with the --match raw frames."""
    with tempfile.TemporaryDirectory() as t:
        native = Path(t) / "n.png"
        snap_grid(a.input, native, a.pixel_size, a.colors)
        crop = max(extract_frames(Image.open(native).convert("RGB")), key=lambda c: c.width * c.height)
    canvas = Image.new("RGB", (crop.width + 2, crop.height + 2), KEY)
    canvas.paste(crop, (1, 1))
    canvas.save(a.out)
    h, target = char_height(canvas), float(np.mean([char_height(Image.open(m)) for m in a.match]))
    print(f"{a.input} -> {a.out} (character {h} dots, --match frames {target:.0f} dots)")
    if abs(h - target) > 2:
        print("WARNING height differs from the matched frames by more than 2 dots: regenerate or hand-fix (no resizing)")


def read_hex(path):
    """Lospec .hex palette file -> set of (r, g, b)."""
    lines = [l.strip().lstrip("#") for l in Path(path).read_text().splitlines() if l.strip()]
    return {tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) for h in lines}


def hexc(c):
    return "#%02x%02x%02x" % c


def cmd_check(a):
    """Report palette / colour-count / alpha problems. Soft gate (AGENTS.md rule 6): reports, never blocks.
    Fully transparent pixels are ignored. Returns True when everything passes."""
    pal = read_hex(a.palette)
    files = [f for p in map(Path, a.inputs) for f in (sorted(p.glob("*.png")) if p.is_dir() else [p])]
    if not files:
        sys.exit("no PNG files to check")
    union, ok = set(), True
    for f in files:
        px = np.asarray(Image.open(f).convert("RGBA"))
        al = px[..., 3]
        semi = int(((al > 0) & (al < 255)).sum())
        cols, counts = np.unique(px[al == 255][:, :3], axis=0, return_counts=True)
        cols = [tuple(int(v) for v in c) for c in cols]
        union.update(cols)
        off = [(c, int(n)) for c, n in zip(cols, counts) if c not in pal]
        good = not off and not semi and len(cols) <= a.max_colors
        ok &= good
        print(f"{'PASS' if good else 'REVIEW'} {f.name}: {len(cols)} colours (max {a.max_colors}), "
              f"off-palette {len(off)}, semi-transparent {semi}")
        for c, n in off:
            ys, xs = np.nonzero((px[..., :3] == c).all(-1) & (al == 255))
            print(f"  off {hexc(c)} x{n} at x{xs.min()}-{xs.max()} y{ys.min()}-{ys.max()}")
    if len(files) > 1:
        uoff = sorted(c for c in union if c not in pal)
        good = not uoff and len(union) <= a.max_colors
        ok &= good
        print(f"{'PASS' if good else 'REVIEW'} union of {len(files)} files: {len(union)} colours (max {a.max_colors}), "
              f"off-palette {len(uoff)}" + (": " + " ".join(map(hexc, uoff)) if uoff else ""))
    print("RESULT:", "PASS" if ok else "REVIEW (not approved as final until reviewed)")
    return ok


# ---------- remap (AGENTS.md rules 4-6: colour table per sheet, same-ramp brightness order) ----------
def read_ramps(path):
    """Material ramps from a palette .md table: rows like '| wood | ... | `#3e2731` `#733e39` ... |' (dark -> light)."""
    ramps = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        cols = re.findall(r"`#([0-9a-fA-F]{6})`", line)
        if line.lstrip().startswith("|") and cols and cells[0]:
            ramps[cells[0]] = [tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) for h in cols]
    if not ramps:
        sys.exit(f"no ramps found in {path}")
    return ramps


def luma(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def cdist(a, b):
    """'Redmean' weighted RGB distance: cheap, closer to perception than plain RGB."""
    rm = (a[0] + b[0]) / 2
    dr, dg, db = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return ((2 + rm / 256) * dr * dr + 4 * dg * dg + (2 + (255 - rm) / 256) * db * db) ** 0.5


def ramp_pick(ramp, c):
    """Ramp colour with the nearest brightness: monotonic, so brightness order inside a material is kept."""
    return min(ramp, key=lambda r: abs(luma(r) - luma(c)))


def propose_table(frames, ramps):
    """Draft rows (source, pixels, material, target, note). Material = nearest ramp; flagged when two ramps are close."""
    counts = {}
    for f in frames:
        px = np.asarray(f.convert("RGBA"))
        cols, n = np.unique(px[px[..., 3] == 255][:, :3], axis=0, return_counts=True)
        for c, k in zip(cols, n):
            c = tuple(int(v) for v in c)
            counts[c] = counts.get(c, 0) + int(k)
    rows = []
    for c, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        d = sorted((min(cdist(c, r) for r in ramp), name) for name, ramp in ramps.items())
        mat = d[0][1]
        note = f"ambiguous: {d[0][1]}/{d[1][1]}" if len(d) > 1 and d[1][0] < d[0][0] * 1.15 else ""
        rows.append((c, n, mat, ramp_pick(ramps[mat], c), note))
    return rows


def write_table(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# source\tpixels\tmaterial\ttarget\tnote  (draft: review, edit material/target, then sheet --table)\n")
        for c, n, mat, t, note in rows:
            fh.write(f"{hexc(c)}\t{n}\t{mat}\t{hexc(t)}\t{note}\n")


def read_table(path):
    """colors.tsv -> {source rgb: (material, target rgb)}."""
    rgb = lambda h: tuple(int(h.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    m = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("# "):  # rows start with '#rrggbb'; comments with '# '
            src, _, mat, tgt, *_ = line.split("\t") + [""]
            m[rgb(src)] = (mat, rgb(tgt))
    return m


def apply_table(img, table):
    """Recolour opaque pixels by the approved table; colours missing from the table are left as they are."""
    px = np.asarray(img.convert("RGBA")).copy()
    op = px[..., 3] == 255
    missing = set()
    for c in {tuple(int(v) for v in c) for c in np.unique(px[op][:, :3], axis=0)}:
        sel = op & (px[..., :3] == c).all(-1)
        if c in table:
            px[sel, :3] = table[c][1]
        else:
            missing.add(c)
    return Image.fromarray(px), missing


def find_aseprite():
    for c in (os.environ.get("ASEPRITE"), shutil.which("aseprite"),
              r"C:\Program Files (x86)\Steam\steamapps\common\Aseprite\Aseprite.exe",
              r"C:\Program Files\Aseprite\Aseprite.exe", "/Applications/Aseprite.app/Contents/MacOS/aseprite"):
        if c and Path(c).exists():
            return c
    return None


REVIEW_LUA = r"""
local p = app.params
local spr = Sprite{ fromFile = p.before }
spr.layers[1].name = "before"
local function add(name, file, visible)
  local l = spr:newLayer(); l.name = name; l.isVisible = visible
  spr:newCel(l, spr.frames[1], Image{ fromFile = file }, Point(0, 0))
end
add("after", p.after, true)
for i = 1, tonumber(p.n) do add("mat_" .. p["m" .. i], p["f" .. i], false) end
local hexes = {}
for h in string.gmatch(p.pal, "%x%x%x%x%x%x") do hexes[#hexes + 1] = h end
local pal = Palette(#hexes)
for i, h in ipairs(hexes) do
  pal:setColor(i - 1, Color{ r = tonumber(h:sub(1, 2), 16), g = tonumber(h:sub(3, 4), 16), b = tonumber(h:sub(5, 6), 16) })
end
spr:setPalette(pal)
spr:saveAs(p.out)
"""


def write_review(out, before, after, table, palette):
    """OUT/review/: before.png, after.png, one PNG per material, review.aseprite (layers before / after / mat_*)."""
    rv = out / "review"
    rv.mkdir(exist_ok=True)
    before.save(rv / "before.png"); after.save(rv / "after.png")
    b = np.asarray(before.convert("RGBA"))
    a = np.asarray(after.convert("RGBA"))
    mats = sorted({m for m, _ in table.values()})
    files = []
    for m in mats:
        keep = np.zeros(b.shape[:2], bool)
        for c, (mm, _) in table.items():
            if mm == m:
                keep |= (b[..., :3] == c).all(-1) & (b[..., 3] == 255)
        layer = a.copy(); layer[~keep] = 0
        f = rv / f"mat_{m}.png"; Image.fromarray(layer).save(f); files.append(f)
    ase = find_aseprite()
    if not ase:
        print("NOTE Aseprite not found (set ASEPRITE=path): review PNGs only in", rv)
        return
    lua = rv / "build_review.lua"; lua.write_text(REVIEW_LUA, encoding="utf-8")
    args = [ase, "-b", "--script-param", f"before={rv / 'before.png'}", "--script-param", f"after={rv / 'after.png'}",
            "--script-param", f"n={len(mats)}", "--script-param", "pal=" + ",".join(hexc(c)[1:] for c in palette),
            "--script-param", f"out={out / 'review.aseprite'}"]
    for i, (m, f) in enumerate(zip(mats, files), 1):
        args += ["--script-param", f"m{i}={m}", "--script-param", f"f{i}={f}"]
    subprocess.run(args + ["--script", str(lua)], capture_output=True, text=True)
    if (out / "review.aseprite").exists():
        print(f"review -> {out / 'review.aseprite'} (layers: before, after, " + ", ".join(f"mat_{m}" for m in mats) + ")")
    else:
        print("WARNING Aseprite did not write review.aseprite; review PNGs are in", rv)


def pack(cells, cols, cell):
    rows = -(-len(cells) // cols)
    sheet = Image.new("RGBA", (cols * cell, rows * cell), (0, 0, 0, 0))
    for i, c in enumerate(cells):
        sheet.paste(c, ((i % cols) * cell, (i // cols) * cell))
    return sheet


def cmd_review_import(a):
    """Take the (hand-edited) 'after' layer of OUT/review.aseprite as the final frames/ + sheet.png, then check."""
    out = Path(a.out)
    ase = find_aseprite()
    if not ase:
        sys.exit("Aseprite not found (set ASEPRITE=path)")
    names = (out / "review" / "frames.txt").read_text(encoding="utf-8").split()
    after = out / "review" / "after_edited.png"
    subprocess.run([ase, "-b", str(out / "review.aseprite"), "--layer", "after", "--save-as", str(after)],
                   capture_output=True, text=True)
    if not after.exists():
        sys.exit("Aseprite did not export the 'after' layer")
    sheet = Image.open(after).convert("RGBA")
    cols = sheet.width // a.cell
    for i, n in enumerate(names):
        x, y = (i % cols) * a.cell, (i // cols) * a.cell
        sheet.crop((x, y, x + a.cell, y + a.cell)).save(out / "frames" / n)
    sheet.save(out / "sheet.png")
    print(f"imported {len(names)} frames from review.aseprite -> {out / 'frames'}, {out / 'sheet.png'}")
    return cmd_check(argparse.Namespace(inputs=[str(out / "frames"), str(out / "sheet.png")],
                                        palette=str(out / "palette.hex"), max_colors=a.max_colors))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    s = p.add_subparsers(dest="cmd", required=True)
    r = s.add_parser("refs", help="dot-grid checkers checker_1024 (16 px) and poseboard_2048x1536 (8 px), walkguide_8, walkguide_4"); r.add_argument("out")
    r = s.add_parser("prompt", help="fill a template from templates/")
    r.add_argument("kind", choices=sorted(p.stem for p in (HERE / "templates").glob("*.txt")))
    r.add_argument("--set", action="append", help="KEY=VALUE or KEY=@file")
    r.add_argument("--out")
    r = s.add_parser("gen", help="generate via Codex built-in image tool")
    r.add_argument("prompt"); r.add_argument("out"); r.add_argument("--ref", action="append")
    r = s.add_parser("snap", help="pixel-snap one 1024 image at the 16 px grid and NN-upscale (anchors)")
    r.add_argument("input"); r.add_argument("output")
    r.add_argument("--size", type=int, default=1024); r.add_argument("--native")
    r.add_argument("--pixel-size", type=float, default=SRC_GRID); r.add_argument("--colors", type=int, default=32)
    r = s.add_parser("idle", help="breathing idle from the anchor native (no generation): writes OUT/raw")
    r.add_argument("anchor"); r.add_argument("out")
    r.add_argument("--frames", type=int, default=8)
    r.add_argument("--waist", type=int, help="rows from the top of the character that move (default 70%% of its height)")
    r = s.add_parser("animate", help="animate the anchor native with PixelLab (needs PIXELLAB_API_KEY): writes OUT/raw")
    r.add_argument("anchor"); r.add_argument("out")
    r.add_argument("--prompt", required=True, help="motion text or @file")
    r.add_argument("--frames", type=int, default=8)
    r.add_argument("--model", choices=["v3", "pixminimax"], default="v3", help="v3: even 4-16 frames; pixminimax (beta): multiple of 4, 4-40")
    r.add_argument("--last-anchor", action="store_true", help="end on the anchor pose (attacks); not for loops")
    r.add_argument("--canvas", type=int, default=128, help="square canvas px around the anchor (room for the motion)")
    r.add_argument("--seed", type=int); r.add_argument("--timeout", type=int, default=600)
    r = s.add_parser("up", help="integer NN enlargement of a native frame (generation reference)")
    r.add_argument("input"); r.add_argument("output"); r.add_argument("--size", type=int, default=1024)
    r = s.add_parser("sheet", help="AI sheet (or raw/ folder) -> snapped, aligned, cleaned, packed sprite sheet")
    r.add_argument("sheet", help="AI sheet PNG, or OUT/raw folder to rebuild after put")
    r.add_argument("out")
    r.add_argument("--pick", help="1-based positions in the printed frame list, in order, e.g. 2,3,4,6")
    r.add_argument("--anchor", choices=["feet", "torso"], default="feet", help="torso for walk/jump")
    r.add_argument("--pixel-size", type=float, default=BOARD_GRID, help="board grid in px per dot (falls back to auto-detect)")
    r.add_argument("--compare", help="anchor *_native.png: warn if the sheet's character height differs (never resizes)")
    r.add_argument("--colors", type=int, default=32)
    r.add_argument("--cell", type=int, default=CELL, help="cell size in dots"); r.add_argument("--cols", type=int)
    r.add_argument("--ramps", help="palette ramps .md (e.g. project/palettes/endesga-32.md): write a draft OUT/colors.tsv")
    r.add_argument("--table", help="approved colors.tsv: recolour, write palette.hex + review.aseprite, then check")
    r.add_argument("--fps", type=int, default=10)
    r = s.add_parser("put", help="insert a fixed / in-between frame into raw/, scaled to match frames")
    r.add_argument("input"); r.add_argument("out")
    r.add_argument("--match", action="append", required=True, help="raw frame(s) whose height to compare")
    r.add_argument("--pixel-size", type=float, default=SRC_GRID); r.add_argument("--colors", type=int, default=32)
    r = s.add_parser("check", help="report off-palette colours, colour count and semi-transparency (frames/ dir or PNGs)")
    r.add_argument("inputs", nargs="+", help="PNG files and/or folders of PNGs (e.g. OUT/frames OUT/sheet.png)")
    r.add_argument("--palette", required=True, help="character palette .hex (or the scene palette)")
    r.add_argument("--max-colors", type=int, default=16)
    r = s.add_parser("review-import", help="use the edited 'after' layer of OUT/review.aseprite as final frames, then check")
    r.add_argument("out"); r.add_argument("--cell", type=int, default=CELL); r.add_argument("--max-colors", type=int, default=16)
    a = p.parse_args(argv)
    return {"refs": cmd_refs, "prompt": cmd_prompt, "gen": cmd_gen, "snap": cmd_snap, "sheet": cmd_sheet,
            "put": cmd_put, "check": cmd_check, "up": cmd_up,
            "review-import": cmd_review_import, "idle": cmd_idle, "animate": cmd_animate}[a.cmd](a)


if __name__ == "__main__":
    main()
