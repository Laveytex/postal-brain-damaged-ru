# Amendment B implementation — advisory review report

Frozen plan SHA256 verified before and after implementation:
`24065ba68bb4e445ee0d2a5404d502111189f51608a077459bf3609c4b692093`.
The base tool and Amendment A were already present in this checkout. This change
implements the missing Amendment B. This report is evidence for independent
review, not acceptance certification.

## Files changed

- `texgen/redraw/patch.py` (new): deterministic multiscale PatchMatch, conservative
  pyramid masks, full-footprint donor indexing, compact target NNF, propagated
  and random candidates, overlapping weighted votes, donor fallback.
- `texgen/redraw/erase.py`: dispatch `method = "patch"` using the current op mask.
- `texgen/redraw/spec.py`: strict parameters/ranges/boxes and geometry-only donor
  preflight; actual mask eligibility is validated during ordered execution.
- `texgen/redraw/engine.py`: group source/exclusion geometry, scaled odd patch
  side and margin; execution errors now include the originating spec path.
- `texgen/redraw/tests/test_patch.py` (new): 15 synthetic regression tests.
- `texgen/redraw/SPEC.md`: schema, defaults, geometry, algorithm and group rules.
- `texgen/redraw/AMENDMENT_B_REPORT.md` (new): this report.

No edits to the frozen plan, art specs, downstream overlay/patcher pipeline,
original checkout, game files, or delivery folder. No commits, pushes or
publication. Test build/check products use temporary synthetic workspaces.
The supplemental log is local and ignored under `texgen/redraw/preview/`.

## Agreed proof: blocked, not passing

Executed from `D:\Work\postal-ru-redraw-wt`:

```text
py -3.12 -m unittest discover -s texgen/redraw/tests -t .

Installed Pythons found by C:\windows\py.exe Launcher for Windows
No Installed Pythons Found!

Requested Python version (3.12) not installed, use -0 for available pythons
Python 3.12 not found!
```

Exit code 1, before test discovery. No interpreter or packages were installed.

## Supplemental verification

Used the already available Python 3.11.8 interpreter:
`D:/Engine/UE_5.7/Engine/Binaries/ThirdParty/Python3/Win64/python.exe`, with
process-local `PYTHONPATH=D:/Work/AR57-UIItegrate/Intermediate/PipInstall/Lib/site-packages`
(numpy 1.26.4, scipy 1.11.4, Pillow 10.1.0).

Full discovery with `-v` after the final code changes:

```text
patch performance: 512x512, 60x60 hole: 5.174s
patch performance: 2048x2048, 20x20 hole: 1.580s
Ran 95 tests in 23.576s
FAILED (failures=1, errors=22)
```

All 15 new Amendment B tests passed, including build/check, actual-mask donor
rejection, op ordering, RGB/RGBA preservation, repeat output hashes, group
transforms, fractional pixel-centre boxes, coarse fallback and multiscale NNF
initialisation. All 22 errors identify the unavailable `fontTools` dependency;
the launcher `fonts` test failure has the same cause. No dependencies or
validation were mocked to claim a pass. Full output:
`texgen/redraw/preview/amendment-b-supplemental.log`.

A separate synthetic checker-plus-noise measurement gave mask MAE 0.969 for
patch versus 79.850 for pull-push; high-pass standard deviation 47.514 versus
ground truth 47.661. The corresponding regression asserts both frozen quality
thresholds. Performance tests enforce the planned generous 120-second cap;
observed supplemental timings are also below the 20-second target.

`git diff --check` passed, with only Git's LF-to-CRLF advisories.

## Denied/blocked actions and deviations

No permission or automatic-approval denials occurred. `rg` was unavailable;
PowerShell file reads/searches were used. Python 3.12 is unavailable through the
agreed launcher, and `fontTools` is absent from the fallback environment.

No implementation requirement was intentionally redesigned. The documented
implementation choices include a 2x2 box-filter pyramid, square default margin
dilation, ties-up odd patch rounding, and pixel-centre mapped source boxes.
The proposed verification deviation is supplemental Python 3.11 evidence only;
it does not replace the agreed Python 3.12 proof. That proof must be rerun by the
host/reviewer with the specified installed dependencies.

Real-texture builds, visual acceptance of 0629 and 0074/1385, and the original
eight-texture overlay acceptance remain unverified in this run. Those are host
review steps in the frozen plan; no existing art specs were changed to guess
new donor areas or lettering decisions. Review should run the agreed proof and
the host visual checks before accepting the changes.

## Fix round B-1

