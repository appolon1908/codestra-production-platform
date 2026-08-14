# Infrastructure-as-code plan

Use OpenTofu modules with separate environment state and a remote encrypted
backend. Modules: Hetzner networks/subnets/routes, firewalls, nodes, volumes,
load balancers and private DNS; configuration modules for OS baseline, time,
named-admin access, PKI enrollment, secrets agent, monitoring and backup client.

CI stages: format → validate → provider lock verification → static security and
policy checks → cost estimate → non-mutating plan → independent approval → apply
with exact plan digest. State credentials and provider tokens remain in the
approved secret manager. Destruction, public database rules, unrestricted CIDRs,
unapproved image IDs and MTU drift are policy failures.

No IaC apply or billable provisioning is authorized by this package.
