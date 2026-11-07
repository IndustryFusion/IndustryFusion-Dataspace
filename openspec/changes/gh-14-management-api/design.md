# Design

## Context

`management-api.md` leads on the contract, and `architecture.md`, "Adding a Participant", on the outcome. The issue fixes the order of provisioning. This document records what they leave open.

## Decisions

### A readiness wait before the registry entry

Step 4 writes the registry entry only once the Deployments from step 3 are available, up to `PROVISION_READY_SECONDS` (default 300). So a participant that peers can find is one that can receive, and a wrong image or a crash is a failed step that is undone, not a silent half-participant. The cost is a request that can take minutes on first registration.

Alternatives: write the entry at once and let callers poll. Rejected, as nothing in the published record says whether the pods are ready, and sends to it would end in `error`.

### Undo only what this request created

Each step returns how to undo itself. A database, a client or a Kubernetes object that existed before the request isn't removed when the request fails, and a Kubernetes object it replaced is put back as it was. That is what keeps a failed re-registration from dropping an existing participant's databases.

If an undo itself fails, the answer says so, and `DELETE` removes the remains.

Alternative: on failure run the same removal as `DELETE`. Rejected, since it destroys an existing participant.

### Repeating a registration

`POST /api/participants` for a participant that exists updates it, and keeps its client secret and connector API key. This is how `externally_reachable` and `peer_notify_url` are changed, as the contract has no other route for them. Changing `hosted` or `participant_type` gives `409`: the first would strand or miss pods and the second would change what an adapter's data means. Delete the participant first.

### Whose client is whose

A shared realm holds other clients (see `keycloak.md`, "Participant identifiers"), so an id that equals an existing client's must not take that client over, or remove it on `DELETE`. A participant's client carries the attribute `dataspace.participant_id`, set when it is created in one call. A client without it gives `409`. One with it, however incomplete, is completed: the mapper, service account and role assignment are each checked and added if missing.

Alternative: a list of reserved ids. Rejected, as it can't cover other clients in a shared realm.

### Slug collisions

Object names use `sha256(participant_id)[:8]`, as the contract says. Each object carries the full id as an annotation, and a request whose slug is held by a different participant gets `409`, instead of overwriting it.

### One request at a time per participant

Requests for one participant are serialised with a lock in the process, so a failing request can't undo what a concurrent one relies on. That needs one replica, which is what #15 deploys. Requests for different participants run concurrently, and `POST /api/demo` provisions its participants concurrently. If one fails its own steps are undone, the others stay, and the call can be repeated.

Alternative: a PostgreSQL advisory lock, which would allow more replicas. Rejected for now: nothing needs a second replica of an administrator's tool.

### The internal key never leaves the cluster

`ADAPTER_INTERNAL_KEY` goes only to adapters of participants recorded as `hosted`. Capability routes for an external participant give `409`, as it runs its own adapter. `GET /api/policy` with an external side reports that side under `unavailable`. Carrying these calls to external adapters belongs to #18.

### `DELETE` keeps going, and can be repeated

It removes the registry entry first, so that no peer finds the participant, then the Kubernetes objects, waiting for the pods to go, then the databases, the Keycloak client and role, and the participant's bucket. It tries every step. If one fails, the answer is `502` naming it, and a repeat finishes the job. So `404` means that nothing at all was found.

The bucket is not named in the issue's list. It is removed because the issue requires no orphans, and a participant registered again later must not inherit content. An external participant has no bucket here.

### Kubernetes and Keycloak access

Plain HTTP with the existing `httpx` dependency, using the service account's token in the cluster. A Kubernetes client library would add a large dependency for six object kinds. New dependencies: `asyncpg` to create databases, `PyJWT[crypto]` to check tokens as the gateway does, and `boto3` to remove a bucket, as the adapter does.

### Configuration the contract names but doesn't define

- `DEMO_PARTICIPANTS`: comma-separated `<id>=<type>`.
- `RESOURCES_PARTICIPANT_CPU_REQUEST`, `_CPU_LIMIT`, `_MEMORY_REQUEST`, `_MEMORY_LIMIT`: applied to each participant container. Unset ones are left out. The memory limit defaults to `2Gi`, as an adapter streams files and a connector runs a JVM.
- `MAIN_REGISTRY`, `MAIN_REPO`, `MAIN_VERSION`: images are `[<registry>/]<repo>/adapter:<version>` and `.../connector:<version>`.
- `MAX_UPLOAD_BYTES` and `MAX_JSON_BYTES` are added: passed on to adapters, so they agree with the gateway.

### Addresses

For a hosted participant `adapter_url` and `dsp_url` come from the slug, whatever the request says. `peer_notify_url` is `{GATEWAY_PEER_URL}/peer/{id}` when `externally_reachable` is true and `GATEWAY_PEER_URL` is set, and otherwise `null`. Adapters notify a peer at `peer_notify_url` if it has one, so setting it for every hosted participant would send all hosted traffic through the gateway for no reason.

An external participant must give `adapter_url` and `dsp_url`, or gets `422`.

### Shape of the views the contract leaves open

`GET /api/health` gives `{"status": "ok" | "degraded", "components": [{"name", "status", "detail"}]}`, and is `200` either way, as the Health tab has to read it when something is down. `/health` stays as the service's own probe.

`GET /api/policy` gives both directions for the pair: each entry has `provider`, `consumer`, the capability's fields, `default_policy`, `status`, `source`, `approval_id` and `decision_note`, so that the Policies tab has what it needs for approve, deny and reset.

`GET /api/participants/{id}/capabilities` gives what the adapter's `GET /internal/capabilities` gives.

## Risks

- Participants' databases use one shared PostgreSQL user, as the local environment does. Per-participant users would be stronger, and are for #20.
- The token route and admin routes have no body limit of their own. Reaching the service at all is restricted (see "What is and is not publicly reachable"), and #15's Ingress limits it.
- A process that dies during provisioning leaves what it had made. A repeat completes it, and `DELETE` removes it.

## Conflicts

`AGENTS.md` asks for the `spec-approved` label before implementation. A maintainer approved this milestone outside GitHub and the label is pending, as the Pull Request states.
