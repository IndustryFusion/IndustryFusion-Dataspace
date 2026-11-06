# Spec Delta

## Purpose

Defines how an agent sends and receives messages through its adapter.

## ADDED Requirements

### Requirement: Agent authentication
Agent routes SHALL require a token with a valid signature, the exact configured issuer, and the realm role for this adapter's participant. The token alone SHALL decide the sender.

#### Scenario: No token or a bad token
- **WHEN** a request has no token, an invalid signature or a different issuer
- **THEN** it is refused as unauthorized

#### Scenario: Another participant's token
- **WHEN** a request has a valid token whose role is for another participant
- **THEN** it is refused as forbidden

#### Scenario: Sender field
- **WHEN** a message body names a different sender
- **THEN** the stored sender is still the adapter's participant

### Requirement: Sending a message
The adapter SHALL accept a message, store its payload outside the database, and answer accepted before delivery finishes.

#### Scenario: Accepted
- **WHEN** an agent sends a message to a compatible participant
- **THEN** the answer is accepted, with a message id, status, `applied` and conversation state

#### Scenario: Conversation started
- **WHEN** a message has no conversation id
- **THEN** a new conversation id is assigned, and is shown on the message

#### Scenario: Unregistered receiver
- **WHEN** the receiver is not registered
- **THEN** the answer is not found, and nothing is stored

#### Scenario: Incompatible receiver
- **WHEN** the receiver's role is not compatible
- **THEN** the answer is forbidden, and nothing is stored

#### Scenario: Payload and content reference
- **WHEN** a message has both a payload and a content reference
- **THEN** it is refused as invalid

#### Scenario: Registry unavailable
- **WHEN** the registry can't be reached
- **THEN** the answer is service unavailable

### Requirement: Send status
The sender SHALL be able to read a message and follow its status through `pending`, `registered`, and then `notified`, `error` or `rejected`.

#### Scenario: Notified
- **WHEN** the receiver accepts the notification
- **THEN** the status becomes `notified`

#### Scenario: Refused by the receiver
- **WHEN** the receiver refuses the notification
- **THEN** the status becomes `rejected`, with the reason

#### Scenario: Failure
- **WHEN** the connector or the receiver can't be reached
- **THEN** the status becomes `error`, with the reason

#### Scenario: Another participant's or unknown message
- **WHEN** an unknown message id is read
- **THEN** the answer is not found

### Requirement: Receiving a message
On a valid notification, the adapter SHALL store an inbox entry and fetch the content through the connectors.

#### Scenario: Delivered
- **WHEN** a peer notifies this adapter of a message
- **THEN** an inbox entry appears as in transfer, and becomes `received` with its payload once the content arrives

#### Scenario: Sender identity
- **WHEN** the notification's token doesn't carry the role for its stated sender
- **THEN** it is refused

#### Scenario: Wrong receiver
- **WHEN** the notification names a different receiver
- **THEN** it is refused

#### Scenario: Duplicate
- **WHEN** the same message id is notified twice
- **THEN** the answer is accepted both times, and one inbox entry exists

#### Scenario: Empty payload
- **WHEN** a message with an empty payload is sent
- **THEN** it reaches `received`, with an empty payload, and not `error`

#### Scenario: Late update
- **WHEN** a transfer status update arrives after the content was received
- **THEN** the entry stays `received`

#### Scenario: Transfer failure
- **WHEN** negotiation or transfer fails, or takes longer than 120 seconds
- **THEN** the entry becomes `error`, with the reason

### Requirement: Reading the inbox
An agent SHALL be able to list, read and acknowledge inbox messages by polling.

#### Scenario: List
- **WHEN** an agent lists the inbox
- **THEN** messages are newest first, and a status filter returns only that status

#### Scenario: Acknowledge
- **WHEN** a message is acknowledged twice
- **THEN** both answers are no content, and its status is `acked`

#### Scenario: Unknown message
- **WHEN** an unknown message is read or acknowledged
- **THEN** the answer is not found

### Requirement: Payload storage
The database SHALL hold message metadata and a payload reference only, with content in object storage.

#### Scenario: Stored message
- **WHEN** a message is stored
- **THEN** its row has no payload content, and its content is in object storage

### Requirement: Retention
The adapter SHALL purge content and delete rows of messages in a final status, by the configured periods.

#### Scenario: Content past its time
- **WHEN** a final message passes its `expires_at`, or the content retention period if it has none
- **THEN** its content is removed, and reading it shows no payload

#### Scenario: Rows past the period
- **WHEN** a final message passes the row retention period
- **THEN** its row is deleted

#### Scenario: Not final
- **WHEN** a message isn't in a final status, including one received and not acknowledged
- **THEN** it and its content are kept

### Requirement: Schema monitor
The adapter SHALL check its tables every 15 seconds, and recreate any that are missing.

#### Scenario: Missing table
- **WHEN** a table has been dropped
- **THEN** the check recreates it, and the adapter keeps working

### Requirement: Two-way exchange
Two adapters SHALL exchange messages in both directions through their connectors.

#### Scenario: Round trip
- **WHEN** participant A sends to participant B, and B replies
- **THEN** each message arrives in the other's inbox with the same payload
