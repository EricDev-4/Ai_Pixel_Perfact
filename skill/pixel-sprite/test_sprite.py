"""Self-check: synthetic AI-ish sheet -> extract, anti-bleed, align, pack. Snapper is faked.
Run: .venv/bin/python test_sprite.py"""
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import sprite

PX = 8  # "true" pixel size of the fake art


def fake_snapper(src, dst, pixel_size=None, colors=16):
    """Honours a given grid like the real snapper; auto-detect finds the art's true PX."""
    ps = pixel_size or PX
    im = Image.open(src).convert("RGB")
    im.resize((round(im.width / ps), round(im.height / ps)), Image.NEAREST).save(dst)
    return ps


sprite.run_snapper = fake_snapper

# 2x2 board of 512 cells; each "character" = body + head, drifting position per frame.
board = Image.new("RGB", (1024, 1024), sprite.KEY)
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

    # board is snapped once at the 8 px board grid, then frames are cut from the native board
    native = Path(t) / "native.png"
    assert sprite.snap_grid(sheet_path, native, sprite.BOARD_GRID, 32) == 8
    assert Image.open(native).size == (128, 128)
    crops = sprite.extract_frames(Image.open(native))
    assert len(crops) == 4, len(crops)
    # frame 2's crop must not contain frame 1's (grey) sword
    c2 = np.asarray(crops[1]).astype(int)
    assert not ((abs(c2[..., 0] - 200) < 20) & (abs(c2[..., 2] - 210) < 20)).any(), "bleeding not removed"

    out = Path(t) / "out"
    sprite.main(["sheet", str(sheet_path), str(out), "--pick", "1,2,3,4"])
    sheet = Image.open(out / "sheet.png")
    assert sheet.size == (4 * 64, 64), sheet.size  # 64-dot cells, 1 dot = 1 px, never resized
    f1 = Image.open(out / "frames" / "02.png")
    bb = f1.getbbox()
    assert bb[3] == 64 and abs(bb[3] - bb[1] - 38) <= 1, bb  # feet on the cell bottom; 304 px / 8 = 38 dots (+blur fringe)

    # anchoring: every frame's foot row and foot x must be identical (bottom centre of the cell)
    pts = [sprite.anchor_point(Image.open(out / "frames" / f"{i:02}.png")) for i in range(1, 5)]
    assert len(set(pts)) == 1 and pts[0] == (32, 63), pts

    # transparent background, no magenta left
    a = np.asarray(sheet)
    assert not sprite.is_key(a[a[..., 3] > 0]).any()

    # re-extracting into a raw/ that has frames must refuse (protects user fixes)
    try:
        sprite.main(["sheet", str(sheet_path), str(out)]); raise AssertionError("should refuse")
    except SystemExit as e:
        assert "already has frames" in str(e)

    # put: a fix generated on the 16 px grid lands in raw/ at the same dot size (no resizing), then rebuild
    raw = out / "raw"
    sprite.main(["up", str(raw / "02.png"), str(Path(t) / "ref02.png")])  # generation reference
    assert Image.open(Path(t) / "ref02.png").size == (1024, 1024)
    src = Image.open(raw / "02.png")
    gen, k = sprite.nn_fit(src, 1024, sprite.KEY, sprite.SRC_GRID)
    assert k == 16
    gen.save(Path(t) / "gen.png")
    sprite.main(["put", str(Path(t) / "gen.png"), str(raw / "02b.png"), "--match", str(raw / "02.png")])
    assert abs(sprite.char_height(Image.open(raw / "02b.png")) - sprite.char_height(src)) <= 1
    sprite.main(["sheet", str(raw), str(out), "--anchor", "torso", "--compare", str(raw / "02.png")])
    names = sorted(p.name for p in (out / "frames").glob("*.png"))
    assert names == ["01.png", "02.png", "02b.png", "03.png", "04.png"], names
    assert Image.open(out / "sheet.png").size == (5 * 64, 64)

    # remap: draft table from ramps -> approve (edit) -> sheet --table -> palette.hex, review, check
    ramps = Path(t) / "ramps.md"
    ramps.write_text("| wood | x | `#3e2731` `#733e39` `#b86f50` `#e4a672` |\n"
                     "| skin | x | `#733e39` `#c28569` `#e8b796` |\n"
                     "| steel | x | `#181425` `#8b9bb4` `#c0cbdc` `#ffffff` |\n", encoding="utf-8")
    sprite.main(["sheet", str(raw), str(out), "--ramps", str(ramps)])
    tsv = out / "colors.tsv"
    rows = sprite.read_table(tsv)
    assert rows and all(len(v) == 2 for v in rows.values())
    # brightness order inside a ramp is kept: a darker source never gets a lighter target
    wood = sprite.read_ramps(ramps)["wood"]
    srcs = sorted(rows, key=sprite.luma)
    picks = [sprite.luma(sprite.ramp_pick(wood, c)) for c in srcs]
    assert picks == sorted(picks)
    lines = tsv.read_text(encoding="utf-8").splitlines()
    lines.append("#123456\t0\twood\t#733e39\tuser added")  # user edits are kept and read back
    tsv.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sprite.main(["sheet", str(raw), str(out), "--ramps", str(ramps)])  # must not overwrite edits
    assert "user added" in tsv.read_text(encoding="utf-8")
    ok = sprite.main(["sheet", str(raw), str(out), "--table", str(tsv)])
    pal = sprite.read_hex(out / "palette.hex")
    assert pal == {v[1] for v in sprite.read_table(tsv).values()}
    used = np.asarray(Image.open(out / "sheet.png"))
    used = {tuple(int(v) for v in c) for c in np.unique(used[used[..., 3] == 255][:, :3], axis=0)}
    assert used <= pal, used - pal  # every table colour remapped
    assert ok is True or len(pal) > 16
    assert (out / "review" / "before.png").exists() and (out / "review" / "after.png").exists()
    if sprite.find_aseprite():
        assert (out / "review.aseprite").exists()
        assert sprite.main(["review-import", str(out)]) in (True, False)
        assert Image.open(out / "sheet.png").size == (5 * 64, 64)

    # idle from the anchor: identical pixels except the top part sinking 1 dot in the second half
    sprite.main(["idle", str(raw / "02.png"), str(Path(t) / "idl"), "--frames", "4"])
    fr = [np.asarray(sprite.clean(Image.open(Path(t) / "idl" / "raw" / f"{i:02}.png"))) for i in range(1, 5)]
    assert (fr[0] == fr[1]).all() and (fr[2] == fr[3]).all() and not (fr[0] == fr[2]).all()
    sprite.main(["sheet", str(Path(t) / "idl" / "raw"), str(Path(t) / "idl")])
    assert Image.open(Path(t) / "idl" / "sheet.png").size == (4 * 64, 64)

    # snap on a source drawn on the 16 px grid: native 64x64, preview x16 = the generation grid
    sprite.main(["snap", str(Path(t) / "gen.png"), str(Path(t) / "anchor.png"), "--native", str(Path(t) / "an.png")])
    assert Image.open(Path(t) / "an.png").size == (64, 64)

    # refs + prompt fill
    sprite.main(["refs", t])
    assert Image.open(Path(t) / "walkguide_8.png").size == (2048, 1536)
    sprite.main(["prompt", "walk", "--out", str(pf := Path(t) / "w.txt"), "--set", "N=8", "--set", "PARTS=none",
                 "--set", "DIRECTION_DESCRIPTION=side view facing left"])
    assert "{" not in pf.read_text()
    chk = np.asarray(Image.open(Path(t) / "checker_1024.png"))
    assert chk[0, 0, 0] == 255 and chk[0, 15, 0] == 255 and chk[0, 16, 0] == 0 and chk[16, 16, 0] == 255  # 16 px dot grid
    pf = Path(t) / "p.txt"
    sprite.main(["prompt", "sheet", "--out", str(pf), "--set", "ACTION=attack", "--set", "N=8", "--set", "PARTS=none",
                 "--set", "DIRECTION_DESCRIPTION=facing left", "--set", "FRAME_BY_FRAME_DESCRIPTION=x"])
    assert "{" not in pf.read_text()

    # check: palette / colour count / alpha report
    hexf = Path(t) / "pal.hex"
    hexf.write_text("181425\nffffff\nb55088\n")
    good = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    good.putpixel((0, 0), (0x18, 0x14, 0x25, 255)); good.putpixel((1, 0), (255, 255, 255, 255))
    good.save(Path(t) / "good.png")
    assert sprite.main(["check", str(Path(t) / "good.png"), "--palette", str(hexf)]) is True
    bad = good.copy()
    bad.putpixel((2, 1), (0x30, 0x29, 0x1f, 255))  # off-palette
    bad.putpixel((3, 3), (255, 255, 255, 128))  # semi-transparent
    bad.save(Path(t) / "bad.png")
    assert sprite.main(["check", str(Path(t) / "bad.png"), "--palette", str(hexf)]) is False
    # union: each file has 2 colours but together 3 > max 2
    two = Image.new("RGBA", (2, 1)); two.putdata([(0x18, 0x14, 0x25, 255), (0xb5, 0x50, 0x88, 255)]); two.save(Path(t) / "two.png")
    assert sprite.main(["check", str(Path(t) / "good.png"), str(Path(t) / "two.png"),
                        "--palette", str(hexf), "--max-colors", "2"]) is False

print("ok")
