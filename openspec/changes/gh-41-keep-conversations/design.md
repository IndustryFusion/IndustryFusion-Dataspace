# Design

## Context

The adapter's retention task removes the content of final messages after `expires_at`, or the content retention period, and deletes a final message's row after the row retention period, once its content is gone. It also deletes every conversation whose `last_message_at` is older than the row retention period. `GET /conversations/{id}` works out `replied_at` and `outstanding_requests` from the message rows it still has: a request is answered if a kept message that isn't refused names it in `in_reply_to`.

## Decisions

### Conversations are not deleted

Retention stops deleting conversations. A conversation row holds its state, outcome, counterpart and a few times, and no content, so it is small. Keeping it means a closed conversation stays closed, and an idle one can be continued by either side, with the same rules as before, as both sides keep their copy.

Alternatives:

- **A longer, separate retention period for conversations.** It moves the problem, and adds a setting. The issue asks for conversations to be kept for as long as participants need them.
- **Deleting a conversation only once it is closed and idle.** A closed conversation can be reopened, and the issue asks for its state and outcome to stay readable.

The table grows with the number of conversations. That is listed as a risk below.

### The answer time is stored on the request

Each message row gains a nullable `replied_at`. It is set on the row of the request that a reply names in `in_reply_to`, in this adapter's own tables, sent or received, and is kept once set:

- **A reply this adapter receives:** when it is accepted. A notification refused by the state or validity rules sets nothing.
- **A reply this adapter sends:** when the receiver accepts its notification. One the receiver refuses sets nothing.

If no row has that id, because it was never here or has been removed, nothing is set. The stored time is the first one, so a second reply doesn't move it.

Reading a conversation, a request's `replied_at` is its stored time, or else, as now, the time of the earliest kept reply that isn't refused. A request is in `outstanding_requests` only if it has neither. So nothing a reader sees today changes while the reply's row is still there, and a sent reply on its way still counts, as it does now.

The column is added by the adapter's existing schema check, which adds missing nullable columns to existing tables.

Alternatives:

- **Keeping a reply's row while its request is kept.** Rows would outlive their retention for an unbounded time.
- **A separate table of answered requests.** One more table for one value per row.
- **Setting the time when a sent reply is written, rather than when it is accepted.** A reply the receiver refuses would then count, which the read rule doesn't allow today.

### Reading a conversation whose messages are gone

`GET /conversations/{id}` already answers from the conversation row and whatever messages remain. With the row kept, an old conversation reads with its state, outcome and times, an empty or shorter `messages`, and `outstanding_requests` from what remains. A request whose row remains and was answered keeps `replied_at`, and isn't outstanding, whether or not its reply's row remains. A request whose own row has been removed isn't listed, as now.

## Conflicts with existing documents and specs

- `protocol.md`, "Known limits", lists both behaviours this change removes.
- `adapter-messaging` "Retention" says nothing of conversations, and the code deletes them. The requirement now says they are kept.
- `conversation-protocol` "Reading conversations", scenario "Outstanding requests", defines answered from the messages kept. It now includes the stored time.

## Risks

- **The conversations table grows** by one small row per conversation, for the life of the participant. Deleting a participant drops its database. If this matters, a later change can add a retention period for conversations.
- **Rows answered before this change** have no stored time, and read as before until their reply's row is removed. There is no migration, as the issue's scope excludes it.
