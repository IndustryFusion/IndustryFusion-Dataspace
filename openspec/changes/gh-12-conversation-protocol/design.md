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

**Tell the receiver whether the sender applied the message, with `sender_applied`.** It defaults to true for a peer that doesn't send it. A message the sender did not apply never moves the receiver's state. And it is what separates a simultaneous `close` from a late duplicate: if the sender applied its `close` while the receiver already closed by a message of its own, then neither had seen the other's. Alternative: comparing timestamps, which depends on two clocks.

**Settle simultaneous `close` and `escalate` by the lower message id.** Each side knows both ids once both notifications have arrived, so each reaches the same answer without another message. The side whose message loses changes to the winner's state, and marks its own message `applied: false`. Stored as `state_message_id` on the conversation, a new nullable column, added on start to a table that already exists. The issue requires both participants to end in the same state, and `protocol.md` doesn't name a rule for different outcomes. Alternatives: the first to arrive wins, which each side sees differently and so doesn't converge; a fixed order of participants, which would let one participant always win; an ordering of outcomes, which is a product rule nobody has asked for.

**A message refused by the other side loses the settlement.** If a side's own closing message was rejected by the receiver, the other side's `close` wins, whatever the ids. This is how a further message settles a difference, as `protocol.md` promises.

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

## Architectural implications

No conflict with `architecture.md`. `protocol.md` says "No ordering across messages". This change keeps that for content, and orders notifications within one conversation. The document is updated to say which is which.

## Risks / Trade-offs

- [A slow receiver delays later messages on the same conversation] → Each step has a 30 second timeout, so the wait is bounded. Other conversations aren't affected.
- [A message accepted by the sender but not by the receiver leaves the copies different] → Accepted by the issue. Recorded in `protocol.md`, shown by status `rejected`, and settled by a further message.
- [An untrusted peer can state `sender_applied` or a low message id] → It affects only a conversation that peer is the counterpart of, and only that conversation's outcome, which it could set by closing first anyway.
