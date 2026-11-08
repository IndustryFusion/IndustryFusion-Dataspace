# Proposal

Issue: #42

## Why

An operator looking after participants in the management UI can't see where a participant's adapter and connector are, can't tell an external participant at a glance, has to copy credentials by hand, and has to leave and reopen a screen to read it again. The Health screen gives a status per component with no summary, timing or time of the check. The Policies screen leaves out each capability's data classification and the conversation access was granted in, and shows nothing for an external participant's side.

## What Changes

- **Participants:** each participant shows its adapter and DSP addresses as the API returns them, an "(external)" marker for an external participant, and copy buttons for the client id and secret when credentials are shown. A Refresh button reads the list again.
- **Health:** a summary line, each component's response time, the time of the check, and a Refresh button. `GET /api/health` gains `checked_at` and a `response_ms` per component.
- **Policies:** each row shows the capability's data classification and the conversation its decision was made in. `GET /api/policy` gains `conversation_id` per entry.
- **An external participant's policies:** `GET /api/policy` reads an external provider's capabilities through the gateway's peer route, with a token of the other side of the pair, and shows them with the rest. Where they can't be read, the side stays under `unavailable` and the answer says why, and the screen shows that reason. Reading policies stays admin-only.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `management-api`: the policy view's new fields and external reads, and the health answer's timing.
- `management-ui`: the Participants, Health and Policies screens.

## Out of Scope

- Changing an external participant's policy from the hub. Approve, deny and reset stay for hosted providers, and the capability routes keep giving `409` for an external participant.
- Showing a hosted participant's addresses to someone who isn't an administrator. Public reads stay as #20 left them.
- Any change to the adapter, the gateway's routes, or what a peer token can read from an adapter.
- New components in the health check.

## Impact

- `manifest.md`: none affected.
- `architecture.md`: "Management API", which gains the read of an external participant's capabilities through the peer route.
- `management-api.md`: `GET /api/policy` and `GET /api/health`, and "Capabilities and policies", which says external sides are listed as unavailable.
- `keycloak.md`: "External participants" gains that the management API asks for a participant's token, to read an external peer's capability state.
