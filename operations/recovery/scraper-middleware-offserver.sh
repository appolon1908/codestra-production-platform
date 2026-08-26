#!/usr/bin/env bash
set -euo pipefail
umask 077

backup_root=/opt/codestra/backups/scraper-middleware-scheduled
stamp=$(date -u +%Y%m%dT%H%M%SZ)
final_dir=${backup_root}/${stamp}
remote_root=/srv/codestra-backups/server-a/middleware
remote_upload=${remote_root}/.${stamp}.upload
remote_dir=${remote_root}/${stamp}
work_dir=
success=no

cleanup() {
  if [[ -n "${work_dir}" ]]; then
    case "${work_dir}" in
      "${backup_root}"/.work-20*T*Z.*)
        if [[ -d "${work_dir}" && ! -L "${work_dir}" ]]; then
          find "${work_dir}" -xdev -type f -exec shred -u -- {} +
          rmdir "${work_dir}"
        fi
        ;;
      *)
        printf 'refusing unsafe work directory: %s\n' "${work_dir}" >&2
        return 1
        ;;
    esac
  fi
  if [[ "${success}" != yes && -d "${final_dir}" && ! -L "${final_dir}" ]]; then
    case "${final_dir}" in
      "${backup_root}"/20??????T??????Z)
        find "${final_dir}" -xdev -type f -exec shred -u -- {} +
        rmdir "${final_dir}"
        ;;
      *)
        printf 'refusing unsafe final directory: %s\n' "${final_dir}" >&2
        return 1
        ;;
    esac
  fi
}
trap cleanup EXIT

install -d -m 0700 "${backup_root}" "${final_dir}"
work_dir=$(mktemp -d "${backup_root}/.work-${stamp}.XXXXXX")

database_head_before=$(docker exec codestra-postgres-1 \
  psql -U postgres -d codestra_middleware -Atqc \
  'select version_num from alembic_version limit 1')
docker exec codestra-postgres-1 \
  pg_dump -U postgres -Fc codestra_middleware \
  > "${work_dir}/codestra_middleware.dump"
database_head_after=$(docker exec codestra-postgres-1 \
  psql -U postgres -d codestra_middleware -Atqc \
  'select version_num from alembic_version limit 1')
if [[ -z "${database_head_before}" || "${database_head_before}" != "${database_head_after}" ]]; then
  printf 'schema head changed while backup snapshot was captured\n' >&2
  exit 1
fi
database_head=${database_head_before}
database_size=$(docker exec codestra-postgres-1 \
  psql -U postgres -d codestra_middleware -Atqc \
  "select pg_database_size('codestra_middleware')")

gpg --homedir /etc/codestra/backup-gpg --batch --yes --trust-model always \
  --recipient 'Codestra Backup Recipient' \
  --output "${final_dir}/codestra_middleware.dump.gpg" \
  --encrypt "${work_dir}/codestra_middleware.dump"

cat > "${final_dir}/METADATA.env" <<EOF
BACKUP_UTC=${stamp}
DATABASE=codestra_middleware
DATABASE_HEAD=${database_head}
DATABASE_SIZE_BYTES=${database_size}
ENCRYPTION=GPG
EOF
(
  cd "${final_dir}"
  sha256sum codestra_middleware.dump.gpg METADATA.env > SHA256SUMS
  sha256sum -c SHA256SUMS
)

# Upload into a hidden directory, validate remotely, then publish atomically.
ssh -o BatchMode=yes codestra-vicidial \
  "install -d -m 0700 '${remote_root}' &&
   test ! -e '${remote_upload}' && test ! -e '${remote_dir}' &&
   install -d -m 0700 '${remote_upload}'"
scp -q "${final_dir}/codestra_middleware.dump.gpg" \
  "${final_dir}/METADATA.env" \
  "${final_dir}/SHA256SUMS" \
  "codestra-vicidial:${remote_upload}/"
ssh -o BatchMode=yes codestra-vicidial \
  "chmod 0600 '${remote_upload}/codestra_middleware.dump.gpg' \
     '${remote_upload}/METADATA.env' '${remote_upload}/SHA256SUMS' &&
   cd '${remote_upload}' && sha256sum -c SHA256SUMS &&
   mv '${remote_upload}' '${remote_dir}'"
ssh -o BatchMode=yes codestra-vicidial \
  "cd '${remote_dir}' && sha256sum codestra_middleware.dump.gpg METADATA.env" \
  > "${final_dir}/REMOTE-SHA256SUMS"
diff -u \
  <(grep -E ' (codestra_middleware.dump.gpg|METADATA.env)$' "${final_dir}/SHA256SUMS" | sort) \
  <(sort "${final_dir}/REMOTE-SHA256SUMS")

cat > "${final_dir}/STATUS.txt" <<EOF
BACKUP_UTC=${stamp}
DATABASE=codestra_middleware
PRODUCTION_SERVICES_PAUSED=NO
LOCAL_ENCRYPTED_CHECKSUM=PASS
OFFSERVER_COPY=PASS
REMOTE_CHECKSUM_READBACK=PASS
EOF
chmod 0600 "${final_dir}"/*
success=yes

# Keep 14 successful local encrypted snapshots. Off-host retention is managed
# independently and is never pruned by this host.
mapfile -t old_snapshots < <(
  find "${backup_root}" -mindepth 1 -maxdepth 1 -type d \
    -name '20??????T??????Z' -exec test -s '{}/STATUS.txt' \; \
    -printf '%f\n' | sort -r | tail -n +15
)
for old_name in "${old_snapshots[@]}"; do
  old_path=${backup_root}/${old_name}
  [[ "${old_path}" == "${backup_root}"/20??????T??????Z ]]
  [[ -d "${old_path}" && ! -L "${old_path}" ]]
  find "${old_path}" -xdev -type f -exec shred -u -- {} +
  rmdir "${old_path}"
done

printf '%s\n' "${final_dir}"
