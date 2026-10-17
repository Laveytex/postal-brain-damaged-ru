# Texture redraw specification (schema 1)

Run from this checkout, with Python 3.12, numpy, scipy, Pillow and fontTools:

```powershell
py -3.12 texgen/redraw.py build texgen/redraw/specs/exit.toml texgen/redraw/specs/walls.toml texgen/redraw/specs/fuckoff.toml --tools-root '<local _ru_tools>'
py -3.12 texgen/redraw.py check
py -3.12 texgen/redraw.py deliver 1976
py -3.12 -m unittest discover -s texgen/redraw/tests -t . -v
```

`build` writes only `texgen/redraw/out/` and `preview/`. `check` is read-only.
Only `deliver` writes delivery PNGs. Neither command patches the game. Never
publish build products or assets: they contain game artwork. Font binaries are
local and ignored. The original downstream overlay builder is unchanged.

## Roots and commands

`--tools-root` overrides `PBD_RU_TOOLS`, which overrides the parent of this
checkout. Build sources default to `<tools>/Текстуры_для_перевода`, overridable
with `--source-root`. Delivery defaults to `<manifest.source_root>/ГОТОВО`,
independent of the current tools-root flags/environment. `--deliver-root` overrides
the delivery destination. Both the manifest's source root and the delivery folder
must already exist; delivery never creates them or their parents. A missing folder
produces a diagnostic naming `--tools-root`, `PBD_RU_TOOLS` and `--deliver-root`.
Delivery rejects the build output directory and every destination within the
source tree except exactly `<source_root>/ГОТОВО`.
Root flags work before or after the subcommand. A texture ID resolves to exactly
one `<source>/*/NNNN_*.png`, excluding `ГОТОВО`. Ambiguous IDs are errors.

* `build SPEC… [--only ID…]`: load all supplied specs as one project and build
  the selection's transitive group closure. Spec paths are relative to the current
  checkout's working directory. No original-checkout path is embedded in recipes.
* `check [--only ID…]`: verify the manifest and the complete selected closure.
  It reopens spec, source, dependency, canonical layer and output files. It derives
  dependencies and geometry from the specs, not the manifest's claims.
* `deliver ID… | --all [--replace]`: fresh verification of exact byte snapshots,
  preflight every destination, skip identical files, reject different files unless
  `--replace`, then temp-file + atomic rename per output. Appends UTC timestamps
  and source/spec/output hashes to `deliver-log.jsonl`. Conflict preflight is for
  the entire selection; OS/I/O failures during copying can still leave a partially
  copied batch (individual files are atomic). Do not run concurrent deliveries.
* `fonts`: JSON list of local then Windows fonts with full Russian Cyrillic plus
  Ёё№«»—, variable axes and named instances. No downloads or font substitution.
* `probe ID|PNG [--kind saturation --min 20 --grow 1 --min-size 3]`: JSON connected
  components with half-open boxes, counts, median RGB. Other predicates accept
  `--max`, `--rgb R G B`, `--tol`, `--channel r|g|b`, `--ratio`.
* `view PNG [x0,y0,x1,y1] [scale]`: nearest-neighbour crop with coordinate grid,
  saved as `preview/view.png`; prints its path for opening in an image viewer.

## Document structure

UTF-8 TOML; only top-level `texture` and `group` arrays. Unknown keys, missing
dependencies, invalid coordinates and forward references are errors. Errors name
the spec, texture/group and operation index wherever applicable.

```toml
[[texture]]
id = "0265"
allow = [[257, 273, 464, 306]] # optional additional allowed boxes

[[texture.op]]
type = "erase"
id = "old"
region = { box = [257, 273, 464, 306] }
mask = { kind = "saturation", min = 20, grow = 1 }
method = "untint"
core = { kind = "saturation", min = 35 }

[[texture.op]]
type = "text"
text = "СЕКТОР"
font = "Tektur.ttf"
axes = { wght = 520 }
box = [260, 276, 461, 303]
fit = "fill_box"
paint_from = "old"
colour = "auto"
blend = "tint"
```

Every texture has one ordered `op` array. Every operation sees preceding results.
Optional op `id` values are unique in their scope. `paint_from` must refer to an
earlier erase in the same scope, including inside a group. A group cannot refer
to a member texture's erase. `use_group` is an insertion point, not a second pass.

## Geometry and pixel rules

