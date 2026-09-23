#!/usr/bin/env python3
"""One seat, one turn. A standalone process so a dead seat never kills the round.

Reads the seat's own growing message list, appends this round's prompt, calls the
provider, and writes every artifact itself. Nothing is handed back through a caller.
Usage: turn.py <run_dir> <seat> <round>
"""
import json, os, sys, time, urllib.request, urllib.error

run_dir, seat, rnd = sys.argv[1:4]
run = json.load(open(f"{run_dir}/run.json"))
model = run["seats"][seat]
msgs_p = f"{run_dir}/seats/{seat}.messages.json"
rd = f"{run_dir}/rounds/{rnd}"
os.makedirs(rd, exist_ok=True)

msgs = json.load(open(msgs_p)) if os.path.exists(msgs_p) else [
    {"role": "system", "content": run["system"].replace("{SEAT}", run["labels"][seat])}
]
prompt = open(f"{rd}/{seat}.prompt.md").read()
send = msgs + [{"role": "user", "content": prompt}]

body = json.dumps({
    "model": model, "messages": send, "max_tokens": 8000,
    "plugins": [{"id": "web", "max_results": 6}],
}).encode()

pid = f"{run_dir}/pids/{seat}.{rnd}.pid"
open(pid, "w").write(str(os.getpid()))
t0 = time.time()
meta = {"seat": seat, "round": rnd, "model_requested": model, "ok": False}
text = ""
try:
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                 "Content-Type": "application/json", "X-Title": "clock"})
    d = json.load(urllib.request.urlopen(req, timeout=600))
    ch = (d.get("choices") or [{}])[0]
    m = ch.get("message") or {}
    text = (m.get("content") or "").strip()
    meta.update(model_served=d.get("model"), provider=d.get("provider"),
                finish_reason=ch.get("finish_reason"), usage=d.get("usage"), gen_id=d.get("id"),
                citations=[a.get("url_citation", {}).get("url")
                           for a in (m.get("annotations") or [])
                           if a.get("type") == "url_citation"])
except urllib.error.HTTPError as e:
    meta["error"] = e.read().decode()[:600]
except Exception as e:
    meta["error"] = f"{type(e).__name__}: {e}"[:600]
finally:
    os.path.exists(pid) and os.remove(pid)

meta["latency_s"] = round(time.time() - t0, 2)
meta["chars"] = len(text)
# a reply cut off at the token cap is a partial failure, not a success
meta["ok"] = bool(text) and meta.get("finish_reason") != "length"

open(f"{rd}/{seat}.md", "w").write(text + "\n" if text else "")
if meta["ok"]:  # only a complete reply joins the seat's memory of the conversation
    json.dump(send + [{"role": "assistant", "content": text}], open(msgs_p, "w"), indent=1)
with open(f"{run_dir}/seats/{seat}.meta.jsonl", "a") as f:
    f.write(json.dumps(meta) + "\n")

# A seat that produced nothing fails. Silence must never read as success.
sys.exit(0 if meta["ok"] else 1)
