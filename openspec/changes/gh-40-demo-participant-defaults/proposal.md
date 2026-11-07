# Proposal

Issue: #40

## Why

A fresh installation can't create its demo participants without extra settings. `DEMO_PARTICIPANTS` is empty by default, so `POST /api/demo` creates nothing. A hosted participant is registered as not reachable unless the administrator asks, so an external participant can't reach it, and asking for reachability where the peer addresses aren't configured is refused with `422`. The IFRIC reader needs its client id set, although `keycloak.md` names the one client it should be.

## What Changes

- `DEMO_PARTICIPANTS` has a default: a demo factory owner, a demo machine builder and a second demo machine builder. Unset or empty means that default, and `[]` means none.
- `DEMO_PARTICIPANTS` also accepts a JSON list of participants, besides `<id>=<type>,...`. A value that can't be used stops the service at start, with a message naming the setting and the problem.
- A hosted participant registered without `externally_reachable` is registered as reachable.
- Where `GATEWAY_PEER_URL` or `DSP_GATEWAY_PEER_URL` isn't set, a hosted participant that asks for reachability, or gets it by default, is registered as not reachable, and the answer says so and why. It is no longer refused.
- The management UI's registration form starts with reachability ticked for a hosted participant.
- `IFRIC_READER_CLIENT_ID` defaults to `dataspace-ifric-reader`.
- The local environment's settings stop overriding the demo default, and the documents describe the new defaults.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `management-api`: demo participants, the reachability default, and registration where the peer addresses are missing.
- `external-participants`: what a hosted participant registered without the flag announces, and registration where the peer addresses are missing.
- `ifric-company-details`: when IFRIC counts as configured.
- `management-ui`: the registration form's starting value.

## Out of Scope

- Changing which addresses a reachable participant announces, or how the peer route and DSP gateway work.
- Making existing participants reachable. A participant changes only when it is registered again.
- Migrating data, and keeping a Helm upgrade from an earlier release unchanged.
- Exposing the gateway or DSP gateway outside the cluster. That stays a deployment choice, through the existing Ingress settings.
- Company details for the demo participants. Their ids are not IFRIC company ids.

## Impact

- `manifest.md`: none affected.
- `architecture.md`: "Adding a Participant" and "Request Flow — External participant ↔ hosted participant", where a hosted participant is now reachable unless registered otherwise.
- `management-api.md`: `POST /api/participants`, `POST /api/demo` and "Configuration".
- `keycloak.md`: the IFRIC reader's client id no longer has to be given.
- `deploy/README.md`, `deploy/local/services.yaml` and the Helm values for the local environment: the demo default.
