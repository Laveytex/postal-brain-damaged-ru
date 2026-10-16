"""Pixel-centre regions and declarative RGB predicates (never eval)."""
import numpy as np
from scipy import ndimage as ndi


def region(size, geometry):
    w, h = size
    yy, xx = np.mgrid[:h, :w]
    x, y = xx + .5, yy + .5
    if "box" in geometry:
        l, t, r, b = geometry["box"]
        return (x >= l) & (x < r) & (y >= t) & (y < b)
    points = geometry["poly"]
    result = np.zeros((h, w), bool)
    for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1]):
        if ay != by:
            result ^= ((ay > y) != (by > y)) & (x < (bx-ax)*(y-ay)/(by-ay)+ax)
    return result


def select(rgb, spec, domain=None):
    rgb = np.asarray(rgb)[..., :3].astype(float)
    kind = spec.get("kind", "all")
    children = spec.get("of", [])
    if kind in ("all", "any"):
        parts = [select(rgb, s, domain) for s in children]
        m = (np.logical_and.reduce(parts) if kind == "all" else np.logical_or.reduce(parts)) if parts else np.ones(rgb.shape[:2], bool)
    elif kind == "saturation":
        v = np.ptp(rgb, axis=2)
        m = (v >= spec.get("min", 0)) & (v <= spec.get("max", 255))
    elif kind == "luminance":
        v = rgb.mean(axis=2)
        m = (v >= spec.get("min", 0)) & (v <= spec.get("max", 255))
    elif kind == "colour":
        m = np.max(np.abs(rgb - spec["rgb"]), axis=2) <= spec.get("tol", 0)
    elif kind == "channel_dominance":
        c = "rgb".index(spec["channel"])
        m = (rgb[..., c] >= spec.get("min", 0)) & (rgb[..., c] >= np.max(np.delete(rgb, c, axis=2), axis=2)*spec.get("ratio", 1))
    elif kind == "near":
        base = select(rgb, spec["of"], domain)
        m = ndi.maximum_filter(base, size=2*int(spec["radius"])+1, mode="constant") if base.any() else base.copy()
    else:
        raise ValueError(f"unknown mask kind {kind!r}")
    if domain is not None:
        m &= domain
    if spec.get("grow", 0):
        m = ndi.binary_dilation(m, structure=np.ones((3,3),bool), iterations=spec["grow"])
    if spec.get("min_size", 0):
        labels, _ = ndi.label(m)
        counts = np.bincount(labels.ravel())
        keep = counts >= spec["min_size"]
        keep[0] = False
        m = keep[labels]
    return m if domain is None else m & domain


def components(rgb, mask):
    labels, _ = ndi.label(mask)
    result = []
    for i, sl in enumerate(ndi.find_objects(labels), 1):
        if sl is None:
            continue
        m = labels[sl] == i
        result.append({"box": [sl[1].start, sl[0].start, sl[1].stop, sl[0].stop],
                       "pixels": int(m.sum()), "median": np.median(rgb[sl][m, :3], axis=0).tolist()})
    return result
