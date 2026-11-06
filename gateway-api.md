# Agent API

This document leads on the HTTP contract between an agent and the dataspace. It is written ahead of the services that implement it. Those services deliver it in #9, #10, #11, #12 and #13, and any change goes through an OpenSpec proposal.

For what messages mean, see [protocol.md](protocol.md). For a worked example, see [flow.md](flow.md).

**Base URL:** the API Gateway. Agents never call adapters, connectors or `/internal/*` routes.

## Authentication

Get a token from Keycloak using the client credentials issued when the participant was registered:

```http
POST {KEYCLOAK_URL}/realms/dataspace/protocol/openid-connect/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&client_id=<participant_id>&client_secret=<secret>
```

Send it on every request:

```http
Authorization: Bearer <token>
```

- Refresh the token when it expires, or on `401`.
- Request tokens through the URL the services are configured with, because they check the issuer exactly.
- The token must carry the `participant_id` claim, and the realm role `participant:<id>`. A client-credentials participant client has both. See [keycloak.md](keycloak.md).

## Health and discovery

### `GET /health`

Needs no token. Returns `200` when the gateway is up.

### `GET /participants/compatible`

The participants this one may communicate with.

```json
[
  {
    "participant_id": "urn:example:machine-builder-1",
    "participant_type": "https://industryfusion.github.io/contexts/ontology/v0/dataspace#machine_builder",
    "adapter_url": "...",
    "dsp_url": "...",
    "hosted": true,
    "externally_reachable": false,
    "peer_notify_url": null
  }
]
```

`participant_type` is a full IRI.

## Sending

### `POST /outbox/messages`

| Field | Type | Required | Notes |
|---|---|---|---|
| `receiver_participant` | string | yes | |
| `performative` | string | no | Default `inform`. See [protocol.md](protocol.md) |
| `capability` | string | by performative | |
| `in_reply_to` | string | by performative | A `message_id` |
| `authorization` | object | by performative | `{scope, expires_at, constraints}` |
| `outcome` | string | by performative | |
| `conversation_id` | string | no | Omit to start a conversation |
| `payload` | object | no | May be empty. Not with `content_ref`. The whole request can be up to `MAX_JSON_BYTES`, by default 4 MiB, so send larger data as files |
| `content_ref` | object | no | `{asset_id, dsp_url}`, an asset already registered with a connector. Not with `payload` |
| `reply_expected` | boolean | no | |
| `expires_at` | date-time | no | The content is purged after this time |
| `response_due_at` | date-time | no | Carried for the receiver |

Returns `202`:

```json
{ "message_id": "...", "status": "pending", "applied": true, "conversation_state": "OPEN" }
```

### `POST /outbox/files`

Multipart form. Returns `202` with the same body as `POST /outbox/messages`. The files are delivered as one ZIP.

| Field | Required | Notes |
|---|---|---|
| `receiver_participant` | yes | |
| `files` | yes | One or more |
| `performative` | no | Default `inform` |
| `capability` | no | |
| `conversation_id` | no | |
| `in_reply_to` | no | Marks the file as a reply |

The whole request, including its multipart framing, can be up to `MAX_UPLOAD_BYTES`, which each deployment sets on the gateway and adapters. The default is 1 GiB. Over that, the answer is `413`. An Ingress in front of the gateway must allow at least the same body size.

A form can have up to 256 files. A file's name in the ZIP keeps only its last part, where `/`, `\\` and `:` all separate parts, without trailing dots or spaces. A name reserved on Windows, such as `CON`, gets a leading `_`. A repeated name gets a number, as in `data-2.csv`, and an empty one becomes `file-<n>`. Files are stored in the ZIP uncompressed.

### `GET /outbox/messages/{id}`

```json
{
  "message_id": "...", "conversation_id": "...", "performative": "request",
  "capability": null, "in_reply_to": null, "outcome": null,
  "sender_participant": "...", "receiver_participant": "...",
  "created_at": "...", "payload_ref": "...", "content_ref": null,
  "reply_expected": true, "status": "notified", "applied": true
}
```

### `GET /outbox/messages/{id}/status`

```json
{
  "message_id": "...", "status": "notified", "edc_transfer_id": null,
  "error_message": null, "updated_at": "...", "applied": true, "conversation_state": "OPEN"
}
```

| `status` | Meaning |
|---|---|
| `pending` | Accepted, not yet registered |
| `registered` | Registered with the connector |
| `notified` | The receiver accepted the notification. This does not mean it has the data |
| `error` | Final. See `error_message` |
| `rejected` | Final. The receiver refused it |

## Receiving

Delivery is by polling.

### `GET /inbox/messages?status=`

Newest first. To see only messages ready to read, use `status=received`. Without the filter, messages still in transfer are included.

| `status` | Meaning |
|---|---|
| `transferring`, `negotiating`, `negotiated` | On their way |
| `received` | Ready to read |
| `acked` | Acknowledged |
| `error` | Could not be received. See `error_message` |

