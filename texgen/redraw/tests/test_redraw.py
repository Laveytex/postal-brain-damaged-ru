import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from texgen.redraw import masks, compose, erase, text, spec, engine, check, cli

FONT = Path("C:/Windows/Fonts/arial.ttf")
REPO = Path(__file__).resolve().parents[3]


def toml(value):
    if isinstance(value,dict):
        return "{ " + ", ".join(f"{k} = {toml(v)}" for k,v in value.items()) + " }"
    if isinstance(value,list):
        return "[" + ", ".join(toml(v) for v in value) + "]"
    if isinstance(value,bool):
        return str(value).lower()
    return json.dumps(value,ensure_ascii=False)


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="redraw-tests-")
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.source=self.root/"исходники с пробелом"
        (self.source/"1_Основное").mkdir(parents=True)
        self.out=self.root/"out"
        self.preview=self.root/"preview"
        self.path=self.root/"тест.toml"
        self.data={"texture":[],"group":[]}

    def source_image(self,tid,size=(64,64),mode="RGBA",colour=None):
        rng=np.random.default_rng(int(tid))
        a=rng.integers(20,220,(size[1],size[0],len(mode)),dtype=np.uint8)
        if colour is not None:
            a[...,:3]=colour
        p=self.source/"1_Основное"/(tid+"_текстура.png")
        Image.fromarray(a).save(p)
        self.data["texture"].append({"id":tid,"op":[]})
        return a,p

    def write_spec(self):
        self.path.write_text("\n".join(f"{k} = {toml(v)}" for k,v in self.data.items()),encoding="utf-8")

    def build(self,only=None):
        self.write_spec()
        return engine.build([self.path],self.source,only,self.out,self.preview)

    def verify(self,only=None):
        return check.verify(self.out/"manifest.json",only)

    def delivery(self,ids=None,replace=False):
        return cli.deliver(self.root/"ГОТОВО",ids,replace,self.out/"manifest.json",self.root/"delivery.jsonl")

    def flat(self,box,colour):
        return {"type":"erase","region":{"box":box},"method":"flat","colour":colour}

    def text_op(self,**kw):
        return {"type":"text","text":"Ёж №«Я»","font":str(FONT),"box":[8,8,56,48],"fit":"fill_box","colour":[255,10,20],**kw}

    def pair(self):
        for tid in ("0001","0002"):
            self.source_image(tid)
            self.data["texture"][-1]["op"]=[{"type":"use_group","group":"pair"}]
        self.data["group"]=[{"id":"pair","space":[64,64],"member":[{"id":"0001"},{"id":"0002"}],"op":[self.text_op()]}]


