# Spec Delta

## ADDED Requirements

### Requirement: Streaming and upload limit
The gateway SHALL forward request and answer bodies as they arrive, and SHALL refuse a request body over the configured limit, `MAX_UPLOAD_BYTES`, with payload too large.

#### Scenario: Large body
- **WHEN** a body is forwarded in either direction
- **THEN** its bytes reach the other side unchanged, without being held whole in the gateway's memory

#### Scenario: Stated length over the limit
- **WHEN** a request states a length over the limit
- **THEN** the answer is payload too large, and the adapter is not contacted

#### Scenario: Unstated length over the limit
- **WHEN** a request has no stated length, and its body passes the limit
- **THEN** the answer is payload too large
