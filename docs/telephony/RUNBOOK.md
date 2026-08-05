# Telephony runbook

1. Confirm `core show channels count`, VICIdial live agents/auto calls and disk.
2. Check Asterisk, MariaDB, Apache, VICIdial, passive gateway and adapter units.
3. Run signed adapter and Asterisk health services; inspect failed units.
4. Verify MariaDB/AMI loopback bindings and nftables default reject.
5. Confirm production activation and all autonomous delivery flags remain off.
6. Run the encrypted backup and verify the remote checksum before mutation.
7. Use only disabled synthetic resources and an approved bounded canary window.
8. On failure, stop the canary, hang up only its exact channels, disable its
   resources, preserve evidence, and execute the configuration rollback.

