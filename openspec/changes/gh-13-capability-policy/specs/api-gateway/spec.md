# Spec Delta

## ADDED Requirements

### Requirement: Peer capability routes
The gateway SHALL forward `GET /peer/{receiver}/internal/capabilities` and `POST /peer/{receiver}/internal/capabilities/approvals` to the named receiver's adapter for any valid token, leaving authorization to the receiver, and SHALL NOT pass on `X-Internal-Key`.

#### Scenario: Forwarded
- **WHEN** a holder of a valid token calls either route for a registered receiver
- **THEN** the receiver's adapter gets the request, and its answer is returned

#### Scenario: Internal key
- **WHEN** a call to either route has an `X-Internal-Key` header
- **THEN** the header doesn't reach the adapter

#### Scenario: Other capability routes
- **WHEN** a caller uses `PATCH` on a capability route under the peer path, or any other internal path
- **THEN** nothing reaches the receiver's adapter

#### Scenario: No token
- **WHEN** either route is called without a valid token
- **THEN** the answer is unauthorized

#### Scenario: Unknown receiver
- **WHEN** the receiver isn't registered
- **THEN** the answer is not found
