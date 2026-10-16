"""Local erasure. All methods leave pixels outside the selected mask untouched."""
import numpy as np
from scipy import ndimage as ndi
from PIL import Image
from . import masks


def pullpush(rgb, mask):
    if not mask.any():
        return rgb.copy()
    if mask.all():
        raise ValueError("pullpush needs at least one unmasked background pixel")
    # Normalized convolution pyramid: pull only known samples, then push missing data.
    def level(values, weight):
        h,w = weight.shape
        if h == 1 and w == 1:
            return values/np.maximum(weight[...,None], 1e-12)
        shape = ((w+1)//2,(h+1)//2)
        def down(a):
            return np.array(Image.fromarray(a.astype(np.float32)).resize(shape, Image.Resampling.BOX))
        low_w = down(weight)
        low_v = np.stack([down(values[...,c]) for c in range(3)], axis=2)
        low = level(low_v, low_w)
        up = np.stack([np.array(Image.fromarray(low[...,c].astype(np.float32)).resize((w,h), Image.Resampling.BILINEAR)) for c in range(3)],axis=2)
        known = weight > 1e-12
        up[known] = values[known]/weight[known,None]
        return up
    result = level(rgb*(~mask)[...,None], (~mask).astype(float))
    result[~mask] = rgb[~mask]
    return result


def regrain(rgb, original, mask, options):
    l,t,r,b = options["ref"]
    patch = original[t:b,l:r].astype(float)
    detail = patch - ndi.gaussian_filter(patch, (options.get("sigma",2), options.get("sigma",2),0))
    h,w = detail.shape[:2]
    rng = np.random.default_rng(options.get("seed",0))
    # Reflect across patch edges instead of wrapping the last column/row onto
    # the first: each crop is continuous even when it crosses a reference edge.
    padded = np.pad(detail,((h,h),(w,w),(0,0)),mode="reflect")
    grain = np.zeros_like(rgb)
    for y in range(0,rgb.shape[0],h):
        for x in range(0,rgb.shape[1],w):
            dy,dx=int(rng.integers(2*h+1)),int(rng.integers(2*w+1))
            tile = padded[dy:dy+h,dx:dx+w]
            if rng.integers(2):
                tile = tile[::-1]
            if rng.integers(2):
                tile = tile[:,::-1]
            bh,bw = min(h,rgb.shape[0]-y), min(w,rgb.shape[1]-x)
            grain[y:y+bh,x:x+bw] = tile[:bh,:bw]
    rgb[mask] += grain[mask]*options.get("gain",1)
    return rgb


def apply(rgb, op, domain):
    selected = masks.select(rgb, op.get("mask", {"kind":"all"}), domain)
    ring = ndi.binary_dilation(domain, iterations=8) & ~ndi.binary_dilation(selected, iterations=2)
    if not ring.any():
        ring = ~domain
    method = op["method"]
    sample = rgb[selected]
    paint = {"colour": np.median(sample, axis=0).tolist() if sample.size else [0,0,0]}
    if sample.size and "paint" in op:
        lum=sample.mean(axis=1)
        for name,quantile in op["paint"].items():
            cutoff=np.percentile(lum,quantile)
            subset=sample[lum>=cutoff] if quantile>=50 else sample[lum<=cutoff]
            paint[name]=np.median(subset,axis=0).tolist()
    if not selected.any():
        if method == "untint":
            raise ValueError("untint mask is empty")
        return rgb.copy(), paint
    result = rgb.copy()
    if method == "flat":
        if "colour" in op:
            colour = op["colour"][:3]
        else:
            ref = masks.region((rgb.shape[1],rgb.shape[0]), {"box":op["sample"]}) if "sample" in op else ring
            if not ref.any():
                raise ValueError("flat sampling needs background pixels")
            colour = np.median(rgb[ref],axis=0)
        result[selected] = colour
    elif method == "pullpush":
        result = pullpush(rgb, selected)
        if op.get("grain"):
            result = regrain(result,rgb,selected,op["grain"])
    elif method == "clone":
        dx,dy = op.get("offset", [0,0])
        yy,xx = np.nonzero(selected)
        if np.any(xx+dx<0) or np.any(xx+dx>=rgb.shape[1]) or np.any(yy+dy<0) or np.any(yy+dy>=rgb.shape[0]):
            raise ValueError("clone source offset leaves image")
        a = np.ones(len(xx))
        if op.get("feather",0):
            a = np.clip(ndi.distance_transform_edt(selected)[selected]/op["feather"],0,1)
        result[selected] = rgb[yy+dy,xx+dx]*a[:,None]+rgb[selected]*(1-a[:,None])
    elif method == "untint":
        core = masks.select(rgb, op.get("core",op.get("mask",{"kind":"all"})),domain)
        if not core.any() or not ring.any():
            raise ValueError("untint needs a nonempty core and background ring")
        bg = np.maximum(np.median(rgb[ring],axis=0), 1)
        colour = np.median(rgb[core],axis=0)
        ratio = colour/bg
        hue = bg/bg.mean()
        # px = intensity*hue + intensity*opacity*hue*(ratio-1).
        # Solve intensity and intensity*opacity together, preserving per-pixel grain.
        basis = np.stack([hue,hue*(ratio-1)],axis=1)
        if np.linalg.cond(basis) > 1e5:
            raise ValueError("untint is underdetermined for achromatic paint; specify pullpush/clone instead")
        # A saturation-selected core is biased toward brighter background grain.
        # Calibrate the paint's intensity against the unpainted ring instead of
        # treating that conditional core median as an unbiased background sample.
        mixture=np.linalg.lstsq(np.stack([hue,colour/bg.mean()],axis=1),rgb[selected].T,rcond=None)[0]
        lo,hi=0.,8.
        if np.median(mixture[0]) < bg.mean() < np.median(mixture[0]+hi*mixture[1]):
            for _ in range(40):
                mid=(lo+hi)/2
                if np.median(mixture[0]+mid*mixture[1])<bg.mean():
                    lo=mid
                else:
                    hi=mid
            correction=(lo+hi)/2
            ratio=ratio/max(correction,.01)
        basis=np.stack([hue,hue*(ratio-1)],axis=1)
        coeff = np.linalg.lstsq(basis,rgb[selected].T,rcond=None)[0]
        opacity = np.clip(coeff[1]/np.maximum(coeff[0],1e-6),0,1)
        restored = rgb[selected]/np.maximum(1+opacity[:,None]*(ratio-1),.01)
        result[selected] = restored
        paint["ratio"] = ratio.tolist()
        if "colour" not in op.get("paint", {}):
            paint["colour"] = np.clip(ratio*bg,0,255).tolist()
    return np.clip(result,0,255), paint
