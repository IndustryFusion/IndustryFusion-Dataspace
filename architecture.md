# Architecture

## Overview

The dataspace provides a **governed communication fabric** between participants (factory owners and machine builders). Agents never talk to each other directly. Every message travels through a single API Gateway, then to the sender's Dataspace Adapter, through an EDC connector pair, and into the receiver's adapter inbox.

The platform is designed for Kubernetes. Participants do not run any infrastructure themselves — they only interact with the public Gateway API using a Keycloak JWT.

---

## Design Philosophy: Managed Dataspace with a Federation Upgrade Path

### Why managed?

Running a Dataspace Protocol (DSP) connector requires DevOps capability, ongoing maintenance, and familiarity with EDC internals — none of which a typical SMB has or should need. The wrapper model hides all of that behind a simple HTTP API:

- Participants interact with familiar REST concepts: send a message, check an inbox, request a capability.
- DSP catalog queries, contract negotiation, and data plane transfers are fully invisible to the participant agent.
- Keycloak client IDs serve as the isolation boundary between participants on the shared infrastructure.

The operator (hub) runs the connectors in a common protected space. Participants trust the hub in a way they would not need to in a true peer-to-peer setup. For a managed industrial dataspace run by a trusted hub operator this is an explicit, acceptable trade-off — not a design flaw.

### The federation seam

The architecture does not prevent federation — it defers it. The participant registry stores an `adapter_url` per participant. In the managed model this points to the hub-operated adapter. In a federated model it points to the participant's own externally-accessible DSP endpoint.

A participant can "graduate" to self-hosted infrastructure in three steps:

1. Stand up their own EDC connector, externally reachable at a stable DSP URL.
2. Update their `adapter_url` in the registry to point at their own connector.
3. Keep using the same Keycloak client credentials and Gateway API — nothing changes from their agent's perspective.

The capability and consent model transfers cleanly: it is already participant-scoped, not adapter-scoped. Keycloak can be federated too if a participant wants their own identity provider rather than the hub's realm.

### Honest positioning

This is a **managed dataspace with a defined federation upgrade path**, not a dead end.

| Property | This platform | Pure federated (EDC-to-EDC) |
|----------|--------------|----------------------------|
| Participant effort | Near-zero (REST API + JWT) | High (run + operate EDC) |
| Data sovereignty | Operator can see all traffic | True peer-to-peer isolation |
| Onboarding cost | Days | Weeks–months |
| Federation possible | Yes, per participant, opt-in | Yes, by definition |

SMBs start in the managed tier. Participants that need full sovereignty can graduate without affecting others or requiring platform changes.

---

## Deployment Topology (Kubernetes)

