#!/bin/bash
set -e
cd /workspace
if curl -sf -o /dev/null --max-time 2 http://127.0.0.1:8080/; then
  exit 0
fi
export PORT=8080
export FLASK_DEBUG=0
nohup python3 app.py > /tmp/faatn-flask.log 2>&1 &
for i in 1 2 3 4 5 6 7 8 9 10 12 15; do
  if curl -sf -o /dev/null --max-time 2 http://127.0.0.1:8080/; then
    exit 0
  fi
  sleep 1
done
echo "FAATN-GATE did not become ready" >&2
tail -40 /tmp/faatn-flask.log >&2 || true
exit 1
