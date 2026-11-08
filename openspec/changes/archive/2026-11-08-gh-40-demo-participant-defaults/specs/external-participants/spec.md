# Spec Delta

## Purpose

A hosted participant is reachable from outside unless registered otherwise, and missing peer addresses no longer refuse a registration.

## MODIFIED Requirements

### Requirement: Addresses of a reachable hosted participant
A hosted participant with `externally_reachable` SHALL announce addresses that work from outside the cluster: `peer_notify_url` through the gateway's peer route, and `dsp_url`, the adapter's advertised DSP address and the connector's callback and public addresses through the DSP gateway. Its `adapter_url` SHALL stay the adapter's real address.

#### Scenario: Registering reachable
- **WHEN** a hosted participant is registered with `externally_reachable` true or without it, and both peer addresses are configured
- **THEN** its record has the peer route as `peer_notify_url`, the DSP gateway's form as `dsp_url`, and the adapter's real address as `adapter_url`

#### Scenario: Not reachable
- **WHEN** a hosted participant is registered with `externally_reachable` false
- **THEN** its record has `peer_notify_url` null and the connector's real address as `dsp_url`, and its connector announces that address

#### Scenario: Changing it
- **WHEN** a participant is registered again with a different `externally_reachable`
- **THEN** its adapter and connector run with the new addresses

#### Scenario: Peer address not configured
- **WHEN** a hosted participant is to be reachable, and the service has no public address for the gateway or the DSP gateway
- **THEN** it is registered as not reachable, with the connector's real address as `dsp_url`, and the answer's `warnings` says why

## ADDED Requirements

### Requirement: An external participant reaches a hosted one registered without the flag
A hosted participant registered without `externally_reachable` SHALL be reachable from an external participant when both peer addresses are configured.

#### Scenario: Exchange with a participant registered without the flag
- **WHEN** a hosted participant is registered without `externally_reachable` on an installation with both peer addresses configured, and an external participant of a compatible type sends it a message with files and a capability request
- **THEN** the hosted participant receives the message and files, its answer reaches the external participant, and the capability request is recorded