The host's 2026-10-17 dispositions are accepted: the pre-fix Python 3.12 proof
passed all 95 tests; all 50 delivered/spec'd textures rebuilt byte-identically,
check passed for 50, and overlay building reported 50/0 errors. B-PROOF-1 is
resolved by that evidence. The local environment limitations below do not reopen
that finding. This round addresses Q1, B-MEM-1 and B-CONF-1 only.

Files changed in this round: `patch.py`, `tests/test_patch.py`, `SPEC.md` and this
report, all under `texgen/redraw/`. The earlier uncommitted changes in `engine.py`,
`erase.py` and `spec.py` were retained. The frozen plan hash is still
`24065ba68bb4e445ee0d2a5404d502111189f51608a077459bf3609c4b692093`.

### Changes and rationale

- Q1: pyramid depth now uses the maximum distance to real known context (at
  most 8px), rather than the lettering's overall bbox. A proposed coarser level
  with more than 50% hole coverage in its context window is rejected, as is one
  without donors. This preserves context for thin strokes over a large area.
- Q1: first-round matching uses real known samples only; wholly unknown patches
  compare mean RGB without penalising donor variance against a smooth estimate.
  Subsequent rounds use unknown-sample weights 0.1 and then 0.35. This schedules
  the transition from reliable boundary evidence to reconstructed texture.
- Q1: each EM vote averages donor low frequencies and takes high-frequency detail
  from the highest-confidence covering patch. The Gaussian split (sigma 1.5)
  reflects within that valid donor footprint, preventing excluded/out-of-source
  samples from contributing. This retains real donor grain without artificial
  noise and avoids the full-colour discontinuities of winner-only pixel voting.
- B-MEM-1: costs, propagation, upsampled initialisation and voting are batched.
  Each batch has at most 256 patches and 65,536 patch samples; patch coordinates
  are int32. No target-domain-by-patch-area temporary remains. Per-target scalar
  arrays and image/index/pyramid storage remain proportional to their domains.
- B-CONF-1: EDT padding uses the actual neighbouring mask when inside the image,
  and unknown pixels outside it. Image edges no longer invent known context.

Five regression tests were added: the requested photo-like lettering fixture
with all four numerical criteria, patch-15 peak allocation/batch bounds, oversized
mapped-side rejection, exact EDT comparisons at image borders, and dense-coarse-
mask rejection. Existing tests and their acceptance criteria were not weakened
or changed. All 20 patch test methods pass in supplemental discovery.

### Verification of this revision

Agreed command executed again from this checkout:

```text
py -3.12 -m unittest discover -s texgen/redraw/tests -t .
Installed Pythons found by C:\windows\py.exe Launcher for Windows
No Installed Pythons Found!

Requested Python version (3.12) not installed, use -0 for available pythons
Python 3.12 not found!
```

Exit 1 before discovery. As directed by the host, the following run is
**supplemental only**, using the same existing Python 3.11.8 interpreter and
process-local package path documented above. No packages were installed.

```text
patch15 memory: peak=7.55 MiB, max batch=256 patches/57600 samples
patch performance: 512x512, 60x60 hole: 12.093s
patch performance: 2048x2048, 20x20 hole: 2.021s
photo lettering: hp ratio=0.885, min block ratio=0.781,
  MAE=8.487 (pullpush 9.183), colour error=0.611
Ran 100 tests in 72.207s
FAILED (failures=1, errors=22)
```

The 22 errors and one failure all identify missing `fontTools` in this fallback
environment; none are from the 20 patch tests. Full output is saved locally in
ignored `texgen/redraw/preview/amendment-b1-supplemental.log`. The new quality test
checks every 8x8 window wholly inside the hole, not just selected sample blocks.
Its 256x256 synthetic scene contains colour bands, a rectangle, straight edges,
a smooth lighting gradient, Gaussian grain sigma 6, and 20px lettering-like
strokes over a 190x84 bbox. No game art is included in the regression.

Performance remains below the unchanged 20-second target on the available
interpreter. The memory regression uses a 96x96 hole with patch 15, instruments
actual batch expansion and measures peak allocation with tracemalloc, enforcing
a generous 64 MiB ceiling. No algorithm output is mocked. `git diff --check`
passed with only Git's LF-to-CRLF advisories.

### Limits, deviations and outstanding host verification