class Invariants(Workspace):
    def test_random_regions_preserve_outside_alpha_size_mode(self):
        for mode,tid in (("RGB","0001"),("RGBA","0002")):
            original,path=self.source_image(tid,mode=mode)
            rng=np.random.default_rng(40)
            ops=[]
            for _ in range(8):
                x,y=map(int,rng.integers(5,40,2))
                ops.append(self.flat([x,y,x+12,y+9],rng.integers(0,256,3).tolist()))
            ops.append({"type":"erase","method":"pullpush","region":{"poly":[[5,6],[31,11],[17,37]]},"mask":{"kind":"saturation","min":30,"grow":1}})
            self.data["texture"][-1]["op"]=ops
        manifest=self.build()
        self.verify()
        for tid,entry in manifest["textures"].items():
            with Image.open(entry["source"]["path"]) as a,Image.open(entry["output"]["path"]) as b:
                self.assertEqual(a.size,b.size); self.assertEqual(a.mode,b.mode)
                before,after=np.array(a),np.array(b)
            allowed=np.zeros(before.shape[:2],bool)
            for g in entry["allowed"]:
                allowed |= check.raster((64,64),g)
            np.testing.assert_array_equal(before[~allowed],after[~allowed])
            if before.shape[2]==4:
                np.testing.assert_array_equal(before[...,3],after[...,3])

    def test_untint_recovers_grey_noise(self):
        rng=np.random.default_rng(5)
        bg=np.repeat(rng.uniform(120,150,(80,120,1)),3,axis=2)
        domain=masks.region((120,80),{"box":[25,20,95,60]})
        opacity=np.zeros((80,120)); opacity[domain]=rng.uniform(.3,1,domain.sum())
        ratio=np.array([.35,.7,.9])
        painted=bg*(1+opacity[...,None]*(ratio-1))
        restored,paint=erase.apply(painted,{"method":"untint","mask":{"kind":"saturation","min":10},"core":{"kind":"saturation","min":60}},domain)
        self.assertLessEqual(np.mean(np.abs(restored[domain]-bg[domain])),3)
        self.assertIn("ratio",paint)

    def test_untint_rejects_underdetermined_colour(self):
        rgb=np.full((32,32,3),120.)
        domain=masks.region((32,32),{"box":[8,8,24,24]})
        rgb[domain]=50
        with self.assertRaisesRegex(ValueError,"underdetermined"):
            erase.apply(rgb,{"method":"untint"},domain)

    def test_mask_boolean_near_components(self):
        rgb=np.full((20,20,3),200,dtype=np.uint8); rgb[9:11,9:11]=[200,0,0]
        red={"kind":"channel_dominance","channel":"r","ratio":1.6,"min":100}
        near=masks.select(rgb,{"kind":"near","of":red,"radius":3})
        self.assertGreater(near.sum(),4)
        both=masks.select(rgb,{"kind":"all","of":[red,{"kind":"saturation","min":150}]})
        self.assertEqual(both.sum(),4)
        self.assertEqual(masks.components(rgb,both)[0]["box"],[9,9,11,11])
        self.assertFalse(masks.select(rgb,{**red,"min_size":5}).any())
        self.assertFalse(masks.select(np.zeros_like(rgb),{"kind":"near","of":red,"radius":3}).any())

    def test_clone_and_regrain_are_deterministic(self):
        rng=np.random.default_rng(7); rgb=rng.uniform(30,210,(80,80,3))
        domain=masks.region((80,80),{"box":[20,20,40,40]})
        clone,_=erase.apply(rgb,{"method":"clone","offset":[10,10]},domain)
        np.testing.assert_array_equal(clone[20:40,20:40],rgb[30:50,30:50])
        op={"method":"pullpush","grain":{"ref":[0,0,10,10],"sigma":2,"gain":1,"seed":12}}
        a,_=erase.apply(rgb,op,domain); b,_=erase.apply(rgb,op,domain)
        np.testing.assert_array_equal(a,b)
        self.assertFalse(np.array_equal(a[20:30,20:30],a[30:40,30:40]))

    def test_op_order_and_determinism(self):
        self.source_image("0001",colour=[40,40,40])
        self.data["texture"][0]["op"]=[self.flat([8,8,56,48],[0,0,0]),self.text_op(),self.flat([8,8,56,48],[5,6,7])]
        first=self.build()
        with Image.open(first["textures"]["0001"]["output"]["path"]) as im:
            np.testing.assert_array_equal(np.array(im)[8:48,8:56,:3],np.broadcast_to([5,6,7],(40,48,3)))
        before=(self.out/"manifest.json").read_bytes()
        second=self.build()
        self.assertEqual(first,second); self.assertEqual(before,(self.out/"manifest.json").read_bytes())


