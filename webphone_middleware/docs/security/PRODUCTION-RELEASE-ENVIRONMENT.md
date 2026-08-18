# Production release environment

The `production-release` GitHub environment is a release-evidence gate. It
does not authorize deployment or activation.

Required configuration:

- required reviewer: the mapped Release Owner, currently `appolon1908-hue`;
- prevent self-review: enabled;
- administrator bypass: disabled;
- deployment branches: protected branches only (`main`);
- environment secrets: none;
- environment variables: none.

The Security Owner decision is independently enforced by the two signed input
artifacts and their protected signer environments. GitHub environment required
reviewers are an any-one gate, so adding both roles to this single environment
would not enforce two approvals. The release job therefore uses this environment
for the separate Release Owner decision.

The workflow uses only the job-scoped GitHub token. Authority and VEX artifact
coordinates are immutable `workflow_dispatch` inputs. Repository or organization
secrets must not be used to replace Security Owner approval.
