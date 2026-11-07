# Management API

This document leads on the administration contract. Services deliver it in #14 and #17, and any change goes through an OpenSpec proposal.

**Base URL:** the management service, on port 3000. It also serves the management UI. Restrict who can reach it, as [architecture.md](architecture.md) describes.

## Authentication

Admin routes need a token with the realm role `dataspace-admin`. Get one with the `dataspace-admin-cli` client:

### `POST /api/admin/token`

```json
{ "client_id": "dataspace-admin-cli", "client_secret": "..." }
```

Returns the token response from Keycloak. Send it as `Authorization: Bearer <token>`.

The API uses the caller's token for the Keycloak Admin API. It stores no data of its own. It holds one credential, `MANAGEMENT_CLIENT_SECRET` for `dataspace-admin-cli`, for finishing what a caller started: undoing a failed registration, and removing a participant's client and role after waiting for its pods, as a caller's token can expire during those waits. Without it, what can't be undone is named in the answer, and `DELETE` finishes it.

## Routes

| Route | Auth |
|---|---|
| `GET /api/health` | None |
| `GET /api/participants` | None, for what is public. See [Reads](#reads) |
| `GET /api/participants/{id}` | None, for what is public |
| `GET /api/participants/compatible/{id}` | None, for what is public |
| `POST /api/participants` | `dataspace-admin` |
| `POST /api/demo` | `dataspace-admin` |
| `DELETE /api/participants/{id}` | `dataspace-admin` |
| `GET /api/participants/{id}/credentials` | `dataspace-admin` |
| `GET /api/participants/{id}/capabilities` | `dataspace-admin` |
| `PATCH /api/participants/{id}/capabilities/{capability}` | `dataspace-admin` |
| `POST /api/participants/{id}/approvals` | `dataspace-admin` |
| `PATCH /api/participants/{id}/approvals/{approval_id}` | `dataspace-admin` |
| `GET /api/policy?fo=&mb=` | `dataspace-admin` |

`GET /api/health` shows each component's status, with details that hold no addresses or credentials.

Errors use `{"detail": "..."}` with `401`, `403`, `404`, `409`, `422`, `502` or `503`.

## Participants

### `POST /api/participants`

```json
{
  "participant_id": "urn:example:machine-builder-1",
  "participant_type": "machine_builder",
  "hosted": true,
  "externally_reachable": false,
  "adapter_url": null,
  "dsp_url": null,
  "peer_notify_url": null
}
```

- `participant_type` accepts a bare name, a `ds:` prefixed name or a full IRI.
- `hosted` defaults to `true`. For a hosted participant, `adapter_url` and `dsp_url` come from the participant id, with the slug `sha256(participant_id)[:8]`.
- An external participant gives its own `adapter_url` and `dsp_url`. See [External participants](#external-participants).
- `peer_notify_url` is the address peers outside the cluster use to reach this participant's adapter. For a hosted participant that is the gateway's peer route.
- `externally_reachable` on a hosted participant makes it announce addresses that work from outside: `peer_notify_url` and `dsp_url` become the public ones, and `adapter_url` stays its adapter's real address. It needs `GATEWAY_PEER_URL` and `DSP_GATEWAY_PEER_URL` on this service, and gives `422` without them.

Returns the participant record with `client_id` and `client_secret`.

**A hosted participant** is provisioned in this order:

1. Create its PostgreSQL user, and the adapter and connector databases, which that user owns and no other can connect to.
2. Create the Keycloak role `participant:<id>`, a client-credentials client named after the participant, a `participant_id` claim mapper, and the role assignment.
3. Create its bucket and an S3 identity limited to it, if `SEAWEEDFS_FILER_URL` is set. Otherwise it uses the configured identity, shared with every other participant, and its adapter creates the bucket. See [deploy/README.md](deploy/README.md).
4. Create the Secret, ConfigMap, and connector and adapter Deployments and Services in `dataspace-participants`. The Secret holds what only this participant has: its database password, S3 keys, internal key and connector API key. They are generated once.
5. Write the registry entry.

**An external participant** gets steps 2 and 5 only, as it runs its own adapter and connector.

The registry entry is written once the participant's pods are available, so a registration can take minutes: at most `PROVISION_READY_SECONDS` in all, with up to 50 seconds more to undo it if that runs out. Allow for that in any proxy in front of this service. A participant that peers can find is one that can receive.

Completed steps are undone if a later one fails. Anything that couldn't be, or that there was no time for, is named in the answer. A failed re-registration does not drop an existing participant's databases, and a half-finished Keycloak client from an earlier failure is completed. Existing participants need no reconfiguration.

Registering an existing participant again updates it and keeps its credentials. This is how to change `externally_reachable` or an external participant's addresses. Changing `externally_reachable` restarts the participant's adapter and connector, which interrupts any transfer in progress. A hosted participant's `peer_notify_url` is the gateway's peer route when `externally_reachable` is true, and `null` otherwise. It gives `409`:

- if `hosted` or `participant_type` would change. Delete the participant first.
- if the id equals a client in the realm that this service did not create.
- if the id's slug is held by another participant.

`participant_id` has up to 200 ASCII letters, digits, `.`, `_`, `:` and `-`, and starts with a letter or digit. It can't be `compatible`. Requests for one participant are handled one at a time, so run one replica of this service.

### `POST /api/demo`

Creates the demo participants named in `DEMO_PARTICIPANTS` through the same steps, at the same time. Returns a list of the same records. If one fails its steps are undone, the others stay, and the call can be repeated.

### `DELETE /api/participants/{id}`

Removes the registry entry, the Keycloak client and role, the pods and every other Kubernetes object, the databases and PostgreSQL user, and the participant's bucket and S3 identity, leaving no orphaned Deployments.

Every step is tried. If one fails the answer is `502` naming it, and repeating the call finishes the removal. `404` means nothing was found.

### `GET /api/participants/{id}/credentials`

Returns `client_id` and `client_secret`.

### Reads

`GET /api/participants`, `GET /api/participants/{id}` and `GET /api/participants/compatible/{id}` return participant records with:

```json
{
  "participant_id": "...", "participant_type": "...", "adapter_url": null, "dsp_url": null,
  "hosted": true, "externally_reachable": false, "peer_notify_url": null,
  "company_name": "...", "company_category": "...", "city": "...", "country": "..."
}
```

**What is public.** Without a token, a hosted participant has `adapter_url` `null`, and `dsp_url` `null` unless it is `externally_reachable`, when that is the DSP gateway's address. An external participant's own addresses are shown, as its peers need them. With a `dataspace-admin` token, the record is whole. Any other token gives `401` or `403`, rather than being treated as none.

The last four fields come from the IFRIC registry, and are left out if it is unavailable, not configured or does not know the participant. See [IFRIC details](#ifric-details).

External adapters use these read routes as their `REGISTRY_URL`, as `<management URL>/api`. What is public is enough for that.

## External participants

An external participant runs its own adapter, connector, PostgreSQL and S3 storage, and exchanges messages with hosted participants through the two public doors in [architecture.md](architecture.md). Its agent calls its own adapter, with the routes in [gateway-api.md](gateway-api.md), except for `/participants/compatible`, which only the gateway has.

**What it costs to trust one.** An adapter proves who it is with its own bearer token, and no audience is checked. So an external participant holds the token of each hosted participant that talks to it, and can use it at the public gateway, as that participant, until it expires. See "External participants" in [keycloak.md](keycloak.md). Registering one is a decision to trust it with that.

**To onboard one:**

1. Make sure of the doors. The gateway has to be reachable from where it runs, and so does the DSP gateway, which isn't exposed by default: see `ingress.dspGateway`, `participants.gatewayPeerUrl` and `participants.dspGatewayPeerUrl` in [deploy/README.md](deploy/README.md). So do these read routes: add its address to `ingress.management.allowFrom`.
2. Register it, with `hosted: false` and the addresses where hosted connectors and adapters can reach it. It gets only its Keycloak client and registry entry, with no databases or pods. The answer has its `client_secret`.

   ```json
   { "participant_id": "urn:example:external-mb", "participant_type": "machine_builder", "hosted": false,
     "adapter_url": "https://mb.example/adapter", "dsp_url": "https://mb.example/connector/api/v1/dsp" }
   ```

3. Set `externally_reachable` on each hosted participant it will talk to, by registering it again. A hosted participant that isn't reachable can't be reached from outside, and a message to it ends with status `error`.
4. Configure its adapter:

   | Setting | Value |
   |---|---|
   | `PARTICIPANT_ID`, `PARTICIPANT_TYPE`, `KEYCLOAK_CLIENT_SECRET` | From the registration |
   | `ADAPTER_URL` | The `adapter_url` it registered. Connectors push content here |
   | `EDC_DSP_URL` | The `dsp_url` it registered |
   | `REGISTRY_URL` | `<management URL>/api` |
   | `KEYCLOAK_URL`, `KEYCLOAK_REALM` | Exactly what the hub's services use, as tokens' issuers are compared exactly |

   Leave `PEER_NOTIFY_URL` empty, as its `adapter_url` is already reachable. Its connector's `edc.participant.id` is its `participant_id`, its callback address is its `dsp_url`, and it needs the same Keycloak settings and client secret: hosted connectors refuse one without a token from that client.

**What it needs to reach:** the gateway, the DSP gateway, these read routes and Keycloak. **What has to reach it:** hosted connectors, on its connector's DSP port and its adapter's `/internal/inbox-receive`, and hosted adapters, on its `/internal/transfer-request` and `/internal/capabilities`. Keep its connector's management and control ports closed.

`scripts/external-demo.py` deploys two like this on a local environment, each with a NetworkPolicy to these limits.

**To remove one,** `DELETE /api/participants/{id}`. Its own services are its own to remove.

## Capabilities and policies

Access is advisory. See [protocol.md](protocol.md). These routes need an administrator, and show who asked for what. They use the adapter's internal capability routes, with the key that participant alone has, read from its Secret. It is only sent to its own hosted adapter, so these routes give `409` for an external participant. A decision on a resolved request gives `409`, as on the agent route: reset first, or use `POST /api/participants/{id}/approvals`, which replaces it.

### `GET /api/participants/{id}/capabilities`

The participant's capabilities, with their default policy and approvals.

```json
{
  "capabilities": [
    { "capability": "twin:history", "label": "...", "description": "...", "data_classification": "operational", "default_policy": "on-request" }
  ],
  "approvals": [
    { "id": "...", "consumer_id": "...", "capability": "twin:history", "status": "pending", "conversation_id": null,
      "purpose": null, "note": null, "decision_note": null, "requested_at": "...", "resolved_at": null }
  ]
}
```

### `PATCH /api/participants/{id}/capabilities/{capability}`

```json
{ "default_policy": "on-request" }
```

`default_policy` is `auto` or `on-request`.

### `POST /api/participants/{id}/approvals`

Records a decision for a consumer.

```json
{ "consumer_id": "...", "capability": "twin:history", "action": "approve" }
```

`action` is `approve`, `deny` or `request`.

### `PATCH /api/participants/{id}/approvals/{approval_id}`

```json
{ "action": "approve" }
```

`action` is `approve`, `deny` or `reset`.

### `GET /api/policy?fo=&mb=`

The capability view for one factory owner and machine builder pair, in both directions, as shown on the Policies tab. Gives `404` for an unregistered side, and `422` if `fo` and `mb` aren't of those types.

```json
{
  "factory_owner": "...", "machine_builder": "...",
  "capabilities": [
    { "provider": "...", "consumer": "...", "capability": "twin:history", "label": "...", "description": "...",
      "data_classification": "operational", "default_policy": "on-request", "status": "approved", "source": "explicit",
      "approval_id": "...", "decision_note": null }
  ],
  "unavailable": []
}
```

An external side's capabilities are held by its own adapter, so it is listed in `unavailable`. This shows who has access to what, so it needs an administrator.

## Health

### `GET /api/health`

The status of each component, with a detail message for any that is not healthy. The answer is `200` either way. The Health tab refreshes it every 15 seconds.

```json
{
  "status": "degraded",
  "components": [
    { "name": "registry", "status": "ok", "detail": null },
    { "name": "gateway", "status": "unhealthy", "detail": "It could not be reached" }
  ]
}
```

The components are `registry`, `gateway`, `dsp-gateway`, `keycloak`, `postgresql` and `storage`. A top-level `status` is `ok` or `degraded`. A component with no address configured has the status `not configured`.

`GET /health` is the service's own probe.

## IFRIC details

If configured, the API reads `GET /company/get-all-companies` from the [IFRIC registry](https://github.com/IndustryFusion/ifric-registry-service-oss), using a token from an optional `dataspace-ifric-reader` client. It caches the result for `IFRIC_LOOKUP_CACHE_SECONDS` (default 300). A failure just leaves the fields out.

## Configuration

`POSTGRES_*`, `SEAWEEDFS_*`, `KEYCLOAK_URL`, `KEYCLOAK_HEALTH_URL`, `KEYCLOAK_REALM`, `MANAGEMENT_CLIENT_ID` (default `dataspace-admin-cli`), `MANAGEMENT_CLIENT_SECRET`, `REGISTRY_URL`, `GATEWAY_URL`, `GATEWAY_PEER_URL`, `DSP_GATEWAY_URL`, `DSP_GATEWAY_PEER_URL`, `PARTICIPANTS_NAMESPACE`, `MAIN_REGISTRY`, `MAIN_REPO`, `MAIN_VERSION`, `RESOURCES_PARTICIPANT_*`, `DEMO_PARTICIPANTS`, `IFRIC_BACKEND_URL`, `IFRIC_READER_CLIENT_ID`, `IFRIC_READER_CLIENT_SECRET`, `IFRIC_LOOKUP_CACHE_SECONDS`.

Also `MAX_UPLOAD_BYTES` and `MAX_JSON_BYTES`, passed on to adapters, which must match the gateway's, and `PROVISION_READY_SECONDS` (default 300), how long a whole registration may take.

| Setting | Holds |
|---|---|
| `DEMO_PARTICIPANTS` | Comma-separated `<id>=<type>` |
| `SEAWEEDFS_FILER_URL` | The storage's filer, for an S3 identity per participant. Empty means participants share the configured identity. See [deploy/README.md](deploy/README.md) before setting it |
| `GATEWAY_PEER_URL`, `DSP_GATEWAY_PEER_URL` | What an `externally_reachable` participant announces. They have to work from outside the cluster and from inside it, as two reachable participants use them too |
| `MAIN_REGISTRY`, `MAIN_REPO`, `MAIN_VERSION` | Participant images are `[<registry>/]<repo>/adapter:<version>` and `.../connector:<version>` |
| `RESOURCES_PARTICIPANT_CPU_REQUEST`, `_CPU_LIMIT`, `_MEMORY_REQUEST`, `_MEMORY_LIMIT` | Per participant container. Unset ones are left out, except the memory limit, which defaults to `2Gi` |

The service needs a PostgreSQL user that can create databases and roles, and RBAC in the participants namespace. It can read Secrets there, so it holds what they hold.
