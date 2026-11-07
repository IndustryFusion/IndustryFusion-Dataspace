# Design

## Context

`protocol.md` leads on the validity and state rules, and `gateway-api.md` on the routes and error bodies. The `conversations` table and the `applied` columns exist from #9. An earlier review found silent message loss under concurrent requests, so the design starts from concurrency.

## Goals / Non-Goals

**Goals:**

- One function decides validity, and one decides the state change, used by both the sender and the receiver.
- Concurrent messages on one conversation never lose an update, on PostgreSQL.
- Two participants end in the same state after every flow the issue names, including simultaneous `close`, when no notification fails.

**Non-Goals:**

- Agreement after a refusal, a failed notification or a crossing other than the two simultaneous ones. `protocol.md` records what each side reads.

## Decisions

**Lock the conversation's row for the decision.** Inserting the message and changing the state happen in one transaction, holding `SELECT ... FOR UPDATE` on the row. Content is stored before the transaction, and removed again if the message is refused. Alternative: a compare-and-set on the state, which needs a retry loop for no gain, or a lock in the process, which doesn't hold across replicas.

**Deliver one conversation's messages in the order they were accepted.** Each accepted message is queued behind the previous one for its conversation while the row lock is still held, and starts once the transaction has committed. So `close` followed by `reopen` reaches the receiver in that order. The receiver applies state at notification, not when content arrives, so content can still arrive in any order, and the known limit in `protocol.md` stays for that. Alternative: a sequence number checked by the receiver, which is more exact across restarts, but has to deal with gaps, and every peer has to implement it. The queue is in the process, so a restart loses it, as the existing known limit on messages in progress already says.

**Only the two simultaneous cases settle.** A `close` crossing a `close`, or an `escalate` crossing an `escalate`, goes to the lower `message_id`, on both sides, with no further message. This is what the issue asks for. Each side knows both ids. The one that lost reads `applied: false`. Every other crossing gets the ordinary state rules on each copy, as in the next decision.

**Settling ends once a step is answered, or has failed.** A close or escalation only settles against the receiver's own step while that step's notification is on its way. A step whose notification failed isn't, as a window left open there would let a peer that answers `500` rewrite a settled state at any later time. Otherwise, a later step with any id doesn't change the state, with one exception. An answer alone can't tell which side lost: if a side's own lower-id step is still on its way when the other's arrives, it keeps its own, and answers. Without a way to say so, that answer would end the other side's chance to take the lower-id step, and each side would keep its own, which the issue doesn't allow for a simultaneous step. So the answer names it, as `kept_step`.

**`kept_step` is a claim, and is only good for what it names.** It comes from a peer, so the sender stores the id on the conversation, changes nothing else, and lets that one id, with the same performative, take its step once. Moving on from the step forgets it. A peer that picks its id in advance can still win once, which `protocol.md` states. Alternatives: taking the claim as true when it arrives, which let any later message with a lower id rewrite a settled state; a signed or precommitted id, which is more than this needs, as a peer that wants its close to win can already send it first.

**The copies can differ, and that is accepted.** The issue asks that a refused message is visible to the sender, and that the resulting difference is recorded in `protocol.md`. A `close` crossing an `escalate`, a `close` and `reopen` crossing a `close`, or any step whose notification failed, can leave different copies. `protocol.md` says what each side reads, and `GET /conversations/{id}` on each side shows it. The sender's status stays `error` or `rejected`, and nothing changes that row afterwards.

**`sender_applied` only ever holds the receiver back.** A message its sender did not apply never moves the receiver's copy, so a duplicate can't settle against the receiver's own step. It is still needed for that: without it, a side's duplicate `close` with a low id would win at the other side but not at its own. But the receiver still applies its rules to it, so stating `false` doesn't get an `inform` onto a closed conversation, and it needs a conversation that exists.

**After a failed notification, a repeat goes to the peer as an applied step.** If the sender's latest step has status `error` or `rejected`, and a new message repeats it, with the same performative and outcome, it reads `applied: true`, and the receiver applies its rules as to any step. The earlier row isn't changed. A different outcome isn't a repeat: it gets the ordinary rules, so this can't get a `close` as `escalated` past them. Alternative: documenting only that the other side's further step recovers it. Rejected, as this takes only a few lines, and lets the side that knows about the failure act on it.

**The role rules apply on the message path too.** A notification from a sender whose role isn't compatible, or isn't registered, gets `403`, as on the capability routes, and the sender sees `rejected`. No row is kept, as there is no conversation it belongs to.