```
╔══════════════════════════════════════════════════════════════════════════╗
║                        Internet / Agent networks                         ║
║                                                                          ║
║  factory-owner-1 ───────────┐                                           ║
║  factory-owner-2 ───────────┤  HTTPS + Keycloak JWT                     ║
║  machine-builder-1 ─────────┤                                           ║
║  machine-builder-2 ─────────┘                                           ║
╚══════════════════════════════╤═══════════════════════════════════════════╝
                               │
                    ┌──────────▼──────────┐
                    │   Ingress / LB      │  HTTPS :443
                    └──────────┬──────────┘
                               │
╔══════════════════════════════╪═══════════════════════════════════════════╗
║  Kubernetes cluster (all internal — no direct external access)           ║
║                              │                                           ║
║              ┌───────────────▼────────────────┐                         ║
║              │          gateway :8080          │                         ║
║              │  • Validates Keycloak JWT       │                         ║
║              │  • Reads participant_id claim   │                         ║
║              │  • Resolves adapter via registry│                         ║
║              │  • Proxies request              │                         ║
║              │  • Blocks /internal/* paths     │                         ║
║              └────┬──────────────────┬─────────┘                        ║
║                   │                  │                                   ║
║       ┌───────────▼───┐      ┌───────▼───────────┐                      ║
║       │  adapter-     │      │  adapter-         │   (one per           ║
║       │  factory-     │      │  machine-         │    participant)       ║
║       │  owner-1 :8000│      │  builder-1 :8000  │                      ║
║       └───────┬───────┘      └────────┬──────────┘                      ║
║               │                       │                                  ║
║        Mgmt API :8081          Mgmt API :8081                            ║
║               │                       │                                  ║
║       ┌───────▼───────┐      ┌────────▼──────────┐                      ║
║       │  edc-factory- │      │  edc-machine-     │   DSP :8082          ║
║       │  owner-1      ◄──────►  builder-1        │   (internal only)    ║
║       │  :8080-8084   │      │  :8080-8084       │                      ║
║       └───────┬───────┘      └────────┬──────────┘                      ║
║               │  GET /internal/payload │  POST /internal/inbox-receive   ║
║               └──────────────┬────────┘                                 ║
║                              │  (adapter-to-adapter and EDC-to-adapter   ║
║                              │   calls stay inside the cluster)          ║
║                                                                          ║
║  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ║
║  │registry  │  │PostgreSQL│  │  MinIO   │  │Keycloak  │  │management│  ║
║  │:19000    │  │:5432     │  │:9000     │  │:8080     │  │:3000     │  ║
║  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘  ║
╚══════════════════════════════════════════════════════════════════════════╝
```

The diagram above shows the *request* path (gateway → adapter → EDC
connector) — it deliberately doesn't draw every component's connection down
to PostgreSQL/MinIO, since that would be four more criss-crossing lines on
top of an already dense diagram. Drawn out explicitly instead, per adapter
(every `adapter-{slug}` has both of these — this is the actual mechanism
that splits protocol from content):

```
                    ┌─────────────────────┐
                    │   adapter-{slug}    │
                    │        :8000        │
                    └──────┬───────┬──────┘
                           │       │
                           ▼       ▼
                  ┌────────────┐ ┌───────────┐
                  │ PostgreSQL │ │   MinIO   │
                  │ db: adapter│ │  bucket:  │
                  │  _{slug}   │ │this part. │
                  └────────────┘ └───────────┘
                  conversation     message/file
                  history +        content, keyed
                  payload_ref      by message_id —
                  only, never      never stored as
                  the payload      a Postgres column
```

The EDC connector (`connector-{slug}`) has the same shape toward
PostgreSQL — its own `edc_{slug}` database, Flyway-managed, that this
project never touches directly — but no direct MinIO connection of its
own: it fetches/pushes payload bytes over HTTP from/to the *adapter*
(`GET /internal/payload`, `POST /internal/inbox-receive`, already shown in
the main diagram), and the adapter is what actually talks to MinIO on
either end. `registry` similarly has its own `registry` database;
`management` only ever provisions the databases above (`CREATE DATABASE`),
it owns none of its own.

Every one of these is a **separate database** on the same shared Postgres
cluster (`acid-cluster.iff`) — not a shared schema. A participant's adapter
can't query another participant's tables even by accident; they're
different databases entirely, just hosted on the same cluster.

### What is and is not publicly reachable

| Component | Public | Notes |
|-----------|--------|-------|
| API Gateway | Yes (via Ingress) | Single HTTPS endpoint for all agents |
| Management GUI | Ops team only | Behind VPN or separate Ingress with IP allowlist |
| Registry | No | Cluster-internal |
| Adapters | No | Cluster-internal; only reachable via gateway |
| EDC connectors | No | Cluster-internal; DSP only between connectors |
| Keycloak | Yes | Agents need to fetch tokens; standard OIDC endpoint |
| MinIO / PostgreSQL | No | Managed / cluster-internal |

---

## Kubernetes Service Names

Fixed infra lives in namespace `dataspace`; per-participant adapter/connector
pods live in `dataspace-participants`, created by the management API
(`k8s_admin.py`) — not by hand-written manifests.

