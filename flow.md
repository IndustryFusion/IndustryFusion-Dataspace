# Message Flow

A worked exchange between a factory owner (FO) and a machine builder (MB), both hosted. Each step uses a route from [gateway-api.md](gateway-api.md), and [protocol.md](protocol.md) defines the rules. Bodies are shortened.

Both agents first get a token, as [gateway-api.md](gateway-api.md) describes, and send it on every call.

## 1. Find the peer

FO:

```http
GET /participants/compatible
```

## 2. Send a request

FO asks MB for help, which starts a conversation:

```http
POST /outbox/messages

{ "receiver_participant": "<MB>", "performative": "request",
  "reply_expected": true, "payload": { "summary": "Spindle temperature alarm" } }
```

The answer is `202` with `message_id` and `conversation_state: OPEN`. FO reads the conversation id from the message:

```http
GET /outbox/messages/{id}
```

Then it follows delivery until `notified`:

```http
GET /outbox/messages/{id}/status
```

Behind this, the adapters and connectors run the transfer. See "Request Flow" in [architecture.md](architecture.md).

## 3. Receive it

MB polls:

```http
GET /inbox/messages?status=received
```

It reads the message, then acknowledges it:

```http
GET /inbox/messages/{id}
POST /inbox/messages/{id}/ack
```

## 4. Send a file as a reply

FO adds its machine data to the conversation as a file:

```http
POST /outbox/files

receiver_participant=<MB>, conversation_id=<conversation>, in_reply_to=<message>,
capability=twin:direct, files=@machine.json
```

MB polls as before. The message has `has_files: true`, and MB downloads the ZIP:

```http
GET /inbox/messages/{id}/download
POST /inbox/messages/{id}/ack
```

## 5. Ask for more data

MB checks what it may access:

```http
GET /capabilities/access?provider=<FO>
```

`twin:history` shows `on-request`, so MB asks:

```http
POST /capabilities/requests

{ "provider_participant": "<FO>", "capability": "twin:history",
  "conversation_id": "<conversation>", "purpose": "Compare with earlier runs" }
```

FO sees the request and decides:

```http
GET /capabilities/requests?status=pending
PATCH /capabilities/requests/{id}

{ "action": "approve" }
```

MB's next access check shows `approved`. FO can also tell MB in the conversation, with a `grant` message:

```http
POST /outbox/messages

{ "receiver_participant": "<MB>", "conversation_id": "<conversation>",
  "performative": "grant", "capability": "twin:history", "in_reply_to": "<message>",
  "authorization": { "scope": "conversation", "expires_at": "2026-12-01T10:00:00Z", "constraints": {} } }
```

Access is advisory, so FO checks it and filters what it shares before sending.

## 6. Reply

MB sends its recommendation:

```http
POST /outbox/messages

{ "receiver_participant": "<FO>", "conversation_id": "<conversation>",
  "performative": "inform", "in_reply_to": "<message>", "payload": { "recommendation": "Replace the coolant filter" } }
```

## 7. Close

FO closes the conversation:

```http
POST /outbox/messages

{ "receiver_participant": "<MB>", "conversation_id": "<conversation>",
  "performative": "close", "outcome": "resolved", "payload": {} }
```

Either side can then check the state, which is now `CLOSED_RESOLVED`:

```http
GET /conversations/{id}
```

A second `close` returns `202` with `applied: false`, and any other message gets `409`.

## Other flows

- **Escalation:** send `escalate`, and later `deescalate` or `close` with outcome `escalated`.
- **Reopening:** send `reopen`, except for conversations closed as `escalated` or `superseded`.
- **External participants:** "Request Flow — External participant ↔ hosted participant" in [architecture.md](architecture.md).
