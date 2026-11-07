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

**Decision for review.** SeaweedFS has no call for one identity that leaves others alone. It keeps identities in one list, either a static file given at start, or the filer's `/etc/iam/identity.json`, and a write to the latter **replaces** what the static file gave, until the next restart, when the static file replaces the list again. A probe confirmed this: an identity added through its IAM API removed the static administrator.

So management keeps the filer's list, when given `SEAWEEDFS_FILER_URL`: it reads the list, sets this participant's entry, keeps every other entry, and adds its own administrator. An identity's actions name its own bucket, so it can't reach another. Management creates the bucket, as the identity can't. The storage must run without a static file, and with `-filer.saveToFilerLimit` larger than the list, as its S3 gateway only takes up a list the filer holds inline. `scripts/local-env.sh` runs it so, writing the first list at setup.

**Without `SEAWEEDFS_FILER_URL`, participants share the configured S3 identity, as they do today, and management logs that at start.** This is deliberate, because the [DigitalTwin](https://github.com/IndustryFusion/DigitalTwin) stack, the default dependency, starts SeaweedFS with a static file. Writing the filer's list there would lock out that stack's own identities. An operator who wants isolation has to move that storage to the filer's list, or give the dataspace its own storage. The acceptance criterion holds only with this set, and `deploy/README.md` says so.

Alternatives:

- The IAM API. It makes the same replacement, and generates keys, so its administrator can't be chosen ahead.
- Refusing to register without `SEAWEEDFS_FILER_URL`. It would stop the default stack from working at all.
- A storage instance per participant, as the external demo has. It gives real isolation on any stack, at the cost of a stateful service per participant and a new backup story.

The filer's port holds these keys in plain text. So only management may reach it. `scripts/local-env.sh` ships a policy for that, and `deploy/README.md` asks the operator for the same.

### The per-participant internal key

Each participant's Secret has its own generated `internal-key`, and management reads it from there for each call. It can already read that Secret. `ADAPTER_INTERNAL_KEY` goes from management's settings, the chart's values and the local environment. Alternative: a key derived from a master key, which keeps one secret that opens every adapter.

### Connector identity

**A connector presents a Keycloak token from its participant's own client, and checks the one it receives.**

- Signature against the realm's published keys, RS256 only, the exact issuer, and an expiry.
- A `participant_id` claim, and the role `participant:<id>`, as an adapter requires.
- The result is the connector's identity for the counterparty, `edc.agent.identity.key=participant_id`. The connector then compares it with the participant the negotiation names. So a connector claiming to be another participant fails, as does one with no valid token.

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
- [No enforcing network plugin] → Policies do nothing, silently. Token checks don't depend on them. `scripts/security-check.py` reports it.
- [Two writers to the filer's list] → Management runs as one replica, and holds a lock around the list. Another writer could lose a change, so the design says it must be the only one.
