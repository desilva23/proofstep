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
   - *Spark said skipped, SAM saw the object in hand.* Spark looks closely at **every** such moment. An agreed "yes" at any of them verifies the step. If every moment is agreed to be something else (rinsing the spoon, moving the bottle aside), the step is missing. If the looks disagree, it stays "can't verify" with both accounts. In `8_3`, the short clip sees two chocolate chips dropped into the mug at 2:42, which Spark missed watching the whole video, while the wide clip doesn't, so the step stays "can't verify" instead of being guessed.
   - A step done with a different item than written is reported as done with a substitution, not as missing.
   - One "no" is never enough on its own. In `8_50` the chocolate went in at 3:03, while the moment SAM flagged only showed the bag being put away. **proofstep changes its mind on evidence found, never on evidence not found**, so every sighting needs a positive explanation before a step is called missing.

   `--no-second-look` stops after stage 3, for comparison.
5. **Search where the step must be** (`proofstep/search.py`). For each step still unresolved, the procedure's order gives a window (after the steps that must come before, before the ones that must come after). Spark searches it in overlapping 20-second slices, then the rest of the video in case it was done out of order. Each "yes" is checked with an open question on a wider clip, "which step is the person doing here?", and counts only if Spark names this step unprompted.
   - **The search points; a person decides.** What it finds becomes "can't verify, likely at 2:42", so whoever checks watches a few seconds instead of the whole video. It never verifies a step by itself.
   - If it finds a step that proofstep had called missing, the step goes back to "can't verify", so nobody is accused on one witness's word.

## Results

Every label in every test set was checked by eye. Each unseen set was picked, label-checked and committed after the rules it tests were frozen, then run once.

- **25 unseen videos** from seven recipes the rules were never developed on (301 steps, 34 skipped):
  - [`eval/scorecard_heldout.md`](eval/scorecard_heldout.md): egg sandwich, French toast.
  - [`eval/scorecard_fresh.md`](eval/scorecard_fresh.md): cucumber raita, cheese pimiento.
  - [`eval/scorecard_confirm.md`](eval/scorecard_confirm.md): pinwheels, zoodles, butter corn cup. This set checks the window search, which came last.
- **Development set** ([`eval/scorecard.md`](eval/scorecard.md)): 20 videos from three recipes (178 steps). The rules were developed while looking at these, so they flatter proofstep.

| | Spark alone, 25 unseen videos | proofstep, 25 unseen videos | Spark alone, dev | proofstep, dev |
|---|---|---|---|---|
| **Wrong answers** | 34 | **9** | 13 | 2 |
| Done steps called missing | 29 | **4** | 12 | 2 |
| Skipped steps passed as done | 5 | 5 | 1 | 0 |
| Right when it answers | 89% | **96%** | 93% | 99% |
| Can't verify (sent to a person) | 0% | 18% | 1% | 9% |
| ...with a "likely at" moment | | 22 of 55 | | 7 of 16 |
| Skipped steps flagged as missing | 29 of 34 | 9 of 34 | 16 of 17 | 13 of 17 |
| Order mistakes caught | 7 of 10 | 7 of 10 | 2 of 5 | 4 of 5 |

**On unseen videos, proofstep makes about a quarter as many wrong calls as Spark alone (9 against 34). It gets there by sending 18% of steps to a person, often with the second to watch.** Almost all of the gain is in false accusations: Spark alone says a completed step was skipped 29 times, proofstep 4. It doesn't reduce false passes (5 each), and it usually abstains on skipped steps rather than calling them missing. So proofstep is a check on "not done", not a replacement for a person on "done".

The first unseen set, `heldout`, was later used for the failed fixes described under "What didn't work". They were reverted, so its numbers didn't change, but it isn't untouched any more. On the other 15 videos, which were never used for any tuning (186 steps), proofstep made 4 wrong calls against 26 for Spark alone, and sent 23% of steps to a person.

