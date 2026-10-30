"""Offline tests for the decision rules and helpers. No API calls: python -m unittest discover tests"""

import unittest

from proofstep import author, decide, evidence, search
from proofstep.decide import CANT_VERIFY, MISSING, VERIFIED
from proofstep.procedure import Procedure, Step

FPS = 2


def frames(a: float, b: float) -> list[int]:
    """Frame indices covering a..b seconds at 2 fps."""
    return list(range(int(a * FPS), int(b * FPS) + 1))


def claim(status, start=None, end=None, objects=()):
    return {"status": status, "start": start, "end": end, "objects": list(objects), "evidence": ""}


def obj(seen=(), handled=(), name_used=None, name=""):
    return {"seen": list(seen), "handled": list(handled), "name_used": name_used or name}


def run(steps: dict, objects: dict, rules=(), duration=600.0):
    procedure = Procedure(name="test", steps=[Step(id=sid, text=f"step {sid}") for sid in steps], rules=list(rules))
    spark = {"duration": duration, "steps": steps, "other_mistakes": []}
    sam = {"fps": FPS, "frames": int(duration * FPS),
           "objects": {k: {**v, "name_used": v.get("name_used") or k} for k, v in objects.items()}}
    report = decide.decide(procedure, spark, sam)
    return {s["id"]: s for s in report["steps"]}, report


class DecideTests(unittest.TestCase):
    def test_both_witnesses_agree_on_done(self):
        steps, _ = run({"S1": claim("done", 10, 20, ["jar"])},
                       {"jar": obj(seen=frames(5, 30), handled=frames(12, 18))})
        self.assertEqual(steps["S1"]["status"], VERIFIED)

    def test_both_witnesses_agree_on_skipped(self):
        steps, _ = run({"S1": claim("not_done", objects=["spoon"])},
                       {"spoon": obj(seen=frames(100, 120))})  # on the counter, never in hand
        self.assertEqual(steps["S1"]["status"], MISSING)

    def test_disagreement_points_at_the_moment(self):
        steps, _ = run({"S1": claim("not_done", objects=["bag"])},
                       {"bag": obj(seen=frames(100, 115), handled=frames(100, 110))})
        self.assertEqual(steps["S1"]["status"], CANT_VERIFY)
        self.assertAlmostEqual(steps["S1"]["look_at"], 100.0)

    def test_missing_needs_sam_to_know_the_object(self):
        steps, _ = run({"S1": claim("not_done", objects=["pepper shaker"])}, {})
        self.assertEqual(steps["S1"]["status"], CANT_VERIFY)

    def test_generic_fallback_name_never_verifies(self):
        steps, _ = run({"S1": claim("done", 150, 160, ["salt box"])},
                       {"salt box": obj(seen=frames(140, 170), handled=frames(150, 160), name_used="box")})
        self.assertEqual(steps["S1"]["status"], CANT_VERIFY)
        self.assertEqual(steps["S1"]["evidence"]["found_as"], "box")

    def test_object_named_for_many_steps_is_not_evidence(self):
        steps, _ = run({"S1": claim("done", 10, 20, ["mug", "kettle"]),
                        "S2": claim("done", 60, 70, ["mug", "jar"]),
                        "S3": claim("done", 120, 130, ["mug", "spoon"])},
                       {"mug": obj(seen=frames(0, 200), handled=frames(0, 200)),
                        "jar": obj(seen=frames(55, 75), handled=frames(60, 70))})
        self.assertEqual(steps["S1"]["status"], CANT_VERIFY)  # only the mug was in hand
        self.assertEqual(steps["S2"]["status"], VERIFIED)     # the jar, specific to this step

    def test_handling_during_another_step_is_not_unexplained(self):
        # The spoon was in hand while stirring (S1); that doesn't contradict "S2 was skipped".
        steps, _ = run({"S1": claim("done", 100, 110, ["spoon"]), "S2": claim("not_done", objects=["spoon"])},
                       {"spoon": obj(seen=frames(90, 120), handled=frames(100, 110))})
        self.assertEqual(steps["S1"]["status"], VERIFIED)
        self.assertEqual(steps["S2"]["status"], MISSING)

    def test_order_is_only_judged_between_verified_steps(self):
        steps, report = run({"S1": claim("done", 200, 210, ["milk"]), "S2": claim("done", 50, 60, ["sugar"])},
                            {"milk": obj(seen=frames(195, 215), handled=frames(200, 210)),
                             "sugar": obj(seen=frames(45, 65), handled=frames(50, 60))},
                            rules=[("S1", "S2")])
        self.assertEqual([(o["before"], o["after"]) for o in report["order_problems"]], [("S1", "S2")])

    def test_no_order_problem_when_a_step_is_unverified(self):
        _, report = run({"S1": claim("done", 200, 210, ["milk"]), "S2": claim("done", 50, 60, ["sugar"])},
                        {"sugar": obj(seen=frames(45, 65), handled=frames(50, 60))},
                        rules=[("S1", "S2")])
        self.assertEqual(report["order_problems"], [])


class HelperTests(unittest.TestCase):
    def test_sam_wire_format(self):
        text = ("<0f>0<|box;x1=1;y1=2;x2=30;y2=40;w=640;h=360;c=0.9|><|mask;x=0;y=0;c=0.9;data=2,2,~<1f>junk|>"
                "<3f>0<|box;x1=5;y1=6;x2=7;y2=8;c=0.4|>")
        parsed = evidence.parse(text)
        self.assertEqual(sorted(parsed), [0, 3])  # a mask payload that looks like a frame tag is ignored
        self.assertEqual(parsed[0][0], (1.0, 2.0, 30.0, 40.0, 0.9))

    def test_rules_that_would_loop_are_dropped(self):
        kept = author._without_cycles([("S1", "S2"), ("S2", "S3"), ("S3", "S1"), ("S1", "S3")])
        self.assertEqual(kept, [("S1", "S2"), ("S2", "S3"), ("S1", "S3")])

    def test_search_slices_cover_the_window_and_overlap(self):
        slices = search._slices(10.0, 70.0)
        self.assertEqual(slices[0][0], 10.0)
        self.assertEqual(slices[-1][1], 70.0)
        self.assertTrue(all(b[0] < a[1] for a, b in zip(slices, slices[1:])))  # consecutive slices overlap
        self.assertTrue(all(round(b - a, 1) <= search.SLICE for a, b in slices))

    def test_short_window_is_one_slice(self):
        self.assertEqual(search._slices(5.0, 12.0), [(5.0, 12.0)])


if __name__ == "__main__":
    unittest.main()
