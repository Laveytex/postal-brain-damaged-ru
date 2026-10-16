# Advisory implementation report

The latest handoff is the **Amendment A implementation** section at the end of this report.

## Fix round 1 (2026-10-16)

Advisory handoff for independent review. F1 is resolved by the host's pre-round
verification: all 30 original tests passed; the eight-texture real build and
check passed; the downstream overlay smoke reported eight textures, zero errors.
Those results are host-reported baseline evidence, not post-fix proof.

Implemented F2-F9 within the requested scope:

* Preserve untint paint quantiles; explicit paint colour overrides solved auto
  colour while retaining the solved tint ratio.
* Fit and reserve effects in the full reading-frame canvas before quad warping,
  including shared group layers and per-member styles.
* Default delivery to the manifest source root's existing `ГОТОВО`; reject
  missing source/destination directories without creating them.
* Validate merged member styles and paint references, require untint for tint,
  and report execution TypeError/KeyError with texture/op context.
* Propagate mask domains through boolean children.
* Retain independently reverified outputs outside a partial build's closure;
  remove and report stale or no-longer-defined outputs, preserving group units.
* Reject simultaneous box and quad; record the hash of the exact spec bytes
  parsed and use that snapshot for the end-of-build input check.

Files changed this round (all under `texgen/redraw/`): `erase.py`, `text.py`,
`engine.py`, `cli.py`, `spec.py`, `check.py`, `masks.py`, `SPEC.md`,
`tests/test_redraw.py`, new `tests/test_fix_round1.py`, and this report.
The original test fixtures were adjusted for the existing-destination and
box/quad exclusivity requirements; their assertions remain. Added 18 regression
test methods covering F2-F9, bringing the suite to 48 methods.

The agreed command was attempted after the fixes:

```text
py -3.12 -m unittest discover -s texgen/redraw/tests -t . -v

Installed Pythons found by C:\windows\py.exe Launcher for Windows
No Installed Pythons Found!

Requested Python version (3.12) not installed, use -0 for available pythons
Python 3.12 not found!
```

Exit 1 before tests. No post-fix all-suite pass is claimed. Supplemental testing
with the existing Python 3.11 environment described below passed 35 selected
tests (18 original plus 17 new):

```text
Ran 35 tests in 7.149s

OK
```

This is **not the agreed proof**. The new untint/auto-stroke end-to-end test could
not run there because `fontTools` is absent (initial attempt raised
ModuleNotFoundError); that test and 12 original font-dependent methods remain
for host execution. No missing dependency was mocked or installed. Syntax
compilation with the accessible bundled Python 3.12 and `git diff --check` passed.

No new deviations or permission escalations. The unavailable proof interpreter
is the local verification blocker. No art spec, frozen plan, `.gitignore`,
launcher, or downstream pipeline edits this round. No real-texture build or
delivery was repeated, and no commit, push, publication, or original-checkout
write was performed. The historical implementation report below is retained;
its proof status is superseded by the host disposition and this round's results.

## Original implementation report (2026-10-15)

Date: 2026-10-15. Checkout: `D:/Work/postal-ru-redraw-wt`.
This is an implementation handoff, **not an acceptance or release approval**.
The required Python 3.12 proof is blocked; do not treat the fallback tests as that
proof. Independent review and the remaining verification are required.

The frozen `PLAN.md` is unchanged and still hashes to
`83483150bde849504b1fa76a9837eedb98a464e4b64675a6789526b182db9912`.
The checkout was clean before implementation. No commit, push, publication, game
patching, or real-texture delivery was performed. No original checkout was edited.
No package downloads or network installs were attempted.

## Changed files

Only `.gitignore` was modified outside the allowed new-code area (ignore rules
appended). New files:

