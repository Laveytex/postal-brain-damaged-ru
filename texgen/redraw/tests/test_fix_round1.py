"""Regression coverage for the host's F2–F9 dispositions."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from texgen.redraw import check, cli, compose, engine, erase, masks, spec, text
from texgen.redraw.tests.test_redraw import Workspace, toml


class FixRound1(Workspace):
    def asset_op(self, **extra):
        path=self.root/"lettering.png"
        if not path.exists():
            Image.new("RGBA",(40,8),(220,40,20,255)).save(path)
        return {"type":"asset","path":str(path),"box":[8,8,56,48],**extra}

    def painted_source(self):
        original,path=self.source_image("0001",mode="RGB",colour=[140,140,140])
        domain=masks.region((64,64),{"box":[8,8,56,48]})
        rng=np.random.default_rng(17)
        alpha=rng.uniform(.4,.95,(domain.sum(),1))
        original[domain]=np.rint(140*(1+alpha*(np.array([.3,.6,.9])-1)))
        Image.fromarray(original).save(path)
        op={"type":"erase","id":"paint","method":"untint","region":{"box":[8,8,56,48]},
            "mask":{"kind":"all"},"core":{"kind":"all"},"paint":{"stroke_colour":15}}
        return original,domain,op

    def test_f2_untint_preserves_quantiles_and_colour_override(self):
        original,domain,op=self.painted_source()
        sample=original[domain].astype(float)
        lum=sample.mean(axis=1)
        stroke=np.median(sample[lum<=np.percentile(lum,15)],axis=0)
        _,paint=erase.apply(original.astype(float),op,domain)
        np.testing.assert_array_equal(paint["stroke_colour"],stroke)
        self.assertIn("ratio",paint)
        op["paint"]["colour"]=70
        expected=np.median(sample[lum>=np.percentile(lum,70)],axis=0)
        _,paint=erase.apply(original.astype(float),op,domain)
        np.testing.assert_array_equal(paint["colour"],expected)
        np.testing.assert_array_equal(paint["stroke_colour"],stroke)
        self.assertIn("ratio",paint)

    def test_f2_untint_text_build_uses_sampled_auto_stroke(self):
        original,domain,op=self.painted_source()
        sample=original[domain].astype(float)
        expected=np.rint(np.median(sample[sample.mean(axis=1)<=np.percentile(sample.mean(axis=1),15)],axis=0)).astype(int).tolist()
        self.data["texture"][0]["op"]=[op,self.text_op(box=[12,12,52,44],text="Я",stroke=2,
            stroke_colour="auto",colour="auto",paint_from="paint")]
        with patch.object(engine,"styled_layer",wraps=engine.styled_layer) as styled:
            manifest=self.build()
        self.assertEqual(styled.call_args.args[2]["stroke_colour"],expected)
        with Image.open(manifest["textures"]["0001"]["output"]["path"]) as im:
            self.assertTrue(np.any(np.all(np.array(im)==expected,axis=2)))
        self.verify()

    def test_f3_fit_preserves_aspect_in_square_quad(self):
        for op in (self.asset_op(),self.text_op(text="WWWWWW")):
            op.update(fit="fit",box=[8,8,56,56])
            rectangular,_,_=text.render(op,(64,64))
            quad={k:v for k,v in op.items() if k!="box"}
            quad["quad"]=[[8,8],[56,8],[56,56],[8,56]]
            perspective,_,_=text.render(quad,(64,64))
            a,b=rectangular.getbbox(),perspective.getbbox()
            ratio_a=(a[2]-a[0])/(a[3]-a[1])
            ratio_b=(b[2]-b[0])/(b[3]-b[1])
            self.assertAlmostEqual(ratio_a,ratio_b,delta=.15)
            self.assertGreater(ratio_b,2)

    def test_f3_quad_stroke_shadow_stay_inside_allowed_area(self):
        self.source_image("0001")
        for quad in ([[8,8],[56,8],[56,56],[8,56]],[[8,12],[56,8],[51,56],[13,52]]):
            op=self.asset_op(fit="fill_box",stroke=2,shadow={"dx":1,"dy":1,"blur":1})
            del op["box"]
            op["quad"]=quad
            self.data["texture"][0]["op"]=[op]
            self.build()
            self.verify()

    def test_f3_group_quad_preserves_shared_frame_and_member_transform(self):
        self.source_image("0001")
        self.source_image("0002",(32,32))
        op=self.asset_op(fit="fill_box",stroke=2,shadow={"dx":1,"dy":1,"blur":1})
        del op["box"]
        op["quad"]=[[8,12],[56,8],[51,56],[13,52]]
        for texture in self.data["texture"]:
            texture["op"]=[{"type":"use_group","group":"quad"}]
        self.data["group"]=[{"id":"quad","space":[64,64],"op":[op],"member":[
            {"id":"0001","transform":{"rot":90}},
            {"id":"0002","transform":{"scale":.5,"mirror":True},"style":{"colour":[10,120,30],"stroke":.5}}]}]
        with patch.object(text,"render",wraps=text.render) as render:
            self.build()
        self.assertEqual(render.call_count,1)
        self.verify()

    def test_f4_nonexistent_derived_or_explicit_delivery_root_creates_nothing(self):
        self.source_image("0001")
        self.data["texture"][0]["op"]=[self.flat([8,8,56,48],[1,2,3])]
        manifest=self.build()
        path=self.out/"manifest.json"
        missing=self.root/"wrong tools"/"Текстуры_для_перевода"
        manifest["source_root"]=str(missing)
        path.write_text(json.dumps(manifest),encoding="utf-8")
        with self.assertRaisesRegex(spec.SpecError,"--tools-root.*PBD_RU_TOOLS.*--deliver-root"):
            cli.deliver(manifest=path,log=self.root/"log.jsonl")
        self.assertFalse(missing.parent.exists())
        manifest["source_root"]=str(self.source)
        path.write_text(json.dumps(manifest),encoding="utf-8")
        for destination in (None,self.root/"missing delivery"):
            with self.assertRaisesRegex(spec.SpecError,"must already exist"):
                cli.deliver(destination,manifest=path,log=self.root/"log.jsonl")
        self.assertFalse((self.source/"ГОТОВО").exists())
        self.assertFalse((self.root/"missing delivery").exists())

    def test_f4_default_delivery_uses_manifest_not_environment(self):
        self.source_image("0001")
        self.data["texture"][0]["op"]=[self.flat([8,8,56,48],[1,2,3])]
        self.build()
        destination=self.source/"ГОТОВО"
        destination.mkdir()
        wrong=self.root/"wrong tools"
        with patch.object(cli,"HERE",self.root),patch.dict("os.environ",{"PBD_RU_TOOLS":str(wrong)}):
            self.assertEqual(cli.main(["deliver","--all"]),0)
        self.assertTrue((destination/"0001_текстура.png").is_file())
        self.assertFalse(wrong.exists())

    def test_f5_merged_member_style_requires_valid_paint_reference(self):
        self.source_image("0001")
        self.data["texture"][0]["op"]=[{"type":"use_group","group":"g"}]
        group={"id":"g","space":[64,64],"member":[{"id":"0001"}],"op":[self.asset_op()]}
        self.data["group"]=[group]
        for style in ({"colour":"auto"},{"stroke_colour":"auto"},{"blend":"tint"}):
            group["member"][0]["style"]=style
            with self.assertRaisesRegex(spec.SpecError,r"texture 0001/op\[0\].*paint_from"):
                self.build()
        group["op"]=[{**self.flat([8,8,56,48],[1,2,3]),"id":"old"},self.asset_op(paint_from="old")]
        group["member"][0]["style"]={"blend":"tint"}
        with self.assertRaisesRegex(spec.SpecError,"tint.*untint"):
            self.build()
        self.data["group"]=[]
        self.data["texture"][0]["op"]=[group["op"][0],self.asset_op(paint_from="old",blend="tint")]
        with self.assertRaisesRegex(spec.SpecError,"tint.*untint"):
            self.build()

    def test_f5_execution_key_and_type_errors_have_texture_op_context(self):
        self.source_image("0001")
        self.data["texture"][0]["op"]=[self.flat([8,8,56,48],[1,2,3])]
        for error in (TypeError("bad type"),KeyError("missing key")):
            with patch.object(erase,"apply",side_effect=error):
                with self.assertRaisesRegex(spec.SpecError,r"texture 0001/op\[0\]"):
                    self.build()
        self.data["texture"][0]["op"]=[{"type":"use_group","group":"g"}]
        self.data["group"]=[{"id":"g","space":[64,64],"member":[{"id":"0001"}],"op":[self.asset_op()]}]
        with patch.object(text,"render",side_effect=TypeError("bad render")):
            with self.assertRaisesRegex(spec.SpecError,r"texture 0001/group g/op\[0\]"):
                self.build()

    def test_f6_nested_masks_respect_domain_for_near_and_min_size(self):
        rgb=np.zeros((20,20,3),np.uint8)
        rgb[10,3:5]=[255,0,0]
        domain=masks.region((20,20),{"box":[5,5,15,15]})
        red={"kind":"colour","rgb":[255,0,0]}
        for kind in ("all","any"):
            near={"kind":"near","of":red,"radius":2}
            expected=masks.select(rgb,near,domain)
            self.assertFalse(expected.any())
            np.testing.assert_array_equal(masks.select(rgb,{"kind":kind,"of":[near]},domain),expected)
            rgb[10,5]=[255,0,0]
            small={**red,"min_size":2}
            expected=masks.select(rgb,small,domain)
            self.assertFalse(expected.any())
            np.testing.assert_array_equal(masks.select(rgb,{"kind":kind,"of":[small]},domain),expected)
            rgb[10,5]=0

    def independent_pair(self):
        for tid in ("0001","0002"):
            self.source_image(tid)
            self.data["texture"][-1]["op"]=[self.flat([8,8,56,48],[int(tid),2,3])]

    def test_f7_only_build_keeps_valid_unselected_output_and_manifest(self):
        self.independent_pair()
        first=self.build()
        kept=first["textures"]["0002"]
        original=Path(kept["output"]["path"]).read_bytes()
        with contextlib.redirect_stdout(io.StringIO()) as report:
            second=self.build(["0001"])
        self.assertEqual(second["textures"]["0002"],kept)
        self.assertEqual(Path(kept["output"]["path"]).read_bytes(),original)
        self.assertNotIn("Removed outputs",report.getvalue())
        self.assertEqual(set(self.verify()),{"0001","0002"})

    def test_f7_stale_or_undefined_output_is_removed_and_reported(self):
        self.independent_pair()
        for kind in ("source","output","undefined"):
            with self.subTest(kind=kind):
                first=self.build()
                old=first["textures"]["0002"]
                if kind=="undefined":
                    self.data["texture"].pop()
                else:
                    p=Path(old[kind]["path"])
                    p.write_bytes(p.read_bytes()+b"changed")
                with contextlib.redirect_stdout(io.StringIO()) as report:
                    second=self.build(["0001"])
                self.assertEqual(set(second["textures"]),{"0001"})
                self.assertFalse(Path(old["output"]["path"]).exists())
                self.assertIn(old["output"]["path"],report.getvalue())
                self.verify()

    def test_f7_merge_separate_spec_sets_remains_checkable(self):
        self.independent_pair()
        first_spec=self.root/"first.toml"
        first_spec.write_text("texture = "+toml([self.data["texture"][0]]),encoding="utf-8")
        second_spec=self.root/"second.toml"
        second_spec.write_text("texture = "+toml([self.data["texture"][1]]),encoding="utf-8")
        engine.build([first_spec],self.source,out=self.out,previews=self.preview)
        merged=engine.build([second_spec],self.source,only=["0002"],out=self.out,previews=self.preview)
        self.assertEqual(set(merged["textures"]),{"0001","0002"})
        self.assertEqual(set(self.verify()),{"0001","0002"})

    def test_f7_missing_unselected_source_or_dependency_is_dropped(self):
        self.independent_pair()
        self.data["texture"][1]["op"]=[self.asset_op()]
        for path in (self.root/"lettering.png",self.source/"1_Основное"/"0002_текстура.png"):
            content=path.read_bytes()
            first=self.build()
            path.unlink()
            with contextlib.redirect_stdout(io.StringIO()) as report:
                second=self.build(["0001"])
            self.assertEqual(set(second["textures"]),{"0001"})
            self.assertFalse(Path(first["textures"]["0002"]["output"]["path"]).exists())
            self.assertIn("Removed outputs",report.getvalue())
            self.verify()
            path.write_bytes(content)

    def test_f7_retains_or_drops_whole_prior_group(self):
        for tid in ("0001","0002","0003"):
            self.source_image(tid)
        self.data["texture"][0]["op"]=[self.flat([8,8,56,48],[1,2,3])]
        for texture in self.data["texture"][1:]:
            texture["op"]=[{"type":"use_group","group":"g"}]
        self.data["group"]=[{"id":"g","space":[64,64],"op":[self.asset_op()],
                              "member":[{"id":"0002"},{"id":"0003"}]}]
        first=self.build()
        kept=self.build(["0001"])
        self.assertEqual(set(kept["textures"]),{"0001","0002","0003"})
        self.assertEqual(kept["groups"],first["groups"])
        self.verify()
        source=Path(first["textures"]["0002"]["source"]["path"])
        source.write_bytes(source.read_bytes()+b"changed")
        with contextlib.redirect_stdout(io.StringIO()):
            dropped=self.build(["0001"])
        self.assertEqual(set(dropped["textures"]),{"0001"})
        self.assertFalse(dropped["groups"])
        for tid in ("0002","0003"):
            self.assertFalse(Path(first["textures"][tid]["output"]["path"]).exists())
        self.verify()

    def test_f8_rejects_both_box_and_quad(self):
        self.source_image("0001")
        for op in (self.text_op(),self.asset_op()):
            op["quad"]=[[8,8],[56,8],[56,48],[8,48]]
            self.data["texture"][0]["op"]=[op]
            with self.assertRaisesRegex(spec.SpecError,"box OR quad"):
                self.build()

    def test_f9_hash_is_of_exact_parsed_spec_bytes_including_bom(self):
        self.source_image("0001")
        self.data["texture"][0]["op"]=[self.flat([8,8,56,48],[1,2,3])]
        self.write_spec()
        raw=b"\xef\xbb\xbf"+self.path.read_bytes()+"\n# Кириллица\r\n".encode("utf-8")
        self.path.write_bytes(raw)
        reads=[]
        original=Path.read_bytes
        def read(path):
            data=original(path)
            if path==self.path:
                reads.append(data)
            return data
        with patch.object(Path,"read_bytes",read):
            project=spec.load([self.path],self.source)
        self.assertEqual(reads,[raw])
        expected={"path":str(self.path.resolve()),"sha256":hashlib.sha256(raw).hexdigest()}
        self.assertEqual(project.spec_records,[expected])
        manifest=engine.build([self.path],self.source,out=self.out,previews=self.preview)
        self.assertEqual(manifest["specs"],[expected])

    def test_f9_change_after_parse_rejected_before_publishing(self):
        self.source_image("0001")
        self.data["texture"][0]["op"]=[self.flat([8,8,56,48],[1,2,3])]
        self.write_spec()
        loads=spec.tomllib.loads
        def race(document):
            parsed=loads(document)
            self.path.write_text(document+"\n# changed after parsing",encoding="utf-8")
            return parsed
        with patch.object(spec.tomllib,"loads",side_effect=race):
            with self.assertRaisesRegex(spec.SpecError,"input changed during build"):
                engine.build([self.path],self.source,out=self.out,previews=self.preview)
        self.assertFalse(self.out.exists())
