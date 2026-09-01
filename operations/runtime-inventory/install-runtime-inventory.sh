#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "installer must run as root" >&2
  exit 2
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
install -d -o root -g root -m 0755 /usr/local/sbin /etc/sudoers.d
getent group codestra-runtime-audit >/dev/null 2>&1 || groupadd --system codestra-runtime-audit
install -o root -g root -m 0755 "$script_dir/codestra-runtime-inventory" /usr/local/sbin/codestra-runtime-inventory
sudoers_tmp=$(mktemp /etc/sudoers.d/.codestra-runtime-inventory.XXXXXX)
trap 'rm -f "$sudoers_tmp"' EXIT HUP INT TERM
install -o root -g root -m 0440 "$script_dir/codestra-runtime-inventory.sudoers" "$sudoers_tmp"
visudo -cf "$sudoers_tmp" >/dev/null
mv -f "$sudoers_tmp" /etc/sudoers.d/codestra-runtime-inventory
trap - EXIT HUP INT TERM
visudo -cf /etc/sudoers.d/codestra-runtime-inventory >/dev/null
echo "RUNTIME_INVENTORY_INSTALL=PASS"
