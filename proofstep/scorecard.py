"""Scorecard: run the test set, then score Spark alone, proofstep's first pass and the full pipeline against the labels.

    python -m proofstep.scorecard run --workers 5     # every test recording; cached answers are reused
    python -m proofstep.scorecard report              # scores whatever has been run; writes eval/scorecard.md

--set heldout uses the held-out set instead, chosen and label-checked after the rules were frozen.
"""

import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import api, config
from .datasets import captaincook4d as cc4d
from .decide import CANT_VERIFY, MISSING, VERIFIED

EVAL = config.ROOT / "eval"
# name: (test set file, results file, how the report describes the set)
SETS = {
    "dev": ("captaincook4d.json", "scorecard.md", "the development set, which the rules were developed on"),
    "heldout": ("captaincook4d_heldout.json", "scorecard_heldout.md",
                "the held-out set, chosen and label-checked after the rules were frozen"),
}
LOGS = config.RUNS / "logs"

SYSTEMS = {"spark": "Spark alone", "first": "proofstep, first pass", "full": "proofstep with second look"}
SPARK_TO_STATUS = {"done": VERIFIED, "not_done": MISSING, "cannot_tell": CANT_VERIFY}


def _test_ids(test_set: str = "dev") -> list[str]:
    return [r["id"] for r in json.loads((EVAL / SETS[test_set][0]).read_text())["recordings"]]


def _costs() -> list[dict]:
    return [json.loads(line) for line in api.COSTS.read_text().splitlines() if line.strip()] if api.COSTS.exists() else []


def run(test_set: str, workers: int, max_sam_usd: float, max_total_usd: float) -> None:
    start = sum(c["usd"] for c in _costs())
    LOGS.mkdir(parents=True, exist_ok=True)

    def one(rid: str) -> str:
        if sum(c["usd"] for c in _costs()) - start > max_total_usd:
            return "not started: this run passed its budget"
        log = LOGS / f"{rid}.log"
        with log.open("w") as f:
            # The second command reuses every cached answer, so it only re-applies the rules without stage 4.
            for extra in ([], ["--no-second-look"]):
                done = subprocess.run([sys.executable, "-u", "-m", "proofstep", "cc4d", rid,
                                       "--max-sam-usd", str(max_sam_usd), *extra],
                                      stdout=f, stderr=subprocess.STDOUT, cwd=config.ROOT)
                if done.returncode:
                    return f"failed, see {log}"
        return "done"

    ids = _test_ids(test_set)
    with ThreadPoolExecutor(workers) as pool:
        futures = {pool.submit(one, rid): rid for rid in ids}
        for n, future in enumerate(as_completed(futures), 1):
            spent = sum(c["usd"] for c in _costs()) - start
            print(f"[{n}/{len(ids)}] {futures[future]}: {future.result()}  (this run so far ${spent:.2f})", flush=True)


def _statuses(rid: str) -> dict[str, dict] | None:
    full, first = config.RUNS / f"{rid}_360p.json", config.RUNS / f"{rid}_360p_first_look.json"
    if not (full.exists() and first.exists()):
        return None
    full, first = json.loads(full.read_text()), json.loads(first.read_text())
    return {
        "spark": {s["id"]: SPARK_TO_STATUS[s["spark"]["status"]] for s in first["steps"]},
        "first": {s["id"]: s["status"] for s in first["steps"]},
        "full": {s["id"]: s["status"] for s in full["steps"]},
        "order": {"spark": _spark_order_flag(first), "first": bool(first["order_problems"]),
                  "full": bool(full["order_problems"])},
    }


def _spark_order_flag(report: dict) -> bool:
    """Spark alone flags an order mistake if two steps it calls done break a rule by its own times."""
    from .procedure import Procedure
    procedure = Procedure.load(config.ROOT / "procedures" / f"{report['procedure']}.json")
    start = {s["id"]: s["spark"]["start"] for s in report["steps"]
             if s["spark"]["status"] == "done" and s["spark"]["start"] is not None}
    return any(a in start and b in start and start[b] < start[a] for a, b in procedure.rules)


