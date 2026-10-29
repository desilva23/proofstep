# Scorecard

10 CaptainCook4D recordings from a second held-out set, chosen and label-checked after the rules were frozen (`eval/captaincook4d_fresh.json`), every label checked by eye: 110 steps, 12 of them skipped; 6 of the videos have steps out of order. Each system's answer for each step is compared with the human label.

| | Spark alone | proofstep, first pass | proofstep, second look | proofstep, second look + search |
|---|---|---|---|---|
| Right | 96 of 110 | 71 of 110 | 91 of 110 | 91 of 110 |
| **Wrong: skipped step passed as done** | **3** | **0** | **3** | **3** |
| Wrong: done step called missing | 10 | 0 | 1 | 1 |
| Can't verify | 1 | 39 | 15 | 15 |
| Right when it answers | 88% | 100% | 96% | 96% |
| Skipped steps caught | 9 of 12 | 0 of 12 | 3 of 12 | 3 of 12 |
| Order mistakes caught | 5 of 6 | 4 of 6 | 5 of 6 | 5 of 6 |
| Order flagged on a video without one | 0 | 0 | 0 | 0 |

Spark alone means its first answer about the whole video, taken at face value: done = verified, skipped = missing, can't tell = can't verify.

Can't verify, with the search: 15 steps. 6 come with a "likely at" moment, and for 3 of those the moment is inside the labelled step (5 s slack); 9 have no pointer.

Verified with a substitution noted (done, but not as written): 17_28 S1: orange plastic measuring cup used to stir instead of a whisk; 27_37 S1: added to the small bowl containing chopped peppers instead of a separate empty microwave-safe cup; 27_37 S6: bowl containing shredded cheese mixed with chopped red pepper instead of a cup with cheese alone, heated for ~10 seconds instead of 30 seconds

Cost: about $3.83 per video on average (10 videos, 110 steps), almost all of it SAM.

## Per video (proofstep, second look + search)

| Video | Recipe | Steps | Skipped | Order mistake | Right | Wrong | Can't verify | Order flagged |
|---|---|---|---|---|---|---|---|---|
| 17_28 | cucumberraita | 11 | 3 |  | 8 | 3 | 0 |  |
| 17_36 | cucumberraita | 11 | 4 | yes | 6 | 0 | 5 |  |
| 17_43 | cucumberraita | 11 | 1 | yes | 9 | 0 | 2 | yes |
| 17_40 | cucumberraita | 11 | 1 | yes | 10 | 0 | 1 | yes |
| 17_14 | cucumberraita | 11 | 0 |  | 10 | 0 | 1 |  |
| 27_37 | cheesepimiento | 11 | 0 | yes | 10 | 0 | 1 | yes |
| 27_49 | cheesepimiento | 11 | 0 | yes | 11 | 0 | 0 | yes |
| 27_38 | cheesepimiento | 11 | 2 | yes | 9 | 1 | 1 | yes |
| 27_34 | cheesepimiento | 11 | 1 |  | 7 | 0 | 4 |  |
| 27_4 | cheesepimiento | 11 | 0 |  | 11 | 0 | 0 |  |