Per-participant Service names use a short slug
(`sha256(participant_id)[:8]`, e.g. `2593a25b`) rather than the raw
participant ID: Kubernetes Service names are RFC 1035 labels with a hard
63-character limit, and participant IDs are long URNs
(`urn:ifric:ifx-eur-com-own-...`) that wouldn't fit once prefixed with
`adapter-`/`connector-`. The raw URN still flows into the `PARTICIPANT_ID`
env var and Keycloak client/role names — only the k8s object names are
shortened.

| k8s Service name | Namespace | Port(s) | Component |
|------------------|-----------|---------|-----------|
| `gateway` | dataspace | 8080 | API Gateway |
| `registry` | dataspace | 19000 | Participant Registry |
| `management` | dataspace | 3000 | Management GUI + API |
| `adapter-{slug}` | dataspace-participants | 8000 | Adapter for that participant |
| `connector-{slug}` | dataspace-participants | 8080 (default), 8081 (mgmt), 8082 (DSP), 8083 (ctrl), 8084 (public) | EDC connector for that participant |
| `keycloak-service` | iff | 8080 | Identity provider (shared with DigitalTwin) |
| `minio` | iff | 9000 | Object storage (shared) |
| `acid-cluster` | iff | 5432 | Relational database (shared, Zalando postgres-operator) |

Every adapter/connector listens on its normal port — no per-participant port
offsetting needed, since each gets its own Pod IP and Service (unlike the
docker-compose-era `network_mode: host` setup, where every participant
needed a unique host port to avoid collisions on `localhost`).

---

## Component Breakdown

### API Gateway

Thin FastAPI proxy. No business logic — routing only. It exposes **two**
routes, checked in this order (the first is registered before the
catch-all, so it wins the match when both could apply):

**1. `POST /peer/{receiver_participant}/internal/transfer-request`** — the
one deliberate exception to "block `internal/*`" below, and the mechanism
behind door #1 in "Request Flow — External participant ↔ hosted
participant" above. Unlike the catch-all, it resolves the adapter for a
*named other* participant (the URL parameter), not the caller's own — this
is what lets an external, self-hosted participant reach into a hosted
one's adapter at all, since a hosted adapter has no other public
reachability. It still requires a valid JWT (proving the caller is *some*
real registered participant), but does **not** itself check which
participant may notify which other — that authorization is left entirely
to the receiving adapter's own `verify_peer_token`, which confirms the
caller's token identity matches the notification body's
`sender_participant`. This route needs no adapter-side code changes to
work: every adapter's send workflow already POSTs to
`{adapter_url}/internal/transfer-request` with zero gateway awareness, so
registering a hosted participant's `peer_notify_url` as this route's own
base URL makes that same string concatenation land here.

**2. The catch-all `/{path:path}`** — everything else:

```
Request in:
  1. Validate Keycloak JWT (RS256, issuer check)
  2. Extract participant_id from token claim
  3. Look up adapter_url from registry (30 s TTL cache)
  4. Block if path starts with "internal/" (404) — no exceptions here;
     route 1 above is the only door into an adapter's /internal/* space
  5. Proxy request verbatim to adapter_url
  6. Return response

Token:  { participant_id: "factory-owner-1",
          realm_access: { roles: ["participant:factory-owner-1"] } }
          ↓
Registry: factory-owner-1 → http://adapter-factory-owner-1:8000
          ↓
Adapter: validates the same JWT again (defense-in-depth: checks participant role)
```

The gateway does not know about participant types, contract negotiation, or EDC. It only routes.

### Participant Registry