B-MEM-1 explicitly permits a documented cap. In addition to batching, mapped
group patch sides above 255 now raise a clear `SpecError` before patch expansion,
so even a single oversized footprint cannot defeat the sample budget. This is
the only added limit relative to the frozen plan; ordinary authored sides 3–15
are unchanged. The donor-detail vote and thickness interpretation follow the
host's Q1 fix request. No other intentional implementation deviations.

No permission/automatic-approval denials occurred. The local agreed proof remains
blocked by unavailable Python 3.12; supplemental font-dependent tests remain
blocked by missing fontTools. No commit, push, publication, game/delivery write,
or edit to an original checkout was performed.

The host must rerun the Python 3.12 proof for this revised code and the outstanding
0074/1385 photo acceptance at 4x. The synthetic quality results support the fix
but do not establish acceptance on those real photographs. Prior host validation
of the 50 non-patch outputs is retained, not disputed or claimed as newly run.

## Fix round B-2

The host's B-1 Python 3.12 proof (`Ran 100 tests, OK`) is accepted. This final
round addresses only B-PYR-DENSITY-1 and B-MARGIN-1. The frozen plan is unchanged;
there are no commits, pushes, publications, delivery writes or edits to an
original checkout.

Files changed in this round: `patch.py`, `tests/test_patch.py`, `SPEC.md`, and
this report, all under `texgen/redraw/`. Earlier uncommitted integration changes
in `engine.py`, `erase.py` and `spec.py` were preserved without additional edits.

- B-PYR-DENSITY-1: removed the density-based coarse-level rejection. Pyramid
  selection retains the B-1 thickness criterion and falls back when a candidate
  level has no valid donors. Large solid erases can therefore use the pyramid.
  Matching, the EM schedule, donor-detail voting and footprint rules are unchanged.
- B-MARGIN-1: source dilation and context bounds clamp effective margin to the
  largest image side. Reconstruction also clamps before calculating per-level
  margins. This prevents oversized filters without changing pixel coverage.
  Preflight uses the same bounded source calculation.
- Replaced the obsolete B-1 density-rejection test, whose expectation directly
  contradicted this fix request, with the 400x200 solid-hole regression in a
  1024x1024 image. Added a huge-margin (`10**100`) test covering bounded filter
  size, load-time preflight, reconstruction, context bounds and an empty mask.
  Existing photo-quality thresholds and default-parameter performance tests
  were not changed.

Targeted supplemental verification passed all three tests: large solid hole,
oversized margin, and unchanged photo-like lettering quality:

```text
solid 400x200 hole: 5 pyramid levels, 22.705s (iterations=1, em=1)
photo lettering: hp ratio=0.885, min block ratio=0.781,
  MAE=8.487 (pullpush 9.183), colour error=0.611
Ran 3 tests in 51.659s
OK
```

The large-hole regression explicitly uses one iteration and one EM round to keep
the structural/runtime test practical; it asserts the existing 120-second cap.
It does not certify default-budget runtime for an 80,000-pixel hole. The existing
60x60-hole performance test still exercises defaults and the 20-second target.
Photo-quality metrics are unchanged from B-1 to the displayed precision.

The agreed proof was executed from this checkout:

```text
py -3.12 -m unittest discover -s texgen/redraw/tests -t .
Installed Pythons found by C:\windows\py.exe Launcher for Windows
No Installed Pythons Found!

Requested Python version (3.12) not installed, use -0 for available pythons
Python 3.12 not found!
```

Exit 1 before discovery, consistent with the host-described sandbox limitation.
No permission or automatic-approval denials occurred. No implementation
deviations beyond the requested fixes; the runtime-test budget is explicitly
stated above. The host will rerun the agreed proof for this revision.

Full supplemental discovery on the existing Python 3.11.8 environment:

```text
solid 400x200 hole: 5 pyramid levels, 18.951s (iterations=1, em=1)
patch15 memory: peak=7.55 MiB, max batch=256 patches/57600 samples
patch performance: 512x512, 60x60 hole: 10.426s
patch performance: 2048x2048, 20x20 hole: 2.320s
photo lettering: hp ratio=0.885, min block ratio=0.781,
  MAE=8.487 (pullpush 9.183), colour error=0.611
Ran 101 tests in 85.731s
FAILED (failures=1, errors=22)
```

All 21 patch test methods passed. Each of the 23 failure/error reports identifies
the known missing `fontTools` dependency in this supplemental environment. No
packages were installed. Full output: ignored local file
`texgen/redraw/preview/amendment-b2-supplemental.log`. `git diff --check` passed
with only LF-to-CRLF advisories; plan SHA256 still matches the supplied value.
This evidence is advisory and does not replace the host's Python 3.12 proof.
