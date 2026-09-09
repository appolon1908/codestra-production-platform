# API assurance source boundaries

Implementation tokens must be nonempty string lists, and route fragments must
participate in actual request-path predicates. A prior single-assignment local
constant is supported; unrelated strings, scalar token lists and reassigned
variables cannot prove a route.

Gateway scope evidence is conservative: only an enabled native OpenID Connect
plugin with bearer-only authentication and a literal mandatory scope is
statically supported. Route overrides take precedence. A scope string inside
conditional Lua is not proof of enforcement and must remain a gap.

Gateway behavior evidence requires tracked Python test functions containing
request/status assertion pairs for each exact method/path: both denied and
allowed requests. Prose, docstrings, dead nested functions and unrelated paths
do not count. Unsupported indirect or parameterized forms remain gaps.

These are source assurance checks, not runtime certification. Even a passing
source shape requires executed tests, effective gateway policy verification,
immutable artifact identity and environment acceptance before deployment.
The strict coverage gate remains fail-closed while cataloged gaps remain.