Coordinates start at top left; x increases right, y increases down. Boxes are
`[left, top, right, bottom]`, with right/bottom exclusive. Polygons are lists of
`[x,y]` points, filled by the even/odd rule at pixel centres. Fractional coordinates
are permitted. Geometry must lie inside the image, even when `clip=true`.

Erase operations require `region = {box = […]}` or `{poly = [[…],…]}`. Text/asset
operations require exactly one of `box` or `quad` (TL, TR, BR, BL order). Their allowed
geometry defaults to `quad` if present, otherwise `box`; explicit `region` overrides
that allowed geometry without changing placement. Texture allowed area is the
union of all operation geometry, group geometry and explicit `allow` boxes.
Any rendered ink outside that union (including stroke/shadow or off-image ink)
fails unless its operation sets `clip=true`. RGBA source alpha is never edited.

`rot = 0|90|180|270` uses Pillow's counterclockwise convention: `270` turns a
horizontal word to read top-to-bottom. `mirror` flips horizontally, `flip` flips
vertically. `angle` is an additional counterclockwise free angle. Fit is measured
in the reading frame, accounting for free-angle expansion, before quarter-turn
orientation. For `quad`, the fitted ink and its reserved stroke/shadow margins are
centred on the full reading-frame canvas. Style is applied in that frame before
the canvas corners are mapped to the quad. Thus `fit` preserves the fitted aspect
ratio rather than stretching a cropped glyph layer to all four quad corners.

## Masks

`kind` defaults to `all`. All predicates use current RGB, ignoring source alpha.
Saturation is max(R,G,B) minus min(R,G,B); luminance here is mean RGB, both on
the 0–255 scale. Bounds are inclusive. No expressions or Python evaluation.

| Kind | Fields |
| --- | --- |
| `all` | All pixels; optional nonempty `of = [mask,…]` means boolean AND |
| `any` | Nonempty `of = [mask,…]`, boolean OR |
| `saturation`, `luminance` | `min=0`, `max=255` |
| `colour` | `rgb=[r,g,b]`, `tol=0` (max channel difference) |
| `channel_dominance` | `channel="r"|"g"|"b"`, `ratio=1`, `min=0`; selected channel must dominate both others |
| `near` | `of=mask`, `radius`; square (Chebyshev) neighbourhood, includes original mask |

Every kind supports `grow=0` (8-neighbour dilation iterations), then `min_size=0`
(remove small 4-connected components). Selection is bounded to the operation's
region before and after postprocessing. A near-mask detects outlines/shadows as
well as the coloured letter itself.

## Erase methods

* `pullpush`: normalized known-pixel pyramid, coarse-to-fine interpolation.
  Optional `grain={ref=[l,t,r,b], sigma=2, gain=1, seed=0}` adds high-pass RGB detail
  from a reflect-padded reference patch, using independent seeded crop windows
  and reflections per tile. Crops do not cyclically join opposite patch edges.
  Reference coordinates are integer pixel indices. No global random state.
* `untint`: `core` is a separate mask selecting paint-colour samples. Background
  hue comes from an 8-pixel ring excluding the selected mask and its 2-pixel
  dilation. Solve per-pixel intensity and opacity in
  `pixel = background * (1-opacity + opacity*ratio)`. Record ratio and RGB for
  subsequent `paint_from`. This model assumes a locally stable background hue;
  paint intensity is calibrated to the ring's median background to reduce bias
  from saturation-based core selection while retaining pixelwise grain.
  achromatic paint is underdetermined and is rejected, not silently inpainted.
* `flat`: explicit `colour=[r,g,b]`, or median of `sample=[l,t,r,b]`, or median
  background ring if neither is given.
* `clone`: `offset=[dx,dy]` samples from `(x+dx,y+dy)` in the current image snapshot;
  `feather=0` optionally ramps coverage by distance from the selected boundary.
  Out-of-image source coordinates fail; they never wrap around.
