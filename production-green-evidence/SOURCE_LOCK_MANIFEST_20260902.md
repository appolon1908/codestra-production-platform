# Source lock manifest — 2026-09-02

Repository: appolon1908-hue/codestra-production-platform
Branch: fix/database-certification-authority
Feature head: 9cf1c6d9254e937b75da601eede788bdb0758f41
Protected base: 5aec485814149434750f2313370ae0ae39db5bd8
PR: #182
Protected merge: PENDING

The database-certification runtime repair is source-identical in behavior to operations/database-certification/backup-all-databases.sh. Full platform GIT_RUNTIME_DRIFT remains nonzero until PR #182 merges and the protected files are installed byte-for-byte.