**Everything above is cooking.** One unscored trial outside it, a 92-second circuit build from [EgoOops](https://y-haneji.github.io/EgoOops-project-page/) (CC BY-SA 4.0) with the dataset's own instructions typed in, went poorly. 8 of 9 steps came back "can't verify", because SAM couldn't find several of the small parts, though 6 of those got a "likely at" moment on or right next to the step. The one verified step, putting in the batteries, is labelled as not done: they are already in the box in the first frame. Assembly work would need its own object names and its own test set.

The window search is measured on the confirmation set, which was picked after the search was frozen:
- It changed no answer into a wrong one.
- It found two steps proofstep had wrongly called missing, and sent them back to a person.
- 8 of the 28 can't-verify steps got a "likely at" moment, and 7 of those were inside the labelled step.

What the unseen videos show:

- **False passes come from errors both models share.** In 17_28 both took the brown chaat masala for cumin. When Spark and SAM agree on the wrong thing, there's nothing to disagree about.
- **Fiddly steps stay unresolved.** Toothpicks and dental floss in pinwheels, or a knife used for several cuts, leave many "can't verify". The confirmation set's 37% abstention rate comes mostly from pinwheels.
- **SAM never finds an English muffin**, so "replace the top of the muffin" can't be backed up in any egg-sandwich video.
- **Some disagreements are about the labels.** 1_28 has a single microwave run, which the labels assign to the second microwave step (flagged before the run). In 17_28 the curd was stirred, not whisked; the dataset calls the step skipped, while proofstep reports it done with that substitution noted.
- **Substitutions are flagged, not called missing**: powdered sugar, a plate instead of a mug or cutting board, cooking oil instead of olive oil, a steak knife instead of a butter knife.

Cost: $2.70 to $3.80 per video depending on length, almost all of it SAM; the window search adds about a cent.

### What didn't work

After the held-out run we tried two fixes, scored them on both sets, and reverted both:

- **"A tool used in several steps can't prove a step on its own."** It turned 27 correct answers into "can't verify" and fixed nothing. A microwave in hand at the right time really is good evidence, even though the recipe uses it twice.
- **"Check up to 8 moments instead of 4."** It settled 2 abstentions but added 2 false "missing" calls. In both, the real knife moment had already been credited to another knife step, so every remaining moment was something else.

The second failure shows the limit of the current approach: "every sighting is explained" only means "missing" if no sighting was set aside for another step first.

Later, the window search was first allowed to decide. On the 20 held-out videos that gave the most right answers of any version (208 against Spark's 203) and cut "can't verify" to 3%. But it passed two more skipped steps as done: Spark described peeling a cucumber that was only chopped, and took another seasoning for salt, and an open "which step is this?" question didn't catch either. A safety check shouldn't add those, so the search now only points.

## What we learned about Meta's models

Things we didn't find in the docs, each measured during the hackathon. Useful to anyone building on Muse Spark and SAM 3.1.

**Muse Spark Open**
- **8 still frames tied Muse Spark on video.** On 60 labelled clips from 8 recipes, both scored 95.0%: yes on 93% of clips where the step happens, no on 97% of clips where it doesn't, with one false yes each ([`eval/frames_vs_video.json`](eval/frames_vs_video.json)). It's a small sample, and only 6 of the 30 negative clips were look-alike steps, so treat it as a promising result, not a proof.
- **It can't break the tie between models that see the same thing.** Asked to confirm the window search's pointers, it accepted 20 of 24 right ones but also 4 of 5 wrong ones. Asked to re-check verified steps, it caught 1 of the 5 false passes and wrongly rejected 10% of good ones. On a lengthwise zucchini slice that looks like peeling, both models said peeling.
- **Allow it room to think.** With a 4,000-token limit, about 1 reply in 25 came back empty because reasoning used up the limit. proofstep allows 16,000. Baseten also accepts at most 8 images per request.

**Muse Spark**
- **There's no confidence signal, and asking again doesn't create one.** `logprobs` returns HTTP 400 on every Muse text model. Re-asking the same question about the whole video gave identical answers: 0 of 14 answers changed across 3 runs, and the wrong ones were wrong every time. That's why proofstep gets its confidence from a second model instead.
- **Whole-video answers miss brief actions.** Watching all 7 minutes of 8_3, Spark said the chocolate was never added. Asked about a 20-second clip around that moment, it sees two chips dropped into the mug at 2:42. Short clips find what a whole-video pass misses.
- **Answers depend on clip length.** The same moment, asked the same question, can get "yes" on a 33-second clip and "no" on a 58-second one (8_3, the chocolate step). proofstep only acts on an answer that both clip lengths agree on.
- **Small wording changes flip answers; identical prompts don't.** Re-running a prompt gives the same answer. One reworded instruction turned "sugar added" into "sugar skipped" on the same video.
- **Leading questions lean towards yes.** "Is step S5 performed here?" said yes to look-alike steps (pepper for salt). The open question "which step is the person doing?" is harder to fool, though not immune.
- **Contributor models are cheap enough to ask many small questions.** Watching a whole video costs about one cent, and a short-clip question about a tenth of a cent. That's what makes searching a window in 20-second slices practical.

**SAM 3.1**
- **It finds plain nouns, not ingredients or compound names.** "cinnamon" and "chocolate" matched nothing in any frame, while "spice jar" found the jar. "milk bottle", "sugar bag" and "measuring spoon" found nothing, while "bottle", "bag" and "spoon" did. So proofstep has Spark name the container it sees, not what's inside.
- **But a generic noun is weak evidence.** A fallback search for "box" "confirmed" salt when the box held pepper. A match under a generic name never verifies a step on its own.
- **"In hand" is a usable signal.** Overlapping SAM's object box with its hand box separates "the jar was used" from "the jar sat on the counter". That distinction is the core of every verdict.
- **It's the cost driver.** At $0.20 per 1,000 frames, SAM is almost all of the roughly $3 per video. Running it on a 2-frames-per-second copy keeps that down without losing the hand-object overlap.

**Operations**
- **Occasional transient failures recover on retry.** A response sometimes fails mid-answer with "The model failed to generate a response", and an upload once returned "Invalid upload request". Both succeeded when retried, so proofstep retries them automatically.

## Open-weight option

`--open-weights` runs the short-clip questions (second look and window search) and typed procedures on **Muse Spark Open**, which can be self-hosted. Any OpenAI-compatible server works: set `PROOFSTEP_OPEN_URL`. Muse Spark Open takes images, not video, so each clip becomes 8 evenly spaced frames ([`proofstep/open_weights.py`](proofstep/open_weights.py)). The whole-video pass and SAM 3.1 stay on the Meta Model API, so this isn't a fully offline mode: footage still reaches Meta's API for those two stages.

Results on the 3 confirmation videos that finished before the Baseten credits ran out (51 steps, all pinwheels; [`eval/scorecard_open.md`](eval/scorecard_open.md)):

| | Right | Wrong | Can't verify |
|---|---|---|---|
| Clip questions on Muse Spark, video | 31 | 0 | 20 |
| Clip questions on Muse Spark Open, 8 frames | 34 | 1 | 16 |

So far it holds up on real videos, but that's a small sample from one recipe. The published results above all use Muse Spark on video; this option doesn't change them. At about 1 cent a question it costs roughly 15 times a Contributor clip question, or $1 to $2 per video.

## Built during the hackathon

Everything in this repository was written during the building period. The repository was created on Oct 29, and the commit history shows each piece as it was built. That includes the pipeline (Spark, SAM, rules, second look, window search), the CaptainCook4D tooling and label checks, the four scored test sets, the viewer, typed procedures, the open-weight option, and the static demo site.

Before kickoff we read the API docs and wrote two throwaway feasibility tests (can Spark place recipe steps in time; can SAM find the objects). They were run on Oct 28, and their findings appear above. None of their code is in this repository.

Not ours, and used under their licences:
- the CaptainCook4D videos (Apache 2.0) and labels (MIT);
- Meta's models, through the Meta Model API;
- Python's standard library and ffmpeg.

## Run it

Needs Python 3.11+ and ffmpeg. No packages to install.

```bash
cp .env.example .env              # then put your Meta Model API key in it
python -m proofstep models        # free: checks the key and lists your models
python -m unittest discover -s tests   # offline tests of the decision rules, no API calls
python -m proofstep.datasets.captaincook4d 8_50 8_3     # labels, recipe procedures, two videos
python -m proofstep cc4d 8_50 8_3                       # check them and compare with the human labels
python -m proofstep check procedures/spicedhotchocolate.json my_video.mp4
python -m proofstep cc4d 10_50 --open-weights           # clip questions on Muse Spark Open (needs BASETEN_API_KEY)
```

To look through the results:

```bash
python -m proofstep serve         # then open http://localhost:8765
```

The viewer shows the video with SAM's box around the evidence object, a timeline of every step (green verified, red missing, amber can't verify, blue where the object was in hand), and each step's reasoning. Clicking a step jumps to the moment that matters. For CaptainCook4D videos, "Compare with human labels" overlays the dataset's labels and marks each answer right or wrong. Browsing reads saved results only. A link like `http://localhost:8765/#run=8_3_360p&step=S5` opens a specific step.

`python -m proofstep export <run>...` writes chosen reports as a static copy of the viewer into `docs/`, which is what the live demo serves.

Every API answer is cached under `data/cache/`, so re-running costs nothing. Each paid call is logged to `data/costs.jsonl`. SAM is billed per frame ($0.20 per 1,000), which makes it the main cost: about $0.10 per object for a 4-minute video at 2 frames per second. `--max-sam-usd` (default $3) stops a run that would cost more per video.

`muse-spark-1.3-contributor` is the default because it is about 12× cheaper, but Meta may train on what it receives. That is fine for the public dataset below and wrong for private footage: add `--private` to `check`, `write` or `serve` to use `muse-spark-1.3` instead. Spark calls then cost about 12× more, and the footage still goes to the Meta Model API. It can't be combined with `--open-weights`.

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
