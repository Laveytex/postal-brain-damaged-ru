"""Deterministic multiscale PatchMatch completion with overlapping-patch voting.

Donor coordinates are centres, but eligibility always tests the entire footprint.
Only the compact target domain participates in search/EM; image-sized work is
limited to pyramid construction and donor indexing. No filled pixel is a donor.
"""
import numpy as np
from scipy import ndimage as ndi

# Bound every patch-expanded temporary, including enlarged group patches.
PATCH_BATCH = 256
PATCH_SAMPLES = 65536
MAX_PATCH_SIDE = 255


def batches(count, side=1):
    step = min(PATCH_BATCH, max(1, PATCH_SAMPLES // (side*side)))
    for start in range(0, count, step):
        yield np.arange(start, min(start+step, count), dtype=np.int32)


def context_bounds(hole, margin):
    margin = min(int(margin), max(hole.shape))
    y, x = np.nonzero(hole)
    return (max(0, int(y.min())-margin), max(0, int(x.min())-margin),
            min(hole.shape[0], int(y.max())+margin+1),
            min(hole.shape[1], int(x.max())+margin+1))


def boundary_distance(hole, bounds):
    """EDT to actual known pixels; off-image padding is always unknown."""
    t, l, b, r = bounds
    yy, xx = np.mgrid[t-1:b+1, l-1:r+1]
    real = (yy >= 0) & (yy < hole.shape[0]) & (xx >= 0) & (xx < hole.shape[1])
    padded = np.ones(yy.shape, bool)
    padded[real] = hole[yy[real], xx[real]]
    return ndi.distance_transform_edt(padded)[1:-1, 1:-1]


def patch_coordinates(centres, offsets, shape):
    """The sole patch expansion for targets: called only on bounded batches."""
    coords = centres[:, None, :] + offsets
    real = ((coords[..., 0] >= 0) & (coords[..., 0] < shape[0]) &
            (coords[..., 1] >= 0) & (coords[..., 1] < shape[1]))
    yy = coords[..., 0].clip(0, shape[0]-1)
    xx = coords[..., 1].clip(0, shape[1]-1)
    return yy, xx, real


def donor_index(eligible, side):
    """Integral-image footprint test; return valid centres and a reverse index."""
    h, w = eligible.shape
    lookup = np.full((h, w), -1, dtype=np.int32)
    if min(h, w) < side:
        return np.empty((0, 2), dtype=np.int32), lookup
    integral = np.pad(eligible.astype(np.int32), ((1, 0), (1, 0)))
    integral = integral.cumsum(0, dtype=np.int32).cumsum(1, dtype=np.int32)
    sums = (integral[side:, side:] - integral[:-side, side:]
            - integral[side:, :-side] + integral[:-side, :-side])
    positions = np.argwhere(sums == side * side).astype(np.int32) + side // 2
    lookup[positions[:, 0], positions[:, 1]] = np.arange(len(positions))
    return positions, lookup


def source_pixels(shape, domain, options):
    """Union of source boxes, minus exclusions (hole removed by caller)."""
    allowed = np.zeros(shape, bool)
    boxes = options.get("source")
    if boxes is None:
        margin = min(int(options.get("margin", 48)), max(shape))
        allowed = ndi.maximum_filter(domain, size=2*margin+1, mode="constant")
        boxes = []
    for box in boxes:
        l, t, r, b = np.ceil(np.asarray(box)-.5).astype(int)
        allowed[t:b, l:r] = True
    for box in options.get("exclude", []):
        l, t, r, b = np.ceil(np.asarray(box)-.5).astype(int)
        allowed[t:b, l:r] = False
    return allowed


def reduce_level(rgb, hole, allowed):
    """2x2 box filter; odd edge cells have only their real fine children.

    A coarse donor pixel must have *all* children known and permitted. In
    particular, averaging RGB never makes masked lettering eligible as a donor.
    """
    h, w = hole.shape
    pad = ((0, h % 2), (0, w % 2))
    def blocks(a, fill):
        a = np.pad(a, pad, constant_values=fill)
        return a.reshape((h+1)//2, 2, (w+1)//2, 2)
    count = blocks(np.ones(hole.shape, np.float32), 0).sum((1, 3))
    low = np.stack([blocks(rgb[..., c], 0).sum((1, 3))/count for c in range(3)], axis=2)
    return low, blocks(hole, False).any((1, 3)), blocks(allowed, True).all((1, 3))


def target_domain(hole, radius):
    """Compact centres of all in-image patches overlapping the hole."""
    y, x = np.nonzero(hole)
    t, l = max(0, y.min()-radius), max(0, x.min()-radius)
    b, r = min(hole.shape[0], y.max()+radius+1), min(hole.shape[1], x.max()+radius+1)
    local = ndi.maximum_filter(hole[t:b, l:r], size=2*radius+1, mode="constant")
    centres = np.argwhere(local).astype(np.int32) + np.array([t, l], dtype=np.int32)
    lookup = np.full(local.shape, -1, dtype=np.int32)
    lookup[local] = np.arange(len(centres))
    return centres, lookup, np.array([t, l], dtype=np.int32)


def lookup_ids(points, lookup, origin=(0, 0)):
    q = points - np.asarray(origin, dtype=np.int32)
    valid = ((q[:, 0] >= 0) & (q[:, 0] < lookup.shape[0]) &
             (q[:, 1] >= 0) & (q[:, 1] < lookup.shape[1]))
    ids = np.full(len(q), -1, dtype=np.int32)
    ids[valid] = lookup[q[valid, 0], q[valid, 1]]
    return ids


def complete_level(rgb, hole, donors, donor_lookup, side, options, rng, previous):
    radius = side // 2
    centres, target_lookup, origin = target_domain(hole, radius)
    n = len(centres)
    offsets = np.stack(np.mgrid[-radius:radius+1, -radius:radius+1], axis=-1).reshape(-1, 2).astype(np.int32)
    result = rgb.copy()
    nnf = rng.integers(len(donors), size=n, dtype=np.int32)
    hy, hx = np.nonzero(hole)
    if previous is None:
        from .erase import pullpush
        t, l = np.maximum(0, origin-radius)
        b, r = np.minimum(hole.shape, origin+target_lookup.shape+radius)
        local_hole = hole[t:b, l:r]
        if local_hole.all():
            result[hy, hx] = rgb[donors[nnf[0], 0], donors[nnf[0], 1]]
        else:
            initial = pullpush(rgb[t:b, l:r], local_hole)
            result[hy, hx] = initial[hy-t, hx-l]
    else:
        coarse, old_nnf, old_targets, old_origin, old_donors = previous
        for rows in batches(len(hy)):
            for c in range(3):
                result[hy[rows], hx[rows], c] = ndi.map_coordinates(coarse[..., c],
                    [(hy[rows]-.5)/2, (hx[rows]-.5)/2], order=1, mode="nearest", prefilter=False)
        for rows in batches(n):
            old_ids = lookup_ids(centres[rows]//2, old_targets, old_origin)
            good = old_ids >= 0
            proposed = old_donors[old_nnf[old_ids[good]]]*2 + centres[rows[good]] % 2
            mapped = lookup_ids(proposed, donor_lookup)
            nnf[rows[good][mapped >= 0]] = mapped[mapped >= 0]

    t, l = origin
    b, r = origin + target_lookup.shape
    distance = boundary_distance(hole, (t, l, b, r))
    confidence = .5 ** (distance[centres[:, 0]-t, centres[:, 1]-l]/max(1, radius))
    directions = [np.array(delta, dtype=np.int32) for step in (8, 4, 2, 1)
                  for delta in ((0, step), (step, 0), (0, -step), (-step, 0))]
    vote_ids = np.full(target_lookup.shape, -1, dtype=np.int32)
    vote_ids[hy-t, hx-l] = np.arange(len(hy))

    for em in range(int(options.get("em", 3))):
        # A smooth guess is not evidence for a smooth donor. First anchor to
        # real known samples; entirely unknown patches compare only mean RGB.
        # Subsequent EM rounds can trust the reconstructed donor detail.
        unknown_weight = (0, .1, .35)[min(em, 2)]

        def costs(ids, rows):
            yy, xx, real = patch_coordinates(centres[rows], offsets, hole.shape)
            unknown = hole[yy, xx]
            target = result[yy, xx]
            cc = donors[ids, None, :] + offsets
            sample = rgb[cc[..., 0], cc[..., 1]]
            difference = sample - target
            weights = np.where(unknown, unknown_weight, 1).astype(np.float32) * real
            denominator = weights.sum(1)*3
            values = (difference*difference*weights[..., None]).sum((1, 2))/np.maximum(denominator, 1)
            unanchored = denominator == 0
            if unanchored.any():
                mean_difference = (difference[unanchored]*real[unanchored, :, None]).sum(1)
                mean_difference /= real[unanchored].sum(1)[:, None]
                values[unanchored] = (mean_difference*mean_difference).mean(1)
            return values

        best = np.empty(n, np.float32)
        for rows in batches(n, side):
            best[rows] = costs(nnf[rows], rows)

        def improve(candidate, rows):
            valid = candidate >= 0
            if not valid.any():
                return
            candidate, rows = candidate[valid], rows[valid]
            score = costs(candidate, rows)
            better = score < best[rows]
            nnf[rows[better]], best[rows[better]] = candidate[better], score[better]

        for iteration in range(int(options.get("iterations", 5))):
            sequence = directions if iteration % 2 == 0 else reversed(directions)
            for delta in sequence:
                for rows in batches(n, side):
                    adjacent = lookup_ids(centres[rows]+delta, target_lookup, origin)
                    proposed = donors[nnf[np.maximum(adjacent, 0)]] - delta
                    candidate = lookup_ids(proposed, donor_lookup)
                    candidate[adjacent < 0] = -1
                    improve(candidate, rows)
            for rows in batches(n, side):
                improve(rng.integers(len(donors), size=len(rows), dtype=np.int32), rows)
            search = max(hole.shape)
            while search >= 1:
                for rows in batches(n, side):
                    proposed = donors[nnf[rows]] + rng.integers(-search, search+1,
                                                              size=(len(rows), 2), dtype=np.int32)
                    improve(lookup_ids(proposed, donor_lookup), rows)
                search //= 2

        # Vote low frequencies, but retain real donor detail from the highest
        # confidence covering patch. Averaging independent grain erases it.
        # Filtering is confined to each valid footprint (reflect at its edge),
        # so an excluded/out-of-source pixel never contributes even indirectly.
        total = np.zeros(len(hy), np.float64)
        sums = np.zeros((len(hy), 3), np.float64)
        detail = np.zeros((len(hy), 3), np.float32)
        winner = np.full(len(hy), -1., np.float64)
        for rows in batches(n, side):
            yy, xx, real = patch_coordinates(centres[rows], offsets, hole.shape)
            valid = hole[yy, xx] & real
            destination = vote_ids[yy[valid]-t, xx[valid]-l]
            cc = donors[nnf[rows], None, :] + offsets
            sample = rgb[cc[..., 0], cc[..., 1]]
            low = ndi.gaussian_filter(sample.reshape(-1, side, side, 3),
                                      (0, 1.5, 1.5, 0), mode="reflect").reshape(sample.shape)
            weight = confidence[rows] / (1 + best[rows])
            weights = np.broadcast_to(weight[:, None], valid.shape)[valid]
            np.add.at(total, destination, weights)
            np.add.at(sums, destination, low[valid]*weights[:, None])
            # Stable sort resolves equal scores by earlier target, then offset.
            order = np.lexsort((-weights, destination))
            dest = destination[order]
            first = np.r_[True, dest[1:] != dest[:-1]]
            chosen = order[first]
            dest = destination[chosen]
            better = weights[chosen] > winner[dest]
            chosen, dest = chosen[better], dest[better]
            winner[dest] = weights[chosen]
            detail[dest] = (sample-low)[valid][chosen]
        result[hy, hx] = sums / total[:, None] + detail
    return result, nnf, target_lookup, origin, donors

def reconstruct(rgb, hole, domain, options):
    """Return RGB with only hole pixels replaced; validate donors before work."""
    from .spec import SpecError
    if not hole.any():
        return rgb.copy()
    side = int(options.get("patch", 7))
    if side > MAX_PATCH_SIDE:
        raise SpecError(f"patch: mapped side {side} exceeds memory cap {MAX_PATCH_SIDE}")
    allowed = source_pixels(hole.shape, domain, options)
    level = (np.asarray(rgb, dtype=np.float32), hole, allowed)
    margin = min(int(options.get("margin", 48)), max(hole.shape))
    levels = []
    while True:
        image, masked, permitted = level
        donors, lookup = donor_index(permitted & ~masked, side)
        if not levels and not len(donors):
            raise SpecError("patch: source minus exclude/erase mask contains no valid whole donor footprint")
        bounds = context_bounds(masked, max(side//2+1, int(np.ceil(margin/2**len(levels)))))
        if levels and not len(donors):
            break
        levels.append((image, masked, donors, lookup))
        if boundary_distance(masked, bounds).max() <= 8 or min(masked.shape) < 2*side:
            break
        level = reduce_level(*level)
    # If conservative downsampling removed all donors, start at the next finer
    # usable level, deterministically; the finest was already checked above.
    while not len(levels[-1][2]):
        levels.pop()
    rng = np.random.default_rng(int(options.get("seed", 0)))
    previous = None
    for image, masked, donors, lookup in reversed(levels):
        previous = complete_level(image, masked, donors, lookup, side, options, rng, previous)
    result = rgb.copy()
    result[hole] = previous[0][hole]
    return result
