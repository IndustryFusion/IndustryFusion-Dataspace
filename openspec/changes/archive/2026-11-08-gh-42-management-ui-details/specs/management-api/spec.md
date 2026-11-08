# Spec Delta

## Purpose

The policy view gives each decision's conversation and an external provider's capabilities, and the health check gives timing.

## MODIFIED Requirements

### Requirement: Policy view

`GET /api/policy?fo=&mb=` SHALL show capability access for a factory owner and a machine builder in both directions, to an administrator. Each entry SHALL have its provider, consumer, data classification, status, source and the conversation its decision was made in. An external provider's capabilities SHALL be read through the gateway's peer route with a token of the consumer, and where they can't be read, the provider SHALL be listed under `unavailable` with a reason.

#### Scenario: A hosted pair
- **WHEN** an administrator calls it for two hosted participants
- **THEN** each capability appears with its provider, consumer, `data_classification`, status, source and `conversation_id`

#### Scenario: The conversation of a decision
- **WHEN** a consumer's request for a capability named a conversation, and the provider decided it
- **THEN** that entry's `conversation_id` is the conversation, and an entry without a decision has `conversation_id` null

#### Scenario: Without an admin token
- **WHEN** it is called without an admin token, for any pair
- **THEN** the answer is `401`, and nothing is read from an adapter

#### Scenario: An external side with an admin token
- **WHEN** an administrator calls it for a pair with an external side whose adapter is reachable through the gateway
- **THEN** the external side's capabilities appear with the hosted side's, with the consumer's status for each, read through the gateway's peer route with the consumer's token, and nothing goes to the external adapter with the internal key

#### Scenario: An external side without a token
- **WHEN** either side is external and the call has no admin token
- **THEN** the answer is `401`, and no token is asked for

#### Scenario: Two external sides
- **WHEN** both sides are external, and both adapters are reachable through the gateway
- **THEN** both directions appear

#### Scenario: An external provider that can't be read
- **WHEN** the external adapter can't be reached, refuses the token, or gives an answer of the wrong shape, or the consumer has no client
- **THEN** the answer is `200`, the hosted side is shown, the external side is listed in `unavailable`, and `unavailable_reasons` gives the reason for it

#### Scenario: Nothing secret in the answer
- **WHEN** an external side is read, or fails to be read
- **THEN** the answer and the log hold no client secret and no token

#### Scenario: A wrong pair
- **WHEN** a side is unregistered, or the two aren't a factory owner and a machine builder
- **THEN** the answer is `404` or `422`

### Requirement: Health

`GET /api/health` SHALL report each component without a token, with the time of the check and each component's response time.

#### Scenario: All healthy
- **WHEN** every component answers
- **THEN** the answer is `200`, with status `ok` for each

#### Scenario: A component is down
- **WHEN** a component doesn't answer
- **THEN** the answer is still `200`, that component has a status other than `ok` with a detail message, and the detail holds no credentials

#### Scenario: Timing
- **WHEN** the health is read
- **THEN** the answer has `checked_at`, and each configured component has `response_ms`, the whole milliseconds its probe took, including one that failed

#### Scenario: Not configured
- **WHEN** a component has no address configured
- **THEN** its status is `not configured`, and its `response_ms` is null

#### Scenario: A connector that doesn't answer
- **WHEN** the connector can't be reached
- **THEN** the answer is service unavailable
