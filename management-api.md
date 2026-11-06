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

The API uses the caller's token for the Keycloak Admin API. It stores no data of its own.

## Routes

| Route | Auth |
|---|---|
| `GET /api/health` | None |
| `GET /api/participants` | None |
| `GET /api/participants/{id}` | None |
| `GET /api/participants/compatible/{id}` | None |
| `POST /api/participants` | `dataspace-admin` |
| `POST /api/demo` | `dataspace-admin` |
| `DELETE /api/participants/{id}` | `dataspace-admin` |
| `GET /api/participants/{id}/credentials` | `dataspace-admin` |
| `GET /api/participants/{id}/capabilities` | None |
| `PATCH /api/participants/{id}/capabilities/{capability}` | `dataspace-admin` |
| `POST /api/participants/{id}/approvals` | `dataspace-admin` |
| `PATCH /api/participants/{id}/approvals/{approval_id}` | `dataspace-admin` |
| `GET /api/policy?fo=&mb=` | None for hosted pairs. `dataspace-admin` if either side is external |

#20 restricts the unauthenticated reads.

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
- An external participant gives its own `adapter_url` and `dsp_url`.
- `peer_notify_url` is the address peers outside the cluster use to reach this participant's adapter. For a hosted participant that is the gateway's peer route.

Returns the participant record with `client_id` and `client_secret`.

**A hosted participant** is provisioned in this order:

1. Create the adapter and connector databases.
2. Create the Keycloak role `participant:<id>`, a client-credentials client named after the participant, a `participant_id` claim mapper, and the role assignment.
3. Create the Secret, ConfigMap, and connector and adapter Deployments and Services in `dataspace-participants`.
4. Write the registry entry.

**An external participant** gets steps 2 and 4 only, as it runs its own adapter and connector.

Completed steps are undone if a later one fails. A failed re-registration does not drop an existing participant's databases, and a half-finished Keycloak client from an earlier failure is completed. Existing participants need no reconfiguration.

### `POST /api/demo`

Creates the demo participants named in `DEMO_PARTICIPANTS` through the same steps. Returns a list of the same records.

### `DELETE /api/participants/{id}`

Removes the registry entry, the Keycloak client and role, the pods and the databases, leaving no orphaned Deployments.

### `GET /api/participants/{id}/credentials`

Returns `client_id` and `client_secret`.

### Reads

`GET /api/participants`, `GET /api/participants/{id}` and `GET /api/participants/compatible/{id}` return participant records with:

```json
{
  "participant_id": "...", "participant_type": "...", "adapter_url": "...", "dsp_url": "...",
  "hosted": true, "externally_reachable": false, "peer_notify_url": null,
  "company_name": "...", "company_category": "...", "city": "...", "country": "..."
}
```

The last four fields come from the IFRIC registry, and are left out if it is unavailable, not configured or does not know the participant. See [IFRIC details](#ifric-details).

External adapters can use these read routes as their `REGISTRY_URL`.

## Capabilities and policies

Access is advisory. See [protocol.md](protocol.md).

### `GET /api/participants/{id}/capabilities`

The participant's capabilities, with their default policy and approvals.

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

The capability view for one factory owner and machine builder pair, as shown on the Policies tab.

## Health

### `GET /api/health`

The status of each component, with a detail message for any that is not healthy. The Health tab refreshes it every 15 seconds.

## IFRIC details

If configured, the API reads `GET /company/get-all-companies` from the [IFRIC registry](https://github.com/IndustryFusion/ifric-registry-service-oss), using a token from an optional `dataspace-ifric-reader` client. It caches the result for `IFRIC_LOOKUP_CACHE_SECONDS` (default 300). A failure just leaves the fields out.

## Configuration

`POSTGRES_*`, `SEAWEEDFS_*`, `KEYCLOAK_URL`, `KEYCLOAK_HEALTH_URL`, `KEYCLOAK_REALM`, `REGISTRY_URL`, `GATEWAY_URL`, `GATEWAY_PEER_URL`, `DSP_GATEWAY_URL`, `ADAPTER_INTERNAL_KEY`, `PARTICIPANTS_NAMESPACE`, `MAIN_REGISTRY`, `MAIN_REPO`, `MAIN_VERSION`, `RESOURCES_PARTICIPANT_*`, `DEMO_PARTICIPANTS`, `IFRIC_BACKEND_URL`, `IFRIC_READER_CLIENT_ID`, `IFRIC_READER_CLIENT_SECRET`, `IFRIC_LOOKUP_CACHE_SECONDS`.

The service needs a PostgreSQL user that can create databases, and RBAC in the participants namespace.
