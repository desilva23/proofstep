# Scorecard

5 CaptainCook4D recordings from the confirmation set for the window search, chosen and label-checked after it was frozen (`eval/captaincook4d_confirm.json`), every label checked by eye: 76 steps, 15 of them skipped; 1 of the videos have steps out of order. Each system's answer for each step is compared with the human label.

| | Spark alone | proofstep, first pass | proofstep, second look | proofstep, second look + search |
|---|---|---|---|---|
| Right | 63 of 76 | 33 of 76 | 48 of 76 | 48 of 76 |
| **Wrong: skipped step passed as done** | **0** | **0** | **0** | **0** |
| Wrong: done step called missing | 13 | 1 | 2 | 0 |
| Can't verify | 0 | 42 | 26 | 28 |
| Right when it answers | 83% | 97% | 96% | 100% |
| Skipped steps caught | 15 of 15 | 1 of 15 | 4 of 15 | 4 of 15 |
| Order mistakes caught | 1 of 1 | 1 of 1 | 1 of 1 | 1 of 1 |
| Order flagged on a video without one | 0 | 0 | 1 | 1 |

Spark alone means its first answer about the whole video, taken at face value: done = verified, skipped = missing, can't tell = can't verify.

Can't verify, with the search: 28 steps. 8 come with a "likely at" moment, and for 7 of those the moment is inside the labelled step (5 s slack); 20 have no pointer.

Verified with a substitution noted (done, but not as written): 10_50 S1: white plate instead of cutting board; 10_31 S10: black-handled kitchen/steak knife instead of butter knife

Cost: about $2.77 per video on average (5 videos, 76 steps), almost all of it SAM.

## Per video (proofstep, second look + search)

| Video | Recipe | Steps | Skipped | Order mistake | Right | Wrong | Can't verify | Order flagged |
|---|---|---|---|---|---|---|---|---|
| 10_50 | pinwheels | 17 | 6 |  | 10 | 0 | 7 |  |
| 10_6 | pinwheels | 17 | 0 |  | 12 | 0 | 5 |  |
| 10_31 | pinwheels | 17 | 3 |  | 9 | 0 | 8 | yes |
| 18_31 | zoodles | 13 | 4 | yes | 7 | 0 | 6 | yes |
| 13_31 | buttercorncup | 12 | 2 |  | 10 | 0 | 2 |  |