class Lettering(Workspace):
    def test_fill_box_rotation_and_mirror(self):
        for rot in (0,270):
            op=self.text_op(rot=rot,box=[12,16,72,94])
            fill,_,_=text.render(op,(100,120))
            actual=fill.getbbox()
            for a,b in zip(actual,op["box"]):
                self.assertLessEqual(abs(a-b),1)
        normal,_,_=text.render(self.text_op(text="AB",box=[10,10,90,70]),(100,80))
        mirrored,_,_=text.render(self.text_op(text="AB",box=[10,10,90,70],mirror=True),(100,80))
        np.testing.assert_array_equal(np.array(normal)[:,::-1],np.array(mirrored))
        rotated,_,_=text.render(self.text_op(text="AB",box=[10,10,70,90],rot=270),(80,100))
        np.testing.assert_array_equal(np.rot90(np.array(normal),3),np.array(rotated))

    def test_multiline_fit_uses_available_ink_height(self):
        op=self.text_op(text="Кнопка\n«Иди на хрен»",box=[64,240,904,741],fit="fit",sx_min=.72,spacing=.88)
        fill,_,warnings=text.render(op,(1024,1024))
        l,t,r,b=fill.getbbox()
        self.assertLessEqual(r-l,840); self.assertLessEqual(b-t,501)
        self.assertTrue(r-l>=830 or b-t>=490)

    def test_asset_crop_key_recolour_premultiplied(self):
        a=np.full((20,40,4),255,np.uint8); a[4:16,24:36]=[240,30,10,255]
        asset=self.root/"sheet.png"; Image.fromarray(a).save(asset)
        op={"type":"asset","path":str(asset),"crop":[20,0,40,20],"box":[10,10,50,50],"fit":"fill_box","key":{"colour":[255,255,255],"softness":80},"recolour":{"colour":[0,180,60]}}
        fill,layer,_=text.render(op,(64,64))
        self.assertEqual(fill.getbbox(),(10,10,50,50))
        rgb=np.array(layer); self.assertTrue(np.all(rgb[rgb[...,3]>0,:3]==[0,180,60]))

    def test_quad_angle_stroke_shadow_blends(self):
        op=self.text_op(box=[20,20,80,70],angle=17,stroke=1,shadow={"dx":2,"dy":2,"blur":1})
        fill,_,_=text.render(op,(100,100))
        layer=compose.styled(fill,op,[100,140,180])
        self.assertTrue(layer.getchannel("A").getbbox())
        for mode in ("normal","multiply","tint"):
            result=compose.blend(np.full((100,100,3),100.),layer,{"blend":mode,"modulate":True},{"ratio":[.5,1,1.5]})
            self.assertTrue(np.isfinite(result).all())
        quad=self.text_op(box=[20,20,80,70],quad=[[20,20],[80,25],[75,75],[25,70]])
        del quad["box"]
        fill,_,_=text.render(quad,(100,100))
        self.assertTrue(fill.getbbox())

    def test_fill_box_final_stroke_and_shadow_bounds(self):
        for rot in (0,270):
            op=self.text_op(box=[20,20,100,110],rot=rot,stroke=2,shadow={"dx":4,"dy":-2,"blur":1})
            fill,_,_=text.render(op,(128,128))
            layer=compose.styled(fill,op,[255,255,255])
            for actual,expected in zip(layer.getchannel("A").getbbox(),op["box"]):
                self.assertLessEqual(abs(actual-expected),1)


