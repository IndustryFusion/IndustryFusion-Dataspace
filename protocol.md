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

The table above leaves these situations open. They are refused too, with these reasons:

| Situation | `reason` |
|---|---|
| `close`, `reopen` or `deescalate` on a conversation this participant doesn't have. `conversation_state` is `null`, and no conversation is created | `conversation_not_found` |
| `deescalate` while `OPEN` | `not_escalated` |
| `reopen` while `ESCALATING` | `not_closed` |
| `escalate` while `ESCALATING`, by the other side, having seen the escalation | `already_escalated` |
| A message on a conversation that is with a different participant. `conversation_state` and `closed_at` are `null` | `counterpart_mismatch` |

## Both sides keep state

Each participant holds its own copy of the conversation's state. The sender applies these rules when it accepts a message, and the receiver applies the same rules to its own copy when notified. The receiver also checks that:

- `receiver_participant` is itself.
- The sender is the conversation's counterpart, on later messages in a conversation.

The receiver also applies the role rules. A sender whose role isn't compatible, or that isn't registered, is refused with `403`, and nothing is kept.

A message its sender did not apply (`applied: false`) is still delivered. It does not move the receiver's state, but the receiver's rules still apply to it, so it can be refused.

### Crossing steps

A **step** is a `close`, `escalate`, `deescalate` or `reopen`. Each names the step it was based on, the one that had last set the sender's copy. So a receiver can tell whether the sender had seen its own latest step.

If it hadn't, the two sides have crossed. This holds for any steps, not only two of the same. Each side compares the same two ids, so each reaches the same answer with no further message: **the lower `message_id` of the two first steps after the fork wins.**

- The state becomes the winner's.
- Every step on the other branch, and any later step based on one of them, reads `applied: false` on both sides. It is still delivered.
- Both senders see `notified`, as neither message was refused.

For example, if one side sends `close` and then `reopen` while the other sends `close`, both end `OPEN` if the first `close` has the lower id, and both end in the other side's closed state if it doesn't.

A step can only be crossed while it is on its way. Once the other side has answered its notification, a later step that names an older base changes nothing, and reads `applied: false`. So a settled state can't be rewritten by a later message, whatever `message_id` or base it states.

### When a notification fails

A step's sender moves its own copy when it accepts the message, and doesn't move it back. If the notification then fails, with status `error`, or is refused, with status `rejected`, the two copies differ. There is no automatic retry. Either of these settles them:

- **The sender repeats the step,** sending the same performative again, with the same or another outcome. It isn't a duplicate: it answers `applied: true`, replaces the earlier step, which reads `applied: false`, and goes to the receiver as a new step. This also holds if the repeat was accepted before the earlier step failed, in which case it first answers `applied: false`, and reads `applied: true` once its turn to be delivered has come. If the earlier step did arrive and only its answer was lost, the receiver keeps it. The sender then takes it back, with status `notified`, and the repeat reads `applied: false`.
- **The other side sends a step.** It wins over a failed or refused step, whatever the ids.

Otherwise the copies stay different. An ordinary message doesn't settle them: on the side that believes the conversation is closed, it is refused. Use `GET /conversations/{id}` on each side to compare, and read `error_message`: a repeat that reads `notified` while the receiver's copy holds another state says so there.

### What else can leave them different

If the receiver refuses a step, the sender sees status `rejected`, with the reason, and its own state has already moved. The receiver keeps the message for audit, with status `error`, `applied: false` and the reason in `error_message`, and starts no transfer. This happens when the receiver's rules don't allow the step on a state both sides share, or when the receiver has no such conversation because the first message's notification failed. In the latter case the receiver has nothing to compare, and the sender's copy stays as it is until the sender sends a message that opens the conversation there.

### Between adapters

A notification, `POST /internal/transfer-request`, carries these fields beyond the message's own. All are optional, so a peer that leaves them out gets the ordinary rules and no settlement:

| Field | Meaning |
|---|---|
| `has_files` | The content is a ZIP |
| `sender_applied` | Whether the sender applied the message. Default `true`. `false` never moves the receiver's state |
| `based_on` | For a step: the step that had last set the sender's copy, or `null` if none has |

Its `202` answer adds the receiver's copy, so the sender can compare at once. A sender whose step lost takes this copy, even if the winner's own notification then fails:

| Field | Meaning |
|---|---|
| `applied` | Whether this copy applied the message |
| `conversation_state`, `outcome`, `escalated_by` | This copy's state |
| `state_message_id` | The step that set it |

A refusal uses the same bodies as the agent routes, in [gateway-api.md](gateway-api.md).

## Delivery

- Delivery to agents is by polling. See `GET /inbox/messages` in [gateway-api.md](gateway-api.md).
- A message with an empty payload is delivered like any other.
- A duplicate `message_id` at the receiver is safe, and creates no second inbox entry.

## Capability access

Capability policy records and reports who may access what. **It is advisory, and it does not block messages.**

- The dataspace does not check capability policy when a message is sent or received. A message naming a denied capability is still delivered.
- The sending application is responsible for checking access and for filtering what it shares.
- `grant` and `deny` messages do not change approval records. Access is changed through the capability routes in [gateway-api.md](gateway-api.md).

- Connecting an application therefore means adding this check to it: read `GET /capabilities/access` before sending, and share only what it allows.

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
- **No ordering of content.** Each message runs its own transfer, so a later message's content can arrive first. Notifications within one conversation are sent in the order the sender accepted the messages, one at a time, and state changes when a notification arrives, so a side's own steps reach the other in the order it took them. That order is kept in the adapter's process, so a restart loses it. Steps crossing from the two sides settle as [Crossing steps](#crossing-steps) describes.
- **A restart can leave a step neither delivered nor failed.** Such a step stays in progress, so a repeat of it doesn't replace it, and doesn't reach the other side's copy as a step. The other side's own step still settles them, by the ids.
- **A closed conversation can come back after retention.** Once a conversation's row has been removed, 30 days by default, a later message with the same id opens a new one in state `OPEN`.
- **A reply removed by retention stops counting.** `outstanding_requests` and `replied_at` come from the messages kept, so a request shows as outstanding again once its reply's row has been removed.
- **Content without files is limited to `MAX_JSON_BYTES` on arrival,** including a `content_ref` asset, as it is read into memory when an agent reads the message. A larger asset gives the message status `error`.
- **Every message runs a full connector cycle,** including messages with an empty payload.
- **Connector policies permit everything,** and DSP identity is mocked. Tracked in #20.
- **The connector's calls to internal adapter routes are unauthenticated.** Tracked in #20.
