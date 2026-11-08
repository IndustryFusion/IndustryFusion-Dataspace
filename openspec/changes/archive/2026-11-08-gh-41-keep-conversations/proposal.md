# Proposal

Issue: #41

## Why

Retention deletes a conversation's row once it has been idle for the row retention period, 30 days by default, and a later message with the same id opens a new conversation in state `OPEN`. Whether a request was answered is worked out from the reply's row, so a request reads as outstanding again once retention has removed its reply. `protocol.md` lists both under "Known limits". Participants need conversations, and which of their requests were answered, for as long as the conversation lasts.

## What Changes

- Retention keeps removing message content and old message rows on the same schedule, and no longer deletes conversations.
- When a request is answered, the adapter stores the time on the request's own row: when it accepts a reply it received, or when the receiver accepts a reply it sent. The request then stays answered after the reply's row is removed.
- `GET /conversations/{id}` returns an old conversation whose messages have all been removed, with its state, outcome and whatever message rows remain, and a request's `replied_at` comes from the stored time first.
- `protocol.md` drops the two limits this fixes.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `adapter-messaging`: retention no longer deletes conversations.
- `conversation-protocol`: when a request counts as answered, and reading a conversation whose messages are gone.

## Out of Scope

- Keeping message rows or content longer. Their retention periods are unchanged.
- A separate retention period for conversations, or removing them at all. Removing a participant still drops its database.
- Migrating existing data. Requests answered before this change keep the current behaviour until their reply's row is removed: the stored time is set only from now on.
- Any change to the gateway, the management API or the UI.

## Impact

- `manifest.md`: none affected.
- `architecture.md`: none affected. It names retention but not what it deletes.
- `protocol.md`: "Known limits" loses "A closed conversation can come back after retention" and "A reply removed by retention stops counting".
- `gateway-api.md`: `GET /conversations/{id}` says where `replied_at` comes from, and that a conversation outlives its messages.
