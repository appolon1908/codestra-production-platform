# Backup failure

1. Confirm the current job status without printing environment variables.
2. Verify local capacity, GPG recipient availability, SSH host-key validation,
   and the protected off-server destination independently.
3. Do not remove the newest two checksum-valid encrypted backups.
4. Rerun the job only after the failure cause is corrected.
5. Verify local checksum, remote receipt, and alert recovery notification.

