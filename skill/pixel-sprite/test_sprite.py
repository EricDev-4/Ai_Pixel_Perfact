"""Self-check: synthetic AI-ish sheet -> extract, anti-bleed, align, pack. Snapper is faked.
Run: .venv/bin/python test_sprite.py"""
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import sprite

PX = 8  # "true" pixel size of the fake art


def fake_snapper(src, dst, pixel_size=None, colors=16):
    im = Image.open(src).convert("RGB")
    im.resize((im.width // PX, im.height // PX), Image.NEAREST).save(dst)
    return pixel_size or PX


sprite.run_snapper = fake_snapper

# 2x2 board of 512 cells; each "character" = body + head, drifting position per frame.
board = Image.new("RGB", (1024, 1024), sprite.GREEN)
d = ImageDraw.Draw(board)
offsets = [(0, 0), (40, -24), (-32, 16), (16, 32)]
for i, (dx, dy) in enumerate(offsets):
    cx, cy = (i % 2) * 512 + 256 + dx, (i // 2) * 512 + 300 + dy
    d.rectangle([cx - 64, cy - 96, cx + 64, cy + 128], fill=(120, 60, 30))  # body; feet at cy+128
    d.rectangle([cx - 40, cy - 176, cx + 40, cy - 96], fill=(230, 190, 150))  # head
# frame bleeding: frame 1's long sword (attached to its head) reaches into frame 2's bbox,
# beside frame 2's head (x>=768) without touching it; frame 2's cape widens its bbox to x=700
d.rectangle([700, 380, 744, 404], fill=(120, 60, 30))
d.rectangle([296, 116, 730, 124], fill=(200, 200, 210))
board = board.filter(ImageFilter.GaussianBlur(1.2))  # AI-style mushy edges

with tempfile.TemporaryDirectory() as t:
    sheet_path = Path(t) / "sheet.png"
    board.save(sheet_path)

    crops = sprite.extract_frames(Image.open(sheet_path))
    assert len(crops) == 4, len(crops)
    # frame 2's crop must not contain frame 1's (grey) sword
    c2 = np.asarray(crops[1]).astype(int)
    assert not ((abs(c2[..., 0] - 200) < 20) & (abs(c2[..., 2] - 210) < 20)).any(), "bleeding not removed"

    out = Path(t) / "out"
    sprite.main(["sheet", str(sheet_path), str(out), "--pick", "1,2,3,4", "--cell", "256"])
    sheet = Image.open(out / "sheet.png")
    assert sheet.size == (1024, 256), sheet.size

    # anchoring: every frame's foot row and foot x must be identical
    pts = [sprite.anchor_point(Image.open(out / "frames" / f"{i:02}.png")) for i in range(1, 5)]
    assert len(set(pts)) == 1, pts

    # transparent background, no green left
    a = np.asarray(sheet)
    assert not sprite.is_green(a[a[..., 3] > 0]).any()

    # re-extracting into a raw/ that has frames must refuse (protects user fixes)
    try:
        sprite.main(["sheet", str(sheet_path), str(out)]); raise AssertionError("should refuse")
    except SystemExit as e:
        assert "already has frames" in str(e)

    # put: a 1024 "regenerated" frame 2x bigger is rescaled to the matched raw frame height, then rebuild
    raw = out / "raw"
    def char_h(p):
        ys = np.nonzero(~sprite.is_green(np.asarray(Image.open(p).convert("RGB"))))[0]
        return ys.max() - ys.min() + 1

    src = Image.open(raw / "02.png")
    big = Image.new("RGB", (1024, 1024), sprite.GREEN)
    big.paste(src.resize((src.width * 2, src.height * 2)), (100, 50))  # regenerated at ~2x size
    big.save(Path(t) / "gen.png")
    sprite.main(["put", str(Path(t) / "gen.png"), str(raw / "02b.png"), "--match", str(raw / "02.png")])
    assert abs(char_h(raw / "02b.png") - char_h(raw / "02.png")) <= 2, (char_h(raw / "02b.png"), char_h(raw / "02.png"))
    sprite.main(["sheet", str(raw), str(out), "--anchor", "torso"])
    names = sorted(p.name for p in (out / "frames").glob("*.png"))
    assert names == ["01.png", "02.png", "02b.png", "03.png", "04.png"], names
    assert Image.open(out / "sheet.png").size == (5 * 256, 256)

    # refs + prompt fill
    sprite.main(["refs", t])
    assert Image.open(Path(t) / "walkguide_8.png").size == (2048, 1536)
    sprite.main(["prompt", "walk", "--out", str(pf := Path(t) / "w.txt"), "--set", "N=8",
                 "--set", "DIRECTION_DESCRIPTION=side view facing left"])
    assert "{" not in pf.read_text()
    chk = np.asarray(Image.open(Path(t) / "checker_1024.png"))
    assert chk[0, 0, 0] == 255 and chk[0, 1, 0] == 0 and chk[1, 1, 0] == 255
    pf = Path(t) / "p.txt"
    sprite.main(["prompt", "sheet", "--out", str(pf), "--set", "ACTION=attack", "--set", "N=8",
                 "--set", "DIRECTION_DESCRIPTION=facing left", "--set", "FRAME_BY_FRAME_DESCRIPTION=x"])
    assert "{" not in pf.read_text()

print("ok")