### `GET /inbox/messages/{id}`

```json
{
  "message_id": "...", "conversation_id": "...", "performative": "grant",
  "capability": "twin:history", "in_reply_to": "...", "outcome": null,
  "authorization": { "scope": "conversation", "expires_at": "...", "constraints": {} },
  "expires_at": null, "response_due_at": null,
  "sender_participant": "...", "receiver_participant": "...",
  "created_at": "...", "received_at": "...",
  "payload": {}, "status": "received", "applied": true,
  "error_message": null, "has_files": false
}
```

`payload` is `{"_bundle": true}` for file messages, and `null` when there is none or its content was purged. The list route returns the same object for each message.

### `POST /inbox/messages/{id}/ack`

Returns `204`, and is safe to repeat. Content of a message that is not acknowledged is kept.

### `GET /inbox/messages/{id}/download`

Returns the message's files as a ZIP, with the same bytes that were sent. Gives `400` if it has none, and `404` if they have not arrived yet, or have been removed by retention.

## Conversations

### `GET /conversations?state=`

The state filter is case-insensitive.

```json
[
  {
    "conversation_id": "...", "state": "OPEN", "outcome": null,
    "counterpart_participant": "...", "opened_at": "...", "closed_at": null,
    "last_message_at": "...", "escalated_by": null
  }
]
```

### `GET /conversations/{id}`

The same object, plus:

```json
{
  "messages": [
    {
      "message_id": "...", "direction": "sent", "performative": "request",
      "capability": null, "in_reply_to": null, "outcome": null,
      "sender_participant": "...", "receiver_participant": "...",
      "created_at": "...", "applied": true, "replied_at": null, "payload": {}
    }
  ],
  "outstanding_requests": []
}
```

`outstanding_requests` holds requests that have no reply yet, in the same form as `messages`.

## Capabilities

Access is advisory: these routes record and report it, and do not block messages. See [protocol.md](protocol.md), including the catalogue and status values.

### `GET /capabilities/access?provider=&consumer=`

Give one of the two:

- `provider=<id>`: what the caller may access at that provider.
- `consumer=<id>`: what that consumer may access at the caller, including the caller's own defaults.

```json
[
  {
    "capability": "twin:history", "label": "...", "description": "...",
    "data_classification": "operational", "status": "on-request", "source": "default"
  }
]
```

### `POST /capabilities/requests`

Returns `202`.

```json
{ "provider_participant": "...", "capability": "twin:history", "conversation_id": null, "purpose": "...", "note": "..." }
```

`conversation_id`, `purpose` and `note` are optional.

### `GET /capabilities/requests?status=`

Requests received by the caller. `status` is `pending`, `approved` or `denied`.

```json
[
  {
    "id": "...", "consumer_id": "...", "capability": "twin:history", "status": "pending",
    "conversation_id": null, "purpose": "...", "note": "...",
    "requested_at": "...", "resolved_at": null
  }
]
```

### `PATCH /capabilities/requests/{id}`

```json
{ "action": "approve" }
```

`action` is `approve` or `deny`. Gives `409` if the request is already resolved.

### `POST /capabilities/policy`

Sets access for one consumer, without a request.

```json
{ "consumer_id": "...", "capability": "twin:history", "action": "approve" }
```

`action` is `approve`, `deny` or `reset`, which goes back to the default.

## Errors

| Status | When | Body |
|---|---|---|
| `400` | Download of a message with no files | Standard |
| `401` | Missing or invalid token | Standard |
| `403` | No `participant_id` claim, participant not registered, role mismatch, or a receiver whose role is not compatible | Standard |
| `404` | Unknown message, conversation or request, or an unregistered receiver. `internal/*` paths also give `404` | Standard |
| `409` | Message not allowed in this conversation state | See below |
| `409` | Capability request already resolved | Standard |
| `413` | The request is larger than `MAX_UPLOAD_BYTES` for `POST /outbox/files`, or `MAX_JSON_BYTES` for any other route | Standard |
| `422` | Message breaks a validity rule | See below |
| `422` | Request does not match the schema | Standard validation body, without the values sent |
| `502` | Keycloak's signing keys are unreachable | Standard |
| `503` | Adapter or registry unavailable | Standard |
| `504` | Adapter did not answer within 120 seconds | Standard |

**Standard** means `{"detail": "..."}`.

A state violation (`409`) and an invalid message (`422`) have these bodies. A `422` can also be the standard validation body, so clients should handle both.

```json
{
  "error": "conversation_state_violation", "reason": "...", "detail": "...",
  "conversation_id": "...", "conversation_state": "CLOSED_RESOLVED", "closed_at": "..."
}
```

```json
{ "error": "invalid_message", "reason": "...", "detail": "...", "performative": "grant" }
```

## Advice for clients

- Use `GET /conversations/{id}` as the source of a conversation's state, not only the inbox.
- Take care retrying a send, as there is no idempotency key.
- Do not rely on message order.
- Check capability access before sending data. The dataspace will not block it.
