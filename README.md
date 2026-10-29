# proofstep

Checks from a video whether each step of a physical procedure was actually done. When the evidence doesn't settle it, proofstep says **"can't verify, look at 2:42"** instead of guessing.

**Live demo (no install): https://desilva23.github.io/proofstep/**. Open the first video and click step S5.

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

Three test sets, every label checked by eye:

- **Two held-out sets**: 20 videos from four recipes the rules never saw (225 steps, 19 skipped). Each set was picked, label-checked and committed after the rules were frozen at `9c1269e`, then run once.
  - [`eval/scorecard_heldout.md`](eval/scorecard_heldout.md): microwave egg sandwich and French toast.
  - [`eval/scorecard_fresh.md`](eval/scorecard_fresh.md): cucumber raita and cheese pimiento.
- **Development set** ([`eval/scorecard.md`](eval/scorecard.md)): 20 videos from three recipes (178 steps, 17 skipped). The rules were developed while looking at these, so they flatter proofstep.

| | Spark alone, 20 unseen videos | proofstep, 20 unseen videos | Spark alone, dev | proofstep, dev |
|---|---|---|---|---|
| **Wrong answers** | 21 | **9** | 13 | 2 |
| Done steps called missing | 16 | **4** | 12 | 2 |
| Skipped steps passed as done | 5 | 5 | 1 | 0 |
| Right when it answers | 91% | **95%** | 93% | 99% |
| Can't verify | 0% | 12% | 1% | 9% |
| Skipped steps flagged as missing | 14 of 19 | 5 of 19 | 16 of 17 | 13 of 17 |
| Order mistakes caught | 6 of 9 | 6 of 9 | 2 of 5 | 4 of 5 |

**On unseen videos, proofstep cuts wrong answers by more than half (21 to 9) by sending 12% of steps to a person, each with the moment to check.** Almost all of the gain is in false alarms: Spark alone calls 16 completed steps "missing", proofstep 4. It does not reduce false passes (5 each), and it flags far fewer skipped steps as missing, usually abstaining instead. So it is a check on Spark's "not done", not a substitute for a human on "done".

What the unseen videos show:

- **False passes come from errors both models share.** In 17_28 both took the brown chaat masala for cumin; when Spark and SAM agree on the wrong thing, there's nothing to disagree about.
- **Tools used in many steps stay unresolved.** A knife or spoon can be in hand more often than the four moments proofstep checks, so those steps stay "can't verify".
- **SAM never finds an English muffin**, so "replace the top of the muffin" can't be backed up in any egg-sandwich video.
- **Some disagreements are about the labels.** 1_28 has a single microwave run, which the labels assign to the second microwave step (flagged before the run). In 17_28 the curd was stirred, not whisked; the dataset calls the step skipped, while proofstep reports it done with that substitution noted.
- **Substitutions are flagged, not called missing**: powdered sugar, a plate instead of a mug, cooking oil instead of olive oil, cheese melted with the peppers instead of on its own.

Cost: about $2.70 per video on the egg-sandwich and French-toast set and $3.80 on the longer raita and cheese videos, almost all of it SAM.

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

The viewer shows the video with SAM's box around the evidence object, a timeline of every step (green verified, red missing, amber can't verify, blue where the object was in hand), and each step's reasoning. Clicking a step jumps to the moment that matters. For CaptainCook4D videos, "Compare with human labels" overlays the dataset's labels and marks each answer right or wrong. Browsing reads saved results only. A link like `http://localhost:8765/#run=8_3_360p&step=S5` opens a specific step.

`python -m proofstep export <run>...` writes chosen reports as a static copy of the viewer into `docs/`, which is what the live demo serves.

Every API answer is cached under `data/cache/`, so re-running costs nothing. Each paid call is logged to `data/costs.jsonl`. SAM is billed per frame ($0.20 per 1,000), which makes it the main cost: about $0.10 per object for a 4-minute video at 2 frames per second. `--max-sam-usd` (default $3) stops a run that would cost more per video.

`muse-spark-1.3-contributor` is the default because it is about 12× cheaper, but Meta may train on what it receives. That is fine for the public dataset below and wrong for private footage: set `PROOFSTEP_SPARK_MODEL=muse-spark-1.3` for that.

## Procedures

A procedure is a JSON file with numbered steps and "this before that" rules. `procedures/` has the 24 CaptainCook4D recipes, generated from the dataset's task graphs.

**Your own procedure:** write the instructions in plain words, and Spark turns them into a checklist. It splits combined sentences into separate actions, drops tips and warnings, and adds an order rule only where a step depends on an earlier one. This reads the text only and costs a fraction of a cent.

```bash
python -m proofstep write my_instructions.txt     # saves procedures/<name>.json
```

In the viewer, **New check** does the whole thing: type the instructions (or pick a saved procedure), upload a video, see the estimated cost, confirm, and watch the result appear. Uploads are shrunk to 360p without audio before anything is sent. The viewer asks you to confirm that everyone in the video agreed to it being analysed, because the default Contributor models let Meta use what is sent.

## Data

[CaptainCook4D](https://github.com/CaptainCook4D) (Peddi et al., NeurIPS 2024): egocentric cooking videos with step timings and labelled mistakes, including skipped steps and wrong order. Videos are Apache 2.0, annotations MIT, and everyone filmed gave written consent.

One label fix is applied: in recording `8_3` the cinnamon and chocolate step labels are swapped, which we confirmed frame by frame (`LABEL_SWAPS` in `proofstep/datasets/captaincook4d.py`). A step counts as skipped when it has no times or is tagged "Missing Step": four steps in the dataset keep their times despite the tag.

**Scorecard.** `python -m proofstep.scorecard run` checks every test recording (5 at a time, with a spending cap), and `python -m proofstep.scorecard report` scores three systems against the labels: Spark alone, proofstep's first pass, and proofstep with the second look. The results are in `eval/scorecard.md`.

**Test set.** `eval/captaincook4d.json` lists the 20 recordings used for the scorecard: three recipes, 178 steps, 17 of them genuinely skipped, and 5 videos with steps out of order. Every label was checked by eye with `python -m proofstep.datasets.label_sheets <id>`, which lays out four frames per labelled step and, for videos with skipped steps, one frame every 10 seconds. The file records what each check found and why two recordings were left out.

## License

MIT
