"""Final host inspection regressions; synthetic files only."""
import contextlib
import io
from pathlib import Path
from unittest.mock import patch

import numpy as np

from texgen.redraw import cli, engine, erase, spec
from texgen.redraw.tests.test_redraw import Workspace, toml


class FixRound3(Workspace):
    def prior_groups(self):
        for tid in ("0001","0002","0003"):
            self.source_image(tid)
        paths=[]
        for gid,tids in (("keep",["0001"]),("pair",["0002","0003"])):
            data={"texture":[{"id":tid,"op":[{"type":"use_group","group":gid}]} for tid in tids],
                  "group":[{"id":gid,"space":[64,64],"member":[{"id":tid} for tid in tids],
                            "op":[self.flat([8,8,40,40],[1,2,3])]}]}
            path=self.root/(gid+".toml")
            path.write_text("\n".join(f"{k} = {toml(v)}" for k,v in data.items()),encoding="utf-8")
            paths.append(path)
        first=engine.build(paths,self.source,out=self.out,previews=self.preview)
        return paths,first

    def missing_prior(self,kind):
        paths,first=self.prior_groups()
        missing={"spec":paths[1],"output":Path(first["textures"]["0002"]["output"]["path"]),
                 "layer":Path(first["groups"]["pair"]["path"])}[kind]
        missing.unlink()
        with contextlib.redirect_stdout(io.StringIO()) as report:
            second=engine.build([paths[0]],self.source,out=self.out,previews=self.preview)
        self.assertEqual(set(second["textures"]),{"0001"})
        self.assertEqual(set(second["groups"]),{"keep"})
        self.assertIn("Dropped stale textures 0002, 0003",report.getvalue())
        self.assertIn(str(missing),report.getvalue())
        for tid in ("0002","0003"):
            self.assertFalse(Path(first["textures"][tid]["output"]["path"]).exists())
        self.verify()
        # Recovery is durable: a second build needs no manual manifest edits.
        engine.build([paths[0]],self.source,out=self.out,previews=self.preview)

    def test_r3_1_deleted_prior_spec_drops_orphaned_closure(self):
        self.missing_prior("spec")

    def test_r3_1_deleted_prior_output_drops_closure(self):
        self.missing_prior("output")

    def test_r3_1_deleted_canonical_layer_drops_closure(self):
        self.missing_prior("layer")

    def test_r3_1_recorded_path_io_errors_still_abort(self):
        paths,first=self.prior_groups()
        snapshots={p:p.read_bytes() for p in self.out.rglob("*") if p.is_file()}
        read=Path.read_bytes
        targets=[paths[1],Path(first["textures"]["0002"]["output"]["path"]),
                 Path(first["groups"]["pair"]["path"])]
        for target in targets:
            for error in (PermissionError,OSError):
                with self.subTest(target=target,error=error):
                    def fail(path):
                        if path==target:
                            raise error("simulated I/O failure")
                        return read(path)
                    with patch.object(Path,"read_bytes",fail),self.assertRaisesRegex(error,"I/O failure"):
                        engine.build([paths[0]],self.source,out=self.out,previews=self.preview)
                    self.assertEqual({p:p.read_bytes() for p in self.out.rglob("*") if p.is_file()},snapshots)

    def test_r3_2_non_table_entries_report_file_and_index(self):
        self.source_image("0001")
        base={"texture":[{"id":"0001","op":[]}],"group":[]}
        cases=[({"texture":[1]},"texture[0]"),({"group":[1]},"group[0]"),
               ({"texture":[{"id":"0001","op":[1]}]},"texture 0001/op[0]"),
               ({**base,"group":[{"id":"g","space":[64,64],"member":[{"id":"0001"}],"op":[1]}]},"group g/op[0]"),
               ({**base,"group":[{"id":"g","space":[64,64],"member":[1]}]},"group g/member[0]")]
        for data,location in cases:
            with self.subTest(location=location):
                self.data=data
                self.write_spec()
                with self.assertRaises(spec.SpecError) as error:
                    spec.load([self.path],self.source)
                self.assertIn(str(self.path),str(error.exception))
                self.assertIn(location,str(error.exception))
                self.assertIn("expected table",str(error.exception))
                with contextlib.redirect_stderr(io.StringIO()) as stderr:
                    self.assertEqual(cli.main(["build",str(self.path),"--source-root",str(self.source)]),1)
                self.assertNotIn("Traceback",stderr.getvalue())
        with self.assertRaisesRegex(spec.SpecError,r"fixture/texture 0001/op\[0\].*expected table"):
            spec.operations([1],(64,64),"fixture/texture 0001")

    def test_r3_2_group_structure_validated_before_closure(self):
        self.source_image("0001")
        groups=[{"id":"g","space":[64,64]},
                {"id":"g","space":[64,64],"member":{}},
                {"id":"g","space":[64,64],"member":[]},
                {"id":"g","space":[64,64],"member":[{}]},
                {"id":"g","space":[64,64],"member":[{"id":["0001"]}]},
                {"id":"g","space":[64,64],"member":[{"id":"0009"}]}]
        for group in groups:
            with self.subTest(group=group):
                self.data["group"]=[group]
                self.write_spec()
                with patch.object(spec.Project,"closure",side_effect=AssertionError("closure ran too early")):
                    with self.assertRaises(spec.SpecError) as error:
                        spec.load([self.path],self.source,only=["0001"])
                self.assertIn(str(self.path),str(error.exception))
                self.assertIn("group g/member",str(error.exception))

    def test_r3_3_reflected_grain_has_no_internal_cyclic_seam(self):
        h,w=8,32
        original=np.repeat(np.broadcast_to(np.arange(4*w,dtype=float),(2*h,4*w))[...,None],3,axis=2)
        rgb=np.zeros_like(original)
        mask=np.ones(original.shape[:2],bool)
        # A broad high-pass filter leaves a near-linear reference detail patch.
        # Wrapping its endpoints would introduce a jump of about 31 units.
        reference_max=np.abs(np.diff(original[:h,:w],axis=1)).max()
        for seed in (0,1,19):
            options={"ref":[0,0,w,h],"sigma":100,"gain":1,"seed":seed}
            a=erase.regrain(rgb.copy(),original,mask,options)
            b=erase.regrain(rgb.copy(),original,mask,options)
            np.testing.assert_array_equal(a,b)
            self.assertGreater(np.ptp(a),10)
            for x in range(0,4*w,w):
                self.assertLessEqual(np.abs(np.diff(a[:,x:x+w],axis=1)).max(),reference_max*1.5)

    def test_r3_4_cleanup_removes_only_dropped_managed_artifacts(self):
        paths,first=self.prior_groups()
        preserved=[self.preview/"0001.png",self.out/"layers"/"keep.png",
                   self.preview/"9999.png",self.out/"layers"/"unmanaged.png"]
        for path in preserved[2:]:
            path.write_bytes(b"unmanaged sentinel")
        snapshots={p:p.read_bytes() for p in preserved}
        paths[1].write_bytes(paths[1].read_bytes()+b"\n# stale")
        with contextlib.redirect_stdout(io.StringIO()) as report:
            engine.build([paths[0]],self.source,out=self.out,previews=self.preview)
        dropped=[self.preview/"0002.png",self.preview/"0003.png",self.out/"layers"/"pair.png"]
        dropped += [Path(first["textures"][tid]["output"]["path"]) for tid in ("0002","0003")]
        for path in dropped:
            self.assertFalse(path.exists())
            self.assertIn(str(path),report.getvalue())
        self.assertEqual({p:p.read_bytes() for p in preserved},snapshots)
        self.verify()
