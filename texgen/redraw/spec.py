"""Strict TOML validation, source resolution and transitive selection."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import math
import re
import tomllib
from fractions import Fraction
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
FONT_DIRS = [HERE / "fonts", Path("C:/Windows/Fonts")]


class SpecError(ValueError):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def record(path):
    path = Path(path).resolve()
    return {"path":str(path),"sha256":sha(path)}


def keys(value, allowed, where):
    if not isinstance(value,dict):
        raise SpecError(f"{where}: expected table")
    unknown = value.keys()-set(allowed.split())
    if unknown:
        raise SpecError(f"{where}: unknown key(s): {', '.join(sorted(unknown))}")


def number(value, where, minimum=None, maximum=None, integer=False):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise SpecError(f"{where}: expected finite number")
    if integer and int(value)!=value or minimum is not None and value<minimum or maximum is not None and value>maximum:
        raise SpecError(f"{where}: number out of range")


def vector(value, count, where, **kw):
    if not isinstance(value,list) or len(value)!=count:
        raise SpecError(f"{where}: expected {count} numbers")
    for x in value:
        number(x,where,**kw)


def colour(c, where, auto=False):
    if auto and c == "auto":
        return
    if not isinstance(c,list) or len(c) not in (3,4):
        raise SpecError(f"{where}: expected RGB or RGBA colour")
    for v in c:
        number(v,where,0,255)


def boolean_fields(value, names, where):
    for name in names.split():
        if name in value and not isinstance(value[name],bool):
            raise SpecError(f"{where}/{name}: expected boolean")


def pixel_box(value,size,where):
    vector(value,4,where,integer=True)
    geometry({"box":value},size,where)


def geometry(g, size, where):
    keys(g,"box poly",where)
    if len(g)!=1:
        raise SpecError(f"{where}: choose exactly one box or poly")
    if "box" in g:
        vector(g["box"],4,where)
        l,t,r,b = g["box"]
        if l>=r or t>=b:
            raise SpecError(f"{where}: empty/inverted box")
        points = [[l,t],[r,b]]
    else:
        points = g["poly"]
        if not isinstance(points,list) or len(points)<3:
            raise SpecError(f"{where}: polygon needs at least three points")
        for p in points:
            vector(p,2,where)
    if any(x<0 or y<0 or x>size[0] or y>size[1] for x,y in points):
        raise SpecError(f"{where}: region outside image {size}")


def mask(m, where):
    kind = m.get("kind", "all") if isinstance(m,dict) else None
    allowed = {"all":"of", "any":"of", "saturation":"min max", "luminance":"min max", "colour":"rgb tol",
               "channel_dominance":"channel ratio min", "near":"of radius"}
    if kind not in allowed:
        raise SpecError(f"{where}: unknown mask kind {kind!r}")
    keys(m,"kind grow min_size "+allowed[kind],where)
    for k in ("grow","min_size","radius","tol","ratio","min","max"):
        if k in m:
            number(m[k],where+"/"+k,0,integer=k in ("grow","min_size"))
    if kind == "any" and "of" not in m:
        raise SpecError(f"{where}: any requires a nonempty of array")
    if kind in ("any","all") and "of" in m:
        if not isinstance(m["of"],list) or not m["of"]:
            raise SpecError(f"{where}: boolean of must be a nonempty mask array")
        for child in m["of"]:
            mask(child,where+"/of")
    if kind == "near":
        if "of" not in m or "radius" not in m:
            raise SpecError(f"{where}: near requires of and radius")
        mask(m["of"],where+"/of")
    if kind == "colour":
        vector(m.get("rgb"),3,where,minimum=0,maximum=255)
    if kind == "channel_dominance" and m.get("channel") not in ("r","g","b"):
        raise SpecError(f"{where}: channel must be r/g/b")


def font_path(name):
    path = Path(name)
    candidates = [path] if path.is_absolute() else [d/path for d in FONT_DIRS]
    for p in candidates:
        if p.is_file():
            return p.resolve()
    raise SpecError(f"missing font {name!r} (searched redraw/fonts and C:/Windows/Fonts)")


def asset_path(name):
    p = Path(name)
    p = p if p.is_absolute() else HERE/"assets"/p
    if not p.is_file():
        raise SpecError(f"missing asset {p}")
    return p.resolve()


def validate_font(op, path, where):
    from fontTools.ttLib import TTFont, TTLibError
    try:
        with TTFont(path) as font:
            cmap = font.getBestCmap() or {}
            missing = set(op["text"])-set(map(chr,cmap))-set("\n\r\t ")
            if missing:
                raise SpecError(f"font lacks glyphs: {''.join(sorted(missing))}")
            if "axes" in op or "variation" in op:
                if "fvar" not in font:
                    raise SpecError("font is not variable")
                if "axes" in op and "variation" in op:
                    raise SpecError("choose axes OR variation")
                axes = {a.axisTag:a for a in font["fvar"].axes}
                if "axes" in op and not isinstance(op["axes"],dict):
                    raise SpecError("axes must be a table")
                for k,v in op.get("axes",{}).items():
                    if k not in axes:
                        raise SpecError(f"unknown font axis {k}")
                    number(v,where,axes[k].minValue,axes[k].maxValue)
                names = [font["name"].getDebugName(i.subfamilyNameID) for i in font["fvar"].instances]
                if "variation" in op and op["variation"] not in names:
                    raise SpecError(f"unknown font variation {op['variation']!r}")
    except TTLibError as exc:
        raise SpecError(f"invalid font {path}: {exc}") from exc


STYLE = "colour stroke stroke_colour shadow opacity blend modulate"
DRAW = "type id box quad region clip rot angle mirror flip fit paint_from " + STYLE


def style(s, where):
    boolean_fields(s,"modulate",where)
    for k in ("colour","stroke_colour"):
        if k in s:
            colour(s[k],where+"/"+k,auto=True)
    if "stroke" in s:
        if s["stroke"] is not False:
            number(s["stroke"],where+"/stroke",0,128)
    if "opacity" in s:
        number(s["opacity"],where+"/opacity",0,1)
    if s.get("blend","normal") not in ("normal","multiply","tint"):
        raise SpecError(f"{where}: invalid blend")
    if s.get("shadow") is not None and s.get("shadow") is not False:
        v = s["shadow"]
        keys(v,"dx dy blur colour opacity",where+"/shadow")
        for k in ("dx","dy","blur","opacity"):
            if k in v:
                number(v[k],where+"/shadow/"+k,0 if k in ("blur","opacity") else None,1 if k=="opacity" else None)
        if "colour" in v:
            colour(v["colour"],where+"/shadow")


def paint_reference(op, erases, where):
    reference = op.get("paint_from")
    if reference is not None and reference not in erases:
        raise SpecError(f"{where}: paint_from must name an EARLIER erase op in this scope")
    if (op.get("colour")=="auto" or op.get("stroke_colour")=="auto" or op.get("blend")=="tint") and reference is None:
        raise SpecError(f"{where}: auto/tint requires paint_from")
    if op.get("blend")=="tint" and erases[reference]["method"]!="untint":
        raise SpecError(f"{where}: tint requires paint_from to reference an untint erase")


def operations(ops, size, where, in_group=False):
    previous, erase_ids = set(), {}
    dependencies = set()
    if not isinstance(ops,list):
        raise SpecError(f"{where}: op must be an array")
    for i,op in enumerate(ops):
        loc = f"{where}/op[{i}]"
        try:
            if not isinstance(op,dict):
                raise SpecError("expected table")
            typ = op.get("type")
            if typ == "use_group":
                keys(op,"type group",loc)
                if in_group or not isinstance(op.get("group"),str):
                    raise SpecError("use_group requires a group id and cannot be nested")
                continue
            if "id" in op:
                if not isinstance(op["id"],str) or op["id"] in previous:
                    raise SpecError("duplicate or invalid op id")
                previous.add(op["id"])
            paint_reference(op, erase_ids, loc)
            if typ == "erase":
                keys(op,"type id region mask method core colour sample grain offset feather paint",loc)
                geometry(op["region"],size,loc)
                mask(op.get("mask",{"kind":"all"}),loc)
                if "core" in op:
                    mask(op["core"],loc+"/core")
                if op.get("method") not in ("flat","pullpush","untint","clone"):
                    raise SpecError("invalid erase method")
                if "colour" in op:
                    colour(op["colour"],loc)
                if "sample" in op:
                    pixel_box(op["sample"],size,loc)
                if "offset" in op:
                    vector(op["offset"],2,loc,integer=True)
                if "feather" in op:
                    number(op["feather"],loc,0)
                if "paint" in op:
                    keys(op["paint"],"colour stroke_colour",loc+"/paint")
                    for value in op["paint"].values():
                        number(value,loc+"/paint",0,100)
                if "grain" in op:
                    keys(op["grain"],"ref sigma gain seed",loc+"/grain")
                    pixel_box(op["grain"]["ref"],size,loc)
                    for k in ("sigma","gain","seed"):
                        if k in op["grain"]:
                            number(op["grain"][k],loc,0,integer=k=="seed")
                if "id" in op:
                    erase_ids[op["id"]] = op
                continue
            if typ not in ("text","asset"):
                raise SpecError(f"unknown op type {typ!r}")
            keys(op,DRAW+(" text font axes variation align spacing tracking size sx_min supersample" if typ=="text" else " path crop recolour key"),loc)
            if "box" not in op and "quad" not in op:
                raise SpecError("text/asset requires box or quad")
            if "box" in op and "quad" in op:
                raise SpecError("text/asset must choose box OR quad, not both")
            if "box" in op:
                geometry({"box":op["box"]},size,loc)
            if "quad" in op:
                if len(op["quad"])!=4:
                    raise SpecError("quad needs four points: TL, TR, BR, BL")
                geometry({"poly":op["quad"]},size,loc)
                p=op["quad"]
                turns=[]
                for j in range(4):
                    a,b,c=p[j],p[(j+1)%4],p[(j+2)%4]
                    turns.append((b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]))
                if not (all(v>0 for v in turns) or all(v<0 for v in turns)):
                    raise SpecError("quad must be convex and nondegenerate")
            if "region" in op:
                geometry(op["region"],size,loc)
            if op.get("rot",0) not in (0,90,180,270):
                raise SpecError("rot must be 0/90/180/270")
            boolean_fields(op,"mirror flip clip",loc)
            if "angle" in op:
                number(op["angle"],loc)
            if op.get("fit","fit") not in ("fill_box","fit","fixed"):
                raise SpecError("fit must be fill_box, fit or fixed")
            style(op,loc)
            if (op.get("colour")=="auto" or op.get("stroke_colour")=="auto" or op.get("blend")=="tint") and "paint_from" not in op:
                raise SpecError("auto/tint requires paint_from")
            if typ == "text":
                if not isinstance(op.get("text"),str) or not op["text"].strip():
                    raise SpecError("text must be a nonempty string")
                path = font_path(op["font"])
                dependencies.add(path)
                validate_font(op,path,loc)
                if op.get("align","center") not in ("left","center","right"):
                    raise SpecError("align must be left/center/right")
                for k in ("size","spacing","sx_min","supersample"):
                    if k in op:
                        number(op[k],loc,.01,1 if k=="sx_min" else 16 if k=="supersample" else None,integer=k=="supersample")
                if "tracking" in op:
                    number(op["tracking"],loc)
                if op.get("fit")=="fixed" and "size" not in op:
                    raise SpecError("fixed text requires size")
            else:
                path = asset_path(op["path"])
                dependencies.add(path)
                with Image.open(path) as im:
                    if im.format!="PNG" or im.mode!="RGBA":
                        raise SpecError("asset must be an RGBA PNG")
                    if "crop" in op:
                        pixel_box(op["crop"],im.size,loc)
                if "recolour" in op:
                    keys(op["recolour"],"mode colour",loc)
                    colour(op["recolour"]["colour"],loc)
                    if op["recolour"].get("mode","set") not in ("set","multiply"):
                        raise SpecError("recolour mode must be set/multiply")
                if "key" in op:
                    keys(op["key"],"colour tolerance softness",loc)
                    colour(op["key"]["colour"],loc)
                    number(op["key"].get("tolerance",0),loc,0,255)
                    number(op["key"].get("softness",30),loc,.01,255)
        except (KeyError,TypeError,ValueError,OSError) as exc:
            raise SpecError(f"{loc}: {exc}") from exc
    return dependencies


@dataclass
class Project:
    textures: dict
    groups: dict
    paths: list
    sources: dict
    dependencies: dict
    spec_records: list
    origins: dict

    def closure(self, only=None):
        selected = set(only) if only else set(self.textures)
        if selected-self.textures.keys():
            raise SpecError(f"unknown texture ids: {sorted(selected-self.textures.keys())}")
        while True:
            old = selected.copy()
            for g in self.groups.values():
                ids = {m["id"] for m in g["member"]}
                if ids & selected:
                    selected |= ids
            if old == selected:
                return sorted(selected)


def load(paths, source_root, only=None):
    textures, groups, origins = {}, {}, {}
    spec_records = []
    paths = list(dict.fromkeys(Path(p).resolve() for p in paths))
    for path in paths:
        try:
            raw = path.read_bytes()
            spec_records.append({"path":str(path), "sha256":hashlib.sha256(raw).hexdigest()})
            data = tomllib.loads(raw.decode("utf-8-sig"))
            keys(data,"texture group",str(path))
            for kind, target in (("texture",textures),("group",groups)):
                items=data.get(kind,[])
                if not isinstance(items,list):
                    raise SpecError(f"{kind}: expected array of tables")
                for index,item in enumerate(items):
                    if not isinstance(item,dict):
                        raise SpecError(f"{kind}[{index}]: expected table")
                    ident = item.get("id")
                    if not isinstance(ident,str) or not re.fullmatch(r"[A-Za-z0-9_-]+",ident):
                        raise SpecError(f"invalid {kind} id {ident!r}")
                    if kind=="texture" and not re.fullmatch(r"\d{4}",ident):
                        raise SpecError("texture id must be four digits")
                    if ident in target:
                        raise SpecError(f"duplicate {kind} {ident}")
                    keys(item,"id op allow" if kind=="texture" else "id space member op",f"{kind} {ident}")
                    target[ident] = item
                    origins[kind,ident] = str(path)
        except (ValueError,KeyError,TypeError) as exc:
            raise SpecError(f"{path}: {exc}") from exc
    # Closure reads member IDs before image-dependent validation. Validate all
    # container structure first, including unselected definitions, with context.
    for kind,items in (("texture",textures),("group",groups)):
        for ident,item in items.items():
            where=f"{origins[kind,ident]}/{kind} {ident}"
            ops=item.get("op",[])
            if not isinstance(ops,list):
                raise SpecError(f"{where}: op must be an array")
            for index,op in enumerate(ops):
                if not isinstance(op,dict):
                    raise SpecError(f"{where}/op[{index}]: expected table")
            if kind=="group":
                members=item.get("member")
                if not isinstance(members,list) or not members:
                    raise SpecError(f"{where}/member: expected nonempty array of tables")
                seen=set()
                for index,member in enumerate(members):
                    loc=f"{where}/member[{index}]"
                    keys(member,"id transform style",loc)
                    tid=member.get("id")
                    if not isinstance(tid,str) or tid not in textures or tid in seen:
                        raise SpecError(f"{loc}: unknown/duplicate member id {tid!r}")
                    seen.add(tid)
    sources, dependencies = {}, {}
    project=Project(textures,groups,paths,sources,dependencies,spec_records,origins)
    active=set(project.closure(only))
    root = Path(source_root)
    if not root.is_dir():
        raise SpecError(f"Missing source root {root}. Set --source-root, --tools-root or PBD_RU_TOOLS.")
    for ident,t in textures.items():
        if ident not in active:
            continue
        where = f"{origins['texture',ident]}/texture {ident}"
        candidates = sorted(p for p in root.glob(f"*/{ident}_*.png") if p.parent.name!="ГОТОВО")
        if len(candidates)!=1:
            raise SpecError(f"{where}: expected one source, found {len(candidates)}")
        sources[ident] = candidates[0].resolve()
        with Image.open(candidates[0]) as im:
            if im.mode not in ("RGB","RGBA"):
                raise SpecError(f"{where}: only RGB/RGBA supported")
            for box in t.get("allow",[]):
                geometry({"box":box},im.size,where)
            dependencies[ident] = operations(t.get("op",[]),im.size,where)
    for ident,g in groups.items():
        if only and not any(m.get("id") in active for m in g.get("member",[])):
            continue
        where = f"{origins['group',ident]}/group {ident}"
        vector(g.get("space"),2,where,minimum=1,integer=True)
        dep = operations(g.get("op",[]),g["space"],where,True)
        members = set()
        for m in g.get("member",[]):
            keys(m,"id transform style",where)
            tid = m.get("id")
            if tid not in textures or tid in members:
                raise SpecError(f"{where}: unknown/duplicate member {tid}")
            members.add(tid)
            tr = m.get("transform",{})
            keys(tr,"scale rot mirror offset",where)
            boolean_fields(tr,"mirror",where)
            s = tr.get("scale",1)
            number(s,where,1e-4,1000)
            if Fraction(str(s)).denominator > 16384:
                raise SpecError(f"{where}: scale requires excessive padding; use a shorter exact decimal")
            if tr.get("rot",0) not in (0,90,180,270):
                raise SpecError(f"{where}: invalid rotation")
            vector(tr.get("offset",[0,0]),2,where,integer=True)
            st = m.get("style",{})
            keys(st,STYLE,where)
            style(st,where)
            erases = {}
            for index, op in enumerate(g.get("op", [])):
                if op["type"] == "erase":
                    if "id" in op:
                        erases[op["id"]] = op
                else:
                    paint_reference({**op, **st}, erases, f"{where}/texture {tid}/op[{index}] member style")
            uses = [o for o in textures[tid].get("op",[]) if o.get("type")=="use_group" and o.get("group")==ident]
            if len(uses)!=1:
                raise SpecError(f"{where}/texture {tid}: exactly one use_group required, found {len(uses)}")
            dependencies[tid] |= dep
        if not members:
            raise SpecError(f"{where}: group has no members")
    for tid,t in textures.items():
        if tid not in active:
            continue
        for i,o in enumerate(t.get("op",[])):
            if o["type"]=="use_group" and (o["group"] not in groups or not any(m["id"]==tid for m in groups[o["group"]]["member"])):
                raise SpecError(f"{origins['texture',tid]}/texture {tid}/op[{i}]: not a member of {o['group']}")
    return project