* `patch`: multiscale PatchMatch nearest-neighbour search and weighted overlapping
  patch voting, for photos and patterned backgrounds. Only selected mask pixels
  change. Parameters belong directly to the erase op:

  ```toml
  [[texture.op]]
  type = "erase"
  method = "patch"
  region = { box = [100, 80, 160, 140] }
  mask = { kind = "all" }
  patch = 7
  iterations = 5
  em = 3
  seed = 0
  margin = 48
  # Optional donor boxes; otherwise the region is dilated by margin pixels.
  source = [[20, 20, 200, 200]]
  exclude = [[170, 40, 190, 100]]
  ```

  `patch` is an odd integer from 3 through 15; `iterations` is 1–20, `em` is
  1–10, `seed` and `margin` are nonnegative integers. Defaults are shown above.
  Source/exclusion boxes use integer pixel coordinates inside the image. Their
  union is evaluated before footprint testing: adjacent source boxes may jointly
  contain a patch. Every pixel of a donor footprint must be inside that union,
  outside all exclusion boxes, and outside the current erase mask. No valid
  footprint is a `SpecError`; the actual mask is checked at execution time so
  earlier ops are respected. Geometry-only donor feasibility is also preflighted
  when loading the spec. These parameters are rejected on other erase methods.

  Default source dilation uses a square neighbourhood around the rasterised
  region, clipped at image edges. Effective margin is clamped to the largest
  image side before dilation and context-window calculation; larger margins
  cannot add pixels and never create an unbounded filter. Target patches can read
  known context outside the region. Full donor footprints are accessible even in distant source boxes;
  source restrictions govern donation, not target/context reads. There are no
  writes outside the erase mask and no alpha edits.

  The pyramid uses a 2×2 box filter (real children only at odd image edges), the
  same patch side at every level, any-child hole masks and all-child source
  eligibility. Thus masked/excluded pixels cannot leak into coarse donors.
  Pyramid depth measures hole **thickness**, stopping when maximum distance to
  actual known pixels is at most 8 pixels (about 16 pixels across), rather than
  shrinking the overall lettering bbox to 16 pixels. A proposed coarser level
  is rejected only if it has no valid donors. Hole density does not suppress
  the pyramid for large solid erases. The context window is the hole bbox
  expanded by the scaled, clamped margin, with at least a patch radius plus one
  pixel of context. Distance calculations treat outside-image
  pixels as unknown; they cannot invent a known border.

  Coarse NNF coordinates and filled pixels initialise finer levels. Matching
  first uses only actual known samples; wholly unknown patches compare mean RGB
  instead of rewarding low donor variance against a smooth initial estimate.
  Later EM rounds use unknown-pixel weights 0.1, then 0.35, relative to known
  samples' weight 1. Each EM round alternates propagation and shrinking random
  search with votes weighted by error and distance from known context.
  Voting averages donor low frequencies, then adds the high-frequency band of
  the highest-confidence covering donor patch. This preserves source grain
  rather than cancelling it by averaging unrelated detail. The low/high split
  uses a Gaussian sigma of 1.5 pixels, reflected **within each valid footprint**:
  no excluded/out-of-source pixel contributes to either band. No noise is
  generated. Randomness uses a private NumPy generator per erase.

  Donors use an integral-image footprint index. Search and voting process only
  target patches overlapping the hole. Costs, propagation, initialisation and
  voting use batches of at most 256 target patches, reduced further so a batch
  contains at most 65,536 patch samples. Coordinates are int32; there are no
  whole-target-domain arrays with a patch-area dimension. NNF, scores, confidence,
  hole votes and image/index/pyramid storage remain proportional to their domains.
  A mapped patch side above 255 is rejected with a clear memory-cap `SpecError`
  before footprint expansion. Distant or large source areas do not become
  matching targets. This is exemplar synthesis, not semantic reconstruction;
  photos still require the planned visual review.

  Group erases map source/exclusion boxes by the member transform using the same
  pixel-centre geometry rules. Patch side scales to the nearest odd integer at
  least 3 (ties upward); a mapped side may exceed 15 when enlarged, up to the
  documented memory cap of 255. Margin scales and rounds to integer pixels.
  Each member validates its own donor footprints.

Every erase records median selected RGB when it has an `id`. Optional
`paint={colour=70, stroke_colour=15}` instead samples the upper/lower luminance
quantile tails of selected pixels. This declarative extension ports the spike's
EXIT colour sampling without hardcoding artist-chosen colours. Quantiles >=50
select the upper tail; lower quantiles select the lower tail. `stroke_colour="auto"`
reads the corresponding value through `paint_from`. `untint` preserves these
quantile samples and adds its solved `ratio`. Its solved `colour` is the default
for `colour="auto"`; an explicit `paint.colour` quantile overrides that colour,
without changing the solved ratio used by `blend="tint"`.

## Text and style

Text requires `text` (newline separates lines) and `font` (local filename or
absolute path). Search order is `texgen/redraw/fonts`, `C:/Windows/Fonts`. Missing
glyphs fail. `axes={wght=450,…}` or `variation="Bold Condensed"` selects a variable
font instance; unknown axes, names or out-of-range values fail.

