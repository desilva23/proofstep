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
   | skipped | object never in hand, except during other steps that use it | **Missing** |
   | anything else | | **Can't verify**, with the moment to look at |

   - The evidence shown is the in-hand stretch closest to Spark's time. Moments inside another step that uses the same object belong to that step.
   - An object named for three or more steps (the mug a drink is made in) is treated as background, not evidence.
   - Order rules are checked only between verified steps.
4. **Second look** (`proofstep/second_look.py`). For each "can't verify", Spark gets a narrower question about a short clip, not the whole video again:
   - *Spark placed the step, SAM never saw its object in hand.* Usually a naming miss. Spark names what's in the person's hands in plain words, SAM searches again, and the rules run again.
   - *Spark said skipped, SAM saw the object in hand.* Spark looks closely at that moment. If it now sees the step performed, the step is verified: both witnesses agree on a specific moment. In `8_3` this finds two chocolate chips dropped into the mug at 2:42, which Spark missed watching the whole video.
   - A "no" never marks a step missing. One clip can't show a step never happened: in `8_50` the chocolate went in at 3:03, a moment both models missed, while the clip SAM pointed to only showed the bag being put away. **proofstep changes its mind on evidence found, never on evidence not found.**

   `--no-second-look` stops after stage 3, for comparison.

## Results so far

On 20 hand-checked CaptainCook4D videos (178 steps, 17 skipped), full table in [`eval/scorecard.md`](eval/scorecard.md):

| | Spark alone | proofstep |
|---|---|---|
| Wrong answers | 13 | **4** |
| Right when it answers | 93% | **97%** |
| Can't verify | 2 | 20 |
| Skipped steps flagged as missing | 16 of 17 | 8 of 17 |
| Order mistakes caught | 2 of 5 | 3 of 5 |

proofstep cuts wrong answers by about 70% by saying "can't verify" on 11% of steps. Known weaknesses, being worked on:

- **It gives up half of Spark's correct "missing" calls.** In 8 skipped steps SAM saw a related object in hand (a spoon, a bottle), and the second look correctly explained each one, but a single "no" never marks a step missing. Checking every such moment would let it conclude "missing" honestly.
- **The one false pass is shared with Spark.** Spark mistook a pepper grinder for salt, and SAM's fallback search for the generic word "box" matched it. Generic fallback names are too weak to count as evidence.

These rules were tuned on the same videos, so the final numbers will come from a fresh held-out set.

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
