# Ignore Policy

Generated UTC: 2026-07-27.

The existing policy was preserved and extended for `.pytest_cache/`,
`*.pgcustom`, transient lock/candidate/remote-edit directories, generated
VICIdial staging repositories, runtime evidence pointers, and evidence backup
directories.

Required protections cover environment and secret files, private keys,
certificate containers, database dumps and backups, archives, recordings,
filestore, runtime data/volumes, Python/Node/build/cache output, logs, and
private evidence/reports. Configuration examples remain eligible for Git.
Source migrations, workflow exports, schemas intentionally designed as source,
tests, and safe deployment definitions are not globally ignored.

Representative `git check-ignore` checks passed for the protected application
environment, database backup, scratch candidate, remote-edit workspace, and
runtime lock paths.

`GITIGNORE_VALIDATED=YES`
