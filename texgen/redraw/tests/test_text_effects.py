"""Amendment A: deterministic glyph coverage, fitting and overflow contracts."""
import copy
import random
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from texgen.redraw import check, compose, spec, text
from texgen.redraw.tests.test_redraw import Workspace


JITTER = {"rotate":8, "shift":.12, "scale":.12, "seed":1}
DRIPS = {"count":.6, "length":[.3,1.2], "width":[.06,.14], "seed":2, "colour":"fill"}


class TextEffects(Workspace):
    def effect_op(self, **kw):
        return self.text_op(text="КРОВЬ\nЁж №«Я»", box=[30,30,330,230],
                            jitter=copy.deepcopy(JITTER), drips=copy.deepcopy(DRIPS), **kw)

    def test_private_seeds_deterministic_and_independent(self):
        np_state, py_state = np.random.get_state(), random.getstate()
        self.addCleanup(np.random.set_state, np_state)
        self.addCleanup(random.setstate, py_state)
        for effect in ("jitter", "drips", "both"):
            with self.subTest(effect=effect):
                op = self.effect_op()
                if effect != "both":
                    op.pop("drips" if effect=="jitter" else "jitter")
                before = text.render(op, (360,260)).fill.tobytes()
                np.random.seed(998); random.seed(775)
                expected_np = np.random.get_state()
                expected_py = random.getstate()
                after = text.render(op, (360,260)).fill.tobytes()
                self.assertEqual(before, after)
                actual_np = np.random.get_state()
                np.testing.assert_array_equal(expected_np[1], actual_np[1])
                self.assertEqual(expected_np[2:], actual_np[2:])
                self.assertEqual(expected_py, random.getstate())
                key = "jitter" if effect=="both" else effect
                op[key]["seed"] += 3
                self.assertNotEqual(before, text.render(op, (360,260)).fill.tobytes())

    def test_zero_effects_byte_identical_in_all_fit_modes(self):
        for fit in ("fit", "fill_box", "fixed"):
            for rot in (0,270):
                op = self.text_op(text="AV Ёж\n№«Я»", box=[80,80,340,300],
                                  fit=fit, size=22, rot=rot, tracking=1.25,
                                  stroke=1, shadow={"dx":2,"dy":1,"blur":1})
                plain = text.render(op, (420,380)).fill
                for effects in ({"jitter":{"rotate":0,"shift":0,"scale":0,"seed":73}},
                                {"drips":{**DRIPS,"count":0}},
                                {"jitter":{},"drips":{"count":0}}):
                    with self.subTest(fit=fit,rot=rot,effects=effects):
                        result = text.render({**op,**effects}, (420,380)).fill
                        self.assertEqual(plain.tobytes(), result.tobytes())

    def test_drips_start_on_lower_ink_and_extend_below_baseline(self):
        op = self.text_op(text="Н", fit="fixed", size=48)
        font = text.font_for(op, 192)
        plain, x, y = list(text.effected_glyphs(op, font, 4))[0]
        dripping, dx, dy = list(text.effected_glyphs(
            {**op,"drips":{**DRIPS,"count":5,"length":[.8,.8],"width":[.06,.06]}}, font, 4))[0]
        self.assertEqual(y, dy)
        self.assertGreater(dy+dripping.height, y+plain.height)
        self.assertGreater(dy+dripping.height, font.getmetrics()[0])
        # Original coverage remains present at its original layout coordinates.
        recovered = np.array(dripping.crop((x-dx,0,x-dx+plain.width,plain.height)))
        self.assertTrue(np.all(recovered >= np.array(plain)))
        low = np.array(plain)[int(plain.height*.85):] > 0
        extensions = np.flatnonzero(np.array(dripping)[plain.height+5] > 0)+dx-x
        origins = np.flatnonzero(low.any(axis=0))
        self.assertTrue(len(extensions))
        for column in extensions:
            self.assertLessEqual(np.min(np.abs(origins-column)), .8*.06*sum(font.getmetrics())+2)

    def test_final_effected_ink_fits_box_with_style_and_rotation(self):
        for fit in ("fit", "fill_box"):
            for rot in (0,90,270):
                op = self.effect_op(fit=fit,rot=rot,stroke=2,
                                    shadow={"dx":3,"dy":-2,"blur":1})
                fill = text.render(op,(360,260)).fill
                bbox = compose.styled(fill,op,[255,255,255]).getchannel("A").getbbox()
                l,t,r,b = op["box"]
                self.assertTrue(l <= bbox[0] < bbox[2] <= r)
                self.assertTrue(t <= bbox[1] < bbox[3] <= b)
                if fit=="fill_box":
                    for actual, expected in zip(bbox,op["box"]):
                        self.assertLessEqual(abs(actual-expected),1)

    def test_wide_short_drops_keep_complete_round_ends(self):
        glyph = Image.new("L",(20,20),255)
        options = {"count":5,"length":[.001,.001],"width":[3,3]}
        layer, (dx,dy) = text.glyph_drips(glyph,20,options,np.random.default_rng(2))
        # A valid very wide, short drop reaches above the original glyph. Its
        # round end must not be silently cropped before fit/overflow checking.
        self.assertEqual(dy,-29)
        self.assertEqual(layer.height,98)
        self.assertLess(layer.getbbox()[1]-(-dy),0)
        np.testing.assert_array_equal(np.array(layer.crop((-dx,-dy,20-dx,20-dy))),np.array(glyph))

    def test_jitter_preserves_advances_spaces_and_glyph_order(self):
        op = self.text_op(text="AV  НАМ",tracking=8)
        font = text.font_for(op,192)
        normal = list(text.effected_glyphs(op,font,4))
        chaotic = list(text.effected_glyphs({**op,"jitter":JITTER},font,4))
        scaled = list(text.effected_glyphs({**op,"jitter":{**JITTER,"rotate":0}},font,4))
        self.assertEqual(len(normal),5)
        centroids = []
        for (plain,x,y),(glyph,gx,gy) in zip(normal,chaotic):
            a = np.array(glyph,dtype=float)
            centroids.append(gx+(a.sum(axis=0)*np.arange(glyph.width)).sum()/a.sum())
        # Rotation can change an asymmetric glyph's cropped bbox centre. With
        # scale/vertical shift alone, its horizontal centre remains unchanged.
        for (plain,x,y),(glyph,gx,gy) in zip(normal,scaled):
            self.assertAlmostEqual(x+plain.width/2,gx+glyph.width/2,delta=1)
        self.assertTrue(all(b>a for a,b in zip(centroids,centroids[1:])))
        self.assertTrue(any((x,y,g.size,g.tobytes()) != (gx,gy,h.size,h.tobytes())
                            for (g,x,y),(h,gx,gy) in zip(normal,chaotic)))
        # Check the kerning/tracking placement against the actual font metrics.
        x0 = normal[0][1]
        v_offset = font.getlength("AV")-font.getlength("V")+8*4
        self.assertAlmostEqual(normal[1][1]-x0, v_offset, delta=2)

    def test_separate_rngs_leave_jitter_unchanged_when_drips_added(self):
        op = self.effect_op()
        font = text.font_for(op,128)
        plain = list(text.effected_glyphs({**op,"drips":{"count":0}},font,1))
        dripping = list(text.effected_glyphs(op,font,1))
        for (glyph,x,y),(drip,dx,dy) in zip(plain,dripping):
            recovered = np.array(drip.crop((x-dx,y-dy,x-dx+glyph.width,y-dy+glyph.height)))
            self.assertTrue(np.all(recovered >= np.array(glyph)))

    def test_invalid_effects_report_file_texture_and_op(self):
        invalid = []
        for key,limit in (("rotate",45),("shift",.5),("scale",.5)):
            invalid.extend(("jitter",{key:value}) for value in (-.01,limit+.01,True,"1",float("nan")))
        invalid.extend(("drips",{"count":value}) for value in (-1,5.01,False,"1",float("inf")))
        for key in ("length","width"):
            invalid.extend(("drips",{key:value}) for value in
                           ([0,1],[-1,1],[2,1],[1,3.01],[1],[1,2,3],"1",[False,1]))
        for name in ("jitter","drips"):
            invalid.extend((name,value) for value in (None,[],False,{"typo":1}))
            invalid.extend((name,{"seed":value}) for value in (-1,.5,True,"1"))
        invalid.append(("drips",{"colour":[255,0,0]}))
        for name,value in invalid:
            with self.subTest(effect=name,value=value):
                with self.assertRaises(spec.SpecError) as error:
                    spec.operations([self.text_op(**{name:value})],(64,64),"fixture.toml/texture 0001")
                self.assertIn("fixture.toml/texture 0001/op[0]",str(error.exception))
                self.assertIn(name,str(error.exception))

    def test_effect_range_boundaries_and_defaults(self):
        for options in ({"jitter":{},"drips":{}},
                        {"jitter":{"rotate":45,"shift":.5,"scale":.5,"seed":0},
                         "drips":{"count":5,"length":[3,3],"width":[.001,3],"seed":0}}):
            spec.text_effects(options,"fixture/texture 0001/op[0]")

    def test_effects_disallowed_on_assets_and_member_styles(self):
        for name, value in (("jitter",JITTER),("drips",DRIPS)):
            with self.assertRaisesRegex(spec.SpecError,"unknown key"):
                spec.operations([{"type":"asset","path":"unused.png","box":[8,8,56,48],name:value}],
                                (64,64),"fixture/texture 0001")
            self.data={"texture":[],"group":[]}
            for tid in ("0001","0002"):
                self.source_image(tid)
                self.data["texture"][-1]["op"]=[{"type":"use_group","group":"pair"}]
            self.data["group"]=[{"id":"pair","space":[64,64],
                                 "member":[{"id":"0001","style":{name:value}},{"id":"0002"}],
                                 "op":[self.flat([8,8,56,48],[0,0,0])]}]
            self.write_spec()
            with self.assertRaisesRegex(spec.SpecError,"unknown key"):
                spec.load([self.path],self.source)

    def test_group_render_once_and_exact_member_coverage(self):
        members = [("0001",(1024,1024),{}), ("0002",(128,128),{"scale":.125}),
                   ("0003",(1024,1024),{"rot":90,"mirror":True})]
        for tid,size,tr in members:
            self.source_image(tid,size,colour=[0,0,0])
            self.data["texture"][-1]["op"]=[{"type":"use_group","group":"blood"}]
        self.data["group"]=[{"id":"blood","space":[1024,1024],
                             "member":[{"id":tid,"transform":tr} for tid,size,tr in members],
                             "op":[self.text_op(box=[128,128,896,896],jitter=JITTER,drips=DRIPS,
                                                colour=[255,255,255])]}]
        with patch("texgen.redraw.engine.text.render",wraps=text.render) as render:
            manifest = self.build(["0002"])
        self.assertEqual(render.call_count,1)
        self.assertEqual(set(self.verify(["0002"])), {tid for tid,size,tr in members})
        with Image.open(manifest["groups"]["blood"]["path"]) as im:
            canonical = im.copy()
        for tid,size,tr in members:
            expected = canonical
            if tr.get("mirror"):
                expected = expected.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            if tr.get("rot"):
                expected = expected.transpose(Image.Transpose.ROTATE_90)
            if tr.get("scale"):
                expected = expected.resize(size,Image.Resampling.BOX)
            with Image.open(manifest["textures"][tid]["output"]["path"]) as im:
                actual = np.array(im)
            np.testing.assert_array_equal(actual[...,0], np.array(expected))
            np.testing.assert_array_equal(check.map_coverage(np.array(canonical),size,tr),np.array(expected))
        hashes = {tid:entry["output"]["sha256"] for tid,entry in manifest["textures"].items()}
        again = self.build()
        self.assertEqual(hashes,{tid:entry["output"]["sha256"] for tid,entry in again["textures"].items()})

    def test_fixed_effects_overflow_allowed_rejected_or_explicitly_clipped(self):
        self.source_image("0001",(256,256),colour=[0,0,0])
        op = self.text_op(text="Н",box=[100,100,156,156],fit="fixed",size=36,
                          jitter=JITTER,drips={**DRIPS,"count":5,"length":[1.5,1.5]},colour=[255,255,255])
        self.data["texture"][0]["op"]=[op]
        with self.assertRaisesRegex(spec.SpecError,"0001.*ink outside allowed"):
            self.build()
        self.data["texture"][0]["allow"]=[[32,32,224,224]]
        manifest = self.build()
        self.verify()
        output = Path(manifest["textures"]["0001"]["output"]["path"])
        with Image.open(output) as im:
            actual = np.array(im)[...,0]
        expected = np.array(text.render(op,(256,256)).fill)
        np.testing.assert_array_equal(actual,expected)
        allowed_box = check.raster((256,256),{"box":op["box"]})
        self.assertTrue(np.any(actual[~allowed_box]))
        del self.data["texture"][0]["allow"]
        op["clip"] = True
        self.build(); self.verify()
        with Image.open(output) as im:
            clipped = np.array(im)[...,0]
        expected[~allowed_box] = 0
        np.testing.assert_array_equal(clipped,expected)

    def test_fixed_size_is_not_refitted_to_box(self):
        op = self.effect_op(fit="fixed",size=28)
        first = text.render(op,(600,600)).fill
        second = text.render({**op,"box":[10,10,590,590]},(600,600)).fill
        self.assertEqual(first.crop(first.getbbox()).tobytes(),second.crop(second.getbbox()).tobytes())
        self.assertEqual(first.crop(first.getbbox()).size,second.crop(second.getbbox()).size)

    def test_group_errors_include_context(self):
        self.pair()
        self.data["group"][0]["op"][0]["jitter"]={"rotate":46}
        self.write_spec()
        with self.assertRaisesRegex(spec.SpecError,r"group pair/op\[0\].*jitter/rotate"):
            spec.load([self.path],self.source)