def report(test_set: str = "dev") -> str:
    ids = _test_ids(test_set)
    set_file, out_file, described = SETS[test_set]
    totals = {k: {"right": 0, "false_pass": 0, "false_alarm": 0, "abstain": 0, "skipped_caught": 0,
                  "order_caught": 0, "order_false": 0} for k in SYSTEMS}
    rows, missing_runs = [], []
    n_steps = n_skipped = n_order = 0
    for rid in ids:
        got = _statuses(rid)
        if got is None:
            missing_runs.append(rid)
            continue
        truth = cc4d.truth(rid)
        has_order_mistake = any("Order Error" in s["errors"] for s in truth["steps"].values())
        n_order += has_order_mistake
        per = {}
        for system in SYSTEMS:
            t = totals[system]
            right = wrong = abstain = 0
            for sid, label in truth["steps"].items():
                status = got[system].get(sid)
                if status == CANT_VERIFY:
                    t["abstain"] += 1
                    abstain += 1
                elif (status == VERIFIED) == label["happened"]:
                    t["right"] += 1
                    right += 1
                    t["skipped_caught"] += not label["happened"]
                else:
                    t["false_pass" if status == VERIFIED else "false_alarm"] += 1
                    wrong += 1
            flagged = got["order"][system]
            t["order_caught"] += flagged and has_order_mistake
            t["order_false"] += flagged and not has_order_mistake
            per[system] = (right, wrong, abstain, flagged)
        n_steps += len(truth["steps"])
        n_skipped += sum(not s["happened"] for s in truth["steps"].values())
        rows.append((rid, truth["recipe"], len(truth["steps"]),
                     sum(not s["happened"] for s in truth["steps"].values()), has_order_mistake, per))

    # Cost per video, from the cost log. 8_3 and 8_50 also carry development re-runs, so they are left out.
    per_video = {}
    for c in _costs():
        m = re.search(r"\b(\d+_\d+)_360p", c["label"])
        if m:
            per_video[m.group(1)] = per_video.get(m.group(1), 0) + c["usd"]
    fresh = [per_video[r] for r, *_ in rows if r in per_video and r not in ("8_3", "8_50")]

    def pct(a: int, b: int) -> str:
        return f"{100 * a / b:.0f}%" if b else "-"

    lines = [
        "# Scorecard",
        "",
        f"{len(rows)} CaptainCook4D recordings from {described} (`eval/{set_file}`), every label checked by eye: "
        f"{n_steps} steps, {n_skipped} of them skipped; {n_order} of the videos have steps out of order. "
        "Each system's answer for each step is compared with the human label.",
        "",
        "| | " + " | ".join(SYSTEMS.values()) + " |",
        "|---|" + "---|" * len(SYSTEMS),
    ]
    t = totals

    def row(name: str, fn) -> None:
        lines.append(f"| {name} | " + " | ".join(fn(k) for k in SYSTEMS) + " |")

    row("Right", lambda k: f"{t[k]['right']} of {n_steps}")
    row("**Wrong: skipped step passed as done**", lambda k: f"**{t[k]['false_pass']}**")
    row("Wrong: done step called missing", lambda k: str(t[k]["false_alarm"]))
    row("Can't verify", lambda k: str(t[k]["abstain"]))
    row("Right when it answers", lambda k: pct(t[k]["right"], t[k]["right"] + t[k]["false_pass"] + t[k]["false_alarm"]))
    row("Skipped steps caught", lambda k: f"{t[k]['skipped_caught']} of {n_skipped}")
    row("Order mistakes caught", lambda k: f"{t[k]['order_caught']} of {n_order}")
    row("Order flagged on a video without one", lambda k: str(t[k]["order_false"]))
    lines += ["", "Spark alone means its first answer about the whole video, taken at face value: done = verified, "
                  "skipped = missing, can't tell = can't verify.", ""]
    subs = [(rid, s["id"], s["substitution"]) for rid in ids if (config.RUNS / f"{rid}_360p.json").exists()
            for s in json.loads((config.RUNS / f"{rid}_360p.json").read_text())["steps"] if s.get("substitution")]
    if subs:
        lines += [f"Verified with a substitution noted (done, but not as written): "
                  + "; ".join(f"{rid} {sid}: {text}" for rid, sid, text in subs), ""]
    if fresh:
        lines += [f"Cost: about ${sum(fresh) / len(fresh):.2f} per video on average ({len(fresh)} videos, "
                  f"{sum(r[2] for r in rows if r[0] not in ('8_3', '8_50'))} steps), almost all of it SAM.", ""]

    lines += ["## Per video (proofstep with second look)", "",
              "| Video | Recipe | Steps | Skipped | Order mistake | Right | Wrong | Can't verify | Order flagged |",
              "|---|---|---|---|---|---|---|---|---|"]
    for rid, recipe, steps, skipped, order, per in rows:
        right, wrong, abstain, flagged = per["full"]
        lines.append(f"| {rid} | {recipe} | {steps} | {skipped} | {'yes' if order else ''} | {right} | "
                     f"{wrong} | {abstain} | {'yes' if flagged else ''} |")
    if missing_runs:
        lines += ["", f"Not run yet: {', '.join(missing_runs)}"]
    text = "\n".join(lines) + "\n"
    (EVAL / out_file).write_text(text)
    return text


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m proofstep.scorecard", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--workers", type=int, default=5)
    r.add_argument("--max-sam-usd", type=float, default=6.0, help="per video")
    r.add_argument("--max-total-usd", type=float, default=50.0, help="stop starting new videos past this")
    rep = sub.add_parser("report")
    for p in (r, rep):
        p.add_argument("--set", dest="test_set", choices=list(SETS), default="dev")
    args = ap.parse_args()
    if args.cmd == "run":
        run(args.test_set, args.workers, args.max_sam_usd, args.max_total_usd)
    print(report(args.test_set))


if __name__ == "__main__":
    main()
