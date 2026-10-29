# proofstep

Checks from a video whether each step of a physical procedure was actually done. When the evidence doesn't settle it, proofstep says **"can't verify, look at 2:42"** instead of guessing.

Built for the Meta Global AI Developer Hackathon (Oct 27 – Nov 4, 2026) on the Meta Model API: **Muse Spark** watches the video, and **SAM 3.1** checks the physical evidence.

## Why two models

A video model asked "was this step done?" answers confidently, including when it's wrong. Asking it again doesn't help: in our tests its answers never changed between runs, and the wrong ones were wrong every time.

So proofstep asks a second, different kind of witness. Spark claims what happened and when. SAM 3.1 then looks for the objects that step needs and checks whether they were actually in someone's hand. When the two agree, the step is verified or missing. When they disagree, proofstep says so and points to the moment to look at.

## How it works

1. **Spark watches** (`proofstep/watch.py`). One call per video. For each step: done / not done / can't tell, start and end times, and the **objects a camera would see handled**, named as they look ("spice jar", not "cinnamon": SAM finds nothing for the ingredient name, but finds the jar).
2. **SAM finds the evidence** (`proofstep/evidence.py`). SAM 3.1 segments each named object and every hand across a 2-frames-per-second copy of the video. A frame counts as "in hand" when a confident object box overlaps a confident hand box. SAM matches plain nouns more reliably than compound ones ("measuring spoon" and "milk bottle" found nothing; "spoon" and "bottle" did), so a name it never finds is retried as its last word.
3. **Rules decide** (`proofstep/decide.py`). Plain code, no model:

   | Spark says | SAM sees | Result |
   |---|---|---|
   | done at t | object in hand within 45 s of t | **Verified** |
   | skipped | object seen in the video, but never in hand except during other steps that use it | **Missing** |
   | anything else | | **Can't verify**, with the moment to look at |

   - The evidence shown is the in-hand stretch closest to Spark's time. Moments inside another step that uses the same object belong to that step.
   - An object named for three or more steps (the mug a drink is made in) is treated as background, not evidence.
   - Order rules are checked only between verified steps.
4. **Second look** (`proofstep/second_look.py`). For each "can't verify", Spark gets a narrower question about a short clip, not the whole video again:
   - *Spark placed the step, SAM never saw its object in hand.* Usually a naming miss. Spark names what's in the person's hands in plain words, SAM searches again, and the rules run again.
   - Every close look is asked twice, on a short clip and on a wide one, and only an answer both agree on counts. Short clips catch one-second actions; wide ones catch an action that happens well before the object is put away. Spark's answers depend on the clip, so a single look is not trusted.
   - *Spark placed the step, but SAM only matched a generic stand-in name* (a "box" for "salt box"). Only an agreed "yes" at that moment verifies the step.
   - *Spark said skipped, SAM saw the object in hand.* Spark looks closely at **every** such moment. An agreed "yes" at any of them verifies the step. If every moment is agreed to be something else (rinsing the spoon, moving the bottle aside), the step is missing. If the looks disagree, it stays "can't verify" with both accounts. In `8_3`, the short clip sees two chocolate chips dropped into the mug at 2:42, which Spark missed watching the whole video, while the wide clip doesn't, so proofstep points a person at 2:32 instead of guessing.
   - A step done with a different item than written is reported as done with a substitution, not as missing.
   - One "no" is never enough on its own. In `8_50` the chocolate went in at 3:03, while the moment SAM flagged only showed the bag being put away. **proofstep changes its mind on evidence found, never on evidence not found**, so every sighting needs a positive explanation before a step is called missing.

   `--no-second-look` stops after stage 3, for comparison.

## Results so far

On 20 hand-checked CaptainCook4D videos (178 steps, 17 skipped), full table in [`eval/scorecard.md`](eval/scorecard.md):

| | Spark alone | proofstep |
|---|---|---|
| **Skipped steps passed as done** | 1 | **0** |
| Done steps called missing | 12 | **2** |
| Right when it answers | 93% | **99%** |
| Can't verify | 2 | 16 (9%) |
| Skipped steps flagged as missing | 16 of 17 | 13 of 17 (the other 4: can't verify) |
| Order mistakes caught | 2 of 5 | **4 of 5** |

Wrong answers drop from 13 to 2, and no skipped step is ever passed. The price is "can't verify" on 9% of steps, each with the moment a person should look at.

- **Substitutions are flagged, not called missing.** Five steps were done with something other than what was written (powdered sugar, a plate instead of a mug, cooking oil instead of olive oil), and proofstep reports them as done with a substitution.
- **The two remaining errors:** in `8_50` both models miss chocolate going into the mug at 3:03, and in `12_41` the "olive oil" was apple cider vinegar that never went onto the dish, which the dataset counts as done.
- **Caveat:** these rules were developed while looking at these 20 videos, so the numbers that count will come from a fresh held-out set.

## Run it

Needs Python 3.11+ and ffmpeg. No packages to install.

```bash
cp .env.example .env              # then put your Meta Model API key in it
python -m proofstep models        # free: checks the key and lists your models
python -m proofstep.datasets.captaincook4d 8_50 8_3     # labels, recipe procedures, two videos
python -m proofstep cc4d 8_50 8_3                       # check them and compare with the human labels
python -m proofstep check procedures/spicedhotchocolate.json my_video.mp4
```

Every API answer is cached under `data/cache/`, so re-running costs nothing. Each paid call is logged to `data/costs.jsonl`. SAM is billed per frame ($0.20 per 1,000), which makes it the main cost: about $0.10 per object for a 4-minute video at 2 frames per second. `--max-sam-usd` (default $3) stops a run that would cost more per video.

`muse-spark-1.3-contributor` is the default because it is about 12× cheaper, but Meta may train on what it receives. That is fine for the public dataset below and wrong for private footage: set `PROOFSTEP_SPARK_MODEL=muse-spark-1.3` for that.

## Procedures

A procedure is a JSON file with numbered steps and "this before that" rules. See `procedures/` for the 24 CaptainCook4D recipes, generated from the dataset's task graphs.

## Data

[CaptainCook4D](https://github.com/CaptainCook4D) (Peddi et al., NeurIPS 2024): egocentric cooking videos with step timings and labelled mistakes, including skipped steps and wrong order. Videos are Apache 2.0, annotations MIT, and everyone filmed gave written consent.

One label fix is applied: in recording `8_3` the cinnamon and chocolate step labels are swapped, which we confirmed frame by frame (`LABEL_SWAPS` in `proofstep/datasets/captaincook4d.py`). A step counts as skipped when it has no times or is tagged "Missing Step": four steps in the dataset keep their times despite the tag.

**Scorecard.** `python -m proofstep.scorecard run` checks every test recording (5 at a time, with a spending cap), and `python -m proofstep.scorecard report` scores three systems against the labels: Spark alone, proofstep's first pass, and proofstep with the second look. The results are in `eval/scorecard.md`.

**Test set.** `eval/captaincook4d.json` lists the 20 recordings used for the scorecard: three recipes, 178 steps, 17 of them genuinely skipped, and 5 videos with steps out of order. Every label was checked by eye with `python -m proofstep.datasets.label_sheets <id>`, which lays out four frames per labelled step and, for videos with skipped steps, one frame every 10 seconds. The file records what each check found and why two recordings were left out.

## License

MIT
