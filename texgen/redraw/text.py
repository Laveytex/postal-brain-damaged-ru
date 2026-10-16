"""Coverage-first text/asset rendering. Pillow uses FreeType; no font substitution."""
import math
from dataclasses import dataclass
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFont
from . import compose
from .spec import font_path, asset_path


@dataclass
class RenderResult:
    fill: Image.Image
    asset: Image.Image | None
    warnings: list
    quad_frame: Image.Image | None = None

    def __iter__(self):
        # Retain the three-value rendering API used by inspection/tests.
        yield self.fill
        yield self.asset
        yield self.warnings


def font_for(op, size):
    path = font_path(op["font"])
    font = ImageFont.truetype(str(path),size)
    if "axes" in op or "variation" in op:
        from fontTools.ttLib import TTFont
        with TTFont(path) as tt:
            values = {a.axisTag:a.defaultValue for a in tt["fvar"].axes}
            if "variation" in op:
                inst = next(i for i in tt["fvar"].instances if tt["name"].getDebugName(i.subfamilyNameID)==op["variation"])
                values.update(inst.coordinates)
            values.update(op.get("axes",{}))
            font.set_variation_by_axes([values[a.axisTag] for a in tt["fvar"].axes])
    return font


def glyph_drips(glyph, line_height, options, rng):
    """Extend transformed ink downward; return coverage and its origin offset."""
    count = rng.poisson(options.get("count", .6))
    if not count:
        return glyph, (0, 0)
    ink = np.asarray(glyph) > 0
    band = max(0, math.floor(glyph.height*.85))
    candidates = np.flatnonzero(ink[band:].any(axis=0))
    drops = []
    for _ in range(count):
        x = int(rng.choice(candidates))
        y = int(np.flatnonzero(ink[:, x])[-1])
        length = rng.uniform(*options.get("length", [.3, 1.2]))*line_height
        width = rng.uniform(*options.get("width", [.06, .14]))*line_height
        drops.append((x, y, length, max(1, width)))
    left = math.floor(min(0, *(x-.8*w for x,y,h,w in drops)))
    top = math.floor(min(0, *(y+h-.8*w for x,y,h,w in drops)))
    right = math.ceil(max(glyph.width, *(x+.8*w+1 for x,y,h,w in drops)))
    bottom = math.ceil(max(glyph.height, *(y+h+.8*w+1 for x,y,h,w in drops)))
    layer = Image.new("L", (right-left, bottom-top))
    draw = ImageDraw.Draw(layer)
    for x,y,length,width in drops:
        x -= left
        y -= top
        end = y+length
        draw.polygon([(x-width/2,y), (x+width/2,y),
                      (x+.325*width,end), (x-.325*width,end)], fill=255)
        radius = .8*width
        draw.ellipse((x-radius,end-radius,x+radius,end+radius), fill=255)
    original = Image.new("L", layer.size)
    original.paste(glyph, (-left, -top))
    return ImageChops.lighter(layer, original), (left, top)


def effected_glyphs(op, font, ss):
    """Yield ink and positions in the unchanged, kerned multiline layout frame.

    Keep glyphs separate until their transforms/drips are complete. Dynamic
    extents prevent clipping long drips or rotated ink before the fit/overflow
    checks. Each invocation restarts private RNGs, including fit measurement.
    """
    jitter = op.get("jitter", {})
    drips = op.get("drips", {})
    jitter_rng = np.random.default_rng(int(jitter.get("seed", 1)))
    drip_rng = np.random.default_rng(int(drips.get("seed", 2)))
    lines = op["text"].split("\n")
    tracking = op.get("tracking", 0)*ss
    widths = [font.getlength(line)+max(0,len(line)-1)*tracking for line in lines]
    line_height = sum(font.getmetrics())
    step = line_height*op.get("spacing", 1)
    for n, (line, width) in enumerate(zip(lines, widths)):
        align = op.get("align", "center")
        x = (max(widths)-width)*(0 if align=="left" else 1 if align=="right" else .5)
        for index, ch in enumerate(line):
            l,t,r,b = font.getbbox(ch)
            if not ch.isspace() and r>l and b>t:
                glyph = Image.new("L", (r-l+4, b-t+4))
                ImageDraw.Draw(glyph).text((2-l,2-t), ch, font=font, fill=255)
                bounds = glyph.getbbox()
                if bounds:
                    gx,gy = x+l-2+bounds[0], n*step+t-2+bounds[1]
                    glyph = glyph.crop(bounds)
                    cx,cy = gx+glyph.width/2, gy+glyph.height/2
                    angle = jitter_rng.uniform(-jitter.get("rotate",0), jitter.get("rotate",0))
                    shift = jitter_rng.uniform(-jitter.get("shift",0), jitter.get("shift",0))*line_height
                    scale = jitter_rng.uniform(1-jitter.get("scale",0), 1+jitter.get("scale",0))
                    if scale != 1:
                        glyph = compose.resize(glyph, (max(1,round(glyph.width*scale)),
                                                      max(1,round(glyph.height*scale))))
                    if angle:
                        glyph = glyph.rotate(angle, Image.Resampling.BICUBIC, expand=True)
                    gx,gy = cx-glyph.width/2, cy-glyph.height/2+shift
                    # Rotation can add transparent margins; drip origins use ink.
                    bounds = glyph.getbbox()
                    if bounds:
                        # Snap once before adding integer drip margins. Rounding
                        # a half-pixel again after an odd margin changes parity.
                        gx,gy = round(gx+bounds[0]), round(gy+bounds[1])
                        glyph = glyph.crop(bounds)
                        if "drips" in op and drips.get("count",.6)>0:
                            glyph, (dx,dy) = glyph_drips(glyph, line_height, drips, drip_rng)
                            gx,gy = gx+dx, gy+dy
                        yield glyph, gx, gy
            advance = (font.getlength(ch+line[index+1])-font.getlength(line[index+1])
                       if index+1<len(line) else font.getlength(ch))
            x += advance+tracking


