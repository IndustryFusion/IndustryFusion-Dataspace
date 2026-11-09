# Spec Delta

## Purpose

What a reachable hosted peer's `dsp_url` is in `GET /participants/compatible`.

## MODIFIED Requirements

### Requirement: Compatible participants
The gateway SHALL answer `GET /participants/compatible` for the calling participant with what the registry answers, leaving out the addresses of hosted participants that only work inside the hub. A reachable hosted peer's `dsp_url` SHALL be its address on the DSP gateway.

#### Scenario: Peers listed
- **WHEN** a registered participant calls it
- **THEN** it gets the participants compatible with it

#### Scenario: A hosted peer
- **WHEN** a peer is hosted
- **THEN** its `adapter_url` is null, and its `dsp_url` is null unless it is reachable

#### Scenario: A reachable hosted peer
- **WHEN** a hosted peer is `externally_reachable`
- **THEN** its `dsp_url` starts with the deployment's DSP gateway peer address followed by one path segment, and ends with `/api/v1/dsp`

#### Scenario: An external peer
- **WHEN** a peer is external
- **THEN** its own addresses stay
