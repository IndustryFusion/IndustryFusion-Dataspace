# Spec Delta

## Purpose

Demo participants and a hosted participant's reachability work without extra settings.

## MODIFIED Requirements

### Requirement: Registering a hosted participant

`POST /api/participants` SHALL provision a hosted participant in this order: the adapter and connector databases; the Keycloak role, client, claim mapper and role assignment; the Secret, ConfigMap, Deployments and Services in the participants namespace; the registry entry. `adapter_url` and `dsp_url` SHALL come from the participant id, using the slug `sha256(participant_id)[:8]`. A hosted participant registered without `externally_reachable` SHALL be registered as reachable.

#### Scenario: A new hosted participant
- **WHEN** an administrator registers a new hosted participant
- **THEN** each object exists, the registry entry is written last and only when its pods are available, and the answer is the participant record with `client_id` and `client_secret`

#### Scenario: The participant can be used
- **WHEN** two registered participants of compatible types get tokens with their credentials
- **THEN** they exchange a message through the gateway

#### Scenario: Other participants need no change
- **WHEN** a participant is added
- **THEN** existing participants' Kubernetes objects are unchanged, and they find the new one through the registry

#### Scenario: Addresses given for a hosted participant
- **WHEN** a hosted registration gives `adapter_url` or `dsp_url`
- **THEN** the addresses derived from the id are stored instead

#### Scenario: Reaching a hosted participant from outside
- **WHEN** a hosted participant is registered with `externally_reachable` true, and both peer addresses are configured
- **THEN** its `peer_notify_url` is the gateway's peer route for it, and when it is registered with `externally_reachable` false, `peer_notify_url` is `null`

#### Scenario: Reachable by default
- **WHEN** a hosted participant is registered without `externally_reachable`, and both peer addresses are configured
- **THEN** its record has `externally_reachable` true and the gateway's peer route as `peer_notify_url`

#### Scenario: Registered again without the flag
- **WHEN** an existing hosted participant that isn't reachable is registered again without `externally_reachable`, and both peer addresses are configured
- **THEN** it becomes reachable, and its credentials are unchanged

#### Scenario: An external participant without the flag
- **WHEN** an external participant is registered without `externally_reachable`
- **THEN** its record has `externally_reachable` false

#### Scenario: An invalid request
- **WHEN** the request has an unknown `participant_type`, or a `participant_id` that doesn't start with a letter or digit, holds anything but ASCII letters, digits, `.`, `_`, `:` and `-`, is longer than 200 characters, or is `compatible`
- **THEN** the answer is `422`, and nothing is created

### Requirement: Demo participants

`POST /api/demo` SHALL create the participants named in `DEMO_PARTICIPANTS` through the same steps. `DEMO_PARTICIPANTS` SHALL accept a JSON list of participants or `<id>=<type>` entries separated by commas. Unset or empty, it SHALL mean the demo companies' IFRIC URNs: `urn:ifric:ifx-eur-com-own-42ced491-b35d-41f7-9949-fcbb5fa4dcd9` as a factory owner, and `urn:ifric:ifx-eur-com-nap-37eb511d-49c0-4700-ba17-dee8248f0fb5` and `urn:ifric:ifx-eur-com-nap-2150a82e-ccbb-47d7-be5a-8059906bc253` as machine builders. A value that can't be used SHALL stop the service at start.

#### Scenario: Creating them
- **WHEN** an administrator calls `POST /api/demo`
- **THEN** the answer lists a record with credentials for each

#### Scenario: Calling it again
- **WHEN** it is called again
- **THEN** the answer lists the same participants with the same credentials

#### Scenario: A fresh installation
- **WHEN** an administrator calls `POST /api/demo` on an installation that doesn't set `DEMO_PARTICIPANTS`
- **THEN** the three default participants are created as hosted and reachable, and the factory owner exchanges a message with each machine builder through the gateway

#### Scenario: The JSON form
- **WHEN** `DEMO_PARTICIPANTS` is a JSON list of objects with `participant_id`, `participant_type` and optionally `externally_reachable`
- **THEN** `POST /api/demo` creates those participants, each with the reachability given or by default reachable

#### Scenario: The comma-separated form
- **WHEN** `DEMO_PARTICIPANTS` is `<id>=<type>` entries separated by commas
- **THEN** `POST /api/demo` creates those participants

#### Scenario: None configured
- **WHEN** `DEMO_PARTICIPANTS` is `[]`
- **THEN** the answer is an empty list

#### Scenario: A value that can't be used
- **WHEN** `DEMO_PARTICIPANTS` is JSON that isn't a list of such objects, an entry has an unknown key, an unknown type or an id that registration would refuse, an id appears twice, or a comma-separated entry has no `=`
- **THEN** the service stops at start with a non-zero status, and its log names `DEMO_PARTICIPANTS` and the problem

## ADDED Requirements

### Requirement: Reachability without peer addresses

A hosted participant that is to be reachable, by default or by asking, SHALL be registered as not reachable when `GATEWAY_PEER_URL` or `DSP_GATEWAY_PEER_URL` isn't configured, and the answer SHALL say so.

#### Scenario: Peer addresses missing
- **WHEN** a hosted participant is registered with `externally_reachable` true or without it, and a peer address isn't configured
- **THEN** the answer is a success, its record has `externally_reachable` false, `peer_notify_url` null and the connector's own `dsp_url`, and `warnings` says it isn't reachable from outside and names the missing setting

#### Scenario: The demo without peer addresses
- **WHEN** `POST /api/demo` is called and a peer address isn't configured
- **THEN** the participants are created as not reachable, and each record has the warning

#### Scenario: Reads have no warning
- **WHEN** such a participant is read afterwards
- **THEN** its record has `externally_reachable` false, and no `warnings`

#### Scenario: Nothing to warn about
- **WHEN** a participant is registered and nothing was changed from what was asked
- **THEN** the answer has `warnings` empty