* `fit="fill_box"`: stretch measured visible ink to the box, independently in x/y.
* `fit="fit"` (default): largest fitted ink, permitting horizontal compression
  down to `sx_min=1` before reducing height. A squeeze below .75 is recorded.
* `fit="fixed"`: require `size` in pixels; overflow is subject to normal ink checks.
* `align="left"|"center"|"right"` controls multiline alignment (default center).
  `spacing=1` multiplies baseline distance; `tracking=0` adds pixels between glyphs.
* `supersample=4` controls text sampling; final resampling uses premultiplied RGBA
  for coloured layers, preventing dark transparent fringes.
  A nominal measurement estimates size, then text is rasterised again at the
  fitted pixel size times `supersample`; only residual fitting and intentional
  horizontal squeeze resample that raster. Lines retain font kerning; nonzero
  tracking adds spacing to pairwise kerned advances.
* `colour=[r,g,b]` or `[r,g,b,a]` (default white), or `"auto"` via `paint_from`.
* `stroke=0`, `stroke_colour=[0,0,0]` expands the shared coverage with a disk.
* `shadow={dx=0,dy=0,blur=0,colour=[0,0,0],opacity=1}` or `shadow=false`.
* `blend="normal"|"multiply"|"tint"`; tint requires an untint `paint_from` ratio.
* `opacity=1` scales layer alpha. `modulate=true` multiplies layer RGB by local
  underlying luminance relative to its Gaussian-smoothed value.

### Optional glyph jitter and drips

These text-only effects are also allowed on group text ops. They are not member
`style` overrides: the group renders its effected coverage once, then maps that
same coverage to every member. Assets do not accept these keys.

```toml
jitter = { rotate = 8.0, shift = 0.12, scale = 0.12, seed = 1 }
drips = { count = 0.6, length = [0.3, 1.2], width = [0.06, 0.14], seed = 2, colour = "fill" }
```

`jitter` independently rotates each visible glyph uniformly within ±`rotate`
degrees, shifts its baseline uniformly within ±`shift` times the font line
height, and scales its ink uniformly within `[1-scale, 1+scale]`. Rotation and
scaling are about the glyph's ink centre. Kerning, tracking, advances, spaces,
line alignment and baseline spacing retain the ordinary layout positions.
Missing rotate/shift/scale values default to zero; seed defaults to 1.
Allowed ranges are rotate 0–45, shift 0–0.5 and scale 0–0.5.

`drips` draws a seeded Poisson count per visible glyph (mean `count`, range 0–5).
Each origin is a random column with ink in the transformed glyph's bottom 15%,
starting at that column's lowest ink pixel. A straight vertical drip tapers to
65% of its starting width and ends in a round drop of diameter about 1.6 times
that width. Length and width are sampled uniformly from their respective ranges,
in units of the font line height (ascent + descent, before `spacing`). Each range
must have `0 < min <= max <= 3`. Missing fields default to the values in the
example. Only `colour="fill"` is supported; drips join the glyph fill coverage
before stroke/shadow, so all ordinary styling and blending also applies to them.

Both seeds are nonnegative integers. Each effect has its own private RNG, reset
on each render, independent of global random state; spaces consume no draws.
All-zero jitter and count-zero drips retain the original rendering path and are
byte-identical to omitting the effects, including in fixed mode. Unknown keys,
invalid types and out-of-range values fail with spec/texture or group/op context.

Effects precede sizing. `fit` and `fill_box` measure complete effected ink and
style extents before fitting. `fixed` retains the requested font size, with no
box fitting: complete ink must fit within the union of allowed geometry, or the
op must explicitly set `clip=true`. An explicit texture `allow` can permit ink
outside the placement box. The independent checker and allowed geometry rules
are unchanged.

## Assets

`type="asset"`, `path="lettering.png"` resolves relative to `redraw/assets/`, or
accepts an absolute path. Input must be RGBA PNG. `crop=[l,t,r,b]` selects a sheet
block. Transparent outer margins are removed before fitting the actual ink.
`key={colour=[r,g,b],tolerance=0,softness=30}` multiplies alpha by a continuous
colour-difference matte. `recolour={mode="set"|"multiply",colour=[r,g,b]}` changes
RGB while keeping alpha. Fit, transforms, stroke/shadow and blending are shared
with text. `fixed` retains the source crop's native pixel size.

