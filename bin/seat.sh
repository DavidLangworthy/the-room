#!/usr/bin/env bash
# One provider seat. Writes its own artifacts; never returns bytes through a caller.
# Usage: seat.sh <run_dir> <seat> <model_id> <prompt_file>
set -uo pipefail
RUN_DIR=$1; SEAT=$2; MODEL=$3; PROMPT_FILE=$4

RAW="$RUN_DIR/seats/$SEAT.json"
TXT="$RUN_DIR/seats/$SEAT.md"
META="$RUN_DIR/seats/$SEAT.meta.json"
LOG="$RUN_DIR/logs/$SEAT.log"
PID="$RUN_DIR/pids/$SEAT.pid"

echo $$ > "$PID"
trap 'rm -f "$PID"' EXIT

START=$(python3 -c 'import time;print(time.time())')
echo "[$(date -u +%FT%TZ)] seat=$SEAT model=$MODEL start" >> "$LOG"

python3 - "$PROMPT_FILE" "$MODEL" > "$RUN_DIR/seats/$SEAT.req.json" <<'PY'
import json,sys
prompt=open(sys.argv[1]).read()
print(json.dumps({
  "model": sys.argv[2],
  "messages":[{"role":"user","content":prompt}],
  "max_tokens": 2000,
  "plugins":[{"id":"web","max_results":8}],
}))
PY

HTTP=$(curl -sS -w '%{http_code}' -o "$RAW" \
  --max-time 600 \
  https://openrouter.ai/api/v1/chat/completions \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  -H "Content-Type: application/json" \
  -H "X-Title: clock" \
  -d @"$RUN_DIR/seats/$SEAT.req.json" 2>>"$LOG")
CURL_RC=$?
END=$(python3 -c 'import time;print(time.time())')

python3 - "$RAW" "$TXT" "$META" "$SEAT" "$MODEL" "$START" "$END" "$HTTP" "$CURL_RC" <<'PY'
import json,sys,os
raw,txt,meta,seat,model,start,end,http,rc = sys.argv[1:10]
out={"seat":seat,"model_requested":model,"http":http,"curl_rc":int(rc),
     "latency_s":round(float(end)-float(start),2),"ok":False}
text=""
try:
    d=json.load(open(raw))
    if "error" in d and not d.get("choices"):
        out["error"]=d["error"]
    ch=(d.get("choices") or [{}])[0]
    msg=ch.get("message") or {}
    text=(msg.get("content") or "").strip()
    out["model_served"]=d.get("model")
    out["provider"]=d.get("provider")
    out["finish_reason"]=ch.get("finish_reason")
    out["usage"]=d.get("usage")
    out["gen_id"]=d.get("id")
    ann=msg.get("annotations") or []
    cites=[a.get("url_citation",{}).get("url") for a in ann if a.get("type")=="url_citation"]
    out["citations"]=[c for c in cites if c]
except Exception as e:
    out["parse_error"]=str(e)
out["chars"]=len(text)
out["ok"]= bool(text) and http=="200"
open(txt,"w").write(text+"\n" if text else "")
json.dump(out,open(meta,"w"),indent=2)
sys.exit(0 if out["ok"] else 1)
PY
STATUS=$?

echo "[$(date -u +%FT%TZ)] seat=$SEAT http=$HTTP curl_rc=$CURL_RC status=$STATUS" >> "$LOG"
# A seat that produced nothing fails. Silence is never a clean bill of health.
exit $STATUS