* `texgen/redraw.py` — UTF-8 checkout-local launcher.
* `texgen/redraw/__init__.py`.
* `texgen/redraw/masks.py` — regions, predicates, morphology, components.
* `texgen/redraw/erase.py` — pull-push, grain, untint, flat, clone.
* `texgen/redraw/compose.py` — transforms, shared coverage styling, RGB blends.
* `texgen/redraw/text.py` — supersampled text, assets, fitting, placement.
* `texgen/redraw/spec.py` — strict TOML validation, dependencies, closure.
* `texgen/redraw/engine.py` — ordered builds, previews, manifests.
* `texgen/redraw/check.py` — independent geometry and byte verification.
* `texgen/redraw/cli.py` — commands, explicit delivery and preflight.
* `texgen/redraw/SPEC.md` — implemented schema and operational details.
* `texgen/redraw/specs/exit.toml`, `walls.toml`, `fuckoff.toml`.
* `texgen/redraw/fonts/README.md` — nine OFL family source URLs.
* `texgen/redraw/tests/__init__.py`, `tests/test_redraw.py` — 30 synthetic test methods.
* This report.

Nine supplied OFL font files were copied from the plan's existing local font
folder to ignored `texgen/redraw/fonts/*.ttf`. They are local dependencies, not
tracked deliverables. Test inputs are synthetic; tests use Windows Arial only
where actual font files are required. Python bytecode caches are also ignored.

`ru_patch.py`, `texgen/build_tex_overlays.py`, `fontgen/`, `ru.json`, and all other
existing tracked files are unchanged. The release `texgen/out` was untouched.

## Agreed proof command and result

Executed from the checkout root, including once after the code fixes:

```text
py -3.12 -m unittest discover -s texgen/redraw/tests -t . -v
```

Exit status: **1**. Launcher diagnostics (stdout/stderr order normalized):

```text
Installed Pythons found by C:\windows\py.exe Launcher for Windows
No Installed Pythons Found!

Requested Python version (3.12) not installed, use -0 for available pythons
Python 3.12 not found!
```

No tests ran through this command. This is not an all-pass result.

## Other verification actually performed

* Bundled Python 3.12.14: `compileall -q texgen/redraw texgen/redraw.py` passed.
* All three acceptance TOML documents parsed successfully with Python 3.12 tomllib.
* `git diff --check` passed; Git printed only its LF-to-CRLF advisory for `.gitignore`.
* 18 selected tests passed using the existing accessible Unreal Engine Python
  3.11.8 and existing local numpy 1.26.4, scipy 1.11.4, Pillow 10.1.0. No missing
  dependencies were mocked, replaced or downloaded. FontTools-dependent cases
  were excluded from this fallback run, not marked as passing.

Fallback interpreter:
`D:/Engine/UE_5.7/Engine/Binaries/ThirdParty/Python3/Win64/python.exe`.
Process-local `PYTHONPATH`:
`D:/Work/AR57-UIItegrate/Intermediate/PipInstall/Lib/site-packages`.

Exact unittest selection following `-m unittest`, all under
`texgen.redraw.tests.test_redraw`:

```text
Invariants.test_random_regions_preserve_outside_alpha_size_mode
Invariants.test_untint_recovers_grey_noise
Invariants.test_untint_rejects_underdetermined_colour
Invariants.test_mask_boolean_near_components
Invariants.test_clone_and_regrain_are_deterministic
Lettering
Groups.test_eighth_scale_and_transposes
Groups.test_shared_atlas_closure_order_validation
Validation.test_rasterizers_agree_for_fractional_polygons_and_boxes
Validation.test_clear_validation_errors
AssetIntegration
```

Final fallback output ended with:

```text
Ran 18 tests in 1.980s

OK
```

Those tests cover RGB/RGBA preservation, local mask invariance, untint accuracy,
near masks, clone/grain determinism, text orientation and final effect bounds,
multiline fit, assets/keying/recolour, blends/perspective, exact 1/8 group mapping,
shared atlas order/closure, independent rasterization, declarative validation,
asset dependency/source/spec/canonical/output tampering, deterministic manifests,
and whole-selection delivery conflict preflight. Delivery tests wrote only
temporary synthetic files, subsequently removed by their test fixtures.

The first fallback run found two real defects (untint MAE 3.35 and a resampling
order difference under quarter turns). Both were fixed; the final run above
passes. Untint now calibrates paint intensity against the background ring; quarter
turns happen after downsampling and are exact transposes.

## Denied and blocked actions

* The installed `C:/Users/Тех/AppData/Local/Programs/Python/Python312/python.exe`
  exists, but launching it returned **Access denied**. Listing its parent
  directory was also denied. The session's approval policy is `never`; no
  elevation or permission bypass was attempted.
