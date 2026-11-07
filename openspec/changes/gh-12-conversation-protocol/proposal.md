# Proposal

Issue: #12

## Why

Messages carry a performative, but nothing checks it, and every conversation stays `OPEN`. Two participants need a defined, shared state for each exchange, as `protocol.md` describes.

## What Changes

- Validate each message against the rules in `protocol.md`, and refuse a broken one with `422` and `invalid_message`.
- Apply the state rules when sending, and refuse a violation with `409` and `conversation_state_violation`. A refused message is stored for audit.
- The receiver applies the same rules to its own copy of the state, and compares the conversation's counterpart on later messages.
- Add `GET /conversations` and `GET /conversations/{id}`, with `messages` and `outstanding_requests`.
- Deliver one conversation's messages to the receiver in the order they were accepted, so both copies apply them in the same order.
- Settle simultaneous `close` with `close`, and `escalate` with `escalate`, by the lower `message_id` on both sides.
- Keep the receiver's rules for every other crossing. A difference this leaves between the copies is accepted, and recorded in `protocol.md`.
- After a failed notification, let the sender's repeat send the step to the receiver as an applied step.

## Capabilities

### New Capabilities

- `conversation-protocol`: Message validity, conversation state on both sides, and the conversation routes.

### Modified Capabilities

None. Existing requirements in `adapter-messaging` still hold. `file-transfer` messages follow the same rules.

## Out of Scope

- Automatic closing after inactivity, and enforcing `authorization.expires_at`. `protocol.md` records them as known limits.
- Ordering of content arrival. Each message still runs its own transfer, so a later message's content can arrive first.
- Retrying a failed notification automatically, or undoing the sender's state when the receiver refuses. `protocol.md` records the resulting difference.
- Making the two copies agree in every crossing or failure. `design.md` records this as a rejected alternative.
- Capability policy (#13).

## Impact

- `architecture.md`: not affected. It already lists the routes.
- `manifest.md`: not affected.
- `protocol.md`: records how simultaneous messages settle, the state difference after a refusal, the states not named in its table, and that delivery of notifications is ordered within a conversation.
- `gateway-api.md`: additive fields only. A `409` also has `message_id`, conversation messages also have `status` and `has_files`, and `conversation_state` can be `null` for an unknown conversation.
- Services: adapter. The notification between adapters gains an optional field, `sender_applied`, and its answer gains an optional field, `kept_step`. `protocol.md` documents them.
