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

### Simultaneous steps

Both sides can send `close`, or both `escalate`, before either has seen the other's. Each side then knows both message ids, so each reaches the same answer with no further message: **the lower `message_id` wins**. The side whose message lost takes the winner's state or `escalated_by`, and its own message reads `applied: false`. Both senders see `notified`.

This only holds while a side's own step is on its way. Once its notification has been answered, or has failed, a later `close` or `escalate` doesn't change the state, whatever its id. So a state that has settled can't be rewritten by a later message, with one exception, which is how the two sides stay agreed when one has answered first: if the answer named a lower id as `kept_step`, the step with that one id can still take this side's step, once. A peer chooses its own ids, so a peer that picks one in advance and names it can win a simultaneous step in this way, once for each step of the other side. It gains nothing it couldn't by sending first.

### When the two copies differ

Only the two cases above settle. Each side otherwise applies the rules to its own copy, and **the copies can stay different**. Nothing makes them agree automatically. To compare them, call `GET /conversations/{id}` on each side, and read each message's `status`, `applied` and `error_message`.

`GET /outbox/messages/{id}/status` reports `conversation_state` for this side's copy. A message's `notified` means only that the receiver accepted that message. It doesn't say that an earlier step reached the other side, or that the two copies agree.

**A `close` crossing an `escalate`.** Each refuses the other's. If factory owner FO sends `close` with outcome `resolved` while machine builder MB sends `escalate`:

| | FO reads | MB reads |
|---|---|---|
| `state` | `CLOSED_RESOLVED` | `ESCALATING` |
| `outcome` | `resolved` | `null` |
| `escalated_by` | `null` | MB |
| Own message's `status` | `rejected` | `rejected` |

If MB, the escalator, then sends `close` with outcome `failed`, both are closed, each with its own outcome: FO stays `CLOSED_RESOLVED`, and has MB's `close` with `applied: false`. MB reads `CLOSED_FAILED`, and its `close` reads `notified` and `applied: true`.

**A `close` and `reopen` crossing a `close`.** If FO sends `close` and `reopen`, both accepted before MB's `close` arrives, then whichever id is lower:

| | FO reads | MB reads |
|---|---|---|
| `state` | `CLOSED_` with MB's outcome | `OPEN` |
| What moved it last | MB's `close`, on FO's `OPEN` | FO's `reopen` |

Every message reads `notified`. If MB's `close` arrives before FO has accepted its `reopen`, the two agree on `OPEN` instead. Either side can then send a further step, under the rules for what its own copy holds.

**A notification that fails, or is refused.** A step's sender moves its own copy when it accepts the message, and doesn't move it back. If the notification then fails, with status `error`, or is refused, with status `rejected`, the receiver's copy hasn't moved. There is no automatic retry. Both statuses are final for that message: its row doesn't change afterwards, and a step in either status can't settle against anything.

The sender can **send the same step again**, with the same performative and outcome. It goes to the receiver as an applied step, reads `applied: true`, and the receiver applies its rules to it as to any step. The earlier row keeps its status. This needs the earlier one to have finished with `error` or `rejected`: a repeat accepted while the earlier one is still on its way is a duplicate, with `applied: false`. If the earlier step did arrive and only its answer was lost, the receiver already holds it, and its copy doesn't change again. A `close` with another outcome isn't a repeat, and has the ordinary result, `applied: false`.

**A failed `close` crossing a `close`.** If FO's `close` with outcome `resolved` fails, and MB then sends `close` with outcome `withdrawn`, the two copies differ, whichever id is lower. FO's step isn't on its way, so FO doesn't claim to have kept it, and MB's stands:

| | FO reads | MB reads |
|---|---|---|
| `state` | `CLOSED_RESOLVED` | `CLOSED_WITHDRAWN` |
| FO's `close` | `status` `error`, `applied: true` | Not there |
| MB's `close` | `applied: false` | `status` `notified`, `applied: true` |

If FO then repeats its `close`, its new id doesn't matter: it reads `notified` and `applied: true`, and MB, already closed, keeps `CLOSED_WITHDRAWN`, with FO's `close` as `applied: false`. To agree, one side sends `reopen`, which opens both copies, and then `close`. A conversation closed as `superseded` or `escalated` can't be reopened, so a difference involving one of those stays.

An ordinary message doesn't change this. On the side that believes the conversation is closed, it is refused.

If the receiver refuses a message, it keeps it for audit, with status `error`, `applied: false` and the reason in `error_message`, and starts no transfer. This happens when the receiver's rules don't allow it on its copy, or when the receiver has no such conversation because the first message's notification failed. In the latter case, the sender's copy stays as it is until a message that can open the conversation there arrives.

### Between adapters

A notification, `POST /internal/transfer-request`, carries these fields beyond the message's own. Both are optional:

| Field | Meaning |
|---|---|
| `has_files` | The content is a ZIP |
| `sender_applied` | Whether the sender applied the message. Default `true`. `false` never moves the receiver's state |

Its `202` answer can add `kept_step`: this side kept its own step, with this lower id, against the one just notified. It is only given while that step is on its way, not once its notification has failed. The sender remembers the id, and when a step of the same performative with that one id arrives, its copy takes it, once, even though its own step has been answered. Until then the sender's own message reads `applied: true`, and if no such step arrives, nothing changes.

A refusal uses the same bodies as the agent routes, in [gateway-api.md](gateway-api.md).

An external participant's adapter has to send `sender_applied` and read `kept_step`, as the two copies otherwise can't settle. The gateway's peer route passes both unchanged. See "API Gateway" in [architecture.md](architecture.md).

The connector's push to `POST /internal/inbox-receive/{id}`, and its read of `GET /internal/payload/{id}`, carry `X-Transfer-Token`. It is good for that route and that message. The receiver gives one to the provider's connector with the transfer's destination, and the sender gives one to its own connector with the asset. Without one, or with a wrong one, the answer is `401`.

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
- **No ordering of content.** Each message runs its own transfer, so a later message's content can arrive first. Notifications within one conversation are sent in the order the sender accepted the messages, one at a time, and state changes when a notification arrives, so a side's own steps reach the other in the order it took them. That order is kept in the adapter's process, so a restart loses it. For steps crossing from the two sides, see [Simultaneous steps](#simultaneous-steps) and [When the two copies differ](#when-the-two-copies-differ).
- **A restart can leave a step neither delivered nor failed.** Such a step stays in progress, so a repeat of it is a duplicate, and doesn't reach the other side's copy as a step.
- **A closed conversation can come back after retention.** Once a conversation's row has been removed, 30 days by default, a later message with the same id opens a new one in state `OPEN`.
- **A reply removed by retention stops counting.** `outstanding_requests` and `replied_at` come from the messages kept, so a request shows as outstanding again once its reply's row has been removed.
- **Content without files is limited to `MAX_JSON_BYTES` on arrival,** including a `content_ref` asset, as it is read into memory when an agent reads the message. A larger asset gives the message status `error`. The push itself is streamed to storage, but the message has no files to download, so an agent could only read it in memory.
- **Every message runs a full connector cycle,** including messages with an empty payload.
- **Connector policies permit any authenticated participant.** A connector checks who it is talking to, not whether that participant may have this asset. The asset's id is what limits it.
- **An adapter's token can be replayed by a peer.** For a peer outside the hub, this reaches the sender's whole agent API at the public gateway. A connector's token has the same exposure. See "External participants" in [keycloak.md](keycloak.md). It is a decision for the maintainers.
