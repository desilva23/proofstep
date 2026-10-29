# Scorecard

20 CaptainCook4D recordings from the hand-checked test set (`eval/captaincook4d.json`): 178 steps, 17 of them skipped; 5 of the videos have steps out of order. Each system's answer for each step is compared with the human label.

| | Spark alone | proofstep, first pass | proofstep with second look |
|---|---|---|---|
| Right | 163 of 178 | 136 of 178 | 154 of 178 |
| **Wrong: skipped step passed as done** | **1** | **1** | **1** |
| Wrong: done step called missing | 12 | 3 | 3 |
| Can't verify | 2 | 38 | 20 |
| Right when it answers | 93% | 97% | 97% |
| Skipped steps caught | 16 of 17 | 8 of 17 | 8 of 17 |
| Order mistakes caught | 2 of 5 | 2 of 5 | 3 of 5 |
| Order flagged on a video without one | 0 | 0 | 0 |

Spark alone means its first answer about the whole video, taken at face value: done = verified, skipped = missing, can't tell = can't verify.

Cost: about $2.17 per video on average (18 videos, 164 steps), almost all of it SAM.

## Per video (proofstep with second look)

| Video | Recipe | Steps | Skipped | Order mistake | Right | Wrong | Can't verify | Order flagged |
|---|---|---|---|---|---|---|---|---|
| 8_3 | spicedhotchocolate | 7 | 0 |  | 7 | 0 | 0 |  |
| 8_50 | spicedhotchocolate | 7 | 2 | yes | 4 | 0 | 3 | yes |
| 8_31 | spicedhotchocolate | 7 | 2 |  | 7 | 0 | 0 |  |
| 8_44 | spicedhotchocolate | 7 | 2 |  | 7 | 0 | 0 |  |
| 8_40 | spicedhotchocolate | 7 | 0 | yes | 4 | 0 | 3 |  |
| 8_25 | spicedhotchocolate | 7 | 0 |  | 7 | 0 | 0 |  |
| 8_16 | spicedhotchocolate | 7 | 0 |  | 7 | 0 | 0 |  |
| 12_43 | tomatomozzarellasalad | 9 | 4 |  | 5 | 2 | 2 |  |
| 12_17 | tomatomozzarellasalad | 9 | 0 |  | 9 | 0 | 0 |  |
| 12_26 | tomatomozzarellasalad | 9 | 1 |  | 8 | 0 | 1 |  |
| 12_51 | tomatomozzarellasalad | 9 | 0 |  | 9 | 0 | 0 |  |
| 12_41 | tomatomozzarellasalad | 9 | 0 | yes | 5 | 1 | 3 |  |
| 12_10 | tomatomozzarellasalad | 9 | 0 |  | 9 | 0 | 0 |  |
| 12_38 | tomatomozzarellasalad | 9 | 1 |  | 8 | 0 | 1 |  |
| 7_32 | breakfastburritos | 11 | 2 |  | 10 | 0 | 1 |  |
| 7_35 | breakfastburritos | 11 | 1 | yes | 9 | 0 | 2 | yes |
| 7_38 | breakfastburritos | 11 | 0 | yes | 8 | 1 | 2 | yes |
| 7_1 | breakfastburritos | 11 | 0 |  | 11 | 0 | 0 |  |
| 7_5 | breakfastburritos | 11 | 0 |  | 11 | 0 | 0 |  |
| 7_26 | breakfastburritos | 11 | 2 |  | 9 | 0 | 2 |  |