## Groups

```toml
[[group]]
id = "pair"
space = [1024, 1024]
[[group.member]]
id = "0100"
transform = { scale = 1, rot = 0, mirror = false, offset = [0, 0] }
[[group.member]]
id = "1841"
transform = { scale = 0.125 }
style = { stroke = 1, stroke_colour = [0, 0, 0] }
[[group.op]]
type = "text"
text = "Кнопка\n«Иди на хрен»"
font = "comicbd.ttf"
box = [64, 240, 904, 741]
colour = [255, 0, 0]

[[texture]]
id = "0100"
[[texture.op]]
type = "use_group"
group = "pair"
[[texture]]
id = "1841"
[[texture.op]]
type = "use_group"
group = "pair"
```

Each member must exist as a texture and include exactly one `use_group` for that
group. Multiple memberships are supported; group nesting is not. Selection
expands transitively through all memberships.

Transform order is mirror about layout vertical centre, counterclockwise quarter
turn and rebase, scale, then integer offset. Coverage and region masks share the
same pixel grid: transpose/reflection is lossless; downscaling uses BOX averaging;
upscaling uses nearest-neighbour. A member allows every pixel with nonzero mapped
region coverage. Padding on right/bottom to the denominator of the decimal scale
preserves the layout origin and exact scaling grid. Scales whose exact denominator
exceeds 16384 are rejected with a diagnostic, rather than approximated silently.

Each text/asset fill is rendered once in canonical layout space, then restyled per
member without re-rendering glyphs. `style` permits colour, stroke, stroke_colour,
shadow, opacity, blend and modulate; it cannot change font, text, fit or geometry.
Group stroke/shadow dimensions scale and rotate with the group; member overrides
are in member pixels. Group erases evaluate the current member RGB in the mapped
region, with mapped clone offsets/reference patches and scaled mask radii.
The merged group operation and member style are validated together: either auto
colour option or tint requires an earlier group `paint_from`, and tint requires
that referenced erase to use `untint`.

## Manifest and verification

`out/manifest.json` has `schema=1`, `specs` records, `source_root`, texture and
group maps keyed by ID. Records contain absolute resolved path and SHA-256.
Each texture stores its source, specs, all fonts/assets, mapped geometry, ordered
group memberships including `use_group` index, output hash, changed/allowed pixel
counts, and warnings. Each group stores the hash of `out/layers/ID.png`, the maximum
of its canonical fill-only coverage layers. Output PNGs have no timestamps.
Each input spec is read once for parsing, hashed from those exact bytes (including
any UTF-8 BOM), then decoded. Its recorded hash is also the end-of-build comparison
baseline; an edit after parsing fails the build before products are published.

`check.py` imports none of the engine's geometry/mask/rendering modules. It uses
an independent scan-line rasteriser, coordinate transform and coverage mapping;
checks source/dependency/spec hashes, exact mode/size/alpha, outside-area invariance,
pixel counts, canonical hashes and mapped canonical containment. It validates
manifest paths and reconstructs the dependency set to catch missing records.
Delivery copies the exact output bytes verified in memory, so changing the output
after verification cannot substitute unverified bytes into delivery.

Determinism is within the same Python/Pillow/FreeType/font/dependency environment.
Library or font upgrades can change rasterization or PNG compression and require
rebuilding and reviewing output. Original assets are always read-only.

Builds merge with the existing manifest. Prior entries outside the rebuilt closure
are independently reverified, including their recorded spec/source/dependency
hashes, output invariants and group layers. Valid entries and outputs remain.
Stale entries (including specs that no longer define them) are dropped as a closure;
missing recorded specs, outputs or canonical layers also make that closure stale.
The dropped IDs and reason are reported. Their managed output PNGs, `preview/ID.png`
and canonical layers of dropped groups are deleted only after the new manifest is
published, and removed paths are printed. Other read/access I/O errors abort retention instead of
marking entries stale. Cleanup failures are reported with paths and do not abort
the successful build; leftover PNGs become unmanaged and must be moved aside
before the next build. `--only` validates inputs needed for its active closure;
a missing stale dependency outside that closure does not prevent rebuilding it.
The merged manifest records the union of spec records, while each texture records
exactly its own texture-definition spec and the specs defining every group it
uses. The checker independently derives and requires that exact set. Checking a selection verifies those
records and reconstructs its actual closure from the parsed specs. Unmanaged PNGs
in the output folder cause an error and are never deleted.
