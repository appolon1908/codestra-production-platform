# Rollback manifest — 2026-09-02

Database script rollback: /opt/codestra/backups/database-certification-script-remediation-20260902T141900Z/backup-all-databases.sh.before
Rollback checksum: 3bb3b9a6467300da6bac0d3c96701d4f4187d5434fdb7279fd81d1d5bc32eb6f
Provisioning rollback image: sha256:db7dfcf1d8547d9daa9f1e1b7f7f834b0138b95e15fce95345e4e2e1211ed578
Middleware webhook rollback image: sha256:93cbb4a11765ad92e9bbf1a1bb9601f15a540164b4e7d6647cb0f16d588ab6e0
Mail API candidate source: e612e38dae1a1e2ec5e770dcd29aabc3c2ea2b53 <!-- gitleaks:allow; protected Git SHA -->
Mail API candidate image: sha256:586ed6aaded359b4cad64905d027079ea910eda5202bae0bac0d44d8baf0df09
Mail API rollback image: sha256:7495d5f0d79f027456ed61b7c3c2ea9331c228f3d2e10bceef3178eef5a62594
Reseller portal candidate source: e612e38dae1a1e2ec5e770dcd29aabc3c2ea2b53 <!-- gitleaks:allow; protected Git SHA -->
Reseller portal candidate image: sha256:74ce88fa3ca05a6c3d595080b78c398be1dc49ac72185ba8aa787d9f6f8247d9
Reseller portal rollback image: sha256:7d7cf6318ac122f7e39ab679dec499dc1f6116129765903d44e42c74541ca12e
Filesystem reserve rollback: verify sufficient free blocks, then run tune2fs -m 5 /dev/md2.
