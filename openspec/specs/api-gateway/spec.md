# api-gateway Specification

## Purpose
Defines the single public entry point for agents: how it validates tokens, routes each caller to its own adapter and keeps internal routes unreachable.

## Requirements

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

### Requirement: Compatible participants
The gateway SHALL answer `GET /participants/compatible` for the calling participant with what the registry answers, leaving out the addresses of hosted participants that only work inside the hub.

#### Scenario: Peers listed
- **WHEN** a registered participant calls it
- **THEN** it gets the participants compatible with it

#### Scenario: A hosted peer
- **WHEN** a peer is hosted
- **THEN** its `adapter_url` is null, and its `dsp_url` is null unless it is reachable

#### Scenario: An external peer
- **WHEN** a peer is external
- **THEN** its own addresses stay

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

### Requirement: Streaming and upload limit
The gateway SHALL forward request and answer bodies as they arrive, and SHALL refuse a request body over the configured limit with payload too large. The limit is `MAX_UPLOAD_BYTES` for `POST /outbox/files`, and `MAX_JSON_BYTES` for anything else.

#### Scenario: Large body
- **WHEN** a body is forwarded in either direction
- **THEN** its bytes reach the other side unchanged, without being held whole in the gateway's memory

#### Scenario: Stated length over the limit
- **WHEN** a request states a length over the limit
- **THEN** the answer is payload too large, and the adapter is not contacted

#### Scenario: Unstated length over the limit
- **WHEN** a request has no stated length, and its body passes the limit
- **THEN** the answer is payload too large

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
