# Spec Delta

## Purpose

What the gateway tells agents about their peers holds no internal addresses.

## MODIFIED Requirements

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
