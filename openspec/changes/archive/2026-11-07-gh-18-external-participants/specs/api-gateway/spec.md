# Spec Delta

## Purpose

The gateway's peer route carries everything an external participant needs from a hosted adapter.

## MODIFIED Requirements

### Requirement: Peer notification route
The gateway SHALL forward `POST /peer/{receiver}/internal/transfer-request`, `GET /peer/{receiver}/internal/capabilities` and `POST /peer/{receiver}/internal/capabilities/approvals` to the named receiver's adapter for any valid token, leaving authorization to the receiver, and SHALL remove `X-Internal-Key` from what it forwards on every peer route.

#### Scenario: Forwarded to the receiver
- **WHEN** a holder of a valid token calls one of these routes for a registered receiver
- **THEN** the receiver's adapter gets the request, and its answer is returned

#### Scenario: Unknown receiver
- **WHEN** the receiver isn't registered
- **THEN** the answer is not found

#### Scenario: No token
- **WHEN** one of these routes is called without a valid token
- **THEN** the answer is unauthorized

#### Scenario: The internal key doesn't pass
- **WHEN** a caller sends `X-Internal-Key` on a peer route
- **THEN** the adapter gets the request without it

#### Scenario: Other internal routes stay closed
- **WHEN** a caller tries another method or path under `/peer/{receiver}/internal/`, such as a management `PATCH`
- **THEN** nothing reaches the receiver's internal route

#### Scenario: Fields between adapters pass through
- **WHEN** a notification has `sender_applied`, and its answer has `kept_step`
- **THEN** each reaches the other side unchanged

## ADDED Requirements

### Requirement: Content route for peers
The gateway SHALL forward `POST /peer/{receiver}/internal/inbox-receive/{id}` to the named receiver's adapter when it has a transfer token header, without asking for a bearer token, up to the upload limit.

#### Scenario: Forwarded with the header
- **WHEN** a connector pushes content with the header for a registered receiver
- **THEN** the receiver's adapter gets the body and the header, and its answer is returned

#### Scenario: No header
- **WHEN** the route is called without the header
- **THEN** the answer is unauthorized, and nothing is forwarded

#### Scenario: Over the limit
- **WHEN** the body is larger than the upload limit
- **THEN** the answer is too large