FastAPI service. Source of truth for which participants are active and where their adapters live. Participants are registered by the management API (`POST /api/participants` or `POST /api/demo`), not by the adapter itself — an adapter never calls the registry; it only ever reads it (to resolve a peer's `adapter_url`/`dsp_url` before sending).

```
POST /participants          { participant_id, participant_type, adapter_url, dsp_url }
GET  /participants          list all (optional ?type= filter)
GET  /participants/{id}     lookup one
GET  /participants/compatible/{id}  who can this participant communicate with?
DELETE /participants/{id}   remove (admin JWT required via management API)
```

In k8s: participant records are persisted in the shared Postgres cluster (registry/app.py provisions its own `registry` database there on startup, the same cluster management uses for per-participant databases), so a registry pod restart no longer forgets registered participants.

### Dataspace Adapter

Python/FastAPI service — the only component that knows about EDC, MinIO, and the dataspace protocol. One instance per participant.

**Agent-facing endpoints** (authenticated via gateway + JWT):
```
POST /outbox/messages              send a JSON message
POST /outbox/files                 send files (multipart, bundled as ZIP)
GET  /outbox/messages/{id}/status  delivery status

GET  /inbox/messages               list received messages
GET  /inbox/messages/{id}          get message + payload
GET  /inbox/messages/{id}/download download file bundle (ZIP)
POST /inbox/messages/{id}/ack      mark as processed
```

**Internal endpoints** (never exposed via gateway):
```
GET  /internal/payload/{id}        EDC data plane fetches payload from here
POST /internal/inbox-receive/{id}  EDC data plane pushes received payload here
POST /internal/transfer-request    peer adapter triggers consumer-side EDC flow
```

**Participant type enforcement**: before sending, the adapter verifies via the registry that sender and receiver are of different types (factory_owner ↔ machine_builder). Same-type sends are rejected with HTTP 403.

### EDC Connector

Eclipse Dataspace Components 0.9.0 — one instance per participant. Handles the Dataspace Protocol (DSP) for catalog queries, contract negotiation, and transfer orchestration. Only adapters and other EDC connectors communicate with it.

| Layer | Purpose |
|-------|---------|
| Control Plane | Asset registry, policy engine, contract negotiation state machine |
| Data Plane | Executes the data transfer (HttpData-PUSH: GET from provider adapter, POST to consumer adapter) |
| DSP endpoint (`:8082`) | Protocol endpoint — used only by other EDC connectors |
| Management API (`:8081`) | Used only by the local adapter |

EDC connectors communicate with each other over DSP **inside the cluster**. No DSP endpoint is ever publicly exposed.

### Management GUI

React SPA + FastAPI backend. Ops-facing, not agent-facing.

- **Health tab**: probes all services every 15 s
- **Participants tab**: shows the registry; admin JWT unlocks add/remove

Admin JWT requires the `dataspace-admin` realm role in Keycloak (see `keycloak.md`).

---

## Request Flow — Agent A sends to Agent B

```
  Agent A       Gateway        Adapter A         EDC A          EDC B        Adapter B      Agent B
    │               │               │               │               │               │            │
    │ POST          │               │               │               │               │            │
    │ /outbox/      │               │               │               │               │            │
    │ messages      │               │               │               │               │            │
    ├──────────────►│               │               │               │               │            │
    │  (JWT:        │ validate JWT  │               │               │               │            │
    │  participant  │ resolve       │               │               │               │            │
    │  _id=A)       │ adapter-A     │               │               │               │            │
    │               ├──────────────►│               │               │               │            │
    │               │               │ 1. store      │               │               │            │
    │               │               │    payload    │               │               │            │
    │               │               │    MinIO      │               │               │            │
    │               │               │               │               │               │            │
    │               │               │ 2. register   │               │               │            │
    │               │               │    asset +    │               │               │            │
    │               │               │    policy +   │               │               │            │
    │               │               │    contract   │               │               │            │
    │               │               ├──────────────►│               │               │            │
    │               │               │               │               │               │            │
    │               │◄──────────────┤ 202           │               │               │            │
    │◄──────────────┤  message_id   │               │               │               │            │
    │               │               │               │               │               │            │
    │               │               │ 3. notify     │               │               │            │
    │               │               │    peer adapter (internal)    │               │            │
    │               │               ├───────────────────────────────────────────────►            │
    │               │               │               │               │               │            │
    │               │               │               │               │ 4. query catalog (DSP)     │
    │               │               │               │◄──────────────┤               │            │
    │               │               │               ├──────────────►│               │            │
    │               │               │               │               │               │            │
    │               │               │               │ 5. negotiate contract (DSP)    │            │
    │               │               │               │◄═════════════►│               │            │
    │               │               │               │               │               │            │
    │               │               │               │ 6. transfer (HttpData-PUSH)    │            │
    │               │  GET /internal/payload/id ◄───┤               │               │            │
    │               │               ├──────────────►│               │               │            │
    │               │               │               │ POST /internal/inbox-receive/id│            │
    │               │               │               ├───────────────────────────────►            │
    │               │               │               │               │ 7. store      │            │
    │               │               │               │               │    inbox DB   │            │
    │               │               │               │               │    + MinIO    │            │
    │               │               │               │               │               │            │
    │               │               │               │               │               │  GET       │
    │               │               │               │               │               │◄───────────┤
    │               │               │               │               │               ├───────────►│
```

1. Agent A `POST`s `/outbox/messages` with a Keycloak JWT carrying
   `participant_id=A`. `gateway` validates the JWT and resolves `adapter-A`
   from the registry.
2. Adapter A uploads the payload to its own MinIO.
3. Adapter A registers an asset, an (empty, permit-everything) policy, and
   a contract definition with its own EDC connector — the asset's
   `dataAddress` is Adapter A's own `/internal/payload/{id}` endpoint (see
   "How EDC actually gets the bytes" below).
