# Spec Delta

## Purpose

Defines how a participant states what it shares, how others ask for access, and that this is advisory.

## ADDED Requirements

### Requirement: Catalogue
Each adapter SHALL offer the capabilities in `protocol.md` for its own role, with a label, a description that matches the default, and a data classification.

#### Scenario: Factory owner
- **WHEN** a factory owner's capabilities are listed
- **THEN** they are `twin:direct` with default `auto`, and `twin:adjacents` and `twin:history` with default `on-request`

#### Scenario: Machine builder
- **WHEN** a machine builder's capabilities are listed
- **THEN** there is `mb:confidential` with default `auto`, and its description says it is available by default

### Requirement: Access check
`GET /capabilities/access` SHALL return, for each capability, `capability`, `label`, `description`, `data_classification`, `status` and `source`.

#### Scenario: Consumer asks about a provider
- **WHEN** a participant calls it with `provider=`
- **THEN** it sees the effective status of each of that provider's capabilities for itself

#### Scenario: Provider views a peer
- **WHEN** a participant calls it with `consumer=`
- **THEN** it sees the effective status of its own capabilities for that consumer, including its own defaults

#### Scenario: Neither or both
- **WHEN** it is called with neither parameter, or both
- **THEN** it is refused as invalid

#### Scenario: Provider not allowed
- **WHEN** the provider is unregistered, or its role is not compatible
- **THEN** the answer is not found, or forbidden

#### Scenario: Provider unreachable
- **WHEN** the provider's adapter can't be reached
- **THEN** the answer is service unavailable

### Requirement: Asking for access
`POST /capabilities/requests` SHALL record a request at the provider, and answer `202`.

#### Scenario: On request
- **WHEN** a participant asks for an `on-request` capability
- **THEN** the provider holds a pending request with `conversation_id`, `purpose` and `note`, and the consumer's status is `pending`, source `explicit`

#### Scenario: Incompatible role
- **WHEN** a participant asks a provider whose role is not compatible, directly or as a peer call to the provider
- **THEN** the answer is forbidden, and nothing is stored

#### Scenario: Unknown capability
- **WHEN** a participant asks for a capability the provider doesn't offer
- **THEN** the answer is not found, and nothing is stored

#### Scenario: Repeated request
- **WHEN** a consumer asks again, at any status
- **THEN** the answer is the existing request, unchanged

#### Scenario: Concurrent requests
- **WHEN** a consumer sends many requests for one capability at once
- **THEN** one request is stored

#### Scenario: Already allowed
- **WHEN** a participant asks for a capability whose default is `auto`, with no request stored
- **THEN** the answer is `202` with status `auto`, and nothing is stored

### Requirement: Deciding a request
`PATCH /capabilities/requests/{id}` SHALL approve or deny a pending request, and SHALL store and return an optional note.

#### Scenario: Approve
- **WHEN** a provider approves a request
- **THEN** its status is `approved`, `resolved_at` is set, and the consumer's status is `approved`, source `explicit`

#### Scenario: Deny with a note
- **WHEN** a provider denies a request with a note
- **THEN** its status is `denied`, and `decision_note` is returned by that call, by listing requests, by the consumer's repeated request and by the consumer's access check

#### Scenario: Consumer's note kept
- **WHEN** a request with a `note` is decided with a note
- **THEN** both are returned, each in its own field

#### Scenario: Already resolved
- **WHEN** a resolved request is approved or denied
- **THEN** the answer is `409`, and it does not change

#### Scenario: Concurrent decisions
- **WHEN** many decisions on one request arrive at once
- **THEN** exactly one succeeds, the others get `409`, and the status and note are the winner's

#### Scenario: Unknown request
- **WHEN** the request doesn't exist
- **THEN** the answer is not found

### Requirement: Listing requests
`GET /capabilities/requests` SHALL return requests received by the caller, optionally by status.

#### Scenario: Filter
- **WHEN** it is called with `status=`
- **THEN** only requests with that status are returned

### Requirement: Setting access directly
`POST /capabilities/policy` SHALL set access for a consumer, without a request.

#### Scenario: Approve or deny
- **WHEN** a provider approves or denies a compatible consumer
- **THEN** the consumer's status is that decision, source `explicit`, whatever it was before

#### Scenario: Reset
- **WHEN** a provider resets a consumer
- **THEN** the consumer's status is the default, source `default`, and the consumer can ask again

#### Scenario: Reset with nothing stored
- **WHEN** there is nothing to reset, or the consumer is no longer registered
- **THEN** the answer is success, and the status is the default

#### Scenario: Consumer not allowed
- **WHEN** approve or deny names a consumer that is unregistered, or whose role is not compatible
- **THEN** the answer is not found, or forbidden

#### Scenario: Unknown capability or action
- **WHEN** the capability isn't this adapter's, or the action isn't known
- **THEN** the answer is not found, or invalid

### Requirement: Internal routes
The internal capability routes SHALL accept `X-Internal-Key`, and, where stated, a peer token limited to that peer's own approvals.

#### Scenario: Management reads
- **WHEN** `GET /internal/capabilities` is called with the key
- **THEN** it returns the defaults and every approval

#### Scenario: Peer reads
- **WHEN** it is called with a compatible peer's token
- **THEN** it returns the defaults and only that peer's approvals

#### Scenario: Peer records a request
- **WHEN** `POST /internal/capabilities/approvals` is called with a peer's token, for itself, with action `request`
- **THEN** the request is recorded

#### Scenario: Peer goes further
- **WHEN** a peer's token asks to decide, names another consumer, or calls a `PATCH` route
- **THEN** the answer is forbidden

#### Scenario: Incompatible peer
- **WHEN** a valid token belongs to a participant whose role is not compatible
- **THEN** the answer is forbidden

#### Scenario: Neither credential
- **WHEN** a call has no credential, a wrong key, or no key is configured
- **THEN** the answer is unauthorized

#### Scenario: Management resolves
- **WHEN** `PATCH /internal/capabilities/approvals/{id}` is called with the key and approve or deny
- **THEN** a pending request is resolved, and a resolved one gives `409`

#### Scenario: Management reset
- **WHEN** it is called with the key and `reset`
- **THEN** the consumer's status returns to the default, as through the agent route

#### Scenario: Management decision
- **WHEN** `POST /internal/capabilities/approvals` is called with the key and a decision
- **THEN** it is recorded for that consumer

#### Scenario: Management default
- **WHEN** `PATCH /internal/capabilities/{capability}` is called with the key and `auto` or `on-request`
- **THEN** that is the capability's default for consumers with nothing stored, and it stays after a restart

### Requirement: Access is advisory
The dataspace SHALL NOT check capability policy when a message is sent or received, and messages SHALL NOT change approval records.

#### Scenario: Denied capability
- **WHEN** a message names a capability denied to its receiver or sender
- **THEN** it is delivered as usual

#### Scenario: Grant and deny messages
- **WHEN** `grant` and `deny` messages are delivered
- **THEN** approval records on both sides are unchanged

#### Scenario: Documents
- **WHEN** someone connecting an application reads `protocol.md`, `architecture.md` or `manifest.md`
- **THEN** they state that access is advisory, and that the check is the application's

### Requirement: End-to-end capability flow
A request, approval and access check SHALL work between two participants through the gateway.

#### Scenario: On the local cluster
- **WHEN** two agents request, decide, deny, reset and check access through the gateway, and an incompatible participant asks
- **THEN** each step gives the documented status, and the incompatible participant gets forbidden
