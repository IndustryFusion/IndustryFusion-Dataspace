# Design

## Context

`protocol.md` leads on the validity and state rules, and `gateway-api.md` on the routes and error bodies. The `conversations` table and the `applied` columns exist from #9. An earlier review found silent message loss under concurrent requests, so the design starts from concurrency.

## Goals / Non-Goals

**Goals:**

- One function decides validity, and one decides the state change, used by both the sender and the receiver.
- Concurrent messages on one conversation never lose an update, on PostgreSQL.
- Two participants end in the same state after every flow the issue names, including simultaneous `close`.

**Non-Goals:**

- Agreement after a refusal. `protocol.md` accepts that the copies can differ until a further message settles them.

## Decisions

**Lock the conversation's row for the decision.** Inserting the message and changing the state happen in one transaction, holding `SELECT ... FOR UPDATE` on the row. Content is stored before the transaction, and removed again if the message is refused. Alternative: a compare-and-set on the state, which needs a retry loop for no gain, or a lock in the process, which doesn't hold across replicas.

**Deliver one conversation's messages in the order they were accepted.** Each accepted message is queued behind the previous one for its conversation while the row lock is still held, and starts once the transaction has committed. So `close` followed by `reopen` reaches the receiver in that order. The receiver applies state at notification, not when content arrives, so content can still arrive in any order, and the known limit in `protocol.md` stays for that. Alternative: a sequence number checked by the receiver, which is more exact across restarts, but has to deal with gaps, and every peer has to implement it. The queue is in the process, so a restart loses it, as the existing known limit on messages in progress already says.

**Each state-changing step names the step it was based on, with `based_on`.** `close`, `escalate`, `deescalate` and `reopen` carry the id of the step that set the sender's copy when it was accepted, `null` if there has been none. The receiver follows its own chain of steps back to that id. So it can tell, for any pair of steps and with no clocks, whether the sender had seen its latest step. Alternatives: comparing timestamps, which depends on two clocks; and a sequence number, which can't tell which side's step came first after a fork.

**Crossing steps settle by the first step after the fork.** If the receiver has steps of its own since `based_on`, the two sides have forked. The lower `message_id` between the incoming step and the receiver's first step after the fork wins, on both sides. The losing branch is void: its steps read `applied: false`, and a later step based on one is void too. The winner's state applies. This holds for any two steps, not only two closes, so `close` crossing `escalate`, or `close` then `reopen` crossing a `close`, all reach the same state. The issue requires both participants to end in the same state, and `protocol.md` names no rule for different outcomes. Alternatives: the first to arrive wins, which each side sees differently and so doesn't converge; a fixed order of participants, which would let one participant always win; an ordering of outcomes, which is a product rule nobody has asked for; and settling only `close` against `close`, which leaves `close` and `reopen` crossing a `close` divided with every status reading `notified`.

**A receiver's answer says what its copy holds.** The answer to a notification adds `applied`, `conversation_state`, `outcome`, `escalated_by` and `state_message_id`. If the receiver voided the sender's step, the sender takes the receiver's copy at once, so the two agree even if the winner's own notification then fails. All of it is optional, so a peer that doesn't send it is treated as before.

**A step the other side has acknowledged can't be crossed.** A crossing is only possible while the receiver's first step after the fork is still in progress. Once its notification has been answered, the other side's copy holds it, or has answered that it doesn't. A later step naming an older base can't be genuine, so it changes nothing and reads `applied: false`. That is how the receiver tells a genuine crossing from a peer stating `based_on` and a low `message_id`: no peer can rewrite a settled state at any later time, and the window is the time one notification is in progress. Within that window a peer can win only what it could have won by closing first. Alternatives: a time window, which depends on a clock and a guess at how long delivery can take; a check on the sender's stated `applied` alone, which a signed peer can state as it likes.

**`sender_applied` only ever holds the receiver back.** A message its sender did not apply never moves the receiver's copy. But the receiver still applies its rules to it, so stating `false` doesn't get an `inform` onto a closed conversation, and it needs a conversation that exists. A step with no `based_on` field at all gets the ordinary rules and no settlement.

**After a failed notification, repeating the step sends it again.** The sender's state has moved and its step never reached the other side, so a repeat isn't a duplicate. If the sender's latest step has status `error` or `rejected`, a further message with the same performative replaces it: it reads `applied: true`, takes its place on the chain, with the same `based_on`, and the earlier one reads `applied: false`. The check runs when the message is accepted, and again when its turn to be delivered comes, as the earlier step may fail in between. If the earlier step did in fact arrive and only its answer was lost, the receiver leaves its copy alone and its answer names that step, which the sender then takes. Its status moves from `error` to `notified`. This is the closest to what exists: the sender's state still moves at accept, there is no new route or performative, and an agent does what it already would. Alternatives: retrying the notification automatically, which helps with a short outage only, holds up the conversation's queue, is lost in a restart, and doesn't change that a client sees `error`; moving the sender's state back on failure, which undoes what later messages were accepted on, and leaves an agent's answer untrue; and a separate resynchronising route, which every peer has to implement, and is a change to the contract.

**The other side's step wins over a failed one.** If the receiver's first step after the fork has status `error` or `rejected`, the incoming step wins whatever the ids, as the other side never took the receiver's step into account. `protocol.md` names both statuses.

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

**New columns.** `state_message_id` on a conversation, and `based_on` on a message, both nullable, and added on start to tables that already exist.

## Architectural implications

No conflict with `architecture.md`. `protocol.md` says "No ordering across messages". This change keeps that for content, and orders notifications within one conversation. The document is updated to say which is which.

## Risks / Trade-offs

- [A slow receiver delays later messages on the same conversation] → Each step has a 30 second timeout, so the wait is bounded. Other conversations aren't affected.
- [A message accepted by the sender but not by the receiver leaves the copies different] → Accepted by the issue. Recorded in `protocol.md`, shown by status `rejected`, and settled by a further message.
- [A signed peer can state `based_on` and a low message id while a step is in progress] → It affects only a conversation that peer is the counterpart of, only in the time a notification is in progress, and only what it could set by closing first anyway. A peer can do nothing with these once the step has been answered.
- [A closed conversation removed by retention] → A later message with the same id opens it again. Rows are kept for 30 days by default. `protocol.md` records this.
