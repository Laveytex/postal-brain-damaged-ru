"""Regressions for the host's second inspection, using synthetic inputs."""
import contextlib
import copy
import io
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

from texgen.redraw import check, cli, compose, engine, spec, text
from texgen.redraw.tests.test_redraw import Workspace, toml


class FixRound2(Workspace):
    def separate_specs(self):
        paths=[]
        for tid in ("0001","0002"):
            self.source_image(tid)
            self.data["texture"][-1]["op"]=[self.flat([8,8,40,40],[1,2,3])]
            path=self.root/(tid+".toml")
            path.write_text("texture = "+toml([self.data["texture"][-1]]),encoding="utf-8")
            paths.append(path)
        return paths

    def test_f1_unrelated_spec_edit_does_not_block_check_delivery_or_retention(self):
        paths=self.separate_specs()
        first=engine.build(paths,self.source,out=self.out,previews=self.preview)
        for tid,path in zip(("0001","0002"),paths):
            self.assertEqual(first["textures"][tid]["specs"],[spec.record(path)])
        paths[0].write_bytes(paths[0].read_bytes()+b"\n# edited\n")
        self.assertEqual(set(self.verify(["0002"])),{"0002"})
        dest=self.source/"ГОТОВО"
        dest.mkdir()
        self.assertEqual(cli.deliver(ids=["0002"],manifest=self.out/"manifest.json",
                                    log=self.root/"log")["copied"],1)
        prior=Path(first["textures"]["0002"]["output"]["path"]).read_bytes()
        second=engine.build([paths[0]],self.source,only=["0001"],out=self.out,previews=self.preview)
        self.assertEqual(second["textures"]["0002"],first["textures"]["0002"])
        self.assertEqual(Path(second["textures"]["0002"]["output"]["path"]).read_bytes(),prior)
        self.verify()

    def test_f1_check_requires_exact_texture_and_group_spec_set(self):
        paths=self.separate_specs()
        group_path=self.root/"group.toml"
        group={"id":"g","space":[64,64],"member":[{"id":"0001"}],
               "op":[self.flat([8,8,40,40],[7,8,9])]}
        self.data["texture"][0]["op"]=[{"type":"use_group","group":"g"}]
        paths[0].write_text("texture = "+toml([self.data["texture"][0]]),encoding="utf-8")
        group_path.write_text("group = "+toml([group]),encoding="utf-8")
        manifest=engine.build([*paths,group_path],self.source,out=self.out,previews=self.preview)
        self.assertEqual({r["path"] for r in manifest["textures"]["0001"]["specs"]},
                         {str(paths[0]),str(group_path)})
        self.verify()
        for records in ([spec.record(paths[0])],
                        [spec.record(paths[0]),spec.record(group_path),spec.record(paths[1])]):
            damaged=copy.deepcopy(manifest)
            damaged["textures"]["0001"]["specs"]=records
            with self.assertRaises(spec.SpecError):
                check.verify(self.out/"manifest.json",["0001"],manifest_data=damaged)

    def test_f2_large_fit_rasterises_at_target_supersampled_size(self):
        op=self.text_op(text="H",fit="fit",box=[10,10,1010,610],supersample=4)
        rasters=[]
        original=text.raw_text
        def capture(*args):
            raster=original(*args)
            rasters.append((args[1],raster.copy()))
            return raster
        with patch.object(text,"raw_text",side_effect=capture):
            rendered=text.render(op,(1020,620)).fill
        self.assertGreaterEqual(rasters[-1][1].height,.9*600*4)
        actual=rendered.crop(rendered.getbbox())
        direct=original(op,rasters[-1][0],4).resize(actual.size,Image.Resampling.LANCZOS)
        # A nominal-size upscale has broad grey ramps; a native raster's edge
        # transition occupancy remains comparable to direct supersampling.
        def transition_fraction(im):
            a=np.asarray(im)
            return np.count_nonzero((a>16)&(a<239))/np.count_nonzero(a>0)
        self.assertLessEqual(transition_fraction(actual),transition_fraction(direct)*1.3+.002)
        self.assertLess(np.abs(np.asarray(actual).astype(float)-np.asarray(direct)).mean(),2)

    def test_f3_delivery_rejects_other_source_folders_and_build_output(self):
        self.source_image("0001")
        self.data["texture"][0]["op"]=[self.flat([8,8,40,40],[1,2,3])]
        self.build()
        another=self.source/"2_Вывески"
        another.mkdir()
        for dest in (another,self.source,self.out):
            before={p:p.read_bytes() for p in dest.rglob("*") if p.is_file()}
            with self.assertRaisesRegex(spec.SpecError,"source/build"):
                cli.deliver(dest,manifest=self.out/"manifest.json",log=self.root/"log",replace=True)
            self.assertEqual({p:p.read_bytes() for p in dest.rglob("*") if p.is_file()},before)
        self.assertFalse((self.root/"log").exists())

    def test_f6_read_error_aborts_without_removing_prior_outputs(self):
        paths=self.separate_specs()
        first=engine.build(paths,self.source,out=self.out,previews=self.preview)
        prior=(self.out/"manifest.json").read_bytes()
        blocked=Path(first["textures"]["0002"]["source"]["path"])
        read=Path.read_bytes
        def fail(path):
            if path==blocked:
                raise PermissionError("simulated read denial")
            return read(path)
        with patch.object(Path,"read_bytes",fail),self.assertRaisesRegex(PermissionError,"read denial"):
            engine.build([paths[0]],self.source,out=self.out,previews=self.preview)
        self.assertEqual((self.out/"manifest.json").read_bytes(),prior)
        for entry in first["textures"].values():
            self.assertEqual(spec.sha(entry["output"]["path"]),entry["output"]["sha256"])

    def test_f6_manifest_precedes_cleanup_and_unlink_failure_is_reported(self):
        paths=self.separate_specs()
        first=engine.build(paths,self.source,out=self.out,previews=self.preview)
        paths[1].write_bytes(paths[1].read_bytes()+b"\n# stale")
        stale=Path(first["textures"]["0002"]["output"]["path"])
        unlink=Path.unlink
        def fail(path,*args,**kwargs):
            if path==stale:
                current=json.loads((self.out/"manifest.json").read_bytes())
                self.assertEqual(set(current["textures"]),{"0001"})
                raise PermissionError("simulated unlink denial")
            return unlink(path,*args,**kwargs)
        with patch.object(Path,"unlink",fail),contextlib.redirect_stdout(io.StringIO()) as report:
            result=engine.build([paths[0]],self.source,out=self.out,previews=self.preview)
        self.assertEqual(set(result["textures"]),{"0001"})
        self.assertTrue(stale.exists())
        self.assertIn(str(stale),report.getvalue())
        self.assertIn("unlink denial",report.getvalue())
        self.verify()

    def test_f7_fractional_rot270_geometry_checks_without_drift(self):
        self.source_image("0001")
        self.data["texture"][0]["op"]=[{"type":"use_group","group":"g"}]
        region={"box":[.1,.3,20.2,30.7]}
        tr={"rot":270,"mirror":True}
        self.data["group"]=[{"id":"g","space":[64,64],"member":[{"id":"0001","transform":tr}],
                            "op":[{"type":"erase","method":"flat","colour":[1,2,3],"region":region}]}]
        self.assertEqual(check.transform_geometry(region,[64,64],tr),compose.map_geometry(region,[64,64],tr))
        self.build()
        self.verify()

    def test_f8_small_scaled_sample_and_grain_reference_remain_nonempty(self):
        self.source_image("0001",(8,8))
        self.data["texture"][0]["op"]=[{"type":"use_group","group":"g"}]
        ops=[{"type":"erase","method":"flat","region":{"box":[16,16,32,32]},"sample":[0,0,4,4]},
             {"type":"erase","method":"pullpush","region":{"box":[32,32,48,48]},
              "grain":{"ref":[0,0,4,4],"seed":9}}]
        self.data["group"]=[{"id":"g","space":[64,64],"member":[{"id":"0001","transform":{"scale":.125}}],"op":ops}]
        self.build()
        self.verify()
        for op,label in zip(ops,("sample","grain.ref")):
            mapped=engine.scaled_erase(op,[64,64],{"scale":.125},(8,8),"texture 0001/group g/op[0]")
            self.assertEqual(mapped["sample"] if label=="sample" else mapped["grain"]["ref"],[0,0,1,1])
            bad=copy.deepcopy(op)
            if label=="sample":
                bad["sample"]=[60,60,68,68]
            else:
                bad["grain"]["ref"]=[60,60,68,68]
            with self.assertRaisesRegex(spec.SpecError,"texture 0001/group g/op\\[0\\]"):
                engine.scaled_erase(bad,[64,64],{"scale":.125},(8,8),"texture 0001/group g/op[0]")

    def test_f9_raw_text_preserves_pair_kerning_and_tracking(self):
        size,ss=80,4
        op=self.text_op(text="AV")
        font=text.font_for(op,size*ss)
        image=text.raw_text(op,size,ss)
        self.assertAlmostEqual(image.width,font.getlength("AV"),delta=1)
        self.assertLess(font.getlength("AV"),font.getlength("A")+font.getlength("V"))
        direct=Image.new("L",(1000,1000))
        ImageDraw.Draw(direct).text((50,50),"AV",font=font,fill=255)
        np.testing.assert_array_equal(image,direct.crop(direct.getbbox()))
        tracked=text.raw_text({**op,"tracking":2},size,ss)
        self.assertAlmostEqual(tracked.width,font.getlength("AV")+2*ss,delta=1)

    def test_f10_malformed_manifests_return_cli_error_without_traceback(self):
        self.out.mkdir()
        for damaged in ({"schema":1}, {"schema":1,"source_root":None,"textures":None}, []):
            (self.out/"manifest.json").write_text(json.dumps(damaged),encoding="utf-8")
            for command in (["check"],["deliver","--all"]):
                with patch.object(check,"HERE",self.root),patch.object(cli,"HERE",self.root),contextlib.redirect_stderr(io.StringIO()) as error:
                    self.assertEqual(cli.main(command),1)
                self.assertIn("error:",error.getvalue())
                self.assertNotIn("Traceback",error.getvalue())
