"""Geometry, premultiplied resampling and RGB-only compositing."""
import math
from fractions import Fraction
import numpy as np
from PIL import Image
from scipy import ndimage as ndi


def resize(image, size, resample=Image.Resampling.LANCZOS):
    if image.mode == "RGBA":
        return image.convert("RGBa").resize(size, resample).convert("RGBA")
    return image.resize(size, resample)


def orient(image, op):
    if op.get("mirror"):
        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if op.get("flip"):
        image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    rot = op.get("rot", 0)
    if rot:
        image = image.transpose({90: Image.Transpose.ROTATE_90, 180: Image.Transpose.ROTATE_180,
                                 270: Image.Transpose.ROTATE_270}[rot])
    if op.get("angle", 0):
        mode = image.mode
        image = image.convert("RGBa") if mode == "RGBA" else image
        image = image.rotate(op["angle"], Image.Resampling.BICUBIC, expand=True)
        image = image.convert(mode)
    return image


def map_points(points, space, transform):
    w, h = space
    out = []
    for x, y in points:
        if transform.get("mirror", False):
            x = w-x
        rot = transform.get("rot", 0)
        if rot == 90:
            x, y = y, w-x
        elif rot == 180:
            x, y = w-x, h-y
        elif rot == 270:
            x, y = h-y, x
        s = transform.get("scale", 1)
        dx, dy = transform.get("offset", [0, 0])
        out.append([x*s+dx, y*s+dy])
    return out


def map_geometry(g, space, transform):
    if "poly" in g:
        return {"poly": map_points(g["poly"], space, transform)}
    l, t, r, b = g["box"]
    p = np.array(map_points([[l,t],[r,t],[r,b],[l,b]], space, transform))
    return {"box": p.min(axis=0).tolist()+p.max(axis=0).tolist()}


def map_layer(image, size, transform):
    image = orient(image, transform)
    scale = transform.get("scale", 1)
    # Pad at the right/bottom, preserving the layout origin and exact sample grid.
    if scale != 1:
        k = Fraction(str(scale)).denominator
        padded = Image.new(image.mode, (math.ceil(image.width/k)*k, math.ceil(image.height/k)*k))
        padded.paste(image, (0, 0))
        image = padded
    target = (round(image.width*scale), round(image.height*scale))
    if target != image.size:
        image = resize(image, target, Image.Resampling.BOX if scale < 1 else Image.Resampling.NEAREST)
    out = Image.new(image.mode, size)
    dx, dy = transform.get("offset", [0, 0])
    out.paste(image, (int(dx), int(dy)))
    return out


def place(image, size, op):
    """Position an already fitted/oriented ink layer; return layer and off-canvas ink flag."""
    if "quad" in op:
        src = [(0,0), (image.width,0), (image.width,image.height), (0,image.height)]
        rows, values = [], []
        for (x,y), (u,v) in zip(op["quad"], src):
            rows.extend([[x,y,1,0,0,0,-u*x,-u*y], [0,0,0,x,y,1,-v*x,-v*y]])
            values.extend([u,v])
        coefficients = np.linalg.solve(rows, values)
        mode = image.mode
        work = image.convert("RGBa") if mode == "RGBA" else image
        return work.transform(size, Image.Transform.PERSPECTIVE, coefficients, Image.Resampling.BICUBIC).convert(mode), False
    l,t,r,b = op["box"]
    x = math.floor((l+r-image.width)/2)
    y = math.floor((t+b-image.height)/2)
    bounds = image.getchannel("A").getbbox() if image.mode == "RGBA" else image.getbbox()
    outside = bool(bounds and (x+bounds[0]<0 or y+bounds[1]<0 or x+bounds[2]>size[0] or y+bounds[3]>size[1]))
    canvas = Image.new(image.mode, size)
    canvas.paste(image, (x,y))
    return canvas, outside


def styled(fill, op, colour):
    """Restyle existing coverage; never re-render glyphs for group members."""
    alpha = np.asarray(fill).astype(float)/255
    w,h = fill.size
    out = Image.new("RGBA", (w,h))

    def coat(coverage, rgb, opacity=1):
        nonlocal out
        c = list(rgb)
        a = c[3]/255 if len(c) == 4 else 1
        layer = np.empty((h,w,4), np.uint8)
        layer[..., :3] = c[:3]
        layer[..., 3] = np.clip(np.rint(coverage*255*opacity*a), 0, 255).astype(np.uint8)
        out = Image.alpha_composite(out, Image.fromarray(layer))

    shadow = op.get("shadow")
    if shadow:
        a = ndi.gaussian_filter(alpha, shadow.get("blur", 0)) if shadow.get("blur", 0) else alpha
        a = ndi.shift(a, (shadow.get("dy", 0),shadow.get("dx", 0)), order=1, mode="constant", prefilter=False)
        coat(a, shadow.get("colour", [0,0,0]), shadow.get("opacity", 1))
    stroke = op.get("stroke", 0)
    if stroke:
        yy,xx = np.mgrid[-math.ceil(stroke):math.ceil(stroke)+1, -math.ceil(stroke):math.ceil(stroke)+1]
        a = ndi.maximum_filter(alpha, footprint=(xx*xx+yy*yy <= stroke*stroke), mode="constant")
        coat(a, op.get("stroke_colour", [0,0,0]))
    coat(alpha, colour)
    return out


def blend(rgb, layer, op, paint=None):
    data = np.asarray(layer).astype(float)
    a = data[..., 3:4]/255*op.get("opacity", 1)
    c = data[..., :3]
    if op.get("modulate", False):
        lum = rgb.mean(axis=2)
        smooth = ndi.gaussian_filter(lum, 3)
        c = c*(lum/np.maximum(smooth,1))[...,None]
    mode = op.get("blend", "normal")
    if mode == "multiply":
        c = rgb*c/255
    elif mode == "tint":
        if paint is None:
            raise ValueError("tint requires paint_from")
        c = rgb*np.asarray(paint["ratio"])
    return np.clip(rgb*(1-a)+c*a, 0, 255)
