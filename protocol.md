# Dataspace Message Protocol

This document leads on what messages mean: which messages exist, when each is valid, and how they change a conversation. For routes and HTTP details, see [gateway-api.md](gateway-api.md).

## Concepts

- **Participant:** a factory owner or machine builder, identified by `participant_id`.
- **Message:** one unit sent from one participant to another. Its `performative` says what the sender is doing.
- **Conversation:** a sequence of messages between two participants, with a state that each side keeps.
- **Capability:** a named kind of data a participant can provide. See [Capability access](#capability-access).

The token decides the sender. A message has no sender field that a client can set.

## Performatives

| Performative | Meaning |
|---|---|
| `request` | Ask the other side for something |
| `inform` | Share information. This is the default |
| `grant` | Allow a requested capability |
| `deny` | Refuse a requested capability |
| `cancel` | Withdraw an earlier message |
| `close` | End the conversation with an outcome |
| `reopen` | Open a closed conversation again |
| `escalate` | Take over a conversation for further handling |
| `deescalate` | Hand back an escalated conversation |

## Validity rules

A message that breaks these rules is refused with `422` and error `invalid_message`.

| Performative | `capability` | `in_reply_to` | `authorization` | `outcome` |
|---|---|---|---|---|
| `request`, `inform` | optional | optional | forbidden | forbidden |
| `grant` | required | required | required | forbidden |
| `deny` | required | required | forbidden | forbidden |
| `cancel` | optional | required | forbidden | forbidden |
| `close` | forbidden | optional | forbidden | required |
| `reopen`, `escalate`, `deescalate` | forbidden | optional | forbidden | forbidden |

**Authorization**, carried by `grant`:

```json
{ "scope": "conversation", "expires_at": "2026-12-01T10:00:00Z", "constraints": {} }
```

**Outcomes**, carried by `close`: `resolved`, `withdrawn`, `rejected`, `failed`, `timed_out`, `superseded`, `escalated`.

## Conversation states

| State | Meaning |
|---|---|
| `OPEN` | The conversation is active |
| `ESCALATING` | One side has escalated it |
| `CLOSED_RESOLVED`, `CLOSED_WITHDRAWN`, `CLOSED_REJECTED`, `CLOSED_FAILED`, `CLOSED_TIMED_OUT`, `CLOSED_SUPERSEDED`, `CLOSED_ESCALATED` | Closed with the matching outcome |

A message without a `conversation_id` starts a new conversation in state `OPEN`.

## State rules

| Situation | Result |
|---|---|
| `escalate` while `OPEN` | Moves to `ESCALATING`, and records who escalated |
| `deescalate` while `ESCALATING`, by the escalator | Moves to `OPEN` |
| `close` while `ESCALATING`, by the escalator | Moves to the closed state for its outcome |
| `close` or `deescalate` while `ESCALATING`, by the other side | Refused |
| `close` with outcome `escalated` | Requires `escalate` first |
| `reopen` of a conversation closed as `escalated` or `superseded` | Refused |
| `reopen` of any other closed conversation | Moves to `OPEN` |
| Duplicate or race-losing `close`, duplicate `escalate`, redundant `reopen` | Accepted with `202` and `applied: false`. The state does not change |
| Any other message on a closed conversation | Refused |

A refused message returns `409` with error `conversation_state_violation`, and is stored for audit.

`applied` tells a client whether its message changed the conversation.

## Both sides keep state

Each participant holds its own copy of the conversation's state. The sender applies these rules when it accepts a message, and the receiver applies the same rules to its own copy when notified. The receiver also checks that:

- `receiver_participant` is itself.
- The sender is the conversation's counterpart, on later messages in a conversation.

If the receiver refuses a message, the sender sees status `error` or `rejected`. The sender's state has already moved at that point, so the two copies can differ until a further message settles them. Use `GET /conversations/{id}` on each side to compare.

## Delivery

- Delivery to agents is by polling. See `GET /inbox/messages` in [gateway-api.md](gateway-api.md).
- A message with an empty payload is delivered like any other.
- A duplicate `message_id` at the receiver is safe, and creates no second inbox entry.

## Capability access

Capability policy records and reports who may access what. **It is advisory, and it does not block messages.**

- The dataspace does not check capability policy when a message is sent or received. A message naming a denied capability is still delivered.
- The sending application is responsible for checking access and for filtering what it shares.
- `grant` and `deny` messages do not change approval records. Access is changed through the capability routes in [gateway-api.md](gateway-api.md).

Communication is still bound by the role rules and by the conversation rules above.

### Catalogue

| Capability | Provider | Default |
|---|---|---|
| `twin:direct` | Factory owner | `auto` |
| `twin:adjacents` | Factory owner | `on-request` |
| `twin:history` | Factory owner | `on-request` |
| `mb:confidential` | Machine builder | `auto` |

### Effective status

| `status` | `source` | Meaning |
|---|---|---|
| `auto` | `default` | The provider allows everyone by default |
| `on-request` | `default` | The consumer must ask first |
| `pending` | `explicit` | A request is waiting for a decision |
| `approved` | `explicit` | The provider allowed this consumer |
| `denied` | `explicit` | The provider refused this consumer |

## Known limits

These behaviours are deliberately not provided at this stage:

- **No automatic closing.** Conversations are not closed for inactivity, and `response_due_at` is carried but does not act.
- **`authorization.expires_at` is not enforced.** It is carried for the applications to use.
- **`cancel` changes no state of its own.** It is recorded, and it is for the applications to act on.
- **No delivery guarantee to the sender.** `notified` means the receiver accepted the notification, not that it has the data.
- **No idempotency key.** Retrying a send can create a second message.
- **A restart strands messages in progress.** Sending and fetching run inside the adapter process. A message in progress when it stops stays in its current status, with no retry, and retention does not remove it.
- **No ordering across messages.** Each message runs its own transfer, so a later message can arrive first.
- **Content without files is limited to `MAX_JSON_BYTES` on arrival,** including a `content_ref` asset, as it is read into memory when an agent reads the message. A larger asset gives the message status `error`.
- **Every message runs a full connector cycle,** including messages with an empty payload.
- **Connector policies permit everything,** and DSP identity is mocked. Tracked in #20.
- **The connector's calls to internal adapter routes are unauthenticated.** Tracked in #20.
