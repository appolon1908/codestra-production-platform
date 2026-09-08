# Runtime composition

`runtime-composition.v1.json` is the central, environment-neutral composition catalog.
It identifies component owners and the reviewed Compose, Caddy, Kong, and
configuration inputs used to render desired state.

Environment differences are GitHub Environment configuration and secret
references, not divergent source branches. One exact set of immutable image
digests is accepted in staging and then promoted unchanged to production.
This catalog contains no credentials and does not itself authorize deployment.
