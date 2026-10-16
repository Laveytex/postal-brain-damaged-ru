"""Local command-line interface and explicit, preflighted delivery."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from PIL import Image, ImageDraw
import numpy as np
from .spec import HERE, REPO, FONT_DIRS, SpecError
from . import masks


def deliver(destination=None, ids=None, replace=False, manifest=None, log=None):
    from .check import verify
    from .engine import atomic_bytes
    manifest=Path(manifest or HERE/"out"/"manifest.json")
    try:
        metadata=json.loads(manifest.read_bytes())
        source=Path(metadata["source_root"]).resolve()
    except (ValueError,KeyError,TypeError) as exc:
        raise SpecError(f"invalid delivery manifest {manifest}: {exc}") from exc
    destination=Path(destination).resolve() if destination is not None else source/"ГОТОВО"
    if ((destination==source or source in destination.parents) and destination!=source/"ГОТОВО") or destination==manifest.resolve().parent or destination==(HERE/"out").resolve():
        raise SpecError(f"refusing delivery into original source/build directory: {destination}")
    if not source.is_dir() or not destination.is_dir():
        raise SpecError(f"Source root and delivery folder must already exist: {source}; {destination}. "
                        "Check --tools-root / PBD_RU_TOOLS when building, or specify an existing --deliver-root.")
    outputs=verify(manifest,ids,manifest_data=metadata)
    pending=[]
    # Resolve every destination and conflict before creating even the first temp file.
    for tid,(name,data,entry) in outputs.items():
        path=(destination/name).resolve()
        if path.parent!=destination or path==Path(entry["source"]["path"]).resolve():
            raise SpecError(f"refusing delivery over an original: {path}")
        if path.exists():
            if path.read_bytes()==data:
                continue
            if not replace:
                raise SpecError(f"destination differs: {path}; use --replace")
        pending.append((tid,path,data,entry))
    # Recheck conflicts immediately before writing the batch.
    for tid,path,data,entry in pending:
        if path.exists() and path.read_bytes()!=data and not replace:
            raise SpecError(f"destination changed during preflight: {path}")
    for tid,path,data,entry in pending:
        atomic_bytes(path,data,create_parent=False)
        event={"time":datetime.now(timezone.utc).isoformat(),"id":tid,
               "source_sha256":entry["source"]["sha256"],"specs":entry["specs"],"output_sha256":entry["output"]["sha256"]}
        log_path=Path(log or HERE/"deliver-log.jsonl")
        log_path.parent.mkdir(parents=True,exist_ok=True)
        with log_path.open("a",encoding="utf-8",newline="\n") as stream:
            stream.write(json.dumps(event,ensure_ascii=False,sort_keys=True)+"\n")
    return {"selected":len(outputs),"copied":len(pending),"skipped":len(outputs)-len(pending)}


def fonts():
    from fontTools.ttLib import TTFont, TTLibError
    required=set(map(ord,"АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя№«»—"))
    seen=set()
    result=[]
    for folder in FONT_DIRS:
        for path in sorted(folder.glob("*")):
            if path.suffix.lower() not in (".ttf",".otf") or path.name.lower() in seen:
                continue
            seen.add(path.name.lower())
            try:
                with TTFont(path) as font:
                    if not required.issubset(font.getBestCmap() or {}):
                        continue
                    entry={"path":str(path),"axes":[],"instances":[]}
                    if "fvar" in font:
                        entry["axes"]=[{"tag":a.axisTag,"min":a.minValue,"default":a.defaultValue,"max":a.maxValue} for a in font["fvar"].axes]
                        entry["instances"]=[font["name"].getDebugName(i.subfamilyNameID) for i in font["fvar"].instances]
                    result.append(entry)
            except (OSError,ValueError,KeyError,TTLibError):
                continue
    return result


def parser():
    p=argparse.ArgumentParser(description="Deterministic, spec-driven Russian texture lettering")
    roots=argparse.ArgumentParser(add_help=False)
    for name in ("tools-root","source-root","deliver-root"):
        roots.add_argument("--"+name,default=argparse.SUPPRESS)
        p.add_argument("--"+name,default=argparse.SUPPRESS)
    subs=p.add_subparsers(dest="command",required=True)
    b=subs.add_parser("build",parents=[roots]); b.add_argument("specs",nargs="+"); b.add_argument("--only",nargs="+")
    c=subs.add_parser("check",parents=[roots]); c.add_argument("--only",nargs="+")
    d=subs.add_parser("deliver",parents=[roots]); d.add_argument("ids",nargs="*"); d.add_argument("--all",action="store_true"); d.add_argument("--replace",action="store_true")
    v=subs.add_parser("view"); v.add_argument("png"); v.add_argument("box",nargs="?",help="x0,y0,x1,y1"); v.add_argument("scale",nargs="?",type=int,default=4)
    q=subs.add_parser("probe",parents=[roots]); q.add_argument("target"); q.add_argument("--kind",default="saturation",choices=["all","saturation","luminance","colour","channel_dominance"])
    for flag in ("min","max","tol","ratio"):
        q.add_argument("--"+flag,type=float)
    q.add_argument("--rgb",type=int,nargs=3); q.add_argument("--channel",choices=["r","g","b"])
    q.add_argument("--grow",type=int); q.add_argument("--min-size",type=int)
    subs.add_parser("fonts")
    return p


def main(argv=None):
    p=parser()
    args=p.parse_args(argv)
    tools=Path(getattr(args,"tools_root",None) or os.environ.get("PBD_RU_TOOLS") or REPO.parent)
    source=Path(getattr(args,"source_root",None) or tools/"Текстуры_для_перевода")
    destination=getattr(args,"deliver_root",None)
    try:
        if args.command=="build":
            from .engine import build
            result=build(args.specs,source,args.only)
            for tid,entry in result["textures"].items():
                print(f"{tid}: changed={entry['changed_pixels']} allowed={entry['allowed_pixels']} warnings={entry['warnings']}")
        elif args.command=="check":
            from .check import verify
            result=verify(only=args.only)
            print(f"check OK: {len(result)} textures")
        elif args.command=="deliver":
            if bool(args.ids)==bool(args.all):
                p.error("deliver requires ID… OR --all")
            print(json.dumps(deliver(destination,args.ids or None,args.replace),ensure_ascii=False))
        elif args.command=="fonts":
            print(json.dumps(fonts(),ensure_ascii=False,indent=2))
        elif args.command=="view":
            with Image.open(args.png) as im:
                box=tuple(map(int,args.box.split(","))) if args.box else (0,0,*im.size)
                image=im.convert("RGB").crop(box)
            if args.scale<1:
                raise SpecError("scale must be positive")
            image=image.resize((image.width*args.scale,image.height*args.scale),Image.Resampling.NEAREST)
            canvas=ImageDraw.Draw(image)
            step=max(1,32//args.scale)
            for x in range(0,image.width,step*args.scale):
                canvas.line((x,0,x,image.height),fill=(80,160,200)); canvas.text((x+2,2),str(box[0]+x//args.scale),fill="white")
            for y in range(0,image.height,step*args.scale):
                canvas.line((0,y,image.width,y),fill=(80,160,200)); canvas.text((2,y+10),str(box[1]+y//args.scale),fill="white")
            path=HERE/"preview"/"view.png"
            path.parent.mkdir(parents=True,exist_ok=True); image.save(path)
            print(path)
        elif args.command=="probe":
            path=Path(args.target)
            if not path.is_file():
                candidates=[p for p in source.glob(f"*/{args.target}_*.png") if p.parent.name!="ГОТОВО"]
                if len(candidates)!=1:
                    raise SpecError(f"cannot resolve {args.target}; set --source-root, --tools-root or PBD_RU_TOOLS")
                path=candidates[0]
            spec={k:getattr(args,k) for k in ("kind","min","max","tol","ratio","rgb","channel","grow","min_size") if getattr(args,k) is not None}
            from .spec import mask
            mask(spec,"probe")
            with Image.open(path) as im:
                rgb=np.array(im.convert("RGB"))
            print(json.dumps(masks.components(rgb,masks.select(rgb,spec)),ensure_ascii=False,indent=2))
        return 0
    except (SpecError,OSError,ValueError,KeyError,TypeError) as exc:
        print(f"error: {exc}",file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