* The accessible bundled Python 3.12.14 lacks scipy and fontTools. A test attempt
  with it failed during import with `ModuleNotFoundError: No module named 'scipy'`.
* Some broad dependency-directory listings were denied. `rg` is not installed;
  PowerShell was used for file discovery instead.
* `HANDOFF.md` is absent from this checkout. The plan's external context copy was
  read, along with ТЗ.md and the spike recipes; those paths were never edited.
* Full proof, the `fonts` subprocess check, real-texture build/check, visual
  acceptance and the eight-texture downstream overlay smoke test remain blocked
  or unperformed. No real acceptance output was produced or delivered.

## Deviations, schema decisions and review items

1. **Environment:** the proposed verification deviation is the explicitly labelled
   Python 3.11 subset above while access to the required Python 3.12 environment
   is repaired. It does not replace the frozen proof. The reviewer should run
   all 30 tests with the agreed command before accepting the implementation.
2. **Underdetermined untint:** achromatic paint and background hue are collinear;
   a colour-only opacity solve cannot uniquely recover lost intensity. The code
   rejects this case. Proposed artistic fallback: explicitly choose `pullpush`
   or `clone` in the spec. The tool never silently changes the erase method.
3. **EXIT recipe port:** the spike unions the base erase mask into the emissive
   erase mask. The frozen mask schema has no cross-member pixel-source reference.
   The supplied fixture therefore evaluates the declared red mask independently
   on each member. It uses the same reference-patch grain rule for both (a black
   emissive reference contributes zero grain). This is a disclosed approximation,
   not a verified visual match. Proposed acceptance path: inspect both previews;
   if that mask union is necessary, approve an explicit cross-member mask-source
   extension rather than hiding a special-case engine rule.
4. **Sampled paint extension:** erase `paint={colour=70,stroke_colour=15}` and
   `stroke_colour="auto"` encode the spike's EXIT luminance-tail colour sampling.
   This small declarative extension is documented in SPEC.md; no fixed replacement
   colours were invented. The small button's dark-shadow threshold is the spike's
   reference-patch formula evaluated against the provided original and stored
   explicitly in TOML. Source hashes prevent silently using a different original.
5. **Scale guard:** exact finite-decimal scales are padded to their rational
   denominator. Denominators above 16384 are rejected to avoid unbounded padding.
   Proposed fallback is an explicitly authored shorter exact decimal. No scale
   is silently rounded to a different geometric transform.
6. **Viewer:** `view` saves a coordinate-grid PNG and prints its path; it does not
   automatically launch a native image viewer. This keeps the tool headless.
7. **Validation limits:** real-image ghosting, colour fidelity and readability are
   still artist/reviewer judgments. Acceptance recipes and variable-font paths
   have not yet run in the required environment. Treat them as review candidates,
   not final delivery assets. The partial test result is not evidence that the
   remaining 12 test methods or the real acceptance pipeline pass.

Next action: make the installed Python 3.12 environment readable/executable for
the review session, run the agreed proof, then build/check the eight fixtures and
perform the plan's visual/overlay acceptance in a fresh temporary output folder.
Any release or actual delivery remains a separate explicit action.

## Fix round 2 (2026-10-16)

Advisory changes for independent review. The host reports the round 1 baseline
passed all 48 tests, real build/check for eight textures, and overlay smoke 8/0
errors. F5 requires no further action; those resolved findings were not reopened.

Implemented the requested F1, F2, F3, F6-F10 fixes: exact per-texture spec
dependencies and independent equality checking; fitted-size supersampled text
rasterisation and kerning; protected delivery destinations; I/O errors propagated
from retention, manifest publication before stale cleanup, and nonfatal cleanup
diagnostics; closed-form fractional quarter turns; outward-rounded, validated
scaled sample/grain boxes; and clear malformed-manifest errors.

Changed files this round, all under `texgen/redraw/`: `engine.py`, `check.py`,
`cli.py`, `text.py`, `SPEC.md`, new `tests/test_fix_round2.py`, and this report.
Added 10 regression methods, for 58 total. Both existing test files are unchanged.
The frozen plan and all three art specs retain their prior SHA-256 values.