def raw_text(op, size, ss):
    font = font_for(op,max(1,round(size*ss)))
    jitter = op.get("jitter", {})
    if (any(jitter.get(key,0) for key in ("rotate","shift","scale")) or
            "drips" in op and op["drips"].get("count",.6)>0):
        glyphs = list(effected_glyphs(op, font, ss))
        if not glyphs:
            raise ValueError("text has no visible ink")
        l,t = min(x for g,x,y in glyphs), min(y for g,x,y in glyphs)
        r,b = max(x+g.width for g,x,y in glyphs), max(y+g.height for g,x,y in glyphs)
        image = Image.new("L", (r-l,b-t))
        for glyph,x,y in glyphs:
            box = (x-l,y-t,x-l+glyph.width,y-t+glyph.height)
            image.paste(ImageChops.lighter(image.crop(box),glyph), box)
        return image.crop(image.getbbox())
    lines = op["text"].split("\n")
    tracking = op.get("tracking",0)*ss
    widths = [font.getlength(line)+max(0,len(line)-1)*tracking for line in lines]
    step = (font.getmetrics()[0]+font.getmetrics()[1])*op.get("spacing",1)
    pad = max(16,round(size*ss))
    image = Image.new("L",(max(1,math.ceil(max(widths)))+2*pad,math.ceil(step*len(lines))+2*pad))
    draw = ImageDraw.Draw(image)
    for line, width, n in zip(lines,widths,range(len(lines))):
        align = op.get("align","center")
        x = pad + (max(widths)-width)*(0 if align=="left" else 1 if align=="right" else .5)
        y = pad+n*step
        if tracking==0:
            draw.text((x,y),line,font=font,fill=255)
        else:
            for index,ch in enumerate(line):
                draw.text((x,y),ch,font=font,fill=255)
                advance=(font.getlength(ch+line[index+1])-font.getlength(line[index+1])
                         if index+1<len(line) else font.getlength(ch))
                x += advance+tracking
    bbox = image.getbbox()
    if not bbox:
        raise ValueError("text has no visible ink")
    return image.crop(bbox)


def target_size(op):
    if "box" in op:
        l,t,r,b = op["box"]
        w,h = r-l,b-t
    else:
        p = np.asarray(op["quad"])
        w = max(np.linalg.norm(p[1]-p[0]),np.linalg.norm(p[2]-p[3]))
        h = max(np.linalg.norm(p[3]-p[0]),np.linalg.norm(p[2]-p[1]))
    if op.get("rot",0) in (90,270):
        w,h = h,w
    return max(1,round(w)),max(1,round(h))


def fit_effect_bounds(image, op, target):
    """Fit and centre the final styled bbox, retaining only the original fill.

    Effects are measured at the final pixel scale; asymmetric shadows therefore
    do not shift the fitted result or silently spill out of its declared box.
    """
    shadow=op.get("shadow") or {}
    pad=math.ceil(max(op.get("stroke",0),abs(shadow.get("dx",0))+4*shadow.get("blur",0),abs(shadow.get("dy",0))+4*shadow.get("blur",0)))+3
    measure={**op,"stroke_colour":[255,255,255]}
    if shadow:
        measure["shadow"]={**shadow,"colour":[255,255,255]}
    fit=op.get("fit","fit")
    for _ in range(8):
        padded=Image.new(image.mode,(image.width+2*pad,image.height+2*pad))
        padded.paste(image,(pad,pad))
        fill=padded.getchannel("A") if image.mode=="RGBA" else padded
        bounds=compose.styled(fill,measure,[255,255,255]).getchannel("A").getbbox()
        if not bounds:
            raise ValueError("no visible ink")
        bw,bh=bounds[2]-bounds[0],bounds[3]-bounds[1]
        if fit=="fixed":
            return padded.crop(bounds)
        if fit=="fill_box":
            tw,th=image.width+target[0]-bw,image.height+target[1]-bh
        else:
            scale=min((target[0]-(bw-image.width))/image.width,(target[1]-(bh-image.height))/image.height)
            tw,th=round(image.width*scale),round(image.height*scale)
        if tw<1 or th<1:
            raise ValueError("stroke/shadow alone exceeds the target box")
        if (tw,th)==image.size:
            return padded.crop(bounds)
        image=compose.resize(image,(tw,th))
    raise ValueError("final styled ink fit did not converge; adjust box/effects explicitly")


