# Python 3.12 release security backports

The middleware runtime remains Python 3.12.13 because Python 3.12 has no newer
upstream security release. The Docker build verifies the official source
archive and every upstream patch by SHA-256 before compiling.

| Finding | Resolution |
| --- | --- |
| CVE-2026-11940 | CPython maintained-branch backport `be13e86f6b9788a6f4d0419dffef72cbae5865c9` |
| CVE-2026-11972 | CPython maintained-branch backport `7f0dc59c9a70f8f3b4da33d7c4a2ba552a7acc21` |
| CVE-2026-15308 | CPython maintained-branch backport `7933f4bf7131aa4140750f9404f5de0aa2969ced` |
| CVE-2026-3644 | CPython maintained-branch backport `dae4b1a21f8df4570e30986affd61bbe4ade4cef` |
| CVE-2026-4224 | CPython maintained-branch backport `642865ddf4b232da1f3b1f7abcfa3254c4bfe785` |
| CVE-2026-6100 | CPython maintained-branch backport `e20c6c9667c99ecaab96e1a2b3767082841ffc8b` |
| CVE-2026-9669 | CPython 3.12 backport contained in `938ec030e90c5e53f1faac6fab1643f14e4f4a79` |
| CVE-2026-4786 | Minimal 3.12 adaptation of upstream `f4654824ae0850ac87227fb270f9057477946769`, including its prerequisite leading-dash validation |
| CVE-2026-7210 | Expat 2.8.2 plus a minimal 3.12 structure adaptation and the remaining upstream `fc9b11ff49cbc82e6f917d07a61517a2b5f3145f` changes |
| CVE-2026-3298 | Not applicable: the vulnerable code is Windows-specific and the release image is Linux/amd64 |

The two local patch files contain only version-layout adaptations needed because
Python 3.12 is source-only. The behavioral changes and regression tests remain
those supplied by CPython upstream. Release evidence must bind the resulting
image digest to a VEX statement for each generic CPE match; the version string
alone does not communicate these source backports to Grype.
