# Proposal

Issue: #11

## Why

Agents need to send files through the dataspace, for example a machine data package that answers a request. `gateway-api.md` already names the routes, and the gateway and adapter hold bodies in memory today, so a large file would not fit.

## What Changes

- Add `POST /outbox/files`, which bundles one or more files into one ZIP stored as `files/{id}.zip`. It travels through the same connector workflow as a message.
- Add `GET /inbox/messages/{id}/download`, which returns the ZIP.
- Inbox rows have `has_files`, and `payload` is `{"_bundle": true}`. `in_reply_to` links a file to the message it answers.
- Stream bodies through the gateway and adapter instead of holding them in memory.
- Add a configured upload limit, `MAX_UPLOAD_BYTES`, enforced by the gateway and the adapter with `413`.
- Add `python-multipart`, which the adapter needs to read a multipart form. It is the only new runtime dependency.

## Capabilities

### New Capabilities

- `file-transfer`: Sending files between participants and downloading them.

### Modified Capabilities

- `api-gateway`: Bodies are streamed, and the gateway enforces the upload limit.

## Out of Scope

- An Ingress and its body size. #15 deploys the Ingress and sets its limit to match. Nothing here runs through one.
- Conversation rules on file messages. #12 applies them to messages and files alike.
- Resuming an interrupted upload, or sending one file in several parts.

## Impact

- `architecture.md`, "Data Flow Detail": matches. "Technology Stack": no change.
- `manifest.md`: not affected.
- `gateway-api.md`: `POST /outbox/files` states the limit, and `413` is added to the errors.
- Services: adapter, gateway. Local deployment: `MAX_UPLOAD_BYTES` is set for both.
