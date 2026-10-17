"""Amendment B: synthetic quality, bounds, pyramid, integration and work scope."""
import time
import tracemalloc
import unittest
from unittest.mock import patch as mock_patch

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

from texgen.redraw import compose, engine, erase, masks, patch, spec
from .test_redraw import Workspace


def rectangle(shape, box):
    result = np.zeros(shape, bool)
    l, t, r, b = box
    result[t:b, l:r] = True
    return result


def periodic(size=96):
    y, x = np.mgrid[:size, :size]
    base = np.repeat((50+150*((x//4+y//4) % 2))[..., None], 3, axis=2)
    return base + np.random.default_rng(4).normal(0, 1, base.shape)


def photo_like(seed=19):
    """Synthetic flat surfaces, straight scene edges, lighting and sensor grain."""
    y, x = np.mgrid[:256, :256]
    image = np.empty((256, 256, 3), float)
    image[:] = [110, 103, 92]
    image[y >= 112] = [160, 145, 122]
    image[x >= 160] += [28, 22, 18]
    image[92:144, 72:196] = [72, 83, 91]
    image += (.05*x+.025*y)[..., None]
    image += np.random.default_rng(seed).normal(0, 6, image.shape)
    hole = np.zeros((256, 256), bool)
    # H, square O, and I: 20px strokes distributed over a 190x84 bbox.
    hole[70:154, 35:55] = True
    hole[70:154, 85:105] = True
    hole[102:122, 35:105] = True
    hole[70:154, 125:185] = True
    hole[90:134, 145:165] = False
    hole[70:154, 205:225] = True
    return image, hole


def photo_metrics(result, truth, hole):
    hp = lambda a: (a-ndi.gaussian_filter(a, (1.5, 1.5, 0)))[hole].std()
    blocks = ndi.minimum_filter(hole, size=8, mode="constant")
    def block_std(a):
        mean = ndi.uniform_filter(a, (8, 8, 1))
        variance = ndi.uniform_filter(a*a, (8, 8, 1))-mean*mean
        return np.sqrt(np.maximum(variance, 0)).mean(2)[blocks]
    return (hp(result)/hp(truth), block_std(result).min()/np.median(block_std(truth)),
            np.abs(result[hole]-truth[hole]).mean(),
            np.abs(result[hole].mean(0)-truth[hole].mean(0)).max())


class PatchAlgorithm(unittest.TestCase):
    def test_patch15_large_hole_uses_bounded_batches(self):
        image = periodic(192).astype(np.float32)
        hole = rectangle(image.shape[:2], [48, 48, 144, 144])
        real_coordinates = patch.patch_coordinates
        observed = {"calls": 0, "rows": 0, "samples": 0}
        def coordinates(centres, offsets, shape):
            self.assertEqual(centres.dtype, np.dtype("int32"))
            self.assertEqual(offsets.dtype, np.dtype("int32"))
            observed["calls"] += 1
            observed["rows"] = max(observed["rows"], len(centres))
            observed["samples"] = max(observed["samples"], len(centres)*len(offsets))
            self.assertLessEqual(len(centres), patch.PATCH_BATCH)
            self.assertLessEqual(len(centres)*len(offsets), patch.PATCH_SAMPLES)
            return real_coordinates(centres, offsets, shape)
        tracemalloc.start()
        try:
            with mock_patch.object(patch, "patch_coordinates", coordinates):
                result = patch.reconstruct(image, hole, hole, {"patch": 15, "iterations": 1, "em": 1})
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        print(f"patch15 memory: peak={peak/1024**2:.2f} MiB, "
              f"max batch={observed['rows']} patches/{observed['samples']} samples", flush=True)
        self.assertGreater(observed["calls"], 100)
        # Includes pyramid/index/output storage; old n*side**2 temporaries alone
        # greatly exceed this cap for the 96px hole. NumPy uses tracemalloc hooks.
        self.assertLess(peak, 64*1024**2)
        np.testing.assert_array_equal(result[~hole], image[~hole])
        self.assertTrue(np.isfinite(result).all())

    def test_oversized_group_patch_fails_before_patch_allocation(self):
        hole = rectangle((64, 64), [20, 20, 40, 40])
        with self.assertRaisesRegex(spec.SpecError, "mapped side 257 exceeds memory cap 255"):
            patch.reconstruct(np.zeros((64, 64, 3)), hole, hole, {"patch": 257})

    def test_boundary_distance_has_no_off_image_known_pixels(self):
        for box in ([0, 0, 12, 20], [0, 8, 12, 24], [20, 0, 32, 20], [8, 20, 24, 32]):
            hole = rectangle((32, 32), box)
            bounds = patch.context_bounds(hole, 4)
            t, l, b, r = bounds
            actual = patch.boundary_distance(hole, bounds)
            expected = ndi.distance_transform_edt(hole)[t:b, l:r]
            np.testing.assert_array_equal(actual, expected)
        hole = rectangle((32, 32), [0, 0, 12, 20])
        self.assertEqual(patch.boundary_distance(hole, (0, 0, 24, 16))[0, 0], 12)

    def test_large_solid_hole_uses_pyramid_within_cap(self):
        image = np.random.default_rng(17).uniform(20, 220, (1024, 1024, 3)).astype(np.float32)
        hole = rectangle((1024, 1024), [312, 412, 712, 612])
        shapes = []
        complete = patch.complete_level
        def record_level(*args):
            shapes.append(args[0].shape[:2])
            return complete(*args)
        start = time.perf_counter()
        with mock_patch.object(patch, "complete_level", record_level):
            # A bounded EM budget keeps this structural 80,000-pixel regression
            # practical. Existing 60x60 performance still exercises defaults.
            result = patch.reconstruct(image, hole, hole,
                {"iterations": 1, "em": 1, "source": [[0, 0, 1024, 1024]]})
        elapsed = time.perf_counter()-start
        print(f"solid 400x200 hole: {len(shapes)} pyramid levels, {elapsed:.3f}s "
              "(iterations=1, em=1)", flush=True)
        self.assertGreater(len(shapes), 1)
        self.assertEqual(shapes[-1], (1024, 1024))
        self.assertLessEqual(shapes[0][0], 128)
        self.assertLess(elapsed, 120)
        self.assertTrue(np.isfinite(result).all())
        np.testing.assert_array_equal(result[~hole], image[~hole])

    def test_oversized_margin_clamps_before_filter_and_preflight(self):
        shape = (32, 48)
        domain = rectangle(shape, [20, 12, 28, 20])
        huge = 10**100
        expected = patch.source_pixels(shape, domain, {"margin": max(shape)})
        maximum_filter = patch.ndi.maximum_filter
        sizes = []
        def bounded_filter(*args, **kwargs):
            sizes.append(kwargs["size"])
            self.assertLessEqual(kwargs["size"], 2*max(shape)+1)
            return maximum_filter(*args, **kwargs)
        with mock_patch.object(patch.ndi, "maximum_filter", bounded_filter):
            actual = patch.source_pixels(shape, domain, {"margin": huge})
            spec.operations([{"type": "erase", "method": "patch",
                "region": {"box": [20, 12, 28, 20]}, "margin": huge}],
                (48, 32), "margin.toml/texture 0001")
            image = np.full((*shape, 3), 71., np.float32)
            result = patch.reconstruct(image, domain, domain,
                {"margin": huge, "iterations": 1, "em": 1})
        self.assertGreaterEqual(len(sizes), 3)
        np.testing.assert_array_equal(actual, expected)
        np.testing.assert_array_equal(result, image)
        self.assertEqual(patch.context_bounds(domain, huge), (0, 0, *shape))
        empty = np.zeros(shape, bool)
        self.assertFalse(patch.source_pixels(shape, empty, {"margin": huge}).any())

    def test_photo_like_lettering_retains_real_grain(self):
        truth, hole = photo_like()
        damaged = truth.copy()
        damaged[hole] = [255, 0, 255]
        baseline = np.abs(erase.pullpush(damaged, hole)[hole]-truth[hole]).mean()
        with mock_patch.object(patch, "complete_level", wraps=patch.complete_level) as run:
            result = patch.reconstruct(damaged, hole, hole, {})
        # Thin lettering must not descend according to its large overall bbox.
        self.assertGreaterEqual(min(c.args[0].shape[0] for c in run.call_args_list), 128)
        hp, block, mae, colour = photo_metrics(result, truth, hole)
        print(f"photo lettering: hp ratio={hp:.3f}, min block ratio={block:.3f}, "
              f"MAE={mae:.3f} (pullpush {baseline:.3f}), colour error={colour:.3f}", flush=True)
        self.assertGreaterEqual(hp, .7)
        self.assertGreaterEqual(block, .5)
        self.assertLessEqual(mae, baseline)
        self.assertLessEqual(colour, 8)
        np.testing.assert_array_equal(result[~hole], truth[~hole])

    def test_periodic_quality_and_high_frequency(self):
        original = periodic()
        hole = rectangle(original.shape[:2], [36, 36, 60, 60])
        damaged = original.copy()
        damaged[hole] = [255, 0, 0]
        result = patch.reconstruct(damaged, hole, hole, {})
        smooth = erase.pullpush(damaged, hole)
        error = np.abs(result[hole]-original[hole]).mean()
        baseline = np.abs(smooth[hole]-original[hole]).mean()
        self.assertLessEqual(error, .5*baseline)
        hp = lambda a: (a-ndi.gaussian_filter(a, (1, 1, 0)))[hole].std()
        self.assertGreaterEqual(hp(result), .6*hp(original))
        np.testing.assert_array_equal(result[~hole], damaged[~hole])

    def test_determinism_and_private_rng(self):
        a = np.random.default_rng(12).uniform(0, 255, (40, 40, 3))
        hole = rectangle(a.shape[:2], [16, 16, 24, 24])
        options = {"iterations": 2, "em": 1, "seed": 44}
        first = patch.reconstruct(a, hole, hole, options)
        np.random.seed(91)
        state = np.random.get_state()
        second = patch.reconstruct(a, hole, hole, options)
        np.testing.assert_array_equal(first, second)
        after = np.random.get_state()
        self.assertEqual(state[0], after[0])
        np.testing.assert_array_equal(state[1], after[1])
        self.assertEqual(state[2:], after[2:])
        other = patch.reconstruct(a, hole, hole, {**options, "seed": 45})
        self.assertFalse(np.array_equal(first[hole], other[hole]))

    def test_far_source_exactly_one_footprint(self):
        a = np.full((100, 140, 3), [255., 0., 0.])
        a[80:87, 120:127] = [17, 103, 209]
        hole = rectangle(a.shape[:2], [5, 5, 18, 18])
        result = patch.reconstruct(a, hole, hole, {"source": [[120, 80, 127, 87]]})
        self.assertLessEqual(np.abs(result[hole]-[17, 103, 209]).max(), 1)

    def test_exclusion_edge_and_entire_footprint(self):
        a = np.full((64, 96, 3), [255., 0., 0.])
        a[8:30, 60:90] = [0, 140, 0]
        a[8:30, 72:76] = [255, 0, 0]  # excluded face, even near its edge
        hole = rectangle(a.shape[:2], [20, 35, 36, 48])
        options = {"source": [[60, 8, 90, 30]], "exclude": [[72, 8, 76, 30]]}
        eligible = patch.source_pixels(hole.shape, hole, options) & ~hole
        donors, _ = patch.donor_index(eligible, 7)
        for y, x in donors:
            self.assertTrue(eligible[y-3:y+4, x-3:x+4].all())
        # Centres just outside the exclusion are ineligible too.
        self.assertFalse(any(x in (70, 71, 76, 77) for y, x in donors))
        result = patch.reconstruct(a, hole, hole, options)
        self.assertLessEqual(np.abs(result[hole]-[0, 140, 0]).max(), 1)

    def test_target_context_outside_region_and_at_image_edge(self):
        original = periodic(64)
        for box in ([20, 20, 44, 44], [0, 20, 12, 36]):
            hole = rectangle(original.shape[:2], box)
            damaged = original.copy()
            damaged[hole] = [255, 0, 255]
            # The entire region is erased: useful target context must be read
            # outside it. The same phase must continue across that boundary.
            result = patch.reconstruct(damaged, hole, hole, {"seed": 2})
            self.assertLess(np.abs(result[hole]-original[hole]).mean(), 20)
            np.testing.assert_array_equal(result[~hole], original[~hole])

    def test_disconnected_source_cannot_contain_footprint(self):
        a = np.zeros((48, 48, 3))
        hole = rectangle(a.shape[:2], [20, 20, 30, 30])
        with self.assertRaisesRegex(spec.SpecError, "whole donor footprint"):
            patch.reconstruct(a, hole, hole, {"source": [[0, 0, 3, 20], [8, 0, 11, 20]]})
        # Adjacent boxes form a union, rather than imposing individual-footprint
        # restrictions at their internal boundary.
        patch.reconstruct(a, hole, hole, {"source": [[0, 0, 3, 7], [3, 0, 7, 7]],
                                        "iterations": 1, "em": 1})

    def test_conservative_pyramid_and_coarse_fallback(self):
        a = np.full((65, 65, 3), 50.)
        hole = rectangle(a.shape[:2], [20, 20, 44, 44])
        allowed = rectangle(hole.shape, [2, 2, 9, 9])
        low, low_hole, low_allowed = patch.reduce_level(a, hole, allowed)
        self.assertEqual(low.shape, (33, 33, 3))
        self.assertFalse(len(patch.donor_index(low_allowed & ~low_hole, 7)[0]))
        with mock_patch.object(patch, "complete_level", wraps=patch.complete_level) as run:
            result = patch.reconstruct(a, hole, hole, {"source": [[2, 2, 9, 9]]})
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0].shape, a.shape)
        np.testing.assert_allclose(result, a)
        hole = np.zeros((5, 5), bool)
        hole[1, 1] = True
        permitted = np.ones((5, 5), bool)
        permitted[2, 3] = False
        _, masked, permitted = patch.reduce_level(np.zeros((5, 5, 3)), hole, permitted)
        self.assertTrue(masked[0, 0])
        self.assertFalse(permitted[1, 1])
        self.assertTrue(permitted[2, 2])

    def test_targets_only_overlap_hole_and_default_dilation(self):
        hole = rectangle((300, 400), [180, 110, 200, 130])
        centres, _, _ = patch.target_domain(hole, 3)
        self.assertEqual(len(centres), 26*26)
        allowed = patch.source_pixels(hole.shape, hole, {"margin": 4})
        np.testing.assert_array_equal(allowed, rectangle(hole.shape, [176, 106, 204, 134]))
        for y, x in centres:
            self.assertTrue(hole[y-3:y+4, x-3:x+4].any())

    def test_multiscale_donors_and_upsampled_initialisation(self):
        original = periodic(128)
        hole = rectangle(original.shape[:2], [40, 40, 88, 88])
        original[hole] = [255, 0, 255]
        with mock_patch.object(patch, "complete_level", wraps=patch.complete_level) as run:
            result = patch.reconstruct(original, hole, hole, {"iterations": 1, "em": 1})
        calls = run.call_args_list
        self.assertEqual([c.args[0].shape[:2] for c in calls], [(32, 32), (64, 64), (128, 128)])
        self.assertIsNone(calls[0].args[-1])
        for call in calls[1:]:
            self.assertIsNotNone(call.args[-1])
        for call in calls:
            image, masked, donors, _, side = call.args[:5]
            self.assertEqual(side, 7)
            for y, x in donors:
                self.assertFalse(masked[y-3:y+4, x-3:x+4].any())
        self.assertTrue(np.isfinite(result).all())

    def test_fractional_mapped_boxes_use_pixel_centres(self):
        domain = rectangle((20, 20), [5, 5, 10, 10])
        options = {"source": [[1.75, 2.5, 12.5, 14.75]],
                   "exclude": [[6.75, 4.25, 8.25, 10.5]]}
        expected = (masks.region((20, 20), {"box": options["source"][0]}) &
                    ~masks.region((20, 20), {"box": options["exclude"][0]}))
        np.testing.assert_array_equal(patch.source_pixels(domain.shape, domain, options), expected)

    def test_performance_60_hole_and_large_donor_extent(self):
        for size, side in ((512, 60), (2048, 20)):
            with self.subTest(size=size):
                a = np.random.default_rng(5).uniform(20, 220, (size, size, 3)).astype(np.float32)
                start = size//2
                hole = rectangle((size, size), [start, start, start+side, start+side])
                t = time.perf_counter()
                result = patch.reconstruct(a, hole, hole, {"source": [[0, 0, size, size]]})
                elapsed = time.perf_counter()-t
                print(f"patch performance: {size}x{size}, {side}x{side} hole: {elapsed:.3f}s", flush=True)
                self.assertLess(elapsed, 120)
                np.testing.assert_array_equal(result[~hole], a[~hole])


class PatchIntegration(Workspace):
    def op(self, **kw):
        return {"type": "erase", "method": "patch", "region": {"box": [20, 20, 36, 36]},
                "iterations": 1, "em": 1, **kw}

    def test_validation_ranges_boxes_unknown_keys(self):
        invalid = [{"patch": v} for v in (2, 4, 17, 3.5, True)]
        invalid += [{"iterations": 0}, {"iterations": 21}, {"em": 0}, {"em": 11},
                    {"seed": -1}, {"seed": .5}, {"margin": -1}, {"margin": float("nan")},
                    {"source": []}, {"source": [[0, 0, 3, 20]]}, {"source": "box"},
                    {"source": [[0, 0, 80, 10]]}, {"exclude": [[-1, 0, 10, 10]]},
                    {"exclude": [[0, 0, 64, 64]]}, {"surprise": 1}]
        for extra in invalid:
            with self.subTest(extra=extra), self.assertRaisesRegex(spec.SpecError, r"texture 0001/op\[0\]"):
                spec.operations([self.op(**extra)], (64, 64), "test.toml/texture 0001")

    def test_mask_donor_validation_uses_current_ordered_pixels(self):
        self.source_image("0001", colour=[40, 40, 40])
        self.data["texture"][0]["op"] = [self.op(region={"box": [0, 0, 64, 64]},
            mask={"kind": "colour", "rgb": [40, 40, 40]})]
        with self.assertRaisesRegex(spec.SpecError, r"texture 0001/op\[0\].*whole donor footprint"):
            self.build()
        # An earlier erase creates an eligible donor patch for the later mask.
        self.data["texture"][0]["op"].insert(0, self.flat([0, 0, 7, 7], [80, 80, 80]))
        self.build()
        self.verify()

    def test_rgb_rgba_invariance_check_and_deterministic_build(self):
        for mode, tid in (("RGB", "0001"), ("RGBA", "0002")):
            original, path = self.source_image(tid, mode=mode)
            self.data["texture"][-1]["op"] = [self.op(mask={"kind": "luminance", "min": 120})]
        self.build()
        hashes = []
        for texture in self.data["texture"]:
            tid = texture["id"]
            path = self.source/"1_Основное"/(tid+"_текстура.png")
            with Image.open(path) as im:
                original, mode, size = np.array(im), im.mode, im.size
            out = self.out/path.name
            with Image.open(out) as im:
                result = np.array(im)
                self.assertEqual((im.mode, im.size), (mode, size))
            op = texture["op"][0]
            domain = masks.region(size, op["region"])
            selected = masks.select(original, op["mask"], domain)
            np.testing.assert_array_equal(result[~selected], original[~selected])
            if mode == "RGBA":
                np.testing.assert_array_equal(result[..., 3], original[..., 3])
            hashes.append(spec.sha(out))
        self.verify()
        self.build()
        self.assertEqual(hashes, [spec.sha(p) for p in sorted(self.out.glob("*.png"))])

    def test_group_source_exclude_patch_size_mapping_and_check(self):
        op = self.op(source=[[0, 0, 16, 16]], exclude=[[0, 0, 4, 16]], patch=7)
        for scale, expected in ((.5, 3), (1, 7), (1.5, 11), (2, 15)):
            tr = {"scale": scale, "rot": 90, "mirror": True, "offset": [3, 4]}
            mapped = engine.scaled_erase(op, [64, 64], tr, (160, 160), "texture 0001/op[0]")
            self.assertEqual(mapped["patch"], expected)
            self.assertEqual(mapped["source"], [compose.map_geometry({"box": op["source"][0]}, [64, 64], tr)["box"]])
            self.assertEqual(mapped["exclude"], [compose.map_geometry({"box": op["exclude"][0]}, [64, 64], tr)["box"]])
        members = []
        for tid, scale in (("0001", 1), ("0002", .5)):
            original, path = self.source_image(tid, size=(int(64*scale),)*2, colour=[71, 123, 181])
            self.data["texture"][-1]["op"] = [{"type": "use_group", "group": "pair"}]
            members.append({"id": tid, "transform": {"scale": scale, "rot": 90, "mirror": True}})
        self.data["group"] = [{"id": "pair", "space": [64, 64], "member": members, "op": [op]}]
        self.build(["0002"])
        self.verify(["0001"])
        self.assertEqual(len(list(self.out.glob("*.png"))), 2)


if __name__ == "__main__":
    unittest.main()
