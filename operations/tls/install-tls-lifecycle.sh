#!/usr/bin/env bash
set -euo pipefail
base=$(cd "$(dirname "$0")" && pwd)
install -d -m 0750 /etc/codestra/tls
install -m 0640 "$base/certificates.tsv" /etc/codestra/tls/certificates.tsv
install -m 0750 "$base/renew-private-certificate" /usr/local/sbin/renew-private-certificate
install -m 0755 "$base/check-certificate-expiry" /usr/local/sbin/check-certificate-expiry
install -m 0750 "$base/codestra-certificate-lifecycle" /usr/local/sbin/codestra-certificate-lifecycle
install -m 0644 "$base/codestra-certificate-renewal.service" /etc/systemd/system/codestra-certificate-renewal.service
install -m 0644 "$base/codestra-certificate-renewal.timer" /etc/systemd/system/codestra-certificate-renewal.timer
install -m 0644 "$base/../monitoring/rules/tls-lifecycle.rules.yml" /opt/codestra/operations/monitoring/rules/tls-lifecycle.rules.yml
systemctl daemon-reload
systemctl enable --now codestra-certificate-renewal.timer
docker kill --signal=SIGHUP codestra-monitoring-prometheus-1 >/dev/null 2>&1 || true
