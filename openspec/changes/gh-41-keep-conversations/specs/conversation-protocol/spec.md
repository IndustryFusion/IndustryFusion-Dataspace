# Spec Delta

## Purpose

A request stays answered after its reply's row is removed, and a conversation can be read and continued after its messages are gone.

## MODIFIED Requirements

### Requirement: Reading conversations
The adapter SHALL offer the conversation routes in `gateway-api.md`. When a request is answered, the adapter SHALL store the time on the request's row, and a request's `replied_at` SHALL be that time, or else that of the earliest kept reply that isn't refused.

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
- **WHEN** a request has no accepted message naming it in `in_reply_to`, and no stored answer time
- **THEN** it is in `outstanding_requests`, and when one arrives it is not, and `replied_at` is set

#### Scenario: A received reply is stored
- **WHEN** this adapter accepts a received message that names one of its requests in `in_reply_to`
- **THEN** the time is stored on that request's row, and a later reply doesn't change it

#### Scenario: A sent reply is stored
- **WHEN** the receiver accepts the notification of a message this adapter sent that names a request in `in_reply_to`
- **THEN** the time is stored on that request's row

#### Scenario: A refused reply
- **WHEN** a reply is refused, by this adapter's rules or by the receiver
- **THEN** no time is stored on the request

#### Scenario: Answered after the reply's row is removed
- **WHEN** retention has removed a reply's row, and its request's row remains
- **THEN** the request has the stored `replied_at`, and isn't in `outstanding_requests`, on both sides

#### Scenario: An old conversation whose messages are gone
- **WHEN** an agent reads a conversation idle for longer than the row retention period, whose message rows have all been removed
- **THEN** the answer has its state, outcome and times, with the messages that remain, and the requests that remain with their `replied_at`

#### Scenario: Continuing an old conversation
- **WHEN** a participant sends a message in a conversation idle for longer than the row retention period
- **THEN** both sides apply it to their existing copy by the state rules, and the conversation's `last_message_at` moves

#### Scenario: Inbox fields
- **WHEN** an agent reads an inbox message
- **THEN** it has `conversation_id`, `performative`, `capability`, `in_reply_to`, `outcome`, `authorization`, `expires_at`, `response_due_at` and `applied`

#### Scenario: Why a message in a conversation failed
- **WHEN** a message in `GET /conversations/{id}` failed or was refused
- **THEN** it has the reason in `error_message`, as the other routes do
