# Scorecard

10 CaptainCook4D recordings from the held-out set, chosen and label-checked after the rules were frozen (`eval/captaincook4d_heldout.json`), every label checked by eye: 115 steps, 7 of them skipped; 3 of the videos have steps out of order. Each system's answer for each step is compared with the human label.

| | Spark alone | proofstep, first pass | proofstep with second look |
|---|---|---|---|
| Right | 107 of 115 | 86 of 115 | 98 of 115 |
| **Wrong: skipped step passed as done** | **2** | **2** | **2** |
| Wrong: done step called missing | 6 | 0 | 3 |
| Can't verify | 0 | 27 | 12 |
| Right when it answers | 93% | 98% | 95% |
| Skipped steps caught | 5 of 7 | 1 of 7 | 2 of 7 |
| Order mistakes caught | 1 of 3 | 1 of 3 | 1 of 3 |
| Order flagged on a video without one | 0 | 0 | 0 |

Spark alone means its first answer about the whole video, taken at face value: done = verified, skipped = missing, can't tell = can't verify.

Cost: about $2.71 per video on average (10 videos, 115 steps), almost all of it SAM.

## Per video (proofstep with second look)

| Video | Recipe | Steps | Skipped | Order mistake | Right | Wrong | Can't verify | Order flagged |
|---|---|---|---|---|---|---|---|---|
| 1_32 | microwaveeggsandwich | 12 | 1 | yes | 10 | 0 | 2 |  |
| 1_42 | microwaveeggsandwich | 12 | 0 | yes | 9 | 1 | 2 |  |
| 1_28 | microwaveeggsandwich | 12 | 1 |  | 9 | 3 | 0 |  |
| 1_7 | microwaveeggsandwich | 12 | 0 |  | 12 | 0 | 0 |  |
| 1_43 | microwaveeggsandwich | 12 | 1 | yes | 10 | 0 | 2 | yes |
| 9_36 | microwavefrenchtoast | 11 | 2 |  | 8 | 0 | 3 |  |
| 9_47 | microwavefrenchtoast | 11 | 2 |  | 8 | 1 | 2 |  |
| 9_8 | microwavefrenchtoast | 11 | 0 |  | 10 | 0 | 1 |  |
| 9_13 | microwavefrenchtoast | 11 | 0 |  | 11 | 0 | 0 |  |
| 9_108 | microwavefrenchtoast | 11 | 0 |  | 11 | 0 | 0 |  |
