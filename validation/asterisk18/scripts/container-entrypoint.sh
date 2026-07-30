#!/usr/bin/env bash
set -euo pipefail
cp -r /asterisk-seed/documentation /var/lib/asterisk/
mkdir -m 0700 /run/harness-pki
cp /harness/pki/*.chain.pem /harness/pki/*.key /run/harness-pki/
chmod 0600 /run/harness-pki/*

tls_proxy() {
  local port=$1 cert=$2
  socat "OPENSSL-LISTEN:${port},reuseaddr,fork,cert=/run/harness-pki/${cert}.chain.pem,key=/run/harness-pki/${cert}.key,verify=0,openssl-min-proto-version=TLS1.2,cipher=ECDHE-RSA-AES256-GCM-SHA384" \
    TCP:127.0.0.1:5038 &
}
tls_proxy 5039 valid
tls_proxy 5040 expired
tls_proxy 5041 future
tls_proxy 5042 missing-san
tls_proxy 5043 unknown-ca

exec runuser -u asterisk -- /usr/sbin/asterisk -f -U asterisk -G asterisk -vvv
