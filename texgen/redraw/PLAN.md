# PLAN: texgen/redraw — erase English text and typeset Russian on POSTAL: Brain Damaged textures

## Goal
A local, deterministic Python tool inside this repository (`texgen/redraw/`) that takes the original game textures,
erases English text in given regions and typesets Russian text (or places a prepared RGBA lettering image) so that it
looks native — driven by **declarative per-texture specs** authored by Claude (coordinates, texts, fonts, colours).
The tool never guesses art decisions; it executes specs exactly and guarantees technical constraints.
It produces the PNGs for `ГОТОВО\`. It does **not** patch the game: embedding stays with the existing
`texgen/build_tex_overlays.py` → `ru_patch.py` pipeline, which must not be modified by this work.

Pipeline: `texgen/redraw` (this plan) → `Текстуры_для_перевода\ГОТОВО\*.png` → `texgen/build_tex_overlays.py` → `ru_patch.py`.

Source requirements (ТЗ, read it): `D:\SteamLibrary\steamapps\common\POSTAL Brain Damaged\_ru_tools\Текстуры_для_перевода\ТЗ.md`.
Repo context: `D:\SteamLibrary\steamapps\common\POSTAL Brain Damaged\_ru_tools\HANDOFF.md`, `GLOSSARY.md` in repo root.
Textures: `…\_ru_tools\Текстуры_для_перевода\` subfolders `1_Основное`, `2_Вывески`, `3_Мониторы_поезда`
(65 PNG; RGB and RGBA; 128×64 … 2048×2048). Delivery folder: `…\Текстуры_для_перевода\ГОТОВО\` (flat, same file name).
Default roots are resolved relative to the repo the same way `build_tex_overlays.py` does (`<repo>/../Текстуры_для_перевода`),
overridable by CLI flags / config.

Prototype (spike, written by Claude, outside the repo, reference only — rebuild cleanly, reuse ideas where sound):
`D:\Work\postal-ru-tex\spike\rutex.py` (masks, pull-push fill, regrain, untint/tint, text rendering with supersampling,
fill_box, homography warp, finalize), `spike\recipes.py` (hand-coded recipes for EXIT pair, 4 painted walls, FuckOff pair),
`spike\texview.py` (zoom/crop viewer). Spike results for painted walls were visually good (untint + tint keeps concrete
grain). Known spike defects are listed below. Do not copy the spike into the repo.

## Downstream consumer (must stay compatible, do not modify)
`texgen/build_tex_overlays.py` compares each `ГОТОВО` PNG with the original (RGBA, per-pixel max channel diff > 10, mask
grown by 3 px, nearby regions merged) and stores only changed rectangles; `ru_patch.py` pastes them into the game's
DXT1/DXT5/BC7/RGB24/RGBA32 textures. Hence: same size, untouched pixels byte-identical (small overlays), alpha unchanged.

## Hard technical constraints — enforced by code
1. Output PNG, lossless, **exact same pixel size and mode** as the original (RGB stays RGB, RGBA stays RGBA).
2. **Only allowed regions change.** Every pixel outside the union of the texture's allowed regions is byte-identical to
   the original. Alpha of RGBA textures never changes (no alpha-editing feature at all).
3. Orientation per spec: rotation in 90° steps plus optional free angle, horizontal mirror, vertical flip, or a 4-point
   quad (perspective) for skewed screens.
4. Pairs must match: texture + emissive `_E` twin, intact/destroyed variants, same word in different files. Text/asset
   geometry of a group is rendered **once** in a shared layout space and mapped into each member by that member's
   geometric transform (scale, 90°-step rotation, reflection, offset) with per-member style, so glyph shapes are
   identical by construction. A texture may belong to several groups (atlas `0053` has STOP with `1649`, WET FLOOR with
   `1633` — rotated in 0053, mirrored in 1633 — and CATE/КОТЭ with `0438`, `1207`).
5. Never overwrite originals. Never write into `ГОТОВО` except via the explicit `deliver` command.
6. Determinism: same inputs + spec → byte-identical output (fixed RNG seeds, no time-dependent PNG chunks).

## Spec format (TOML, `texgen/redraw/specs/*.toml`) — final schema documented in `texgen/redraw/SPEC.md`
One **ordered** op array per texture; ops run in array order; later ops see earlier results.

```toml
[[texture]]
id = "0265"                          # 4-digit prefix; file resolved by prefix across source subfolders

[[texture.op]]
type = "erase"
id = "word"                          # op ids unique within a texture
region = { box = [257, 273, 464, 306] }    # or poly = [[x,y],...]; region is also the allowed area
mask = { kind = "saturation", min = 20, grow = 1, min_size = 3 }
method = "untint"                    # untint | pullpush | flat | clone
core = { kind = "saturation", min = 35 }   # untint: pixels used to estimate paint colour

[[texture.op]]
type = "text"
paint_from = "word"                  # tint ratio / auto colour from that EARLIER erase op (validation error otherwise)
text = "СЕКТОР"                      # "\n" for line breaks
font = "Tektur.ttf"
axes = { wght = 450 }                # or variation = "Bold Condensed"
fit = "fill_box"                     # fill_box | fit | fixed
box = [260, 276, 461, 303]
blend = "tint"                       # tint | normal | multiply
colour = "auto"                      # auto (from paint_from) or [r,g,b(,a)]

# Linked layout: 0100 (_E, 1024) = 8 x 1841 (128).
[[group]]
id = "fuckoff"
space = [1024, 1024]

[[group.member]]
id = "0100"
transform = { scale = 1.0, rot = 0, mirror = false, offset = [0, 0] }

[[group.member]]
id = "1841"
transform = { scale = 0.125, rot = 0, mirror = false, offset = [0, 0] }
style = { stroke = 1, stroke_colour = [0, 0, 0] }

[[group.op]]                         # ops in layout space, mapped into every member
type = "text"
text = "Кнопка\n«Иди на хрен»"
font = "comicbd.ttf"
fit = "fit"
box = [64, 240, 904, 741]
blend = "normal"
colour = [255, 0, 0]

# Each member texture places the group's ops explicitly in its own ordered op list:
[[texture]]
id = "1841"

[[texture.op]]
type = "erase"
id = "old"
region = { box = [4, 26, 118, 97] }
mask = { kind = "channel_dominance", channel = "r", ratio = 1.6, min = 110, grow = 1 }
method = "pullpush"

[[texture.op]]
type = "use_group"                   # group ops are applied exactly here, mapped by this member's transform
group = "fuckoff"
```

Capabilities:
- **Regions**: `box`, `poly`. Allowed area = union of op regions/boxes + optional explicit `allow` boxes. Text/asset ink
  outside the allowed area is an error unless the op sets `clip = true`.
- **Mask kinds** (no `eval`): `all`, `saturation{min,max}`, `colour{rgb,tol}`, `channel_dominance{channel,ratio,min}`,
  `luminance{min,max}`, `near{of=<mask>, radius}` (shadows/outlines next to text), boolean `any`/`all` of sub-masks; then
  `grow`, `min_size`.
- **Erase methods**: `pullpush` (+ optional `grain = {ref, sigma, gain, seed}`: high-pass detail of a reference patch,
  tiled with per-block random offsets / mirrored tiling to avoid visible repetition); `untint` (per-pixel opacity solve,
  px = bg·(1−a+a·r), r = paint/bg, bg hue from a ring around the region; records paint ratio + colour for `paint_from`);
  `flat` (given or sampled colour); `clone` (offset dx, dy with feathered edge).
- **Text**: lines, alignment, spacing, tracking, font file + variable axes or named instance, sizing `fill_box` (ink box
  exactly fills box), `fit` (largest that fits; squeeze down to `sx_min` before shrinking), `fixed`; rotation, `angle`,
  `mirror`, `flip`, `quad`; fill, stroke, drop shadow (dx, dy, blur, colour, opacity), blend, `modulate` (multiply by local
  luminance variation of the underlying texture), opacity. Supersampled (default 4×), premultiplied-alpha downsampling.
  Sizing measures the **ink bbox of the final transformed layer**, fitting in the text's reading frame, then rotating.
- **Asset** (`type = "asset"`): external RGBA PNG (lettering drawn by ChatGPT, usually real transparency) with optional
  source `crop` (one block of a lettering sheet), placed into box/quad with fit/fill; optional recolour (keep alpha; set
  or multiply RGB); optional soft key-out of a solid background colour (colour-difference matte, not binary threshold);
  same transform/blend options as text. Asset paths relative to `texgen/redraw/assets/` or absolute.
- **Groups**: layout space + members, each with `transform` = scale, `rot` (0/90/180/270), `mirror`, `offset`, applied in
  this fixed order to layout coordinates: mirror (about the layout's vertical centre line) → rotate (about layout origin,
  then re-based so the rotated layout space starts at 0,0) → scale → translate by offset. The same transform maps the
  canonical layer image and all group geometry (boxes/polys) into the member. Layers are rendered once in layout space
  and resampled per member; positions snap so mapping is exact (pad layer to a multiple of 1/scale); 90°-step
  rotation/reflection of the layer is lossless (transpose), then scaled. Per-member `style` overrides (colours,
  stroke/shadow on or off) restyle the same coverage. A texture may be a member of any number of groups; a member must
  contain exactly one `type = "use_group"` op per group it belongs to (validation error otherwise) — group ops run at
  that point of the texture's ordered op list, so the combined order is fully deterministic and explicit.
  Group erase ops are allowed and mapped the same way. `paint_from` inside group ops may name a group erase op only.

## CLI — launcher `py -3.12 texgen/redraw.py <cmd>` from the repo root
Launcher inserts the repo root into `sys.path`; no installation; no `-I` (isolated mode drops script dir and env
encoding). Force UTF-8 stdout. Paths with Cyrillic and spaces must work on Windows.
- **Roots**: `_ru_tools` root resolved as: `--tools-root` flag → env `PBD_RU_TOOLS` → `<repo>/..` (the normal checkout
  `_ru_tools\repo`). Source root = `<tools>/Текстуры_для_перевода`, deliver root = `<tools>/Текстуры_для_перевода/ГОТОВО`,
  both overridable (`--source-root`, `--deliver-root`). The worktree `D:\Work\postal-ru-redraw-wt` needs the env/flag;
  the error message for a missing root names all three options.
- **Group closure**: any selection (`--only`, `check`, `deliver`) expands transitively over group membership (texture →
  all its groups → all their members → their other groups …); the closure is built/checked/delivered as a unit.
- `build <spec…> [--only ID…]` → `texgen/redraw/out/<original name>.png`, `texgen/redraw/preview/<id>.png` (original |
  result zoomed on the union of regions, nearest-neighbour, plus full-texture thumbnail), and `texgen/redraw/out/manifest.json`
  (`schema = 1`): per texture — spec paths + sha256, texture id, **list** of group memberships (group id, member transform,
  position of its `use_group` op), source path + sha256, every dependency (asset and font files: resolved path + sha256),
  allowed-region geometry exactly as applied (after group mapping), output sha256, changed/allowed pixel counts, warnings
  ("ink touches region edge", "squeezed below 0.75"). Per group: sha256 of the canonical fill-only coverage layer saved
  as `out/layers/<group>.png`.
- `check [--only ID…]` → **independent** verification: re-reads specs named in the manifest and compares sha256;
  re-hashes the source and every recorded dependency (asset/font) at its recorded path — missing or changed → fail;
  rasterises allowed masks itself from spec geometry and group transforms (own small rasteriser + transform code in
  `check.py`, not engine code); re-reads source and output and verifies size/mode equal, alpha equal, zero changed pixels
  outside allowed, output sha256 = manifest. Groups: canonical layer hash = manifest; canonical ink mapped by each
  member's transform lies inside that member's allowed mask. Non-zero exit on any violation.
- `deliver ID… | --all` → group closure, then **fresh validation at delivery time** of the exact bytes to copy (same checks
  as `check`, no reliance on earlier records). Preflight all destination conflicts for the whole selection before copying:
  an existing different file needs `--replace`; identical → skip. Copy via temp + atomic rename. Append
  `texgen/redraw/deliver-log.jsonl` (time, id, source/spec/output sha256).
- `view <png> [box] [scale]` → crop/zoom with coordinate grid. `probe <id|png> [--kind saturation --min 20 …]` → connected
  components (bbox, pixel count, median colour). `fonts` → usable fonts (`texgen/redraw/fonts/`, then `C:\Windows\Fonts`)
  covering Cyrillic incl. «Ёё№«»—», with named instances/axes.

## Repo hygiene
- New code only under `texgen/redraw/` plus launcher `texgen/redraw.py`; no changes to `ru_patch.py`,
  `build_tex_overlays.py`, `fontgen/`, `ru.json` or other existing files, except appending ignore rules to `.gitignore`.
- `.gitignore`: `texgen/redraw/out/`, `texgen/redraw/preview/`, `texgen/redraw/deliver-log.jsonl`,
  `texgen/redraw/fonts/*.ttf`, `texgen/redraw/assets/` (game-derived or ChatGPT images — never published; ТЗ forbids
  publishing game graphics). `texgen/redraw/fonts/README.md` lists the OFL fonts and their Google Fonts GitHub URLs
  (Tektur, Oswald, RussoOne, PressStart2P, Lobster, Caveat, BadScript, RubikDirt, Forum); Claude copies the already
  downloaded files there (from `D:\Work\imgloop-pilot\work\postal-ru\fonts\`). Tests must not depend on them.
- Python 3.12, existing packages only: numpy, scipy, Pillow, fontTools (all installed). No OpenCV/scikit-image/network/ML.
  Not part of the PyInstaller exe (build-time tool, like `build_tex_overlays.py`).

## Deliverables (builder)
- `texgen/redraw/` package: `masks.py`, `erase.py`, `text.py`, `compose.py`, `spec.py` (TOML load + validation with errors
  naming file/texture/op), `engine.py`, `check.py`, `cli.py`; launcher `texgen/redraw.py`; `SPEC.md`; `.gitignore` rules.
- `texgen/redraw/specs/`: acceptance fixtures ported from the spike: `exit.toml` (group 1976 + 1977), `walls.toml`
  (0265, 0879, 0303, 1281), `fuckoff.toml` (group 0100 + 1841). Coordinates/texts from `spike/recipes.py`.
- `texgen/redraw/tests/` (unittest, synthetic images and Windows system fonts only — no game files).

## Known spike defects to fix
- Text undersized when fitting multi-line text (FuckOff: 2-line Comic Sans visibly small in an 840×500 box).
- `fit_size` inconsistent for rot 90/270; fit in reading frame, then rotate.
- `paste_center` rounding can shift pair members by 1 px; use group mapping.
- `regrain` single random offset → visible repetition on large masks.
- Outlined text left a dark ghost when the shadow ring was outside the mask → `near` mask kind.

## Verification
Proof command (repo root): `py -3.12 -m unittest discover -s texgen/redraw/tests -t . -v` → all pass, 0 errors.
Tests (synthetic):
1. Outside-allowed invariance for random ops; RGBA alpha identical.
2. Size/mode preserved for RGB and RGBA.
3. `untint`: grey-noise bg + text painted with known ratio/opacity → restored bg mean abs error ≤ 3.
4. `fill_box`: ink bbox equals box within ±1 px (rot 0 and 270).
5. Orientation: rot=270 reads top→bottom (first glyph nearer top); `mirror` flips left-right.
6. Group mapping 1024 → 128 (scale 1/8): member coverage equals 8× box-downsample of canonical within tolerance; positions exact.
7. `check` fails (non-zero) on: out-of-region change, alpha change, size mismatch, spec edited after build, asset or font
   file replaced/missing after build, source modified after build (even inside an allowed region).
8. `deliver`: refuses overwriting a different file without `--replace`; check → modify output → deliver rejected;
   one pair member selected → both delivered; conflict on the second member aborts before the first is copied.
9. Determinism: same spec twice → identical sha256.
10. Spec validation: unknown key, missing font, box outside image, `paint_from` unknown/later op → clear error with texture id.
11. Op ordering: erase → text → erase gives the order-dependent result.
12. Launcher subprocess smoke test: `texgen/redraw.py --help` and `fonts`.
13. Group transforms: a layout mapped into member A with `rot = 90` and member B with `mirror = true` gives coverage
    equal to the canonical layer transposed/flipped (exact for scale 1); `check` reconstructs the same mapped boxes.
14. Shared atlas: one texture in two groups plus its own ops, with `use_group` ops at different positions → output equals
    applying the ops in that combined order; missing or duplicate `use_group` → validation error; closure from a member of
    one group pulls in the other group's members.
Manual/visual (Claude, after build), from the worktree with `PBD_RU_TOOLS` set to the real `_ru_tools`:
`py -3.12 texgen/redraw.py build texgen/redraw/specs/exit.toml texgen/redraw/specs/walls.toml texgen/redraw/specs/fuckoff.toml`
and `check` (exit 0) on real textures; previews show no ghosting, Russian text in the original's colour/position/
orientation, pairs matching. Overlay compatibility, never touching the release `texgen/out`:
`py -3.12 texgen/build_tex_overlays.py --ready texgen/redraw/out --orig "<_ru_tools>/Текстуры_для_перевода"
--index "<_ru_tools>/tex_inventory/index.json" --out <temp dir outside the repo>` → printed lines list exactly the 8
acceptance texture names with small areas, "ошибок 0", no "ВНИМАНИЕ"; the temp dir contains `NNNN.json` for those 8 ids.
(`build_tex_overlays.py` itself is not modified; it deletes its `--out` contents, hence the temp dir.)

## Non-goals
Art decisions (fonts, colours, texts) — specs by Claude. Image generation — ChatGPT via imgloop, separately.
Game patching/compression — existing pipeline. GUI.

## Risks
- Photos/illustrations under text erase imperfectly with pull-push → `clone`, asset coverage, per-texture visual review.
- 128×64 textures: readability over fidelity (ТЗ allows).
- Concurrent work on `main` by another session: this branch (`texgen-redraw`, worktree `D:\Work\postal-ru-redraw-wt`) touches
  only new files + `.gitignore`; merge after inspection.

## Amendment A (2026-10-16): glyph chaos and drips for text ops
Context: the base implementation (commit fb81608: 66 tests, 3 independent inspections) is the starting point; this
amendment only adds two optional text effects. Motivating case: 0629_Hospital_Blood — the original has chaotic, punk-style
hand lettering with blood drips; no free Cyrillic font has both, so the effects are procedural on top of a font
(e.g. Unutterable-Regular.ttf, local OFL font in ignored `texgen/redraw/fonts/`).

New optional text-op keys (also allowed in group ops; not in member `style` overrides):
- `jitter = { rotate = 8.0, shift = 0.12, scale = 0.12, seed = 1 }` — per-glyph chaos. For every visible glyph:
  rotation uniform in ±rotate degrees about the glyph's ink centre, baseline shift uniform in ±shift × line height,
  uniform scale factor in [1−scale, 1+scale] about the glyph centre. Glyph advances (layout positions) stay as in normal
  rendering (kerning/tracking preserved); only each glyph's ink is transformed. Spaces unaffected. Seeded, deterministic,
  independent of global random state; the same op renders identically for every group member (render-once guarantee).
- `drips = { count = 0.6, length = [0.3, 1.2], width = [0.06, 0.14], seed = 2, colour = "fill" }` — drips from glyph
  bottoms: `count` = expected drips per glyph (Poisson/binomial, seeded); each drip starts at a random x on the glyph's
  lowest ink row segment (x where the glyph has ink within its bottom 15 % of height), runs straight down for a length
  drawn from `length` × line height, width from `width` × line height, tapering slightly, ending in a round drop
  (diameter ≈ 1.6 × width). Drawn into the same coverage layer as the glyph fill (same colour, before stroke/shadow), so
  stroke/shadow/blend/style apply to drips too. `colour = "fill"` only (reserved for future).
- Both effects are part of the text layer before fitting: fit/fill_box/fixed measure the final ink including jitter and
  drips, so the result never leaves the box; the existing "ink outside allowed" check stays authoritative.
- Validation: numeric ranges (rotate 0–45, shift 0–0.5, scale 0–0.5, count 0–5, length/width as [min ≤ max] in (0, 3]);
  unknown keys → SpecError naming texture/op.
- check.py needs no change beyond accepting the new keys in spec parsing (allowed geometry unchanged).

Verification additions (repo root, same proof command): tests for
(a) determinism — same seed → identical layer bytes, different seed → different;
(b) jitter=0 and drips count=0 produce byte-identical output to the op without these keys;
(c) drips extend ink below the baseline (max ink row increases) while staying inside the fitted box;
(d) jitter changes per-glyph ink positions but keeps glyph order (left-to-right ink centroids monotonic for a single line);
(e) group render-once still holds with jitter+drips (member coverage equals mapped canonical);
(f) validation errors for out-of-range values.
Manual: host builds 0629 with Unutterable-Regular.ttf + jitter + drips and reviews the preview visually.
