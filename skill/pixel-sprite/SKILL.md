---
name: pixel-sprite
description: Turn GPT Image (Codex / ChatGPT) pixel art into pixel-perfect, game-ready sprites and sprite sheets — source character, directional anchors, animation sheets (idle/attack/hurt/jump/death/walk), then pixel-snap, frame recovery, anti-bleed, drift alignment, background removal, packing, and per-frame fixes. Use for "픽셀아트 스프라이트 만들어줘", "스프라이트시트", "걷기 애니메이션", "pixel snap", "game sprite", "캐릭터 애니메이션 시트".
---

# pixel-sprite

All generation uses **GPT Image** (no video models). Roles: Claude writes prompts, reviews every image, runs `sprite.py`; GPT Image generates.
Core loop: **generate → pixel-snap → integer NN upscale → use as the reference for the next generation.**
User guide (Korean): `USAGE.md` (also in Bear: "pixel-sprite 사용법").
Multi-model setup (Fable conductor, Opus `sprite-qa`, Codex generator): `ORCHESTRA.md` — when asked to install it, follow its "설치 절차".

`S=~/.claude/skills/pixel-sprite` · run `$S/.venv/bin/python $S/sprite.py <cmd>`.

## Setup check (once per session)
- `command -v spritefusion-pixel-snapper` — missing → ask the user to run `! brew install Hugo-Dz/tap/spritefusion-pixel-snapper` (don't build from source).
- `$S/.venv` missing → `python3 -m venv $S/.venv && $S/.venv/bin/pip install pillow numpy`.

## Generation step (used everywhere below)
Inputs: filled prompt file + ordered refs + target path.
1. If `command -v codex`: `sprite.py gen PROMPT.txt OUT.png --ref A --ref B [--ref C]`. It rejects fake output (<1024px, script-drawn).
   codex-cli 0.166 `exec` did not expose image_gen → expect failure, fall to 2; don't loop.
2. Manual: tell the user tool (ChatGPT / Codex app), settings (**PNG, high quality, 1 image; square 1024 for single frames, largest landscape size for sheets; edit mode when refs**), the refs **in order**, the prompt file path (offer to `pbcopy` it), and the exact save path. Wait.
Always Read the result before continuing. Reject and regenerate on identity drift, wrong facing, green clothing, or missing chroma background.

## Workflow (job folder `./sprites/<char>/`)
1. `sprite.py refs sprites/<c>/refs` → checker_1024, poseboard_2048x1536, walkguide_8, walkguide_4.
2. Source: `prompt source --set CONCEPT="..."` → generate (no refs) → `source.png`. The template already draws a left-facing side view, so the source is the west anchor.
3. Anchor: `snap source.png <scratch>/check.png --native anchor_west_native.png` → record `pixel_size` (tell the user). Keep only the native file in the job folder; the enlarged preview goes to scratch and is not kept. Create the enlarged `anchor_west.png` only when it is needed as a generation reference (the first action sheet, fix, or inbetween): `snap originals/source.png anchor_west.png --pixel-size P` (same P gives a byte-identical file). Move `source.png` to `originals/` after snapping.
   **Generation budget: 1 image per character + 1 per requested action. Bad frames: drop with `--pick` first; generate a fix only when the cycle breaks without that frame.**
4. Direction (skip by default — only when the user explicitly asks for another direction): `prompt direction --set DIRECTION_NAME=west --set DIRECTION_DESCRIPTION="side view facing left"` → refs `[anchor, checker_1024]` → `snap` → `anchor_west.png`. **One direction only (west), for every game type including top-down: the engine mirrors it for the other side. Do not generate south/north/east or a flipped copy unless the user explicitly asks for that direction.**
5. Action sheet: `prompt sheet --set ACTION=attack --set N=8 --set DIRECTION_DESCRIPTION=... --set FRAME_BY_FRAME_DESCRIPTION=@motion.txt` → refs `[anchor_west, poseboard]` → `<action>_ai.png`.
   Walk: `prompt walk --set N=8 --set DIRECTION_DESCRIPTION=...` → refs `[anchor_west, poseboard, walkguide_8]`.
6. Post: `sheet <action>_ai.png sprites/<c>/<action> --match anchor_west_native.png [--anchor torso]` (torso for walk/jump). **`--match` is mandatory, also on rebuilds: it makes the character exactly as tall as in the anchor, so every action of a character has the same size in the game. Never pass the anchor's pixel_size to `sheet`:** the model draws each image at its own pixel density (a walk sheet came out ~15% smaller than its anchor), and the snapper's output size is a step function of pixel_size, so `--match` trial-snaps to find the grid itself and then enlarges the remainder.
   Outputs raw/, frames/, sheet.png, preview.gif. Prints `frames: 1=01.png ...` — `--pick` uses those positions.
7. Review (Read raw/ + sheet.png): pick frames, find wrong weapon hand / broken poses / height warnings. Then fix → step 8.
8. Fix or insert a frame:
   - Wrong frame: `prompt fix --set FIX_DESCRIPTION="move the sword to the near-side hand, tip pointing forward"` → refs `[anchor_west, raw/05.png]` → `gen_fix.png` → `put gen_fix.png raw/05.png --match raw/05.png`.
   - Missing in-between: `prompt inbetween --set MOTION_NOTE="..."` → refs `[anchor_west, raw/03.png, raw/04.png]` → `put gen_mid.png raw/03b.png --match raw/03.png --match raw/04.png`.
   - Rebuild: `sheet sprites/<c>/<action>/raw sprites/<c>/<action> --match anchor_west_native.png ...` (re-extracting into a non-empty raw/ is refused on purpose).

## Walk cycle strategy (image model is weak at walk)
A. One sheet with `walkguide_8` (stick figures; red = near limbs, blue = far limbs). Check leg order frame by frame.
B. If the order is wrong: 4 key poses with `walkguide_4` (N=4), fix bad keys, then generate in-betweens (`inbetween`) between each pair, incl. 4→1 for the loop → `put` as 01b, 02b, 03b, 04b → rebuild with `--anchor torso`.
C. Accept 4-frame walk, or hand-edit a few pixels (Aseprite).

## Motion text (FRAME_BY_FRAME_DESCRIPTION)
Frame counts: idle 10 · attack 8 · hurt 6 · jump 6 · death 10 · walk 8. Specific (per-frame lines) for idle/death; Loose (motion guidance) for attack. Switch style if one fails. Examples in USAGE.md.

## Limits
- Size match: `sheet` prints `match: frames xN`. N outside 0.8–1.25 prints a WARNING (uneven pixels) → regenerate that sheet. Output cells use one integer scale derived from the anchor height (`--scale` overrides), so all sheets of a character share it.
- Characters <~24px apart on an AI sheet merge into one frame → regenerate.
- `--anchor torso` keeps y on the lowest pixel: airborne jump frames may need a manual check in preview.gif.
- `put` rescales by character height; poses that change height a lot (crouch, death lying) → match to the nearest similar pose.
- Self-check: `$S/.venv/bin/python $S/test_sprite.py` (snapper faked).
