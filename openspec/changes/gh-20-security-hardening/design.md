# Design

## Context

`protocol.md` lists the known limits this closes, and #18 has already put a token on content arriving through the gateway. Requirements here come from #20, which asks for the connector identity's alternatives to be presented.

## Decisions

### Tokens on the routes the data plane calls

A connector's data plane holds no Keycloak token, and only follows the address and header it is given. So each route takes a token good for one purpose and one message: a keyed hash of the two, made with the participant's own client secret.

- `GET /internal/payload/{id}`: the token goes in the asset's data address, kept by this participant's own connector.
- `POST /internal/inbox-receive/{id}`: the token goes in the transfer's destination, which the provider's connector sees. That only lets it deliver that message.

Neither can be used for the other, or for another message, and nothing has to be stored. Both are now required. Alternatives: a static key per participant, which a provider would then hold and could use for any message; a random token per message, which needs a column and gains nothing.

### NetworkPolicies

| To | From |
|---|---|
| An adapter's port 8000 | The gateway, management, and pods in the participants' namespace: peers notify directly, and connectors read and push content |
| A connector's DSP and public ports | Connectors, and the DSP gateway |
| A connector's management port | Adapters |
| A connector's control port | Connectors. It calls itself there |
| A connector's default port | Nothing but the kubelet's probe |
| The registry | The gateway, management, and adapters |

The gateway, the DSP gateway and management are left open: the first two are public, and the Ingress restricts the third. Egress is not limited, as external participants' addresses aren't known in advance. The chart ships these, on by default, with `networkPolicy.enabled`. So does `scripts/local-env.sh`. They need a network plugin that enforces them, which is the operator's to provide.

A policy can't tell one adapter from another without one object per participant, which adds a kind of object to provisioning for little: any adapter route a peer can reach already checks a token or a message's token. Alternative considered and dropped: per-participant policies created by management.

### The registry

By network rules, as above. Alternatives: a token on each call, which also means changing every caller, for routes that only hub services use. External adapters read through the management API, as #18 set out.

### Per-participant database users

Management creates a role `participant_<slug>` with a generated password, makes it the owner of the participant's two databases, and removes `CONNECT` from `PUBLIC` on them. So it can't connect to another participant's. The password is in the participant's Secret, and is kept when it is registered again. Removal drops the role. Alternatives: one role per database, which adds nothing as the two belong to one participant; schemas in a shared database, which `architecture.md` rules out.

Management's PostgreSQL user needs `CREATEROLE` as well as `CREATEDB`. A participant registered before this change owns nothing under the new role, so it has to be removed and added again. Nothing has been released, so there is no migration.

### Per-participant S3 identities

**Decision for review.** SeaweedFS keeps identities in one list, either a static file given at start, or the filer's `/etc/iam/identity.json`. A change to the latter **replaces** what the static file gave, until the next restart, when the static file replaces the list again. A probe confirmed this.

So management uses SeaweedFS's IAM API, when given `SEAWEEDFS_IAM_URL`: for each participant, a user, a generated access key and a policy naming its bucket, and the storage's other identities stay. Management creates the bucket, as the identity can't. The storage must run without a static file, and with its list holding the administrator in the secrets file, which `scripts/local-env.sh` writes at setup with `weed shell`.