4. Adapter A returns `202` with `message_id`; the agent gets this
   immediately — everything from here on runs in the background.
5. Adapter A notifies Adapter B directly (`/internal/transfer-request`,
   authenticated with a Keycloak token asserting A's own identity, verified
   by B against the claimed `sender_participant`) and tells its own EDC
   connector to pull.
6. EDC B queries EDC A's catalog for the asset, then negotiates a contract.
7. EDC A executes the transfer (`HttpData-PUSH`): it `GET`s the payload
   from Adapter A's own `/internal/payload/{id}` and `POST`s it to Adapter
   B's `/internal/inbox-receive/{id}`.
8. Adapter B stores the received content in its own MinIO and marks the
   inbox row `received`; Agent B sees it on its next `GET /inbox/messages`.

Steps 6–7 (catalog, negotiation, transfer) happen entirely inside the cluster between EDC connectors. No external network access is needed for these steps.

---

## Request Flow — External participant ↔ hosted participant

Not trivial — this is the one flow that actually exercises the "two public
doors" (`protocol_concept.md`, "Third-party interoperability"), and the two
directions use a *different* door each. Concrete example: `thirdparty-mb`
(external, self-hosted) and the hosted factory owner FO.

**Direction 1 — external MB sends to hosted FO (door #1: `gateway`'s peer route)**

```
Agent MB         Adapter MB       EDC MB           gateway          EDC FO           Adapter FO       Agent FO
│                │                │                │                │                │                │
│ POST           │                │                │                │                │                │
│ /outbox/       │                │                │                │                │                │
│ messages       │                │                │                │                │                │
├───────────────►│                │                │                │                │                │
│                │ 1. store       │                │                │                │                │
│                │    payload     │                │                │                │                │
│                │    (own MinIO) │                │                │                │                │
│                │ 2. register    │                │                │                │                │
│                │    asset       │                │                │                │                │
│                ├───────────────►│                │                │                │                │
│◄───────────────┤                │                │                │                │                │
│  202           │                │                │                │                │                │
│                │ 3. mint own    │                │                │                │                │
│                │    token,      │                │                │                │                │
│                │    POST /peer/ │                │                │                │                │
│                │    {FO}/internal/               │                │                │                │
│                │    transfer-req│                │                │                │                │
│                ├────────────────────────────────►│                │                │                │
│                │                │                │ 4. validate    │                │                │
│                │                │                │    JWT, look up│                │                │
│                │                │                │    FO's real   │                │                │
│                │                │                │    adapter_url │                │                │
│                │                │                ├────────────────────────────────►│                │
│                │                │                │                │                │ 5. verify      │
│                │                │                │                │                │    token,      │
│                │                │                │                │                │    enforce,    │
│                │                │                │                │                │    store inbox │
│                │                │                │                │◄───────────────┤                │
│                │                │                │                │ 6. query       │                │
│                │                │                │                │    catalog +   │                │
│                │                │                │                │    negotiate + │                │
│                │                │                │                │    transfer    │                │
│                │                │◄═══════════════════════════════►│                │                │
│                │                │                │                │    (direct — no│                │
│                │                │                │                │    dsp-gateway │                │
│                │                │                │                │    hop needed  │                │
│                │                │                │                │    here; MB is │                │
│                │                │                │                │    self-hosted │                │
│                │                │                │                │    already)    │                │
│                │                │ GET /internal/ │                │                │                │
│                │                │ payload/id     │                │                │                │
│                │◄───────────────┤                │                │                │                │
│                │                │                │                │                │ 7. store       │
│                │                │                │                │                │    received    │
│                │                │                │                │                │    content     │
│                │                │                │                │                │    (own MinIO) │
│                │                │                │                │                │◄───────────────┤
│                │                │                │                │                │                │  GET
│                │                │                │                │                ├───────────────►│
```

1. MB's agent `POST`s `/outbox/messages` straight to **MB's own adapter** —
   no `gateway` hop at all; MB operates its own infrastructure end to end.
2. MB's adapter uploads the payload to its own MinIO and registers the
   asset with its own EDC connector, exactly like a hosted participant
   would with its own.
3. MB's adapter mints its own Keycloak token and `POST`s the transfer
   notification to `gateway.dataspace/peer/{FO}/internal/transfer-request`
   — **this is the first public door**: the only way to reach into a
   hosted participant's protocol layer from outside.
4. `gateway` validates the JWT, resolves FO's real (otherwise internal-
   only) adapter address, and proxies the notification through.
