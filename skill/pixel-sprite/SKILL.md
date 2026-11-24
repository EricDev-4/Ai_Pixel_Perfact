---
name: pixel-sprite
description: Turn GPT Image (Codex / ChatGPT) pixel art into pixel-perfect, game-ready sprites and sprite sheets — source character, directional anchors, animation sheets (idle/attack/hurt/jump/death/walk), then pixel-snap, frame recovery, anti-bleed, drift alignment, background removal, packing, and per-frame fixes. Use for "픽셀아트 스프라이트 만들어줘", "스프라이트시트", "걷기 애니메이션", "pixel snap", "game sprite", "캐릭터 애니메이션 시트".
---

# pixel-sprite

All generation uses **GPT Image** (no video models). Roles: Claude writes prompts, reviews every image, runs `sprite.py`; GPT Image generates.
Core loop: **generate on a fixed dot grid → pixel-snap at that grid → integer NN upscale → use as the reference for the next generation.**
Dot size (AGENTS.md): 1 dot = 1 px in every saved file, the engine scales x2. Never resize native art. Runtime cells are 64x64 dots; a normal character fits in 32x32 dots (`--set BODY_DOTS=N` for larger tiers). Generation grids: 16 px per dot on 1024 single frames, 8 px per dot on the 2048x1536 pose board (512 px cell = 64 dots).
User guide (Korean): `USAGE.md` (also in Bear: "pixel-sprite 사용법").
Multi-model setup (Fable conductor, Opus `sprite-qa`, Codex generator): `ORCHESTRA.md` — when asked to install it, follow its "설치 절차".

`S=~/.claude/skills/pixel-sprite` · run `$S/.venv/bin/python $S/sprite.py <cmd>`.

## Ai_PixelArt output location

For this project, use `D:\Ai_PixelArt\workspace\<type>\<asset>` as the working directory. Keep originals, intermediate frames, review files and previews there. Resolve paths such as `sprites/<c>/` against the workspace. Once the pixel-perfect asset is finished and checked, publish exactly one final PNG per asset directly as `D:\Ai_PixelArt\workspace\PixelPerfact\<asset>.png`. For an animation, publish the packed sheet.