Agreed proof attempted from the checkout root:

```text
py -3.12 -m unittest discover -s texgen/redraw/tests -t . -v

Installed Pythons found by C:\windows\py.exe Launcher for Windows
No Installed Pythons Found!

Requested Python version (3.12) not installed, use -0 for available pythons
Python 3.12 not found!
```

Exit 1 before tests; no post-fix Python 3.12 proof is claimed. The same accessible
Python 3.11 environment documented above ran all 10 new methods successfully.
The combined supplemental selection (18 original + 17 round 1 + 10 round 2) ended:

```text
Ran 45 tests in 5.825s

OK
```

This is not the agreed proof. The 13 existing fontTools-dependent methods remain
for host execution; no dependencies were mocked or installed. Bundled Python 3.12
syntax compilation and `git diff --check` passed.

F6 interpretation disclosed: existing validation still classifies confirmed
missing source/asset inputs as SpecError/stale, preserving the round 1 regression.
Read/access errors propagate and leave prior outputs/manifest intact. This
distinction was raised with the host; no existing test was weakened. If every
missing file must instead abort, that conflicts with the existing missing-input
regression and would require an explicit test/behavior revision. Cleanup failures
leave an unreferenced PNG with a printed diagnostic; the next build's unmanaged
PNG guard requires it to be moved aside. No other new deviations.

No actual permission denial occurred this round; permission failures in tests
were injected regressions. The launcher environment blocks local proof. No art
edits, real build/delivery, original-checkout writes, commits, pushes or publication
were performed this round. The host owns the pending EXIT art correction.

## Fix round 3 (2026-10-16)

Advisory handoff for independent review. Host-reported baseline: 58 tests OK,
real build/check OK, overlay smoke eight textures / zero errors. Resolved prior
findings were not reopened.

Implemented R3-1 through R3-4: missing recorded spec/output/canonical-layer files
drop and report the prior group closure; PermissionError and other I/O errors
still abort. Table and group/member structure validation now precedes closure
with file/texture/group/index diagnostics. Regrain uses seeded random crops of
reflect-padded detail instead of cyclic shifts. Stale cleanup also removes the
dropped IDs' previews and dropped groups' canonical layers, with path guards and
the existing publish-before-cleanup/nonfatal cleanup-error behavior.

Changed only `texgen/redraw/engine.py`, `spec.py`, `erase.py`, `SPEC.md`, new
`tests/test_fix_round3.py`, and this report. Eight regression methods were added
(66 total); all existing test files, the frozen plan and all art specs are
byte-unchanged. No new deviations.

Agreed proof attempted from the checkout root:

```text
py -3.12 -m unittest discover -s texgen/redraw/tests -t . -v
Installed Pythons found by C:\windows\py.exe Launcher for Windows
No Installed Pythons Found!

Requested Python version (3.12) not installed, use -0 for available pythons
Python 3.12 not found!
```

Exit 1 before tests. The existing supplemental Python 3.11 environment ran the
45 previously executable methods plus all eight new methods:

```text
Ran 53 tests in 8.059s

OK
```

This is **not agreed proof**; the 13 existing fontTools-dependent methods remain
for host execution. The first new-test run exposed escaped Windows paths in the
missing-file diagnostic; the diagnostic was corrected before the passing run.
Bundled Python 3.12 syntax compilation and `git diff --check` passed. No packages
were installed or missing dependencies mocked.

The launcher environment remains the local proof blocker. No actual permission
denials occurred; I/O failures in regression tests were injected. No art edits,
real-texture delivery, original-checkout writes, commits, pushes or publication
were performed. This round implements the host's explicit missing-file policy,
superseding the round 2 F6 interpretation note for recorded specs/outputs/layers.
## Amendment A implementation (2026-10-16)

Advisory handoff for independent review. Implemented only the frozen plan's
Amendment A on the existing base. PLAN.md SHA256 was verified before work and
remains `280a6de726894dffb0a67bcc7b903496881534fc3ff9860b6197af5ff808efcb`.

Files changed in this round:

* `texgen/redraw/text.py`: private seeded per-glyph jitter and Poisson drips;
  unchanged kerning/tracking advances; dynamically sized coverage before fit;
  zero-effect fast path retains existing bytes. Snap glyph positions before
  adding integer drip margins to avoid half-pixel rounding parity shifts.
* `texgen/redraw/spec.py`: strict nested effect validation, numeric ranges,
  nonnegative integer seeds, fill-only drip colour; text/group-text only.
* `texgen/redraw/SPEC.md`: fields, defaults, ranges, RNG, fitting and overflow
  semantics documented.
* `texgen/redraw/tests/test_text_effects.py`: 14 new test methods for seeded
  determinism, zero effects, drip origins/baseline extension, styled fitting,
  advances/order, independent RNGs, validation, group mapping/render-once,
  fixed-size overflow/allow/clip, fixed-size invariance across boxes, and complete
  round-drop coverage at the maximum width/minimum length range boundaries.
* `texgen/redraw/IMPLEMENTATION_REPORT.md`: this advisory record.

No engine/checker changes were needed: effected ink feeds the existing canonical
coverage, style, group cache, allowed-region enforcement and independent check.
The frozen plan, art specs, original checkout and downstream pipeline were not
modified. No commits, pushes, publication or real-texture delivery occurred.

Agreed proof command attempted from this checkout, including after code changes:

```text
py -3.12 -m unittest discover -s texgen/redraw/tests -t . -v
Installed Pythons found by C:\windows\py.exe Launcher for Windows
No Installed Pythons Found!

Requested Python version (3.12) not installed, use -0 for available pythons
Python 3.12 not found!
```

Exit 1 before test discovery. The agreed proof is BLOCKED, not passing.

Supplemental full discovery used the existing Python 3.11.8 interpreter at
`D:/Engine/UE_5.7/Engine/Binaries/ThirdParty/Python3/Win64/python.exe`, with
process-local `PYTHONPATH=D:/Work/AR57-UIItegrate/Intermediate/PipInstall/Lib/site-packages`
(numpy 1.26.4, scipy 1.11.4, Pillow 10.1.0). Its actual summary was:

```text
Ran 80 tests in 14.039s

FAILED (failures=1, errors=22)
```

65 test methods passed. The other 15 methods are blocked by the absent
`fontTools` dependency (22 error entries include subtests; the one failure is
the launcher `fonts` subprocess encountering the same missing module). Of the
14 new methods, 12 passed; group end-to-end mapping and fixed-mode end-to-end
build/check remain blocked by font validation's missing dependency. No packages
were installed and no dependency or validation was mocked to claim a pass.
The earlier new-test run exposed the rounding issue noted above and an incorrect
test assumption that an asymmetric rotated glyph retains its cropped bbox
centre; both were corrected before this final supplemental discovery.
Final review also caught round ends extending above the glyph for very wide,
short drips; the temporary coverage now includes those upper extents. All
supplemental errors/failures were checked to reference missing `fontTools`.
The full final output is saved locally in ignored
`texgen/redraw/preview/amendment-a-supplemental.log`.

A direct render/composite check additionally confirmed fixed-mode overflow fails
outside allowed geometry and preserves complete coverage with explicit allow.
An Arial synthetic visual sample was inspected: straight drips join the rotated
glyph fill, and the effected text fits its box. The sample is local/ignored at
`texgen/redraw/preview/amendment-a-synthetic.png`; it contains no game artwork.
`git diff --check` passed (only Git's LF-to-CRLF advisories).

Denied/blocked actions: no permission or automatic-approval denials occurred in
this round. `rg` was unavailable, so PowerShell reads were used. The PATH Python
3.10 virtual environment also could not launch its base interpreter. The
checkout-relative `HANDOFF.md` and `../Текстуры_для_перевода/ТЗ.md` were absent;
`GLOSSARY.md` was read. Source paths were resolved from this checkout; the
original checkout was not used as an alternate write target. Real-texture
0629 build/visual acceptance remains for the host with the source root and
working Python 3.12 dependencies.

No implementation deviations. Verification deviation: the supplemental 3.11
results above are evidence only, not a substitute for the agreed 3.12 proof.
Independent review should run the exact proof command (80 methods now) and the
host's 0629 preview review before acceptance.
