#!/usr/bin/env bash
set -euo pipefail
umask 077
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
pki="$root/runtime/pki"
rm -rf "$pki"
mkdir -p "$pki" "$root/runtime"
secret=$(openssl rand -hex 32)
sed "s/@TEST_AMI_SECRET@/$secret/" "$root/config/manager.conf.template" > "$root/runtime/manager.conf"
printf '%s' "$secret" > "$root/runtime/ami.secret"

make_ca() {
  local name=$1
  openssl req -x509 -newkey rsa:2048 -nodes -days 2 -sha256 \
    -subj "/CN=${name}" -keyout "$pki/${name}.key" -out "$pki/${name}.pem" >/dev/null 2>&1
}
make_ca test-ca
make_ca unknown-root

issue() {
  local name=$1 ca=$2 subject=$3 start_date=$4 end_date=$5 san=${6:-}
  openssl req -newkey rsa:2048 -nodes -sha256 -subj "/CN=${subject}" \
    -keyout "$pki/${name}.key" -out "$pki/${name}.csr" >/dev/null 2>&1
  local ext=()
  if [[ -n "$san" ]]; then
    printf 'subjectAltName=DNS:%s\nextendedKeyUsage=serverAuth\n' "$san" > "$pki/${name}.ext"
    ext=(-extfile "$pki/${name}.ext")
  fi
  openssl ca -batch -config "$pki/ca.cnf" -cert "$pki/${ca}.pem" -keyfile "$pki/${ca}.key" \
    "${ext[@]}" -startdate "$start_date" -enddate "$end_date" \
    -in "$pki/${name}.csr" -out "$pki/${name}.pem" >/dev/null 2>&1
  cat "$pki/${name}.pem" "$pki/${ca}.pem" > "$pki/${name}.chain.pem"
}

now=$(date -u +%y%m%d%H%M%SZ)
past=$(date -u -d '2 days ago' +%y%m%d%H%M%SZ)
past_end=$(date -u -d '1 day ago' +%y%m%d%H%M%SZ)
future=$(date -u -d '1 day' +%y%m%d%H%M%SZ)
future_end=$(date -u -d '2 days' +%y%m%d%H%M%SZ)
cat > "$pki/ca.cnf" <<EOF
[ca]
default_ca=local
[local]
database=$pki/index.txt
serial=$pki/serial
new_certs_dir=$pki
default_md=sha256
policy=policy
[policy]
commonName=supplied
EOF
: > "$pki/index.txt"; printf '1000\n' > "$pki/serial"
issue valid test-ca asterisk-ami.test.invalid "$now" "$future_end" asterisk-ami.test.invalid
issue expired test-ca expired.test.invalid "$past" "$past_end" asterisk-ami.test.invalid
issue future test-ca future.test.invalid "$future" "$future_end" asterisk-ami.test.invalid
issue missing-san test-ca missing-san.test.invalid "$now" "$future_end"
openssl req -newkey rsa:2048 -nodes -sha256 -subj "/CN=unknown-ca.test.invalid" \
  -keyout "$pki/unknown-ca.key" -out "$pki/unknown-ca.csr" >/dev/null 2>&1
printf 'subjectAltName=DNS:asterisk-ami.test.invalid\nextendedKeyUsage=serverAuth\n' > "$pki/unknown-ca.ext"
openssl x509 -req -sha256 -days 2 -in "$pki/unknown-ca.csr" \
  -CA "$pki/unknown-root.pem" -CAkey "$pki/unknown-root.key" -CAcreateserial \
  -extfile "$pki/unknown-ca.ext" -out "$pki/unknown-ca.pem.tmp" >/dev/null 2>&1
mv "$pki/unknown-ca.pem.tmp" "$pki/unknown-ca.pem"
cat "$pki/unknown-ca.pem" "$pki/unknown-root.pem" > "$pki/unknown-ca.chain.pem"
find "$root/runtime" -type f -exec chmod go-rwx {} +
