#!/usr/bin/env python3
"""Merge seat metadata into the run index and a readable digest. Scripts move bytes."""
import json,sys,os,glob,datetime
run_dir=sys.argv[1]
run=json.load(open(f"{run_dir}/run.json"))
seats=[]
for m in sorted(glob.glob(f"{run_dir}/seats/*.meta.json")):
    d=json.load(open(m))
    name=d["seat"]
    d["text_file"]=f"seats/{name}.md"
    seats.append(d)
run["seats_result"]=seats
run["finished_utc"]=datetime.datetime.now(datetime.timezone.utc).isoformat()
run["ok_count"]=sum(1 for s in seats if s.get("ok"))
run["seat_count"]=len(seats)
json.dump(run,open(f"{run_dir}/run.json","w"),indent=2)

L=[f"# {run['run_id']}\n",f"**Q:** {run['prompt']}\n",
   f"_{run['ok_count']}/{run['seat_count']} seats ok_\n"]
for s in seats:
    txt=open(f"{run_dir}/{s['text_file']}").read().strip()
    L.append(f"\n## {s['seat']} — `{s.get('model_served') or s['model_requested']}`\n")
    L.append(f"_{s['latency_s']}s · {(s.get('usage') or {}).get('total_tokens','?')} tok · "
             f"{len(s.get('citations') or [])} citations · ok={s.get('ok')}_\n")
    L.append(txt if txt else f"**FAILED** — {json.dumps(s.get('error') or s)[:400]}")
    L.append("")
open(f"{run_dir}/digest.md","w").write("\n".join(L)+"\n")
