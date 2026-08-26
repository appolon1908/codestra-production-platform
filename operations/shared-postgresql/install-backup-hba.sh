#!/usr/bin/env bash
set -euo pipefail
umask 077

test "$(id -u)" -eq 0
container=${1:?postgres container required}
role=${2:?backup role required}
cidr=${3:?private source CIDR required}

[[ $container =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]+$ ]]
[[ $role =~ ^[a-z_][a-z0-9_]*$ ]]
[[ $cidr =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/([0-9]|[12][0-9]|3[0-2])$ ]]
line="host replication $role $cidr scram-sha-256"

docker inspect "$container" >/dev/null
mapfile -t attached_networks < <(docker inspect "$container" --format '{{range $name,$network := .NetworkSettings.Networks}}{{$name}}{{println}}{{end}}')
attached_cidrs=()
for network in "${attached_networks[@]}"; do
  [[ -n $network ]] || continue
  while IFS= read -r subnet; do
    [[ -n $subnet ]] && attached_cidrs+=("$subnet")
  done < <(docker network inspect "$network" --format '{{range .IPAM.Config}}{{if .Subnet}}{{.Subnet}}{{println}}{{end}}{{end}}')
done
python3 - "$cidr" "${attached_cidrs[@]}" <<'PY'
import ipaddress
import sys

requested = ipaddress.ip_network(sys.argv[1], strict=True)
attached = {ipaddress.ip_network(value, strict=True) for value in sys.argv[2:]}
if not requested.is_private or requested not in attached:
    raise SystemExit("CIDR is not an exact private network attached to PostgreSQL")
PY

docker exec -i -u postgres "$container" sh -ceu '
  line=$1
  role=$2
  cidr=$3
  hba=$(psql -X -A -t -d postgres -c "show hba_file")
  test -f "$hba" -a ! -L "$hba"
  equivalent=$(psql -X -A -t -v ON_ERROR_STOP=1 -d postgres -c \
    "select count(*) from pg_hba_file_rules where type=\$\$host\$\$ and database=array[\$\$replication\$\$] and user_name=array[\$\$$role\$\$] and address=split_part(\$\$$cidr\$\$,\$\$/\$\$,1) and netmask=host(netmask(\$\$$cidr\$\$::cidr)) and auth_method=\$\$scram-sha-256\$\$ and error is null")
  if [ "$equivalent" -eq 0 ]; then
    temporary=$(mktemp "${hba}.codestra.XXXXXX")
    original=$(mktemp "${hba}.original.XXXXXX")
    cp "$hba" "$original"
    cp "$hba" "$temporary"
    printf "\n# Codestra restricted physical-backup authority\n%s\n" "$line" >>"$temporary"
    chmod "$(stat -c %a "$hba")" "$temporary"
    chown "$(stat -c %u "$hba"):$(stat -c %g "$hba")" "$temporary"
    mv "$temporary" "$hba"
    rollback() {
      cp "$original" "$hba"
      chmod "$(stat -c %a "$original")" "$hba"
      chown "$(stat -c %u "$original"):$(stat -c %g "$original")" "$hba"
      psql -X -A -t -d postgres -c "select pg_reload_conf()" >/dev/null 2>&1 || true
      rm -f "$original"
    }
    trap rollback EXIT
    psql -X -A -t -v ON_ERROR_STOP=1 -d postgres -c "select pg_reload_conf()" | grep -qx t
    verified=$(psql -X -A -t -v ON_ERROR_STOP=1 -d postgres -c \
      "select count(*) from pg_hba_file_rules where type=\$\$host\$\$ and database=array[\$\$replication\$\$] and user_name=array[\$\$$role\$\$] and address=split_part(\$\$$cidr\$\$,\$\$/\$\$,1) and netmask=host(netmask(\$\$$cidr\$\$::cidr)) and auth_method=\$\$scram-sha-256\$\$ and error is null")
    [ "$verified" -ge 1 ]
    trap - EXIT
    rm -f "$original"
  fi
' sh "$line" "$role" "$cidr"

verified=$(docker exec -u postgres "$container" psql -X -A -t -d postgres -v ON_ERROR_STOP=1 -c \
  "select count(*) from pg_hba_file_rules where type='host' and database=array['replication'] and user_name=array['$role'] and address=split_part('$cidr','/',1) and netmask=host(netmask('$cidr'::cidr)) and auth_method='scram-sha-256' and error is null")
[[ $verified -ge 1 ]]
printf 'SHARED_BACKUP_HBA=PASS\nROLE=%s\nCIDR=%s\n' "$role" "$cidr"