**Without `SEAWEEDFS_IAM_URL`, participants share the configured S3 identity, as they do today, and management logs that at start.** This is deliberate, because the [DigitalTwin](https://github.com/IndustryFusion/DigitalTwin) stack, the default dependency, starts SeaweedFS with a static file, and doesn't run the IAM API. Writing a list there would lock out that stack's own identities. An operator who wants isolation has to move that storage to the filer's list, or give the dataspace its own storage. The acceptance criterion holds only with this set, and `deploy/README.md` says so.

Alternatives:

- Writing the filer's file over HTTP. The S3 gateway only takes up a list the filer holds inline, which an HTTP write isn't, and `-filer.saveToFilerLimit` to make it so breaks any multipart upload with a small last part. A live run found both.
- Refusing to register without `SEAWEEDFS_IAM_URL`. It would stop the default stack from working at all.
- A storage instance per participant, as the external demo has. It gives real isolation on any stack, at the cost of a stateful service per participant and a new backup story.

**A known gap: this version of SeaweedFS lets an identity copy from another's bucket.** `CopyObject` and `UploadPartCopy` are only checked for `Write` on the destination, and nothing checks read permission on the source. So with a participant's real keys, a direct read, write or list of another's bucket is refused, and a copy of an object it can name into its own bucket succeeds, after which it reads those bytes. Listing stays refused, so it has to know the key. A key is `messages/<message_id>.json` or `files/<message_id>.zip`, so a peer knows the keys of the messages it exchanged with that participant, not of others, unless it can guess an id. **So "one participant's credentials cannot read another's storage" is only partly met.** It awaits a maintainer's decision.

A live probe of 3.80 found no small fix. `Write` is what a put needs too, so an identity that can store its own content can copy. A policy with only named actions refused everything, a `Deny` on the other bucket or on `s3:CopyObject` and `s3:UploadPartCopy` changed nothing, an identity with actions scoped by `s3.configure -buckets` copies the same way, and `weed s3` has no setting for it. Alternatives for the decision, none built:

- A newer SeaweedFS, if it checks the source. Not tested here.
- A proxy in front of S3 that refuses `X-Amz-Copy-Source`. A component in the path of all content.
- A storage instance per participant, as above, where there is no other bucket to name.
- A key prefix that peers can't derive, or encrypting content in the adapter with a per-participant key. Either leaves the copy possible and makes it useless, and changes how content is stored.

**The IAM API of this version didn't refuse a wrong signature** in a probe, and the filer's port serves the list, with every identity's keys in plain text. So only management may reach either. `scripts/local-env.sh` ships a policy for that, and `deploy/README.md` asks the operator for the same.

### The per-participant internal key

Each participant's Secret has its own generated `internal-key`, and management reads it from there for each call. It can already read that Secret. `ADAPTER_INTERNAL_KEY` goes from management's settings, the chart's values and the local environment. Alternative: a key derived from a master key, which keeps one secret that opens every adapter.

### Connector identity

**A connector presents a Keycloak token from its participant's own client, and checks the one it receives.**

- Signature against the realm's published keys, RS256 only, the exact issuer, and an expiry.
- A `participant_id` claim, and the role `participant:<id>`, as an adapter requires.
- The result is the connector's identity for the counterparty, `edc.agent.identity.key=participant_id`. So one with no valid token is refused, and an agreement has to come from the identity it names, and match the offer, which names the expected participant.

`scripts/security-check.py` shows a real connector, named in a notification as another participant's, failing: the consumer refuses its agreement as not matching the offer, and the negotiation stays unfinished until the budget runs out, while the same connectors complete the same asset for its real owner. It doesn't show a connector built to lie in its own messages, as it uses this project's connector.

| Alternative | Why not |
|---|---|
| **Keycloak token from the participant's own client** (chosen) | Closest to how adapters already prove who they are. No new infrastructure or registration data. Replay as in `keycloak.md` applies |
| EDC's OAuth2 extension | Built around private-key client authentication and a certificate, and asks for per-audience tokens Keycloak doesn't issue without a client scope per peer |
| A key pair per connector, with self-signed tokens naming their audience | Would end replay between connectors, as a token names who it is for. Needs public keys in the registry, a change of its contract, and rotation |
| Dataspace Connector Credentials and an identity hub | The direction of the field, and what a federated dataspace would want. Needs a credential issuer and a wallet per participant. Too much to run for this |
| Mutual TLS | Needs a certificate authority and a change to how each door terminates TLS. The Ingress in the middle would have to pass client certificates through |

A token a connector sends to a peer can be replayed by that peer, for the same reason as an adapter's, and in the same places: `keycloak.md` says so. It adds no new reach, since it comes from the same client.

### Public reads

| Route | Now |
|---|---|
| `GET /api/participants/{id}/capabilities`, `GET /api/policy` | Admin token |
| `GET /api/participants`, `/{id}`, `/compatible/{id}` | Public, without hosted addresses. An admin token gets the whole record |
| `GET /api/health` | Public as it is. Its details never hold addresses or credentials |

In a public read, `adapter_url` is `null` for a hosted participant, as is `dsp_url` unless it is reachable, where it is the DSP gateway's address. An external participant's own addresses stay, as peers need them. So an external adapter's `REGISTRY_URL` keeps working. The gateway's `/participants/compatible` leaves out the same fields, as agents never need them. The Policies tab asks for admin mode.

### The management Ingress

Rendering it without `ingress.management.allowFrom` now fails, rather than leaving it open. An external adapter reads these routes, so its address has to be on the list. Alternative: a second Ingress with only the read routes, open to all, which would serve a public directory no one has asked for.

## Conflicts

`architecture.md` says the registry is only reached inside the cluster, and this makes it true. `management-api.md` said `GET /api/policy` needs no token for hosted pairs, and this changes it. `gateway-api.md` shows addresses in `/participants/compatible`, and this changes it, which an agent application reading those fields would notice. They were never for agents.

## Risks

- [A policy that is too tight stops transfers] → The end-to-end and external tests run with them active.
- [An identity can copy from another's bucket] → Not closed. See "A known gap" above. `scripts/security-check.py` reports it, and exits with 2 while it is there.
- [No enforcing network plugin] → Policies do nothing, silently. Token checks don't depend on them. `scripts/security-check.py` reports it.
- [Two writers to the filer's list] → Management runs as one replica, and holds a lock around the list. Another writer could lose a change, so the design says it must be the only one.
