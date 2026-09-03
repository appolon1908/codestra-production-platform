# Git/runtime drift — 2026-09-02

GIT_RUNTIME_DRIFT=NONZERO.

The database authority correction and WAL-retention correction are protected and installed. Mail API and reseller portal now match protected source and digest-pinned deployment authority. Monitoring network, staging identity endpoint, and non-root secret-projection changes are protected and installed.

Global drift remains nonzero because canonical Middleware convergence PR #283 is open and its exact-head workflows failed before job allocation, the webhook worker remains on its prior rollback image, and the protected source-lock inventory still lists unresolved custom runtimes. Do not promote the transitional Appolon Middleware candidate as canonical Middleware.
