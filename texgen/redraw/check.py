"""Independent verification: does not import engine, masks, compose or text.

All files are read once into byte snapshots. Delivery consumes the verified output
snapshots, so a subsequent source/output write cannot change the bytes delivered.
"""
from pathlib import Path
import hashlib
import io
import json
import math
from fractions import Fraction
import tomllib
import numpy as np
from PIL import Image
from .spec import HERE, SpecError, font_path, asset_path


def raster(size, g):
    """Independent scan-line rasteriser at pixel centres, half-open boundaries."""
    w,h = size
    result = np.zeros((h,w),bool)
    if "box" in g:
        l,t,r,b = g["box"]
        x0,x1 = max(0,math.ceil(l-.5)),min(w,math.ceil(r-.5))
        y0,y1 = max(0,math.ceil(t-.5)),min(h,math.ceil(b-.5))
        result[y0:y1,x0:x1] = True
        return result
    points = g["poly"]
    for row in range(h):
        y = row+.5
        cuts = []
        for i,(x0,y0) in enumerate(points):
            x1,y1 = points[(i+1)%len(points)]
            if min(y0,y1)<=y<max(y0,y1):
                cuts.append(x0+(y-y0)*(x1-x0)/(y1-y0))
        cuts.sort()
        for a,b in zip(cuts[::2],cuts[1::2]):
            result[row,max(0,math.ceil(a-.5)):min(w,math.ceil(b-.5))] = True
    return result


def transform_geometry(g, space, t):
    if "box" in g:
        a,b,c,d = g["box"]
        points = [[a,b],[c,b],[c,d],[a,d]]
    else:
        points = g["poly"]
    w,h = space
    mapped = []
    for x,y in points:
        if t.get("mirror",False):
            x=w-x
        rotation=t.get("rot",0)
        if rotation==90:
            x,y=y,w-x
        elif rotation==180:
            x,y=w-x,h-y
        elif rotation==270:
            x,y=h-y,x
        s=t.get("scale",1)
        dx,dy=t.get("offset",[0,0])
        mapped.append([x*s+dx,y*s+dy])
    if "poly" in g:
        return {"poly":mapped}
    return {"box":[min(p[0] for p in mapped),min(p[1] for p in mapped),max(p[0] for p in mapped),max(p[1] for p in mapped)]}