def render(op, canvas_size):
    """Return full-canvas fill coverage, optional asset RGB layer, diagnostics."""
    warnings = []
    w,h = target_size(op)
    typ = op["type"]
    ss = op.get("supersample",4) if typ=="text" else 1
    if typ == "text":
        raster_size=op.get("size",128)
        image = raw_text(op,raster_size,ss)
    else:
        with Image.open(asset_path(op["path"])) as source:
            image = source.copy()
        if "crop" in op:
            image = image.crop(op["crop"])
        data = np.array(image).astype(float)
        if "key" in op:
            key = op["key"]
            difference = np.max(np.abs(data[...,:3]-key["colour"][:3]),axis=2)
            matte = np.clip((difference-key.get("tolerance",0))/key.get("softness",30),0,1)
            data[...,3] *= matte
        if "recolour" in op:
            c = op["recolour"]
            data[...,:3] = data[...,:3]*np.array(c["colour"][:3])/255 if c.get("mode","set")=="multiply" else c["colour"][:3]
        image = Image.fromarray(np.rint(data).astype(np.uint8))
        bbox = image.getchannel("A").getbbox()
        if not bbox:
            raise ValueError("asset has no visible ink after crop/key")
        image = image.crop(bbox)
    # Reserve style extents in the reading frame. Geometry derives from the fill once.
    stroke = op.get("stroke",0)
    sh = op.get("shadow") or {}
    left = max(stroke,3*sh.get("blur",0)-sh.get("dx",0),0)
    right = max(stroke,3*sh.get("blur",0)+sh.get("dx",0),0)
    top = max(stroke,3*sh.get("blur",0)-sh.get("dy",0),0)
    bottom = max(stroke,3*sh.get("blur",0)+sh.get("dy",0),0)
    aw,ah = max(1,w-left-right),max(1,h-top-bottom)
    fit = op.get("fit","fit")
    def fitted_size(image):
        if fit == "fill_box":
            return round(aw*ss),round(ah*ss),1
        if fit == "fixed":
            return *image.size,1
        natural_w,natural_h = image.width/ss,image.height/ss
        factor = min(ah/natural_h,aw/(natural_w*op.get("sx_min",1)))
        squeeze = min(1,aw/(natural_w*factor))
        return round(natural_w*factor*squeeze*ss),round(natural_h*factor*ss),squeeze
    tw,th,squeeze=fitted_size(image)
    if typ=="text" and fit!="fixed":
        # The nominal raster measures proportions only. Rasterise FreeType at
        # the fitted supersampled size before the residual resize/downsample.
        for _ in range(2):
            factor=max(tw/image.width,th/image.height)
            raster_size=max(1/ss,math.ceil(raster_size*factor*ss)/ss)
            image=raw_text(op,raster_size,ss)
            tw,th,squeeze=fitted_size(image)
    if squeeze < .75:
        warnings.append("squeezed below 0.75")
    image = compose.resize(image,(max(1,tw),max(1,th)))
    # Free-angle rotation changes the measured ink bbox before fitting in reading frame.
    if op.get("angle",0):
        image = compose.orient(image,{"angle":op["angle"]})
        bbox = image.getchannel("A").getbbox() if typ=="asset" else image.getbbox()
        image = image.crop(bbox)
        if fit != "fixed":
            if fit == "fill_box":
                dest = (max(1,round(aw*ss)),max(1,round(ah*ss)))
            else:
                f = min(aw*ss/image.width,ah*ss/image.height)
                dest = (max(1,round(image.width*f)),max(1,round(image.height*f)))
            image = compose.resize(image,dest)
    if ss!=1:
        image = compose.resize(image,(max(1,round(image.width/ss)),max(1,round(image.height/ss))))
    # Quarter turns occur after downsampling, so they are exact transposes and
    # cannot change the separable filter's rounding order or glyph coverage.
    image = compose.orient(image,{k:op[k] for k in ("rot","mirror","flip") if k in op})
    screen_target=(h,w) if op.get("rot",0) in (90,270) else (w,h)
    image=fit_effect_bounds(image,op,screen_target)
    quad_frame=None
    if "quad" in op:
        # Fit describes ink inside the entire reading frame, not an instruction
        # to stretch the cropped ink to the perspective corners. Keep its blank
        # margins (including stroke/shadow reservation) through the homography.
        image,outside=compose.place(image,screen_target,{"box":[0,0,*screen_target]})
        if outside and not op.get("clip",False):
            raise ValueError("ink outside quad reading frame; set clip=true explicitly")
        quad_frame=image
    image, outside = compose.place(image,canvas_size,op)
    if outside and not op.get("clip",False):
        raise ValueError("ink outside image; set clip=true explicitly")
    return RenderResult(image.getchannel("A") if typ=="asset" else image,
                        image if typ=="asset" else None, warnings, quad_frame)
