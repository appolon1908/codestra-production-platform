# Ignore Policy

Generated UTC: 2026-07-27.

The existing `.gitignore` was preserved and extended to cover:

- protected environment and secret files;
- private keys and certificate containers;
- SQL dumps, database backups, and archives;
- runtime data, volumes, recordings, and filestore content;
- Python, Node, coverage, build, cache, and log output;
- private evidence and report directories.

Representative checks passed for `.env`, the protected application environment,
key material, database dumps, archives, `node_modules`, build output, runtime
data, volumes, and private evidence/report paths.

Configuration examples remain eligible for Git. Source migrations, schemas,
tests, and workflow exports are not globally ignored.

`GITIGNORE_VALIDATED=YES`
