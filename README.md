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

## Results

Two test sets, every label checked by eye:

- **Held-out set** ([`eval/scorecard_heldout.md`](eval/scorecard_heldout.md)): 10 videos from two recipes the rules never saw (115 steps, 7 skipped). They were picked, label-checked and committed after the rules were frozen at `9c1269e`, then run once.
- **Development set** ([`eval/scorecard.md`](eval/scorecard.md)): 20 videos from three recipes (178 steps, 17 skipped). The rules were developed while looking at these, so they flatter proofstep.

| | Spark alone, held-out | proofstep, held-out | Spark alone, dev | proofstep, dev |
|---|---|---|---|---|
| Skipped steps passed as done | 2 | 2 | 1 | 0 |
| Done steps called missing | 6 | 3 | 12 | 2 |
| Right when it answers | 93% | **95%** | 93% | 99% |
| Can't verify | 0% | 10% | 1% | 9% |
| Skipped steps flagged as missing | 5 of 7 | 2 of 7 | 16 of 17 | 13 of 17 |
| Order mistakes caught | 1 of 3 | 1 of 3 | 2 of 5 | 4 of 5 |

**On unseen videos the gain is real but smaller than on the development set:** wrong answers fall from 8 to 5, and 10% of steps go to a person with the moment to check. It does not yet reduce false passes there. What the held-out set shows:

- **Tools used in many steps defeat the "check every moment" rule.** A knife or spoon can be in hand more often than the four moments proofstep checks, so those steps stay "can't verify" (5 of the 12).
- **SAM never finds an English muffin**, so the three "replace the top of the muffin" steps can't be backed up.
- **One of the two false passes was flagged as ambiguous before the run.** 1_28 has a single microwave run, which the labels assign to the second microwave step; proofstep assigns it to the first.
- **Substitutions are flagged, not called missing.** On the development set, five steps done with something other than written (powdered sugar, a plate instead of a mug, cooking oil instead of olive oil) come out as done with a substitution noted.

### What didn't work

After the held-out run we tried two fixes, scored them on both sets, and reverted both:

- **"A tool used in several steps can't prove a step on its own."** It turned 27 correct answers into "can't verify" and fixed nothing. A microwave in hand at the right time really is good evidence, even though the recipe uses it twice.
- **"Check up to 8 moments instead of 4."** It settled 2 abstentions but added 2 false "missing" calls. In both, the real knife moment had already been credited to another knife step, so every remaining moment was something else.

The second failure shows the limit of the current approach: "every sighting is explained" only means "missing" if no sighting was set aside for another step first.

## Run it

Needs Python 3.11+ and ffmpeg. No packages to install.

```bash
cp .env.example .env              # then put your Meta Model API key in it
python -m proofstep models        # free: checks the key and lists your models
python -m proofstep.datasets.captaincook4d 8_50 8_3     # labels, recipe procedures, two videos
python -m proofstep cc4d 8_50 8_3                       # check them and compare with the human labels
python -m proofstep check procedures/spicedhotchocolate.json my_video.mp4
```

To look through the results:

```bash
python -m proofstep serve         # then open http://localhost:8765
```

The viewer shows the video with SAM's box around the evidence object, a timeline of every step (green verified, red missing, amber can't verify, blue where the object was in hand), and each step's reasoning. Clicking a step jumps to the moment that matters. For CaptainCook4D videos, "Compare with human labels" overlays the dataset's labels and marks each answer right or wrong. It reads saved results only and never calls the API. A link like `http://localhost:8765/#run=8_3_360p&step=S5` opens a specific step.

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
