# Spec Delta

## Purpose

Retention removes message content and rows, and keeps conversations.

## MODIFIED Requirements

### Requirement: Retention
The adapter SHALL purge content and delete rows of messages in a final status, by the configured periods, and SHALL NOT delete conversations.

#### Scenario: Content past its time
- **WHEN** a final message passes its `expires_at`, or the content retention period if it has none
- **THEN** its content is removed, and reading it shows no payload

#### Scenario: Rows past the period
- **WHEN** a final message passes the row retention period
- **THEN** its row is deleted

#### Scenario: Not final
- **WHEN** a message isn't in a final status, including one received and not acknowledged
- **THEN** it and its content are kept

#### Scenario: Conversations are kept
- **WHEN** a conversation has had no message for longer than the row retention period, and retention runs
- **THEN** the conversation is kept with its state, outcome and times, while its messages' content and rows are removed on time

#### Scenario: A closed conversation stays closed
- **WHEN** a conversation was closed longer ago than the row retention period, and a message without `reopen` arrives with its id
- **THEN** the message is refused by the state rules, as for any closed conversation, and no new conversation is opened