5. FO's adapter verifies the token really is MB (`verify_peer_token`),
   applies enforcement, stores the inbox row, and tells its own EDC
   connector to pull the asset.
6. FO's EDC connector negotiates and transfers **directly** against MB's
   own EDC connector's real DSP address — MB is self-hosted, so its DSP
   endpoint is already genuinely reachable; no `dsp-gateway` hop needed
   in this direction.
7. FO's adapter stores the received content in its own MinIO; FO's agent
   polls its own inbox as usual, through `gateway` (FO is hosted).

Step 6 crosses the external/hosted boundary just as much as anything in
Direction 2 does — the reason it doesn't need `dsp-gateway` isn't "external
↔ internal always needs a relay," it's narrower than that: `dsp-gateway`
exists specifically because IFF chooses not to expose `dataspace-
participants`' real connector addresses to the internet at all — that's an
IFF-side policy about *its own* infrastructure, not a rule about crossing
boundaries in general. MB's own DSP endpoint isn't behind any such
restriction; whether MB is reachable is entirely MB's own choice, the same
as it would be for a hosted participant if IFF chose to expose connectors
directly (it doesn't). So the asymmetry is real, not accidental: whichever
side hosts the asset being pulled determines whether a relay is needed —
`dsp-gateway` only ever guards the hosted side.

**Direction 2 — hosted FO sends to external MB (door #2: `dsp-gateway`)**

Steps 1–2 (agent → `gateway` → Adapter FO, store + register) are identical
to the pure-hosted flow above, so the diagram picks up from there:

```
Adapter FO       EDC FO           dsp-gateway      EDC MB           Adapter MB       Agent MB
│                │                │                │                │                │
│ 1. store payload                │                │                │                │
│    (own MinIO),│                │                │                │                │
│    register asset               │                │                │                │
│    — dsp address                │                │                │                │
│    advertised =│                │                │                │                │
│    dsp-gateway form             │                │                │                │
│ 2. mint own token,              │                │                │                │
│    notify MB   │                │                │                │                │
│    directly (no│                │                │                │                │
│    gateway hop —                │                │                │                │
│    MB's adapter_url             │                │                │                │
│    is already real)             │                │                │                │
├──────────────────────────────────────────────────────────────────►│                │
│                │                │                │                │ 3. verify token,
│                │                │                │                │    enforce, store
│                │                │                │                │    inbox row   │
│                │                │                │◄───────────────┤                │
│                │                │                │ 4. query catalog +              │
│                │                │                │    negotiate + │                │
│                │                │                │    transfer against             │
│                │                │                │    the advertised               │
│                │                │                │    dsp-gateway addr             │
│                │                │◄───────────────┤                │                │
│                │                │ 5. resolves    │                │                │
│                │                │    participant slug             │                │
│                │                │    from URL path,               │                │
│                │                │    proxies DSP │                │                │
│                │                │    request through              │                │
│                │◄───────────────┤                │                │                │
│                │ 6. negotiates +│                │                │                │
│                │    transfers as the             │                │                │
│                │    real provider —              │                │                │
│                │    EDC MB never│                │                │                │
│                │    learns FO's real             │                │                │
│                │    connector address            │                │                │
│◄───────────────┤                │                │                │                │
│ GET /internal/ │                │                │                │                │
│ payload/id     │                │                │                │                │
│                │                │                │                │ 7. store received
│                │                │                │                │    content     │
│                │                │                │                │    (own MinIO) │
│                │                │                │                │◄───────────────┤
│                │                │                │                │                │  GET
│                │                │                │                ├───────────────►│
```

1. FO's agent `POST`s `/outbox/messages` through `gateway` as usual (FO's
   own traffic, same as the pure-hosted flow above).
2. FO's adapter uploads the payload to its own MinIO and registers the
   asset with its own EDC connector — but because FO is
   `externally_reachable`, the DSP address it advertises for this asset
   is `dsp-gateway`'s form, not its real connector address.
3. FO's adapter notifies MB **directly** — MB's registered `adapter_url`
   is already a real, reachable address, so a hosted participant's own
   outbound call needs no gateway hop; only the reverse direction does.
4. MB's adapter tells its own EDC connector to pull the asset.
5. MB's EDC connector negotiates and transfers against the advertised
   `dsp-gateway` address — **this is the second public door**:
   `dsp-gateway` resolves the participant slug from the URL path and
   proxies the DSP request through to FO's real, otherwise-unreachable
   connector.
6. MB's adapter stores the received content in its own MinIO; MB's agent
   polls its own inbox directly — no `gateway` involved, MB operates its
   own infrastructure end to end.

**External ↔ external** (e.g. `thirdparty-mb` ↔ `thirdparty-fo`) needs
neither door — it's the same shape as "Request Flow — Agent A sends to
Agent B" above, minus the `gateway` hops on both ends, entirely on
infrastructure IFF never touches.

---

## Security Layers

```
Agent
  │
  │  HTTPS + Keycloak JWT
  ▼
Gateway            validates JWT signature + issuer
                   blocks /internal/* paths
  │
  │  HTTP (cluster-internal)
  ▼
Adapter            validates JWT again (participant role check)
                   enforces cross-type rule (factory ↔ machine builder)
  │
  │  HTTP (cluster-internal)
  ▼
EDC Management     API key auth (X-Api-Key header)
  │
  │  (internal / DSP)
  ▼
EDC DSP            Dataspace Protocol (connector-to-connector)
```

Defense-in-depth: even if the gateway misroutes a request, the adapter rejects it because the JWT's `participant:X` role does not match the adapter's own participant ID.

---

## Participant Types and Communication Rules

Two participant types exist:

| Type | Can send to | Cannot send to |
|------|-------------|----------------|
| `factory_owner` | `machine_builder` | other `factory_owner` participants |
| `machine_builder` | `factory_owner` | other `machine_builder` participants |

The rule is enforced by the adapter at send time by querying the registry for the receiver's type. It is not a Keycloak or gateway concern.

---

## Data Flow Detail

```
Provider adapter (A)                          Consumer adapter (B)
────────────────────────────────              ──────────────────────────────────
                                              
Agent A POSTs JSON or files                   
  │                                           
  ▼                                           
Adapter A:                                    
  • stores payload in MinIO                   
    messages/{id}.json  or files/{id}.zip     
  • registers EDC asset with:                 
    dataAddress.baseUrl =                     
      http://adapter-factory-owner-1:8000     
      /internal/payload/{id}                  
  • creates permissive ODRL policy            
  • notifies Adapter B ─────────────────────► Adapter B:
                                                • creates inbox_messages row (status=transferring)
                                                • triggers consumer EDC flow async
                                              
EDC-A DSP ◄─── catalog query ─────────────── EDC-B
EDC-A DSP ─── catalog response ───────────►
EDC-A DSP ◄══════ contract negotiation ═════ EDC-B
                                              
                                              EDC-B initiates transfer →
EDC-A data plane: GET /internal/payload/{id}
  → Adapter A reads from MinIO               
  → returns bytes                            
  → EDC-A data plane POSTs to: ────────────► Adapter B /internal/inbox-receive/{id}:
                                                • detects JSON vs binary
                                                • stores to MinIO
                                                • updates inbox row (status=received)
                                              
                                              Agent B: GET /inbox/messages → sees message
                                              Agent B: GET /inbox/messages/{id}/download
                                                → streams ZIP from MinIO
```

---

## Technology Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| API Gateway | Python 3.12 / FastAPI + httpx | JWT validation + HTTP proxy; stateless |
| Participant Registry | Python 3.12 / FastAPI + asyncpg | Persisted in its own `registry` database — see "Participant Registry" above |
| Dataspace Adapter | Python 3.12 / FastAPI + SQLAlchemy asyncpg | One per participant |
| EDC Connector | Eclipse EDC 0.9.0 (Java 21) | One per participant; combined CP+DP |
| Adapter database | PostgreSQL | One separate database per adapter (`adapter_{slug}` — outbox_messages, inbox_messages, conversations, capability_policies, capability_approvals), not a shared schema |
| EDC database | PostgreSQL | One separate database per EDC connector (`edc_{slug}`, Flyway-managed) |
| Payload storage | MinIO (S3-compatible) | One bucket per participant |
| Transfer type | HttpData-PUSH | Provider pushes to consumer's internal endpoint |
| Identity | Keycloak (OIDC) | RS256 JWT; realm `dataspace`; see keycloak.md |
| Management UI | React 18 + Vite / FastAPI | Health + participant administration |

---

## Adding a Participant

A single API call — no Keycloak console steps, no manifests to write, no
deploy to run:

```bash
curl -s -X POST http://dataspace-management.local/api/participants \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"participant_id": "urn:ifric:...", "participant_type": "machine_builder"}'
```

The management API (`management/api/app/routes/participants.py`,
`k8s_admin.py`) does everything in one request: creates the Postgres
databases, creates the adapter + EDC connector Deployments/Services in
`dataspace-participants`, provisions the Keycloak client/role, and registers
the participant. `adapter_url`/`dsp_url` are derived automatically from
`participant_id` — see [Kubernetes Service Names](#kubernetes-service-names).

`DELETE /api/participants/{id}` tears the same set down again, including the
pods — no orphaned Deployments left behind.

No existing participants need to be reconfigured. The registry and gateway handle discovery automatically.
