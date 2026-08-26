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
docker exec -i -u postgres "$container" sh -ceu '
  line=$1
  hba=$(psql -X -A -t -d postgres -c "show hba_file")
  test -f "$hba" -a ! -L "$hba"
  if ! grep -Fqx "$line" "$hba"; then
    temporary=$(mktemp "${hba}.codestra.XXXXXX")
    cp "$hba" "$temporary"
    printf "\n# Codestra restricted physical-backup authority\n%s\n" "$line" >>"$temporary"
    chmod "$(stat -c %a "$hba")" "$temporary"
    chown "$(stat -c %u "$hba"):$(stat -c %g "$hba")" "$temporary"
    mv "$temporary" "$hba"
  fi
  psql -X -A -t -v ON_ERROR_STOP=1 -d postgres -c "select pg_reload_conf()" | grep -qx t
' sh "$line"

verified=$(docker exec -u postgres "$container" psql -X -A -t -d postgres -v ON_ERROR_STOP=1 -c \
  "select count(*) from pg_hba_file_rules where type='host' and database=array['replication'] and user_name=array['$role'] and address='$cidr' and auth_method='scram-sha-256' and error is null")
[[ $verified -eq 1 ]]
printf 'SHARED_BACKUP_HBA=PASS\nROLE=%s\nCIDR=%s\n' "$role" "$cidr"