## Setup check (once per session)
- `command -v spritefusion-pixel-snapper` — missing → ask the user to run `! brew install Hugo-Dz/tap/spritefusion-pixel-snapper` (don't build from source).
- `$S/.venv` missing → `python3 -m venv $S/.venv && $S/.venv/bin/pip install pillow numpy`.

## Generation step (used everywhere below)
Inputs: filled prompt file + ordered refs + target path.
1. If `command -v codex`: `sprite.py gen PROMPT.txt OUT.png --ref A --ref B [--ref C]`. It rejects fake output (<1024px, script-drawn).
   codex-cli 0.166 `exec` did not expose image_gen → expect failure, fall to 2; don't loop.
2. Manual: tell the user tool (ChatGPT / Codex app), settings (**PNG, high quality, 1 image; square 1024 for single frames, largest landscape size for sheets; edit mode when refs**), the refs **in order**, the prompt file path (offer to `pbcopy` it), and the exact save path. Wait.
Always Read the result before continuing. Reject and regenerate on identity drift, wrong facing, magenta clothing, or missing chroma background.

## Workflow (job folder `./sprites/<char>/`)
1. `sprite.py refs sprites/<c>/refs` → checker_1024 (16 px dot grid), poseboard_2048x1536 (8 px dot grid), walkguide_8, walkguide_4.
0. **Ask the user for the base direction** of every new character (e.g. west side view, south front view). Make only that direction; the engine mirrors left/right.
2. Source: `prompt source --set CONCEPT="..."` → generate with refs `[refs/checker_1024.png, <style ref>]` → `source.png`. Style ref = the approved house character's AI original in the same direction (currently `sprites/banana/originals/source.png` west, `gen_south.png` south), added as "Image 2 role: style reference - same game; match style, outline, shading, face, gloves, shoes, camera; do not copy the character". The template draws west; for another base direction replace its facing line in Composition. Every Codex request adds "Do not resize or edit the result with code; save the generated image as is". Tested 2026-11-17: this prompt (BODY_DOTS=32, half canvas) gives a clean ~30x40-dot character at ~16 px blocks, which is the protagonist standard. The model's block size cannot be forced by prompt; never shrink a result to fewer dots (coarser snap) - it smears faces and hands. The template already draws a left-facing side view, so the source is the west anchor.
3. Anchor: **house grid** — snap with the snapper directly so every character shares one dot size: `spritefusion-pixel-snapper source.png anchor_<dir>_native.png 32 --pixel-size <13.5 × width/1254>` (`sprite.py snap --pixel-size` silently falls back to auto-detect when the grid is >5% off, giving a different dot size per image). Check the height is within 2 dots of the house character (banana ≈ 57 dots). Without a house character: `snap source.png <scratch>/check.png --native anchor_west_native.png` (16 px grid by default; a WARNING means the model ignored the grid and the dot size may differ → regenerate) → tell the user the character size in dots. Keep only the native file in the job folder; the enlarged preview goes to scratch and is not kept. Create the enlarged `anchor_west.png` only when it is needed as a generation reference (the first action sheet, fix, or inbetween): `up anchor_west_native.png anchor_west.png` (x16 = the generation grid). Move `source.png` to `originals/` after snapping.
   **Generation budget: 1 image per character + 1 per requested action. Bad frames: drop with `--pick` first; generate a fix only when the cycle breaks without that frame.**
   **Cell size (user rule, 2026-11-24): right after the anchor is approved, ask the user for the character's cell size** (square, multiple of 32 for 32 PPU: 64, 96, 128, 192, 256 dots; at least anchor height + 4 and wide enough for the widest action such as a swing or jump; PixelLab max 256 per side, v3 side² × frames ≤ 524288 → 192 allows 14 frames, 256 allows 8). Write it to `sprites/<c>/cell.txt`. Every action of that character uses that one value for both `animate --canvas N` and `sheet --cell N`; never mix cells within a character (goblin_dagger_64 had walk 96 / attack 128 and jumped 16 dots with a centre pivot).
4. Direction (skip by default — only when the user explicitly asks for another direction): `prompt direction --set DIRECTION_NAME=<dir> --set DIRECTION_DESCRIPTION="..."` → refs `[identity original, checker_1024, house character's original in that direction (camera reference)]` → house-grid snap → `anchor_<dir>_native.png`. **One base direction per character (asked in step 0); the engine mirrors left/right. Do not generate other directions or a flipped copy unless the user explicitly asks.** The template has weapon lines: delete only those template lines for characters without a weapon.
5. Idle: **do not generate.** `idle anchor_west_native.png sprites/<c>/idle [--frames 8] [--waist N]` builds a breathing loop from the anchor (top part sinks 1 dot in the second half), so the face and hair never drift; then `sheet sprites/<c>/idle/raw sprites/<c>/idle ...` as in step 6.
   Every `sheet`/`walk`/`fix`/`inbetween` prompt needs `--set PARTS="..."`: the character's attached non-limb parts and where they hang (e.g. `blue cape hanging from the shoulders behind the back; short sword in the front hand`, or `none`). Write it once when the anchor is approved and reuse it.
   Other action sheets: `prompt sheet --set ACTION=attack --set N=8 --set DIRECTION_DESCRIPTION=... --set FRAME_BY_FRAME_DESCRIPTION=@motion.txt` → refs `[anchor_west, poseboard]` → `<action>_ai.png`.
   Walk: `prompt walk --set N=8 --set DIRECTION_DESCRIPTION=...` → refs `[anchor_west, poseboard, walkguide_8]`.
6. Post: `sheet <action>_ai.png sprites/<c>/<action> --compare anchor_west_native.png [--anchor torso]` (torso for walk/jump). The whole board is snapped once at the 8 px grid (one dot size, one colour set for all frames), frames are cut from the native board and placed in 64x64-dot cells with the anchor at the bottom centre. **Nothing is resized:** `--compare` only warns when the sheet's character height differs from the anchor by more than 2 dots → regenerate or hand-fix.
   Outputs raw/ (native crops), frames/ and sheet.png (1 dot = 1 px), preview.gif (x4, viewing only). Prints `frames: 1=01.png ...` — `--pick` uses those positions.
7. Review (Read raw/ + sheet.png): pick frames, find wrong weapon hand / broken poses / height warnings. Then fix → step 8.
7b. Colours (AGENTS.md palette rules; do this after the frames are final):
   - Draft: add `--ramps <palette .md>` (current: `project/palettes/softmilk-32.md`) to the `sheet` run → `OUT/colors.tsv` (source, pixels, material, target, note). Never overwritten once it exists.
   - Check every row against the frames: fix wrong materials (rows marked `ambiguous` first; e.g. a dark pot interior is wood, not purple), keep targets in the same material ramp in brightness order. Show the table to the user in chat. **The user approves the table for every sheet.**
   - Apply: `sheet OUT/raw OUT --table OUT/colors.tsv [--pick ...]` → recoloured frames/ + sheet.png, `palette.hex` (character palette), `review.aseprite` (layers before / after / mat_<material>, palette loaded) and an automatic `check` (off-palette, ≤16 colours, semi-transparency, union). Pass `--table` on every later rebuild.
   - Corrections: colour-level → edit colors.tsv and re-apply; pixel-level → the user edits the `after` layer in Aseprite, saves, then `review-import OUT` (takes that layer as final frames/ + sheet.png and re-runs check).
   - A REVIEW result is reported, never blocks; it is not final until the user approves.
8. Fix or insert a frame:
   - Wrong frame: `prompt fix --set FIX_DESCRIPTION="move the sword to the near-side hand, tip pointing forward"` → refs `[anchor_west, up(raw/05.png)]` (`up raw/05.png <scratch>/ref05.png`) → `gen_fix.png` → `put gen_fix.png raw/05.png --match raw/05.png` (snapped at 16 px, never resized; warns if the height differs).
   - Missing in-between: `prompt inbetween --set MOTION_NOTE="..."` → refs `[anchor_west, up(raw/03.png), up(raw/04.png)]` → `put gen_mid.png raw/03b.png --match raw/03.png --match raw/04.png`.
   - Rebuild: `sheet sprites/<c>/<action>/raw sprites/<c>/<action> --compare anchor_west_native.png ...` (re-extracting into a non-empty raw/ is refused on purpose).

## PixelLab animation (default for action sheets; GPT sheets in steps 5-6 are the fallback)
Animates the approved anchor native itself (frames come back at the input size), so identity and dot size stay fixed. PixelLab has no palette lock and no training opt-out: colours are fixed by the step 7 colour table + `check`. Use it for every requested action except idle; fall back to GPT sheets only without a key or balance, and say so.
- **Every PixelLab generation needs the user's explicit approval first, including regenerations** (user rule, 2026-11-21). Before each `animate` call, tell the user the character, action, model, frames, canvas, prompt and current balance, then wait for a yes. Approval covers only that one call.
- Check the balance first (`.venv/bin/python -c "import sprite; print(sprite.pl_call('/balance'))"` in `$S`) and report what the job will use.
- Use the character's cell from `cell.txt` for `--canvas` and `--cell` (ask the user if it is missing). Fast strikes can skip the mid-swing frame → `inbetween`; an unfinished recovery → append a copy of frame 01.
- Needs `PIXELLAB_API_KEY` or the key in `~/.config/pixellab/api_key`. Models: `v3` (default, even 4-16 frames, w×h×frames ≤ 524288) and `pixminimax` (beta, multiple of 4, 4-40 frames). Canvas max 256 px. Cost is reported per job (`usage`).
- `animate anchor_<dir>_native.png sprites/<c>/<action>_<dir> --prompt "walking cycle, ..." --frames 8 [--canvas 128] [--model pixminimax] [--last-anchor] [--seed N]` → `OUT/raw/NN.png` (AI originals). `--last-anchor` ends on the anchor pose: use it for attacks, not loops.
- Then `sheet OUT/raw OUT --compare anchor_<dir>_native.png [--anchor torso]` and review / colours / fix exactly as steps 6-8. One call per direction; mirror east from west in the engine.

## Walk cycle strategy (image model is weak at walk)
A. One sheet with `walkguide_8` (stick figures; red = near limbs, blue = far limbs). Check leg order frame by frame.
B. If the order is wrong: 4 key poses with `walkguide_4` (N=4), fix bad keys, then generate in-betweens (`inbetween`) between each pair, incl. 4→1 for the loop → `put` as 01b, 02b, 03b, 04b → rebuild with `--anchor torso`.
C. Accept 4-frame walk, or hand-edit a few pixels (Aseprite).

## Motion text (FRAME_BY_FRAME_DESCRIPTION)
Frame counts: idle 10 · attack 8 · hurt 6 · jump 6 · death 10 · walk 8. Specific (per-frame lines) for idle/death; Loose (motion guidance) for attack. Switch style if one fails. Examples in USAGE.md.

## Limits
- Size: `sheet --compare` prints the frames' median height vs the anchor in dots; > 2 dots apart prints a WARNING → regenerate. Frames that do not fit the 64x64 cell print a WARNING and are cropped.
- Characters <~24px apart on an AI sheet merge into one frame → regenerate.
- `--anchor torso` keeps y on the lowest pixel: airborne jump frames may need a manual check in preview.gif.
- `put` never rescales; it compares the height with `--match` frames. Poses that change height a lot (crouch, death lying) → compare with the nearest similar pose.
- Palette check: `check OUT/frames OUT/sheet.png --palette <character or scene .hex> [--max-colors 16]` → per-file and union report of off-palette colours (hex, count, position), colour count and semi-transparent pixels. Soft gate: REVIEW is reported, never blocks; a REVIEW result is not final until the user reviews it.
- Self-check: `$S/.venv/bin/python $S/test_sprite.py` (snapper faked).