class Groups(Workspace):
    def test_eighth_scale_and_transposes(self):
        canonical=Image.new("L",(1024,1024))
        a=np.array(canonical); a[240:741,64:904]=np.random.default_rng(9).integers(0,256,(501,840),dtype=np.uint8)
        canonical=Image.fromarray(a)
        actual=compose.map_layer(canonical,(128,128),{"scale":.125})
        expected=canonical.resize((128,128),Image.Resampling.BOX)
        np.testing.assert_array_equal(np.array(actual),np.array(expected))
        for tr in ({"rot":90},{"mirror":True},{"rot":270,"mirror":True}):
            result=np.array(compose.map_layer(canonical,canonical.size,tr))
            expected=np.rot90(a[:,::-1] if tr.get("mirror") else a,tr.get("rot",0)//90)
            np.testing.assert_array_equal(result,expected)
            np.testing.assert_array_equal(result,check.map_coverage(a,canonical.size,tr))

    def test_group_geometry_independent_reconstruction(self):
        self.pair()
        g=self.data["group"][0]
        g["member"][0]["transform"]={"rot":90}
        g["member"][1]["transform"]={"mirror":True}
        self.build(); self.verify()
        geo={"box":[8,8,56,48]}
        for m in g["member"]:
            self.assertEqual(compose.map_geometry(geo,g["space"],m["transform"]),check.transform_geometry(geo,g["space"],m["transform"]))

    def test_shared_atlas_closure_order_validation(self):
        for tid in ("0001","0002","0003"):
            self.source_image(tid,colour=[1,2,3])
        self.data["group"]=[
            {"id":"a","space":[64,64],"member":[{"id":"0001"},{"id":"0002"}],"op":[self.flat([10,10,40,40],[100,0,0])]},
            {"id":"b","space":[64,64],"member":[{"id":"0001"},{"id":"0003"}],"op":[self.flat([20,20,50,50],[0,0,200])]}
        ]
        self.data["texture"][0]["op"]=[{"type":"use_group","group":"a"},self.flat([15,15,45,45],[0,100,0]),{"type":"use_group","group":"b"}]
        self.data["texture"][1]["op"]=[{"type":"use_group","group":"a"}]
        self.data["texture"][2]["op"]=[{"type":"use_group","group":"b"}]
        manifest=self.build(["0002"])
        self.assertEqual(set(manifest["textures"]),{"0001","0002","0003"})
        self.assertEqual(set(self.verify(["0002"])),{"0001","0002","0003"})
        with Image.open(manifest["textures"]["0001"]["output"]["path"]) as im:
            a=np.array(im)
        np.testing.assert_array_equal(a[12,12,:3],[100,0,0]); np.testing.assert_array_equal(a[18,18,:3],[0,100,0]); np.testing.assert_array_equal(a[30,30,:3],[0,0,200])
        original=copy.deepcopy(self.data)
        for ops in ([],[{"type":"use_group","group":"a"}]*2):
            self.data=copy.deepcopy(original); self.data["texture"][1]["op"]=ops
            with self.assertRaisesRegex(spec.SpecError,"0002.*exactly one"):
                self.build()

    def test_shared_coverage_rendered_once_with_member_styles(self):
        self.pair()
        self.data["texture"][0]["allow"]=[[4,4,60,52]]
        self.data["texture"][1]["allow"]=[[4,4,60,52]]
        self.data["group"][0]["member"][1]["style"]={"colour":[0,255,0],"stroke":1}
        with patch("texgen.redraw.engine.text.render",wraps=text.render) as render:
            self.build()
            self.assertEqual(render.call_count,1)
        self.verify()


class Tampering(Workspace):
    def setUp(self):
        super().setUp()
        self.original,self.source_path=self.source_image("0001")
        self.data["texture"][0]["op"]=[self.text_op()]

    def rewrite_output_hash(self):
        path=self.out/"manifest.json"
        manifest=json.loads(path.read_text(encoding="utf-8"))
        output=manifest["textures"]["0001"]["output"]
        output["sha256"]=spec.sha(output["path"])
        path.write_text(json.dumps(manifest),encoding="utf-8")

    def test_changed_output_alpha_size_and_outside_independently(self):
        for damage in ("outside","alpha","size","mode","hash"):
            with self.subTest(damage=damage):
                entry=self.build()["textures"]["0001"]
                path=Path(entry["output"]["path"])
                with Image.open(path) as im:
                    im=im.copy()
                a=np.array(im)
                if damage=="size": im=im.resize((65,64))
                elif damage=="mode": im=im.convert("RGB")
                else:
                    a[0,0,3 if damage=="alpha" else 0]^=255
                    im=Image.fromarray(a)
                im.save(path)
                if damage!="hash": self.rewrite_output_hash()
                with self.assertRaises(spec.SpecError): self.verify()

    def test_spec_and_source_changes_fail(self):
        self.build(); self.path.write_text(self.path.read_text(encoding="utf-8")+"\n# changed",encoding="utf-8")
        with self.assertRaisesRegex(spec.SpecError,"hash changed"): self.verify()
        self.build(); a=self.original.copy(); a[20,20,0]^=255; Image.fromarray(a).save(self.source_path)
        with self.assertRaisesRegex(spec.SpecError,"hash changed"): self.verify()

    def test_dependencies_changed_missing_or_omitted(self):
        font=self.root/"copied.ttf"; shutil.copyfile(FONT,font)
        asset=self.root/"lettering.png"; Image.new("RGBA",(8,8),(20,40,60,255)).save(asset)
        self.data["texture"][0]["op"]=[self.text_op(font=str(font)),{"type":"asset","path":str(asset),"box":[10,10,20,20]}]
        for dep in (font,asset):
            for missing in (False,True):
                with self.subTest(dep=dep.name,missing=missing):
                    content=dep.read_bytes(); self.build()
                    dep.unlink() if missing else dep.write_bytes(content+b"changed")
                    with self.assertRaises(spec.SpecError): self.verify()
                    dep.write_bytes(content)
        self.build(); path=self.out/"manifest.json"; m=json.loads(path.read_text(encoding="utf-8")); m["textures"]["0001"]["dependencies"]=[]; path.write_text(json.dumps(m),encoding="utf-8")
        with self.assertRaisesRegex(spec.SpecError,"dependency records"): self.verify()

    def test_check_cli_nonzero_after_tampering(self):
        self.build()
        with patch.object(check,"HERE",self.root):
            self.assertEqual(cli.main(["check"]),0)
            self.path.write_text("invalid",encoding="utf-8")
            self.assertEqual(cli.main(["check"]),1)


class Delivery(Workspace):
    def test_conflict_preflight_replace_skip_closure_and_fresh_check(self):
        self.pair(); manifest=self.build()
        dest=self.root/"ГОТОВО"; dest.mkdir()
        name=Path(manifest["textures"]["0002"]["output"]["path"]).name
        (dest/name).write_bytes(b"different")
        with self.assertRaisesRegex(spec.SpecError,"--replace"): self.delivery(["0001"])
        self.assertEqual([p.name for p in dest.iterdir()],[name])
        self.assertEqual(self.delivery(["0001"],True)["copied"],2)
        self.assertEqual(self.delivery(["0001"])["skipped"],2)
        self.verify()
        path=Path(manifest["textures"]["0001"]["output"]["path"]); path.write_bytes(path.read_bytes()+b"tamper")
        with self.assertRaises(spec.SpecError): self.delivery(["0001"],True)

    def test_originals_cannot_be_delivery_or_build_targets(self):
        self.pair(); self.build()
        with self.assertRaisesRegex(spec.SpecError,"original"):
            cli.deliver(self.source/"1_Основное",manifest=self.out/"manifest.json",replace=True)
        with self.assertRaises(spec.SpecError):
            engine.build([self.path],self.source,out=self.source/"ГОТОВО")

    def test_deliver_copies_verified_snapshot(self):
        self.pair(); manifest=self.build()
        (self.root/"ГОТОВО").mkdir()
        original_verify=check.verify
        def race(*args, **kwargs):
            snapshot=original_verify(*args, **kwargs)
            p=Path(manifest["textures"]["0001"]["output"]["path"])
            p.write_bytes(b"changed after check")
            return snapshot
        with patch.object(check,"verify",side_effect=race):
            self.delivery(["0001"])
        path=self.root/"ГОТОВО"/"0001_текстура.png"
        self.assertEqual(spec.sha(path),manifest["textures"]["0001"]["output"]["sha256"])


class Validation(Workspace):
    def test_clear_validation_errors(self):
        self.source_image("0001")
        cases=[self.text_op(unknown=3),self.text_op(font="missing.ttf"),self.text_op(box=[0,0,70,70]),self.text_op(paint_from="later")]
        for op in cases:
            self.data["texture"][0]["op"]=[op]
            with self.subTest(op=op),self.assertRaisesRegex(spec.SpecError,"0001.*op"):
                self.build()
        self.data["texture"][0]["op"]=[self.text_op(paint_from="later"),{**self.flat([0,0,20,20],[0,0,0]),"id":"later"}]
        with self.assertRaisesRegex(spec.SpecError,"EARLIER"): self.build()

    def test_ink_outside_allowed_requires_explicit_clip(self):
        self.source_image("0001")
        op=self.text_op(stroke=5,region={"box":[20,20,40,40]})
        self.data["texture"][0]["op"]=[op]
        with self.assertRaisesRegex(spec.SpecError,"ink outside"): self.build()
        op["clip"]=True; self.build(); self.verify()

    def test_rasterizers_agree_for_fractional_polygons_and_boxes(self):
        for g in ({"box":[3.5,5.5,21.5,29.5]},{"poly":[[3.5,4],[25,8.5],[28,25],[12,20]]}):
            np.testing.assert_array_equal(masks.region((32,32),g),check.raster((32,32),g))

    def test_launcher_help_and_fonts(self):
        for cmd in ("--help","fonts"):
            run=subprocess.run([sys.executable,str(REPO/"texgen"/"redraw.py"),cmd],cwd=REPO,capture_output=True,encoding="utf-8")
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertTrue(run.stdout)
        self.assertTrue(cli.fonts(),"Windows system fonts with Cyrillic required")


class AssetIntegration(Workspace):
    """End-to-end asset coverage also exercises the font-independent code path."""
    def setUp(self):
        super().setUp()
        self.asset=self.root/"asymmetric lettering.png"
        a=np.zeros((40,48,4),np.uint8)
        a[2:38,4:12]=[200,40,30,255]
        a[2:10,4:42]=[200,40,30,255]
        a[20:28,4:34]=[200,40,30,180]
        Image.fromarray(a).save(self.asset)
        for tid,size,scale in (("0001",(64,64),1),("0002",(32,32),.5)):
            self.source_image(tid,size)
            self.data["texture"][-1]["op"]=[{"type":"use_group","group":"letters"}]
        self.data["group"]=[{"id":"letters","space":[64,64],
            "member":[{"id":"0001"},{"id":"0002","transform":{"scale":.5}}],
            "op":[{"type":"asset","path":str(self.asset),"box":[8,8,56,48],"fit":"fill_box"}]}]

    def test_asset_group_build_check_determinism(self):
        one=self.build(["0002"])
        self.assertEqual(set(self.verify(["0002"])),{"0001","0002"})
        two=self.build(["0001"])
        self.assertEqual(one,two)

    def test_asset_delivery_conflict_and_verified_snapshot(self):
        manifest=self.build(); self.verify()
        dest=self.root/"ГОТОВО"; dest.mkdir()
        other=dest/"0002_текстура.png"; other.write_bytes(b"different")
        with self.assertRaisesRegex(spec.SpecError,"--replace"):
            self.delivery(["0001"])
        self.assertFalse((dest/"0001_текстура.png").exists())
        self.assertEqual(self.delivery(["0002"],True)["copied"],2)
        self.assertEqual(self.delivery(["0001"])["skipped"],2)
        out=Path(manifest["textures"]["0001"]["output"]["path"])
        out.write_bytes(out.read_bytes()+b"tampered after check")
        with self.assertRaises(spec.SpecError): self.delivery(["0001"],True)

    def test_asset_checker_detects_dependency_source_and_canonical_tampering(self):
        for kind in ("asset_changed","asset_missing","source","canonical","spec"):
            with self.subTest(kind=kind):
                manifest=self.build()
                path=self.asset if kind.startswith("asset") else self.source/"1_Основное"/"0001_текстура.png" if kind=="source" else self.out/"layers"/"letters.png" if kind=="canonical" else self.path
                data=path.read_bytes()
                if kind.endswith("missing"): path.unlink()
                else: path.write_bytes(data+b"changed")
                with self.assertRaises(spec.SpecError): self.verify()
                path.write_bytes(data)

    def test_asset_checker_does_not_trust_output_hash_or_geometry(self):
        for damage in ("outside","alpha","size","geometry"):
            with self.subTest(damage=damage):
                manifest=self.build()
                entry=manifest["textures"]["0001"]
                path=Path(entry["output"]["path"])
                if damage=="geometry":
                    entry["allowed"]=[{"box":[0,0,64,64]}]
                else:
                    with Image.open(path) as im: im=im.copy()
                    if damage=="size": im=im.resize((65,64))
                    else:
                        a=np.array(im); a[0,0,3 if damage=="alpha" else 0]^=255; im=Image.fromarray(a)
                    im.save(path)
                    entry["output"]["sha256"]=spec.sha(path)
                (self.out/"manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
                with self.assertRaises(spec.SpecError): self.verify()


if __name__=="__main__":
    unittest.main()
