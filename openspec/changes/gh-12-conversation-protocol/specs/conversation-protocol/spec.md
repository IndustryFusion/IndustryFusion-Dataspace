# Spec Delta

## Purpose

Defines when a message is valid, how it changes a conversation on each side, and how an agent reads a conversation.

## ADDED Requirements

### Requirement: Message validity
The adapter SHALL refuse a message that breaks the validity rules in `protocol.md`, with `422` and error `invalid_message`, the reason, detail and performative. This applies to messages and files.

#### Scenario: Every performative against every field
- **WHEN** a message is sent with each performative, and each of `capability`, `in_reply_to`, `authorization` and `outcome` present or absent
- **THEN** it is accepted or refused exactly as the table in `protocol.md` says

#### Scenario: Unknown performative or outcome
- **WHEN** a message names a performative or outcome that doesn't exist
- **THEN** it is refused as invalid

#### Scenario: Malformed authorization
- **WHEN** a `grant` has an authorization whose scope isn't `conversation`, whose `expires_at` isn't a date-time, or whose `constraints` isn't an object
- **THEN** it is refused as invalid

#### Scenario: Nothing stored
- **WHEN** a message is refused as invalid at the sender
- **THEN** no content, message or conversation is stored

### Requirement: Conversation state rules
The adapter SHALL apply the state rules in `protocol.md` in one transaction with storing the message, and SHALL answer with `applied` and the resulting state.

#### Scenario: Close
- **WHEN** a participant sends `close` on an `OPEN` conversation
- **THEN** the state becomes the closed state for its outcome, with `outcome` and `closed_at` set

#### Scenario: Close as escalated without escalating
- **WHEN** `close` with outcome `escalated` is sent on an `OPEN` conversation
- **THEN** the answer is `409`, and the state does not change

#### Scenario: Escalate
- **WHEN** a participant sends `escalate` on an `OPEN` conversation
- **THEN** the state becomes `ESCALATING`, and `escalated_by` names that participant

#### Scenario: Only the escalator
- **WHEN** the other side sends `close` or `deescalate` while `ESCALATING`
- **THEN** the answer is `409`, and the state does not change

#### Scenario: The escalator
- **WHEN** the escalator sends `deescalate`, or `close`
- **THEN** the state becomes `OPEN`, or the closed state for its outcome

#### Scenario: Ordinary messages while escalating
- **WHEN** either side sends `request`, `inform`, `grant`, `deny` or `cancel` while `ESCALATING`
- **THEN** it is accepted, and the state does not change

#### Scenario: Reopen
- **WHEN** `reopen` is sent on a closed conversation, other than one closed as `escalated` or `superseded`
- **THEN** the state becomes `OPEN`, and `outcome` and `closed_at` are cleared

#### Scenario: Reopen refused
- **WHEN** `reopen` is sent on a conversation closed as `escalated` or `superseded`
- **THEN** the answer is `409`

#### Scenario: Repeats that change nothing
- **WHEN** `close` is sent on a closed conversation, `escalate` by the escalator while `ESCALATING`, or `reopen` while `OPEN`, and the sender's latest step reached the other side or is still on its way
- **THEN** the answer is `202` with `applied: false`, and the state does not change

#### Scenario: Other messages on a closed conversation
- **WHEN** any other message is sent on a closed conversation
- **THEN** the answer is `409`

#### Scenario: Unknown conversation
- **WHEN** `close`, `reopen` or `deescalate` names a conversation this side doesn't have
- **THEN** the answer is `409`, and no conversation is created

#### Scenario: Another counterpart
- **WHEN** a message on an existing conversation names a different receiver
- **THEN** the answer is `409`

#### Scenario: Cancel
- **WHEN** a participant sends `cancel`
- **THEN** it is recorded, and the state does not change

### Requirement: Refusals
A message refused by the state rules SHALL be stored for audit, without its content, and answered with `409` and error `conversation_state_violation`.

#### Scenario: Refusal body
- **WHEN** a message is refused
- **THEN** the body has `error`, `reason`, `detail`, `conversation_id`, `conversation_state`, `closed_at` and `message_id`

#### Scenario: Stored for audit
- **WHEN** a message is refused
- **THEN** its row has status `rejected`, `applied` false and the reason, its content is removed, and nothing is sent to the receiver

### Requirement: The receiver's copy
The receiver SHALL validate each notification, apply the same state rules to its own copy, and compare the sender with the conversation's counterpart on later messages.

#### Scenario: Same rules
- **WHEN** a notification breaks a validity or state rule on the receiver's copy
- **THEN** it is refused with the same status and body, its row is kept with status `error`, `applied` false and the reason, and no transfer starts

#### Scenario: Different counterpart
- **WHEN** a participant that isn't the counterpart sends on an existing conversation
- **THEN** it is refused, and the conversation does not change

#### Scenario: Seen by the sender
- **WHEN** the receiver refuses a notification
- **THEN** the sender's message has status `rejected`, with the reason

#### Scenario: Not applied by the sender
- **WHEN** a notification says the sender did not apply the message
- **THEN** the receiver's state does not change, and the message is delivered with `applied` false

#### Scenario: Stated as not applied, to get past the rules
- **WHEN** a notification says the sender did not apply it, and the rules would refuse it, or the conversation doesn't exist
- **THEN** it is refused

#### Scenario: Role rules
- **WHEN** the sender's role isn't compatible, or it isn't registered
- **THEN** the answer is forbidden, nothing is stored, no transfer starts, and the sender's message has status `rejected`

