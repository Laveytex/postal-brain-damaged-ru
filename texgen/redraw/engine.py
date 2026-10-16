"""Ordered build execution. Writes only local build products, never delivery files."""
from pathlib import Path
import copy
import io
import json
import os
import tempfile
import math
import hashlib
import tomllib
import re
import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from . import masks, erase, compose, text
from .spec import HERE, load, record, geometry, SpecError


def atomic_bytes(path, data, *, create_parent=True):
    path = Path(path)
    if create_parent:
        path.parent.mkdir(parents=True,exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".redraw-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def png_bytes(image):
    stream = io.BytesIO()
    image.save(stream,format="PNG",compress_level=9)
    return stream.getvalue()


def op_geometry(op):
    if "region" in op:
        return op["region"]
    return {"poly":op["quad"]} if "quad" in op else {"box":op["box"]}


def member_for(group, tid):
    return next(m for m in group["member"] if m["id"]==tid)


def mapped_region(g, size, space, transform):
    source = Image.fromarray(masks.region(space,g).astype(np.uint8)*255)
    return np.asarray(compose.map_layer(source,size,transform))>0


def allowed_for(project, tid, size):
    allowed = np.zeros((size[1],size[0]),bool)
    geometries = []
    for box in project.textures[tid].get("allow",[]):
        g = {"box":box}
        allowed |= masks.region(size,g)
        geometries.append(g)
    for op in project.textures[tid].get("op",[]):
        if op["type"]!="use_group":
            g = op_geometry(op)
            allowed |= masks.region(size,g)
            geometries.append(g)
        else:
            group = project.groups[op["group"]]
            tr = member_for(group,tid).get("transform",{})
            for item in group.get("op",[]):
                g = op_geometry(item)
                mapped = compose.map_geometry(g,group["space"],tr)
                geometry(mapped,size,f"texture {tid}/group {group['id']}")
                allowed |= mapped_region(g,size,group["space"],tr)
                geometries.append(mapped)
    return allowed,geometries


def scaled_erase(op, space, tr, size, where):
    out = copy.deepcopy(op)
    out["region"] = compose.map_geometry(op["region"],space,tr)
    s = tr.get("scale",1)
    def scale_mask(m):
        for k in ("grow","radius"):
            if k in m:
                m[k] = round(m[k]*s)
        if "min_size" in m:
            m["min_size"] = max(1,round(m["min_size"]*s*s))
        if "of" in m:
            for child in m["of"] if isinstance(m["of"],list) else [m["of"]]:
                scale_mask(child)
    for key in ("mask","core"):
        if key in out:
            scale_mask(out[key])
    def sample_box(box, label):
        l,t,r,b=compose.map_geometry({"box":box},space,tr)["box"]
        mapped=[math.floor(l),math.floor(t),math.ceil(r),math.ceil(b)]
        geometry({"box":mapped},size,f"{where}/{label}")
        return mapped
    if "sample" in out:
        out["sample"] = sample_box(out["sample"],"sample")
    if "grain" in out:
        out["grain"]["ref"] = sample_box(out["grain"]["ref"],"grain.ref")
        out["grain"]["sigma"] = out["grain"].get("sigma",2)*s
    if "offset" in out:
        a,b = compose.map_points([[0,0],out["offset"]],space,tr)
        out["offset"] = [round(b[i]-a[i]) for i in (0,1)]
    if "feather" in out:
        out["feather"] *= s
    return out


def styled_layer(fill, asset, op, colour):
    shadow=op.get("shadow") or {}
    pad=math.ceil(max(op.get("stroke",0),abs(shadow.get("dx",0))+4*shadow.get("blur",0),abs(shadow.get("dy",0))+4*shadow.get("blur",0)))+2
    expanded=Image.new("L",(fill.width+2*pad,fill.height+2*pad))
    expanded.paste(fill,(pad,pad))
    full=compose.styled(expanded,op,colour)
    bbox=full.getchannel("A").getbbox()
    if bbox and (bbox[0]<pad or bbox[1]<pad or bbox[2]>pad+fill.width or bbox[3]>pad+fill.height) and not op.get("clip",False):
        raise SpecError("styled ink outside image; set clip=true explicitly")
    layer = full.crop((pad,pad,pad+fill.width,pad+fill.height))
    if asset is not None:
        # Preserve the supplied lettering RGB unless a style explicitly sets colour.
        if "colour" not in op:
            layer = Image.alpha_composite(compose.styled(fill,{**op,"colour":[0,0,0,0]},[0,0,0,0]),asset)
    return layer


def draw(rgb, fill, asset, op, allowed, paints, warnings, *, quad_frame=None, layout_size=None, transform=None):
    op=copy.deepcopy(op)
    paint = paints.get(op.get("paint_from"))
    colour = op.get("colour",[255,255,255])
    if colour == "auto":
        colour = [int(round(v)) for v in paint["colour"]]
    if op.get("stroke_colour")=="auto":
        if not paint or "stroke_colour" not in paint:
            raise SpecError("stroke_colour=auto requires paint.stroke_colour on the referenced erase")
        op["stroke_colour"]=[int(round(v)) for v in paint["stroke_colour"]]
    if quad_frame is None:
        layer=styled_layer(fill,asset,op,colour)
    else:
        # Style the reserved reading frame before warping, so effects are not
        # expanded outward from an already warped/cropped glyph at the quad edge.
        frame_op=copy.deepcopy(op)
        if transform is not None:
            scale=transform.get("scale",1)
            frame_op["stroke"]=frame_op.get("stroke",0)/scale
            if frame_op.get("shadow"):
                sh=frame_op["shadow"]
                x,y=sh.get("dx",0)/scale,sh.get("dy",0)/scale
                for _ in range(transform.get("rot",0)//90):
                    x,y=-y,x
                if transform.get("mirror",False):
                    x=-x
                sh["dx"],sh["dy"],sh["blur"]=x,y,sh.get("blur",0)/scale
        frame_asset=quad_frame if quad_frame.mode=="RGBA" else None
        frame_fill=quad_frame.getchannel("A") if frame_asset is not None else quad_frame
        layer=styled_layer(frame_fill,frame_asset,frame_op,colour)
        layer,_=compose.place(layer,layout_size or fill.size,op)
        if transform is not None:
            layer=compose.map_layer(layer,fill.size,transform)
    data = np.array(layer)
    ink = data[...,3]>0
    if np.any(ink & ~allowed):
        if not op.get("clip",False):
            raise SpecError("ink outside allowed regions (set clip=true to clip explicitly)")
        data[~allowed,3] = 0
        layer = Image.fromarray(data)
        ink &= allowed
    if np.any(ink & ~ndi.binary_erosion(allowed)):
        warnings.append("ink touches region edge")
    return compose.blend(rgb,layer,op,paint)


def preview(original, result, allowed):
    ys,xs = np.nonzero(allowed)
    box = (max(0,int(xs.min())-6),max(0,int(ys.min())-6),min(original.width,int(xs.max())+7),min(original.height,int(ys.max())+7)) if len(xs) else (0,0,*original.size)
    w,h = box[2]-box[0],box[3]-box[1]
    scale = max(1,min(8,640//max(w,h)))
    tiles = [im.convert("RGB").crop(box).resize((w*scale,h*scale),Image.Resampling.NEAREST) for im in (original,result)]
    thumb = result.convert("RGB")
    thumb.thumbnail((256,256))
    sheet = Image.new("RGB",(2*w*scale+8,max(h*scale,thumb.height)+thumb.height+12),(32,32,32))
    sheet.paste(tiles[0],(0,0)); sheet.paste(tiles[1],(w*scale+8,0))
    sheet.paste(thumb,(0,max(h*scale,thumb.height)+12))
    return sheet


def retain_previous(manifest_path, previous, project, selected, root):
    """Keep independently reverified prior closures; never trust hashes alone."""
    from .check import verify
    kept, groups, records, inputs = {}, {}, {}, {}
    if Path(previous.get("source_root", "")).resolve()!=root:
        return kept, groups, records, inputs
    owners=dict(project.origins)
    seen=set(selected)
    recorded_paths={Path(r["path"]).resolve()
                    for e in previous.get("textures",{}).values()
                    for r in [*e["specs"],e["output"]]}
    recorded_paths.update(Path(r["path"]).resolve() for r in previous.get("groups",{}).values())
    def stale_closure(tid, reason):
        unit={tid}
        while True:
            gids={m["id"] for ident in unit for m in previous["textures"][ident]["groups"]}
            expanded=unit | {ident for ident,e in previous["textures"].items()
                             if gids & {m["id"] for m in e["groups"]}}
            if expanded==unit:
                break
            unit=expanded
        seen.update(unit)
        print(f"Dropped stale textures {', '.join(sorted(unit))}: {reason}")
    for tid in sorted(previous.get("textures", {})):
        if tid in seen:
            continue
        try:
            verified=verify(manifest_path,[tid],manifest_data=previous)
            if set(verified) & set(selected):
                continue
            unit_records={r["path"]:r for _,_,e in verified.values() for r in e["specs"]}
            unit_owners={}
            for path,rec in unit_records.items():
                raw=Path(path).read_bytes()
                if hashlib.sha256(raw).hexdigest()!=rec["sha256"]:
                    raise SpecError(f"prior spec changed: {path}")
                data=tomllib.loads(raw.decode("utf-8-sig"))
                for kind in ("texture","group"):
                    for item in data.get(kind,[]):
                        key=kind,item["id"]
                        if key in owners and owners[key]!=path:
                            raise SpecError(f"prior spec conflicts with current {kind} {item['id']}")
                        unit_owners[key]=path
            owners.update(unit_owners)
            records.update(unit_records)
            for ident,(_,_,entry) in verified.items():
                kept[ident]=entry
                seen.add(ident)
                for rec in [entry["source"],entry["output"],*entry["dependencies"],*entry["specs"]]:
                    inputs[Path(rec["path"])]=rec
                for membership in entry["groups"]:
                    gid=membership["id"]
                    groups[gid]=previous["groups"][gid]
                    rec=groups[gid]
                    inputs[Path(rec["path"])]=rec
        except FileNotFoundError as exc:
            if exc.filename is None or Path(exc.filename).resolve() not in recorded_paths:
                raise
            stale_closure(tid,f"recorded file missing: {exc.filename}")
        except SpecError as exc:
            # An invalid prior closure is stale. Deletion waits until the new
            # selected outputs have built successfully and all inputs recheck.
            stale_closure(tid,exc)
    return kept, groups, records, inputs


def build(paths, source_root, only=None, out=None, previews=None):
    out = Path(out or HERE/"out").resolve()
    previews = Path(previews or HERE/"preview").resolve()
    project = load(paths,source_root,only)
    selected = project.closure(only)
    # Even API callers cannot redirect build products into source/delivery directories.
    root = Path(source_root).resolve()
    protected = set(project.sources.values()) | set(project.paths)
    protected |= set().union(*project.dependencies.values()) if project.dependencies else set()
    for dest in (out,previews):
        if dest==root or root in dest.parents or "готово" in {p.casefold() for p in dest.parts} or any(dest==p or dest in p.parents for p in protected):
            raise SpecError(f"build destination overlaps originals/dependencies/delivery: {dest}")
    previous_outputs=set()
    previous={}
    previous_manifest=out/"manifest.json"
    if previous_manifest.is_file():
        try:
            previous=json.loads(previous_manifest.read_bytes())
            for entry in previous.get("textures",{}).values():
                p=Path(entry["output"]["path"]).resolve()
                if p.parent==out and p.suffix.lower()==".png":
                    previous_outputs.add(p)
        except (ValueError,KeyError,TypeError) as exc:
            raise SpecError(f"existing manifest is invalid; move the generated out directory aside: {exc}") from exc
    unexpected={p.resolve() for p in out.glob("*.png")}-previous_outputs
    if unexpected:
        raise SpecError(f"unmanaged PNGs in output directory; move them aside first: {sorted(map(str,unexpected))}")
    spec_records = project.spec_records
    input_records = {p:record(p) for p in protected-set(project.paths)}
    input_records.update({Path(rec["path"]):rec for rec in spec_records})
    manifest = {"schema":1,"specs":spec_records,"source_root":str(root),"textures":{},"groups":{}}
    kept, kept_groups, kept_specs, kept_inputs = retain_previous(previous_manifest,previous,project,selected,root)
    manifest["textures"].update(kept)
    manifest["groups"].update(kept_groups)
    kept_specs.update({r["path"]:r for r in spec_records})
    manifest["specs"]=[kept_specs[p] for p in sorted(kept_specs)]
    # Current parsed snapshots win; any mid-build edit to those specs must fail.
    input_records={**kept_inputs, **input_records}
    group_cache = {}
    products = {}
    for gid,g in project.groups.items():
        if not any(m["id"] in selected for m in g["member"]):
            continue
        combined = np.zeros((g["space"][1],g["space"][0]),np.uint8)
        cache = []
        for index, op in enumerate(g.get("op",[])):
            if op["type"]=="erase":
                cache.append(None)
            else:
                try:
                    rendered = text.render(op,tuple(g["space"]))
                    fill,asset,warnings = rendered
                except (ValueError,KeyError,TypeError,OSError) as exc:
                    members = ",".join(m["id"] for m in g["member"] if m["id"] in selected)
                    raise SpecError(f"texture {members}/group {gid}/op[{index}]: {exc}") from exc
                if op.get("clip",False):
                    domain = masks.region(tuple(g["space"]),op_geometry(op))
                    a = np.array(fill); a[~domain]=0; fill=Image.fromarray(a)
                    if asset is not None:
                        a=np.array(asset); a[~domain,3]=0; asset=Image.fromarray(a)
                combined = np.maximum(combined,np.asarray(fill))
                rendered.fill,rendered.asset=fill,asset
                cache.append(rendered)
        group_cache[gid] = cache
        layer_path = out/"layers"/(gid+".png")
        products[layer_path] = png_bytes(Image.fromarray(combined))
        manifest["groups"][gid] = {"path":str(layer_path),"sha256":hashlib.sha256(products[layer_path]).hexdigest()}
    for tid in selected:
        source = project.sources[tid]
        with Image.open(source) as im:
            original = im.copy()
        arr = np.array(original)
        rgb = arr[...,:3].astype(float)
        allowed,geometries = allowed_for(project,tid,original.size)
        paints,warnings,memberships = {},[],[]
        for index,op in enumerate(project.textures[tid].get("op",[])):
            try:
                if op["type"]=="erase":
                    rgb,paint = erase.apply(rgb,op,masks.region(original.size,op["region"]))
                    if "id" in op:
                        paints[op["id"]]=paint
                elif op["type"]=="use_group":
                    gid = op["group"]
                    g = project.groups[gid]
                    member = member_for(g,tid)
                    tr = member.get("transform",{})
                    memberships.append({"id":gid,"transform":tr,"use_group":index})
                    local_paints = {}
                    for j,item in enumerate(g.get("op",[])):
                        if item["type"]=="erase":
                            mapped = scaled_erase(item,g["space"],tr,original.size,
                                                  f"texture {tid}/group {gid}/op[{j}]")
                            domain = mapped_region(item["region"],original.size,g["space"],tr)
                            rgb,paint = erase.apply(rgb,mapped,domain)
                            if "id" in item:
                                local_paints[item["id"]]=paint
                        else:
                            rendered = group_cache[gid][j]
                            fill,asset,ww = rendered
                            fill = compose.map_layer(fill,original.size,tr)
                            asset = compose.map_layer(asset,original.size,tr) if asset is not None else None
                            effective = copy.deepcopy(item)
                            if "stroke" in effective:
                                effective["stroke"] *= tr.get("scale",1)
                            if effective.get("shadow"):
                                shadow=effective["shadow"]
                                a,b=compose.map_points([[0,0],[shadow.get("dx",0),shadow.get("dy",0)]],g["space"],tr)
                                shadow["dx"],shadow["dy"]=b[0]-a[0],b[1]-a[1]
                                shadow["blur"]=shadow.get("blur",0)*tr.get("scale",1)
                            effective.update(member.get("style",{}))
                            warnings.extend(ww)
                            rgb = draw(rgb,fill,asset,effective,allowed,local_paints,warnings,
                                       quad_frame=rendered.quad_frame,layout_size=tuple(g["space"]),transform=tr)
                else:
                    rendered = text.render(op,original.size)
                    fill,asset,ww = rendered
                    warnings.extend(ww)
                    rgb = draw(rgb,fill,asset,op,allowed,paints,warnings,quad_frame=rendered.quad_frame)
            except (ValueError,KeyError,TypeError,OSError) as exc:
                raise SpecError(f"texture {tid}/op[{index}]: {exc}") from exc
        result = arr.copy()
        result[...,:3] = np.rint(rgb).astype(np.uint8)
        if np.any(result[~allowed]!=arr[~allowed]):
            raise SpecError(f"texture {tid}: internal error: changed pixels outside allowed area")
        output = Image.fromarray(result)
        output_path = out/source.name
        products[output_path] = png_bytes(output)
        products[previews/(tid+".png")] = png_bytes(preview(original,output,allowed))
        required_specs={project.origins["texture",tid]} | {
            project.origins["group",m["id"]] for m in memberships}
        texture_specs=[r for r in spec_records if r["path"] in required_specs]
        manifest["textures"][tid] = {"id":tid,"specs":texture_specs,"source":record(source),
            "dependencies":[record(p) for p in sorted(project.dependencies[tid])],"groups":memberships,
            "allowed":geometries,"output":{"path":str(output_path),"sha256":hashlib.sha256(products[output_path]).hexdigest()},
            "changed_pixels":int(np.any(result!=arr,axis=2).sum()),"allowed_pixels":int(allowed.sum()),"warnings":sorted(set(warnings))}
    # Do not publish a manifest for mixed generations if an input changed mid-build.
    for p,rec in input_records.items():
        if record(p)!=rec:
            raise SpecError(f"input changed during build: {p}")
    for p,data in products.items():
        atomic_bytes(p,data)
    final_outputs={Path(e["output"]["path"]).resolve() for e in manifest["textures"].values()}
    atomic_bytes(out/"manifest.json",json.dumps(manifest,ensure_ascii=False,indent=2,sort_keys=True).encode("utf-8"))
    stale_files=previous_outputs-final_outputs
    for tid in previous.get("textures",{}).keys()-manifest["textures"].keys():
        if re.fullmatch(r"\d{4}",tid):
            candidate=(previews/(tid+".png")).resolve()
            if candidate.parent==previews:
                stale_files.add(candidate)
    for gid in previous.get("groups",{}).keys()-manifest["groups"].keys():
        if re.fullmatch(r"[A-Za-z0-9_-]+",gid):
            candidate=Path(previous["groups"][gid]["path"]).resolve()
            if candidate==out/"layers"/(gid+".png"):
                stale_files.add(candidate)
    removed=[]
    for stale in sorted(stale_files):
        try:
            stale.unlink()
            removed.append(str(stale))
        except FileNotFoundError:
            pass
        except OSError as exc:
            print(f"Could not remove stale output {stale}: {exc}")
    if removed:
        print("Removed outputs: " + ", ".join(removed))
    return manifest
