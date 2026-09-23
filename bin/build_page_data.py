#!/usr/bin/env python3
"""Emit one run as a JS data file for the reading view."""
import json, sys, os, glob
run_dir = sys.argv[1]
run = json.load(open(f"{run_dir}/run.json"))
ORDER = run["order"]
meta = {}
for f in glob.glob(f"{run_dir}/seats/*.meta.jsonl"):
    for line in open(f):
        d = json.loads(line)
        meta[(d["seat"], d["round"])] = d   # last write wins = the turn that stuck

rounds = []
for rd in sorted(glob.glob(f"{run_dir}/rounds/*")):
    key = os.path.basename(rd)
    if not os.path.isdir(rd) or key.startswith("zz-"):
        continue  # synthesis is presented on its own, not as a round
    turns = []
    for s in ORDER:
        p = f"{rd}/{s}.md"
        if not os.path.exists(p):
            continue
        t = open(p).read().strip()
        if not t:
            continue
        d = meta.get((s, key), {})
        u = d.get("usage") or {}
        turns.append({"seat": s, "text": t, "latency": d.get("latency_s"),
                      "tokens": u.get("total_tokens"), "cost": u.get("cost"),
                      "cites": len(d.get("citations") or []),
                      "citations": (d.get("citations") or [])[:6]})
    if turns:
        rounds.append({"key": key, "turns": turns})

totals = {"turns": 0, "tokens": 0, "cost": 0.0, "cites": 0}
per = {}
for (s, k), d in meta.items():
    if not d.get("ok"):
        continue
    u = d.get("usage") or {}
    totals["turns"] += 1
    totals["tokens"] += u.get("total_tokens") or 0
    totals["cost"] += u.get("cost") or 0
    totals["cites"] += len(d.get("citations") or [])
    p = per.setdefault(s, {"tokens": 0, "cost": 0.0, "cites": 0, "turns": 0})
    p["turns"] += 1; p["tokens"] += u.get("total_tokens") or 0
    p["cost"] += u.get("cost") or 0; p["cites"] += len(d.get("citations") or [])

synth = ""
if os.path.exists(f"{run_dir}/synthesis.md"):
    synth = open(f"{run_dir}/synthesis.md").read().strip()

out = {"run_id": run["run_id"], "question": run["prompt"], "date": run["date"],
       "labels": run["labels"], "models": run["seats"], "order": ORDER,
       "rounds": rounds, "synthesis": synth, "totals": totals, "per_seat": per}
sys.stdout.write("window.CLOCK_RUN = " + json.dumps(out, indent=1) + ";\n")