#### Scenario: Another counterpart's refusal
- **WHEN** a refusal goes to a participant that isn't the conversation's counterpart
- **THEN** its `conversation_state` and `closed_at` are null

#### Scenario: Content for a refused message
- **WHEN** content is pushed to a refused message
- **THEN** the answer is not found, and the row stays as it was

#### Scenario: A settled state
- **WHEN** a counterpart sends a step naming an older base, with any message id, after the receiver's own step has been answered
- **THEN** the state does not change, and the message reads `applied` false

#### Scenario: Repeated notification
- **WHEN** the same notification arrives twice
- **THEN** the state changes once, and there is one entry

### Requirement: Both sides end in the same state
Two participants SHALL hold the same `state` and `outcome` after each flow, without any further message.

#### Scenario: Request and reply
- **WHEN** one side sends `request`, and the other answers with `in_reply_to`
- **THEN** both are `OPEN`, and neither has that request outstanding

#### Scenario: Grant, deny and cancel
- **WHEN** a `grant`, `deny` or `cancel` is delivered
- **THEN** both are `OPEN`, and the receiver can read a grant's authorization

#### Scenario: Close
- **WHEN** one side closes, and the notification has been delivered
- **THEN** both have the same closed state and outcome

#### Scenario: Escalate and deescalate
- **WHEN** one side escalates, and later deescalates or closes
- **THEN** both have the same state and `escalated_by` at each step

#### Scenario: Reopen
- **WHEN** one side reopens a closed conversation
- **THEN** both are `OPEN`

#### Scenario: Simultaneous close
- **WHEN** both sides send `close` before seeing the other's, with the same or different outcomes
- **THEN** both end in the same closed state, which is that of the lower message id, and only that message reads `applied: true` on both sides

#### Scenario: Simultaneous escalate
- **WHEN** both sides send `escalate` before seeing the other's
- **THEN** both are `ESCALATING` with the same `escalated_by`, the sender of the lower message id

#### Scenario: Other crossing steps
- **WHEN** one side's `close`, or `close` and `reopen`, crosses the other side's `close` or `escalate`
- **THEN** both end in the state of the branch whose first step has the lower message id, and the other branch reads `applied: false`

#### Scenario: Ordered on one conversation
- **WHEN** a side sends several state-changing messages on a conversation, without waiting
- **THEN** the receiver applies them in the order the sender accepted them, and both end in the same state

### Requirement: After a failed notification
The sender's state SHALL stay moved when a notification fails, and the two sides SHALL have a way to agree again.

#### Scenario: The sender repeats the step
- **WHEN** a step's notification failed or was refused, and the sender sends the same performative again
- **THEN** the repeat reads `applied: true` and replaces it, and both sides end in the state of the repeat

#### Scenario: A repeat accepted before the failure
- **WHEN** a repeat was accepted while the earlier step was still in progress, and that step then fails
- **THEN** the repeat replaces it when its turn comes, and both sides end in its state

#### Scenario: The answer was lost
- **WHEN** a step arrived but its answer was lost, and the sender repeats it with another outcome
- **THEN** both sides end in the state of the first, which reads `applied: true` and `notified`

#### Scenario: The other side's step
- **WHEN** a step's notification failed or was refused, and the other side's step arrives
- **THEN** the other side's step wins whatever the ids, and both sides end in its state

#### Scenario: Status of a repeat
- **WHEN** a repeat reads `notified`
- **THEN** the other side has the state, or the status has an `error_message` naming the state it holds

### Requirement: Concurrent messages
Concurrent messages on one conversation SHALL all be kept, and SHALL change its state as if they ran one at a time.

#### Scenario: Burst of messages
- **WHEN** many messages are sent on one conversation at once, on either side
- **THEN** every message is stored, none is taken for a duplicate, and its state is unchanged

#### Scenario: Racing closes on one side
- **WHEN** many `close` messages are sent on one side at once
- **THEN** exactly one reads `applied: true`, and the others are accepted with `applied: false`

#### Scenario: Racing with a close
- **WHEN** ordinary messages race with a `close`
- **THEN** each is either accepted before it, or refused with `409` after it, and no message is lost

### Requirement: Reading conversations
The adapter SHALL offer the conversation routes in `gateway-api.md`.

#### Scenario: List
- **WHEN** an agent calls `GET /conversations`, with or without `state=` in any case
- **THEN** it gets its conversations in that state, with `conversation_id`, `state`, `outcome`, `counterpart_participant`, `opened_at`, `closed_at`, `last_message_at` and `escalated_by`

#### Scenario: One conversation
- **WHEN** an agent calls `GET /conversations/{id}`
- **THEN** it also gets `messages`, both sent and received, and `outstanding_requests`

#### Scenario: Unknown conversation
- **WHEN** an agent asks for a conversation it doesn't have
- **THEN** the answer is not found

#### Scenario: Outstanding requests
- **WHEN** a request has no accepted message naming it in `in_reply_to`
- **THEN** it is in `outstanding_requests`, and when one arrives it is not, and `replied_at` is set

#### Scenario: Inbox fields
- **WHEN** an agent reads an inbox message
- **THEN** it has `conversation_id`, `performative`, `capability`, `in_reply_to`, `outcome`, `authorization`, `expires_at`, `response_due_at` and `applied`

### Requirement: End-to-end conversations
The rules SHALL hold between two real adapters and connectors, through the gateway.

#### Scenario: Flows on the local cluster
- **WHEN** two agents run each flow above, and a burst on one conversation, through the gateway on the local cluster
- **THEN** `GET /conversations/{id}` gives the same state and outcome on each side, and every message accepted is delivered
