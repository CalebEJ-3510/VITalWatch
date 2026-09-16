#!/usr/bin/env bash
# Pre-flight against a deployed instance, or against localhost.
#
#   ./scripts/deploy_check.sh                       # local
#   ./scripts/deploy_check.sh https://your.app      # deployed, also warms a cold start
#
# Probes only public/unauthenticated routes plus /health, since every other route in the
# approved CTMS scope now requires an authenticated session (see app/main.py session_gate).
set -euo pipefail
BASE="${1:-http://localhost:8000}"

echo "checking ${BASE}"
fail=0
for path in /health /robots.txt /login /docs; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "${BASE}${path}")
    if [ "$code" = "200" ]; then
        printf '  ok   %s\n' "$path"
    else
        printf '  FAIL %s -> %s\n' "$path" "$code"
        fail=1
    fi
done

echo
# Which engine is actually serving. "The database is in the cloud" is a claim the
# deployment should be able to answer for itself.
echo "backend:"
curl -s --max-time 30 "${BASE}/health"
echo
exit $fail
