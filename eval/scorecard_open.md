# Scorecard

3 CaptainCook4D recordings from the 3 confirmation videos that finished on Muse Spark Open before its credits ran out (`eval/captaincook4d_open.json`), every label checked by eye: 51 steps, 9 of them skipped; 0 of the videos have steps out of order. Each system's answer for each step is compared with the human label.

| | Spark alone | proofstep, first pass | proofstep, second look | proofstep, second look + search | same, clip questions on Muse Spark Open |
|---|---|---|---|---|---|
| Right | 40 of 51 | 21 of 51 | 31 of 51 | 31 of 51 | 34 of 51 |
| **Wrong: skipped step passed as done** | **0** | **0** | **0** | **0** | **0** |
| Wrong: done step called missing | 11 | 1 | 2 | 0 | 1 |
| Can't verify | 0 | 29 | 18 | 20 | 16 |
| Right when it answers | 78% | 95% | 94% | 100% | 97% |
| Skipped steps caught | 9 of 9 | 1 of 9 | 2 of 9 | 2 of 9 | 2 of 9 |
| Order mistakes caught | 0 of 0 | 0 of 0 | 0 of 0 | 0 of 0 | 0 of 0 |
| Order flagged on a video without one | 0 | 0 | 1 | 1 | 0 |

Spark alone means its first answer about the whole video, taken at face value: done = verified, skipped = missing, can't tell = can't verify.

Can't verify, with the search: 20 steps. 6 come with a "likely at" moment, and for 5 of those the moment is inside the labelled step (5 s slack); 14 have no pointer.

Verified with a substitution noted (done, but not as written): 10_50 S1: white plate instead of cutting board; 10_31 S10: black-handled kitchen/steak knife instead of butter knife

Cost: about $2.66 per video on average (3 videos, 51 steps), almost all of it SAM.

## Per video (proofstep, second look + search)

| Video | Recipe | Steps | Skipped | Order mistake | Right | Wrong | Can't verify | Order flagged |
|---|---|---|---|---|---|---|---|---|
| 10_50 | pinwheels | 17 | 6 |  | 10 | 0 | 7 |  |
| 10_6 | pinwheels | 17 | 0 |  | 12 | 0 | 5 |  |
| 10_31 | pinwheels | 17 | 3 |  | 9 | 0 | 8 | yes |
