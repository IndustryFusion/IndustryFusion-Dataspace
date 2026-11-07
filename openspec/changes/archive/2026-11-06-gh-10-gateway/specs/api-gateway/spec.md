# Spec Delta

## Purpose

Defines the single public entry point for agents.

## ADDED Requirements

### Requirement: Token validation
The gateway SHALL accept only tokens with a valid RS256 signature from the realm's signing keys and an exact issuer match.

#### Scenario: Missing or invalid token
- **WHEN** a request has no token, a wrong signature or a different issuer
- **THEN** the answer is unauthorized

#### Scenario: Signing key rotated
- **WHEN** a token is signed with a key the gateway hasn't seen
- **THEN** the gateway fetches the keys again, and accepts the token

#### Scenario: Keys unreachable
- **WHEN** the signing keys can't be fetched and none are cached for the token
- **THEN** the answer is bad gateway

### Requirement: Routing to the caller's own adapter
The gateway SHALL forward a request to the adapter of the participant named by the token's claim, and to no other.

#### Scenario: Own adapter
- **WHEN** a participant calls a route such as the inbox
- **THEN** the request reaches its own adapter, with method, path, query, body and `Authorization` header unchanged, and the adapter's answer is returned

#### Scenario: Two participants
- **WHEN** two participants make the same request
- **THEN** each reaches only its own adapter

#### Scenario: No claim
- **WHEN** a valid token has no `participant_id` claim
- **THEN** the answer is forbidden

#### Scenario: Not registered
- **WHEN** the claim names a participant that isn't registered
- **THEN** the answer is forbidden

### Requirement: Internal routes blocked
The catch-all route SHALL NOT reach any `internal/*` path of an adapter, however the path is written.

#### Scenario: Internal path
- **WHEN** a request's path starts with `internal/`
- **THEN** the answer is not found, and nothing is forwarded

#### Scenario: Disguised path
- **WHEN** the path reaches `internal/` by percent-encoding, a different case, or `.` and `..` segments
- **THEN** the answer is not found, and nothing is forwarded

### Requirement: Peer notification route
The gateway SHALL forward `POST /peer/{receiver}/internal/transfer-request` to the named receiver's adapter for any valid token, leaving authorization to the receiver.

#### Scenario: Forwarded to the receiver
- **WHEN** a holder of a valid token calls the route for a registered receiver
- **THEN** the receiver's adapter gets the request, and its answer is returned

#### Scenario: Unknown receiver
- **WHEN** the receiver isn't registered
- **THEN** the answer is not found

#### Scenario: No token
- **WHEN** the route is called without a valid token
- **THEN** the answer is unauthorized

### Requirement: Compatible participants
`GET /participants/compatible` SHALL answer from the registry for the participant in the token.

#### Scenario: Peers listed
- **WHEN** a participant asks for its compatible participants
- **THEN** the registry's answer for that participant is returned

### Requirement: Registry cache
The gateway SHALL cache each participant's registry record for 30 seconds, and SHALL NOT cache failures.

#### Scenario: Repeated requests
- **WHEN** a participant makes several requests within 30 seconds
- **THEN** the registry is asked once

#### Scenario: After 30 seconds
- **WHEN** a request arrives more than 30 seconds after the last lookup
- **THEN** the registry is asked again

### Requirement: Upstream errors
The gateway SHALL report upstream problems by status, in the standard error body.

#### Scenario: Registry or adapter unavailable
- **WHEN** the registry or the adapter can't be reached
- **THEN** the answer is service unavailable

#### Scenario: Adapter too slow
- **WHEN** the adapter doesn't answer within 120 seconds
- **THEN** the answer is gateway timeout

### Requirement: Health
`GET /health` SHALL answer with no token.

#### Scenario: Health check
- **WHEN** the health route is called with no token
- **THEN** the answer is OK

### Requirement: End-to-end exchange through the gateway
Two agents SHALL exchange messages in both directions using only the gateway and Keycloak.

#### Scenario: Definition of done
- **WHEN** agent A sends a request through the gateway, and agent B reads it and replies through the gateway
- **THEN** each message arrives in the other's inbox through the connectors, with no direct call between the agents or to an adapter
