#!/usr/bin/env bash
set -euo pipefail

CONFIG=${CODESTRA_ALERTMANAGER_CONFIG:-/etc/codestra/monitoring/alertmanager.yml}
GOVERNANCE=${CODESTRA_GOVERNANCE_REFERENCES:-/etc/codestra/governance/production.env}
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

python3 "$ROOT/validate-governance.py" "$GOVERNANCE"
[[ -r "$CONFIG" ]] || {
    echo "approved Alertmanager configuration is missing" >&2
    exit 2
}
if grep -q 'REPLACE_WITH_APPROVED' "$CONFIG"; then
    echo "refusing monitoring deployment with placeholder alert receiver" >&2
    exit 2
fi
for secret in primary_receiver_url secondary_receiver_url recovery_receiver_url; do
    path="/etc/codestra/secrets/monitoring/$secret"
    [[ -s "$path" ]] || {
        echo "protected Alertmanager receiver secret is missing: $path" >&2
        exit 2
    }
    mode=$(stat -c '%a' "$path")
    [[ "$mode" == "400" || "$mode" == "440" || "$mode" == "600" || "$mode" == "640" ]] || {
        echo "unsafe Alertmanager receiver secret mode: $path ($mode)" >&2
        exit 2
    }
done

docker run --rm \
    --entrypoint /bin/promtool \
    -v "$ROOT/prometheus.yml":/etc/prometheus/prometheus.yml:ro \
    -v "$ROOT/rules":/etc/prometheus/rules:ro \
    prom/prometheus@sha256:3c42b892cf723fa54d2f262c37a0e1f80aa8c8ddb1da7b9b0df9455a35a7f893 \
    promtool check config /etc/prometheus/prometheus.yml
docker run --rm \
    --entrypoint /bin/amtool \
    -v "$CONFIG":/etc/alertmanager/alertmanager.yml:ro \
    prom/alertmanager@sha256:9e082985f56f4c8c9f724e18f2288c6708f472e56a5286b8863d080434ea065d \
    amtool check-config /etc/alertmanager/alertmanager.yml

docker compose -f "$ROOT/compose.monitoring.yaml" up -d
