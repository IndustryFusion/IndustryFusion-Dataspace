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
- **WHEN** a counterpart sends a `close` or `escalate`, with any message id, after the receiver's own step of that kind has been answered as applied
- **THEN** the state does not change, and a `close` reads `applied` false

#### Scenario: Repeated notification
- **WHEN** the same notification arrives twice
- **THEN** the state changes once, and there is one entry

### Requirement: Both sides end in the same state
Two participants SHALL hold the same `state` and `outcome` after each of these flows, without any further message, when every notification is answered.

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
- **WHEN** both sides send `close` before seeing the other's, with the same or different outcomes, and both notifications are answered
- **THEN** both end in the same closed state, which is that of the lower message id, and only that message reads `applied: true` on both sides

#### Scenario: Simultaneous close, answered before the other arrives
- **WHEN** the lower id's own step is still in progress when the other's arrives and is answered, and only then does the lower id's notification arrive
- **THEN** both end in the lower id's closed state

#### Scenario: Simultaneous escalate
- **WHEN** both sides send `escalate` before seeing the other's
- **THEN** both are `ESCALATING` with the same `escalated_by`, the sender of the lower message id

#### Scenario: An answer that names a step
- **WHEN** a side's step is answered with `kept_step` naming a lower id, of the same performative
- **THEN** its state and its message's `applied` don't change until a step with that one id arrives, which then takes its step, once

#### Scenario: Another id after such an answer
- **WHEN** a step with any other id arrives
- **THEN** the ordinary rules decide, and the state doesn't change

#### Scenario: A named step stated as not applied
- **WHEN** the named id arrives with `sender_applied` false, or as another performative
- **THEN** it doesn't take the step

#### Scenario: A step whose notification failed
- **WHEN** a side's step has status `error`, and a step of the other side arrives, with any id
- **THEN** the ordinary rules decide, the answer has no `kept_step`, and the state and the row of the failed step don't change

#### Scenario: Ordered on one conversation
- **WHEN** a side sends several state-changing messages on a conversation, without waiting
- **THEN** the receiver applies them in the order the sender accepted them, and both end in the same state

### Requirement: Copies that differ
When steps cross in other ways, or a notification fails or is refused, the copies SHALL be left different, with each side's reading as `protocol.md` records it, and the sender's status SHALL stay truthful.

#### Scenario: A close crossing an escalate
- **WHEN** one side's `close` crosses the other side's `escalate`
- **THEN** each refuses the other's, each reads `rejected` for its own, one stays closed, and the other stays `ESCALATING`

#### Scenario: The escalator closes afterwards
- **WHEN** the escalator of that crossing then sends `close`
- **THEN** both are closed, each with its own outcome, and `escalated_by` is set only on the escalator's copy

#### Scenario: A close and reopen crossing a close
- **WHEN** one side's `close` and `reopen` are both accepted before the other side's `close` arrives, whichever id is lower
- **THEN** the side that reopened reads the other side's closed state, and the other side reads `OPEN`

#### Scenario: A failed notification
- **WHEN** a step's notification fails, or is refused
- **THEN** the sender's state stays moved, its status stays `error` or `rejected`, and the receiver's state does not change

#### Scenario: A later message
- **WHEN** a later message on that conversation reads `notified`
- **THEN** the earlier step's row still reads `error` or `rejected`, and the receiver's copy hasn't moved because of it

#### Scenario: The sender repeats the step
- **WHEN** a step's notification failed or was refused, and the sender sends the same performative and outcome again
- **THEN** the repeat reads `applied` true, the receiver applies it as a step and moves, and the earlier row does not change

#### Scenario: A repeat after the other side has closed
- **WHEN** a `close` failed, the other side then closed with another outcome, and the sender repeats its `close`, with any id
- **THEN** the repeat reads `notified` and `applied` true, each keeps its own outcome, and a `reopen` followed by a `close` makes them agree

#### Scenario: A repeat with another outcome
- **WHEN** a `close` with a different outcome follows a failed `close`
- **THEN** the ordinary rules apply, so it reads `applied` false, and the receiver doesn't apply it

#### Scenario: A repeat after only the answer was lost
- **WHEN** the earlier step arrived and only its answer was lost, and the sender repeats it
- **THEN** both are closed with that outcome, the receiver's state does not change again, and the earlier row stays `error`

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

#### Scenario: Why a message in a conversation failed
- **WHEN** a message in `GET /conversations/{id}` failed or was refused
- **THEN** it has the reason in `error_message`, as the other routes do

### Requirement: End-to-end conversations
The rules SHALL hold between two real adapters and connectors, through the gateway.

#### Scenario: Flows on the local cluster
- **WHEN** two agents run each flow above, and a burst on one conversation, through the gateway on the local cluster
- **THEN** `GET /conversations/{id}` gives the same state and outcome on each side, and every message accepted is delivered