**A refusal for another counterpart says nothing about the conversation.** `conversation_state` and `closed_at` are `null`, so a third party can't read a conversation's state by probing its id.

**Refused rows stay refused.** A push of content to a refused row gets `404`, as `/internal/inbox-receive/{id}` has no authentication yet (#20).

**Still deliver a message with `applied: false`.** A duplicate `close` can carry a payload, and the receiver's conversation should show it. It runs the same connector workflow. Alternative: not delivering it, which saves a transfer but leaves the two message lists different.

**Refusal at the receiver answers with the same body as at the sender.** `409` or `422`, which the sender's delivery records as `rejected`, with the reason. The receiver keeps its row for audit with status `error` and `applied: false`, using the status `gateway-api.md` already has for "could not be received", and starts no transfer. Alternative: a new inbox status `rejected`, which changes the published contract for no extra information.

**States the table in `protocol.md` doesn't name.** Each choice keeps a client's retry safe where the table says so, and otherwise refuses:

| Situation | Result | Reason |
|---|---|---|
| `close`, `reopen` or `deescalate` on an unknown conversation | `409` | `conversation_not_found`. There is nothing to act on, and `conversation_state` is `null` |
| `deescalate` while `OPEN` | `409` | `not_escalated` |
| `reopen` while `ESCALATING` | `409` | `not_closed`. It is not redundant, as the conversation isn't open |
| `escalate` while `ESCALATING`, by the other side, having seen the escalation | `409` | `already_escalated`. Only the same side's is a duplicate |
| `escalate` or `deescalate` on a closed conversation | `409` | `conversation_closed` |

Alternatives: treating these as `applied: false`, which would tell a client that an action nobody performed was fine.

**A refused message that opens an unknown conversation creates no conversation.** Its row is kept in the outbox, and readable by the `message_id` in the `409`. Alternative: an empty conversation, which the other side knows nothing about.

**`in_reply_to` isn't looked up.** `protocol.md` requires it by performative and doesn't say it must exist here. The original may also have been removed by retention. Alternative: refusing an unknown id, which adds a rule the documents don't have.

**`outstanding_requests`, and `replied_at`, come from the messages.** A request has a reply once an accepted message in the conversation names it in `in_reply_to`. A refused message doesn't count, and neither does a request that was itself refused. They are worked out on read. Alternative: a stored `replied_at` column, which survives retention removing the reply, but needs a write on every reply and a second row lock. Consequence: when retention removes a reply's row, its request shows as outstanding again. Rows are kept for 30 days by default, so this is recorded as a limit.

**Files follow the same rules.** `POST /outbox/files` has no `authorization` or `outcome` field, so a `grant` or `close` sent that way is refused as invalid.

**The escalator and outcome are cleared on the way back.** `deescalate` clears `escalated_by`. `reopen` clears `outcome`, `closed_at` and `escalated_by`.

**New column.** `state_message_id` on a conversation, nullable, and added on start to tables that already exist.

**Rejected: general settlement of crossing steps.** Each step could name the step it was based on, each receiver could walk its chain to find the fork, the lower id of the two first steps after the fork could win, a repeat could replace a failed step, and a side could take the other's copy from the answer to a notification. So the two copies would converge after any crossing or failure. Rejected, as it is too complex for the requirement, and failed review: its several ways of changing a settled state didn't agree in all orders, and a copy taken from an answer could set any state.

## Architectural implications

No conflict with `architecture.md`. `protocol.md` says "No ordering across messages". This change keeps that for content, and orders notifications within one conversation. The document is updated to say which is which.

## Risks / Trade-offs

- [A slow receiver delays later messages on the same conversation] → Each step has a 30 second timeout, so the wait is bounded. Other conversations aren't affected.
- [A message accepted by the sender but not by the receiver leaves the copies different] → Accepted by the issue. Recorded in `protocol.md`, and shown by status `rejected` or `error`. Applications compare with `GET /conversations/{id}`.
- [A signed peer can state a low message id while a step is in progress] → It affects only a conversation that peer is the counterpart of, only until the step is answered as applied, and only what it could set by closing first anyway.
- [A later message's `notified` says nothing about an earlier step] → `notified` is about that message alone. Recorded in `protocol.md`.
- [A closed conversation removed by retention] → A later message with the same id opens it again. Rows are kept for 30 days by default. `protocol.md` records this.
