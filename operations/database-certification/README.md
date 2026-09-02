# Production database certification authority

This package owns the fail-closed encrypted backup and isolated restore
certification for the production database set. Runtime credentials remain in
root-controlled environment files and are never stored here.

The WebSocket backup source is the streaming standby. The backup refuses an
unhealthy receiver, a server not in recovery, missing replay state, or receive
to replay lag beyond the configured byte policy. Provisioning backup always
uses the production state volume mounted by the production container; the
retired volume is rollback evidence and is never selected.

The systemd timers serialize execution, enforce bounded runtime, publish
freshness metrics after success, and retain encrypted, checksummed off-host
evidence. Restore rehearsals use isolated disposable databases only.

The root ext4 filesystem reserve was changed on 2026-09-02 from 5% to 0.5%.
This exposed capacity already present on `/dev/md2`; it deleted no data and
retains approximately 2.2 GiB for UID 0. Rollback is `tune2fs -m 5 /dev/md2`
after first proving sufficient free blocks. The production warning threshold
remains unchanged.
