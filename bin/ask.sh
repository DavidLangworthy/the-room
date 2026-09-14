#!/usr/bin/env bash
# Fan one question out to every provider seat. Each seat writes its own artifacts.
# Usage: ask.sh "<question>"   [env: SEATS="name=model ..."]
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
Q=${1:?usage: ask.sh "<question>"}

: "${SEATS:=opus=anthropic/claude-opus-5 sol=openai/gpt-5.6-sol gemini=google/gemini-3.1-pro-preview grok=x-ai/grok-4.6}"

RUN_ID=$(date -u +%Y-%m-%dT%H%M%SZ)
RUN_DIR="$ROOT/store/runs/$RUN_ID"
mkdir -p "$RUN_DIR"/{seats,logs,pids}
printf '%s' "$Q" > "$RUN_DIR/prompt.txt"

python3 - "$RUN_DIR" "$RUN_ID" "$SEATS" <<'PY'
import json,sys,datetime
run_dir,run_id,seats=sys.argv[1:4]
json.dump({"run_id":run_id,
  "started_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
  "prompt":open(run_dir+"/prompt.txt").read(),
  "seats":dict(s.split("=",1) for s in seats.split()),
  "transport":"openrouter chat/completions, web plugin (8 results)"},
  open(run_dir+"/run.json","w"),indent=2)
PY

for s in $SEATS; do
  name=${s%%=*}; model=${s#*=}
  "$ROOT/bin/seat.sh" "$RUN_DIR" "$name" "$model" "$RUN_DIR/prompt.txt" &
done
wait

"$ROOT/bin/index.py" "$RUN_DIR"
echo "$RUN_DIR"
