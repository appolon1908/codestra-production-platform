# Rollback

Pre-change evidence is `/root/codestra-section1-backups/20260805T001500Z` and
the encrypted daily backup is under
`/root/codestra-platform-backups/20260805T041052Z`, with an off-server copy on
the middleware host. Restore tests must target an isolated database/directory.

For a configuration-only rollback, restore the exact backed-up file, validate
its checksum, verify zero active calls, reload only the affected module, then
confirm channels, endpoint state, signed health and no failed units. Do not
restore the production database during routine rollback. Campaign rollback is
disable-first; historical rows are never deleted.