def map_coverage(array, size, t):
    if t.get("mirror",False):
        array = array[:,::-1]
    array = np.rot90(array,t.get("rot",0)//90)
    s=t.get("scale",1)
    if s!=1:
        k=Fraction(str(s)).denominator
        ph,pw=(-array.shape[0])%k,(-array.shape[1])%k
        array=np.pad(array,((0,ph),(0,pw)))
    image=Image.fromarray(array)
    if s!=1:
        image=image.resize((round(image.width*s),round(image.height*s)),Image.Resampling.BOX if s<1 else Image.Resampling.NEAREST)
    result=np.zeros((size[1],size[0]),np.uint8)
    array=np.asarray(image)
    x,y=t.get("offset",[0,0])
    x,y=int(x),int(y)
    l,r=max(0,x),min(size[0],x+image.width)
    top,bottom=max(0,y),min(size[1],y+image.height)
    if r>l and bottom>top:
        result[top:bottom,l:r]=array[top-y:bottom-y,l-x:r-x]
    return result


def region_of(op):
    return op.get("region",{"poly":op["quad"]} if "quad" in op else {"box":op.get("box")})


def closure(textures, groups, ids):
    result=set(ids) if ids else set(textures)
    if result-textures.keys():
        raise SpecError(f"unknown selection {sorted(result-textures.keys())}")
    while True:
        prior=result.copy()
        for group in groups.values():
            members={m["id"] for m in group["member"]}
            if members & result:
                result |= members
        if prior==result:
            return sorted(result)


def verify(manifest_path=None, only=None, *, manifest_data=None):
    manifest_path=Path(manifest_path or HERE/"out"/"manifest.json").resolve()
    try:
        manifest=json.loads(manifest_path.read_bytes()) if manifest_data is None else manifest_data
        if manifest.get("schema")!=1:
            raise SpecError("unsupported manifest schema")
        snapshots={}
        def read_record(rec):
            path=Path(rec["path"]).resolve()
            if path not in snapshots:
                snapshots[path]=path.read_bytes()
            data=snapshots[path]
            if hashlib.sha256(data).hexdigest()!=rec["sha256"]:
                raise SpecError(f"hash changed: {path}")
            return data
        # A merged manifest can contain independent generations/spec sets. Start
        # with recorded membership, then require the parsed specs to confirm it.
        wanted=set(only or manifest["textures"])
        if wanted-manifest["textures"].keys():
            raise SpecError(f"unknown selection {sorted(wanted-manifest['textures'].keys())}")
        while True:
            group_ids={g["id"] for tid in wanted for g in manifest["textures"][tid]["groups"]}
            expanded=wanted | {tid for tid,e in manifest["textures"].items() if group_ids & {g["id"] for g in e["groups"]}}
            if wanted==expanded:
                break
            wanted=expanded
        selected_records={}
        for tid in wanted:
            for rec in manifest["textures"][tid]["specs"]:
                if rec not in manifest["specs"]:
                    raise SpecError(f"{tid}: spec records disagree")
                selected_records[rec["path"]]=rec
        textures,groups,origins={},{},{}
        for rec in selected_records.values():
            data=tomllib.loads(read_record(rec).decode("utf-8-sig"))
            for key,target in (("texture",textures),("group",groups)):
                for item in data.get(key,[]):
                    if item["id"] in target:
                        raise SpecError(f"duplicate {key} id")
                    target[item["id"]]=item
                    origins[key,item["id"]]=rec["path"]
        selected=closure(textures,groups,only or list(manifest["textures"]))
        if set(selected)!=wanted:
            raise SpecError("manifest lacks members of selected group closure; rebuild together")
        outputs={}
        for tid in selected:
            entry=manifest["textures"][tid]
            required_specs={origins["texture",tid]} | {origins["group",op["group"]] for op in textures[tid].get("op",[]) if op["type"]=="use_group"}
            if required_specs!={r["path"] for r in entry["specs"]} or len(entry["specs"])!=len(required_specs) or entry["id"]!=tid:
                raise SpecError(f"{tid}: spec/id records disagree")
            source_path=Path(entry["source"]["path"]).resolve()
            candidates=sorted(p.resolve() for p in Path(manifest["source_root"]).glob(f"*/{tid}_*.png") if p.parent.name!="ГОТОВО")
            if candidates!=[source_path]:
                raise SpecError(f"{tid}: source resolution differs")
            with Image.open(io.BytesIO(read_record(entry["source"]))) as im:
                original=im.copy()
            output_path=Path(entry["output"]["path"]).resolve()
            if output_path!=manifest_path.parent/source_path.name or output_path==source_path:
                raise SpecError(f"{tid}: output must be the manifest-local original filename")
            output_bytes=read_record(entry["output"])
            with Image.open(io.BytesIO(output_bytes)) as im:
                if im.format!="PNG" or im.size!=original.size or im.mode!=original.mode or im.mode not in ("RGB","RGBA"):
                    raise SpecError(f"{tid}: output format/size/mode mismatch")
                result=np.array(im)
            before=np.array(original)
            if original.mode=="RGBA" and not np.array_equal(before[...,3],result[...,3]):
                raise SpecError(f"{tid}: alpha changed")
            allowed=np.zeros(before.shape[:2],bool)
            geometries=[]
            memberships=[]
            dependencies=set()
            canonical_checks=[]
            def dependency(op):
                if op["type"]=="text":
                    dependencies.add(font_path(op["font"]))
                elif op["type"]=="asset":
                    dependencies.add(asset_path(op["path"]))
            for box in textures[tid].get("allow",[]):
                g={"box":box}
                allowed |= raster(original.size,g)
                geometries.append(g)
            for index,op in enumerate(textures[tid].get("op",[])):
                if op["type"]!="use_group":
                    g=region_of(op)
                    allowed |= raster(original.size,g)
                    geometries.append(g)
                    dependency(op)
                    continue
                gid=op["group"]
                group=groups[gid]
                member=next(m for m in group["member"] if m["id"]==tid)
                t=member.get("transform",{})
                memberships.append({"id":gid,"transform":t,"use_group":index})
                for item in group.get("op",[]):
                    g=region_of(item)
                    geometries.append(transform_geometry(g,group["space"],t))
                    allowed |= map_coverage(raster(group["space"],g).astype(np.uint8)*255,original.size,t)>0
                    dependency(item)
                rec=manifest["groups"][gid]
                if Path(rec["path"]).resolve()!=manifest_path.parent/"layers"/(gid+".png"):
                    raise SpecError(f"{gid}: unexpected canonical path")
                with Image.open(io.BytesIO(read_record(rec))) as layer:
                    if layer.mode!="L" or layer.size!=tuple(group["space"]):
                        raise SpecError(f"{gid}: invalid canonical coverage")
                    canonical_checks.append(map_coverage(np.array(layer),original.size,t)>0)
            if geometries!=entry["allowed"] or memberships!=entry["groups"]:
                raise SpecError(f"{tid}: geometry/group records differ from specs")
            if len(entry["dependencies"])!=len(dependencies) or {Path(r["path"]).resolve() for r in entry["dependencies"]}!=dependencies:
                raise SpecError(f"{tid}: dependency records differ from specs")
            for rec in entry["dependencies"]:
                read_record(rec)
            if any(np.any(ink & ~allowed) for ink in canonical_checks):
                raise SpecError(f"{tid}: mapped canonical ink outside allowed area")
            changed=np.any(before!=result,axis=2)
            if np.any(changed & ~allowed):
                raise SpecError(f"{tid}: changed pixels outside allowed area")
            if int(changed.sum())!=entry["changed_pixels"] or int(allowed.sum())!=entry["allowed_pixels"]:
                raise SpecError(f"{tid}: pixel counts differ")
            outputs[tid]=(output_path.name,output_bytes,entry)
        # Recheck all inputs before returning a consistent snapshot of the batch.
        for path,data in snapshots.items():
            if path.read_bytes()!=data:
                raise SpecError(f"file changed during verification: {path}")
        return outputs
    except (ValueError,KeyError,TypeError,AttributeError,StopIteration) as exc:
        if isinstance(exc,SpecError):
            raise
        raise SpecError(f"check failed: {exc}") from exc
