"""Command line: python -m proofstep {models,check,cc4d} ..."""

import argparse
import json
import sys
from pathlib import Path

from . import api, config, decide, evidence, watch
from .procedure import Procedure

MARK = {decide.VERIFIED: "VERIFIED", decide.MISSING: "MISSING", decide.CANT_VERIFY: "CAN'T VERIFY"}


def run(procedure: Procedure, video_path: Path, *, max_sam_usd: float, effort: str) -> dict:
    spark = watch.watch(procedure, video_path, effort=effort)
    concepts = [o for s in spark["steps"].values() for o in s["objects"]]
    sam = evidence.gather(video_path, concepts, max_usd=max_sam_usd)
    report = decide.decide(procedure, spark, sam)
    report["video"] = str(video_path)
    config.RUNS.mkdir(exist_ok=True)
    out = config.RUNS / f"{video_path.stem}.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"Report saved to {out}")
    return report


def show(report: dict, truth: dict | None = None) -> None:
    print(f"\n{report['procedure']} - {Path(report['video']).name}")
    for s in report["steps"]:
        line = f"  {s['id']:<4}{MARK[s['status']]:<14}{s['text']}"
        if truth:
            label = truth["steps"].get(s["id"])
            if label:
                happened = label["happened"]
                verdict = {
                    (decide.VERIFIED, True): "right", (decide.MISSING, False): "right",
                    (decide.VERIFIED, False): "WRONG: false pass", (decide.MISSING, True): "WRONG: false alarm",
                }.get((s["status"], happened), "abstained")
                line += f"   [label: {'done' if happened else 'skipped'}; {verdict}]"
        print(line)
        print(f"        {s['reason']}")
    for o in report["order_problems"]:
        print(f"  ORDER  {o['reason']}")
    for m in report["other_mistakes"]:
        when = f" at {decide.clock(m['time_sec'])}" if m.get("time_sec") is not None else ""
        print(f"  NOTED BY SPARK (not checked){when}: {m['description']}")
    c = report["counts"]
    print(f"  {c['verified']} verified, {c['missing']} missing, {c['cant_verify']} can't verify")


def main() -> None:
    ap = argparse.ArgumentParser(prog="proofstep", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("models", help="list the models your API key can use (free)")
    check = sub.add_parser("check", help="check one video against a procedure file")
    check.add_argument("procedure", type=Path)
    check.add_argument("video", type=Path)
    cc = sub.add_parser("cc4d", help="check CaptainCook4D recordings and compare with the human labels")
    cc.add_argument("recordings", nargs="+")
    for p in (check, cc):
        p.add_argument("--max-sam-usd", type=float, default=3.0, help="stop if SAM would cost more per video")
        p.add_argument("--effort", default="medium", choices=["minimal", "low", "medium", "high", "xhigh"])
    args = ap.parse_args()

    try:
        if args.cmd == "models":
            for m in sorted(m["id"] for m in api.get_json("/models").get("data", [])):
                print(m)
        elif args.cmd == "check":
            show(run(Procedure.load(args.procedure), args.video, max_sam_usd=args.max_sam_usd, effort=args.effort))
        else:
            from .datasets import captaincook4d as cc4d
            for rid in args.recordings:
                truth = cc4d.truth(rid)
                procedure = Procedure.load(config.ROOT / "procedures" / f"{truth['recipe']}.json")
                report = run(procedure, cc4d.fetch_video(rid), max_sam_usd=args.max_sam_usd, effort=args.effort)
                show(report, truth)
    except (api.ApiError, evidence.TooExpensive) as e:
        sys.exit(f"\n{e}")


if __name__ == "__main__":
    main()
