# Spec Delta

## Purpose

Defines how agents send files to each other and download them.

## ADDED Requirements

### Requirement: Sending files
The adapter SHALL accept one or more files for a receiver, store them as one ZIP at `files/{id}.zip`, and send them through the same connector workflow as a message.

#### Scenario: Several files
- **WHEN** an agent posts several files to a compatible receiver
- **THEN** the answer is accepted, with a message id, status, `applied` and conversation state, and the message goes through `registered` to `notified`

#### Scenario: No files
- **WHEN** a request has no files, or no receiver
- **THEN** it is refused as invalid, and nothing is stored

#### Scenario: Receiver not allowed
- **WHEN** the receiver is unregistered, or its role is not compatible
- **THEN** the answer is the same as for a message, and nothing is stored

#### Scenario: Before authentication
- **WHEN** a request has no valid token
- **THEN** it is refused before its body is read

#### Scenario: Storage fails
- **WHEN** the ZIP can't be stored
- **THEN** the answer is service unavailable, and no message is recorded

### Requirement: File names in the bundle
The ZIP SHALL contain every file sent, under a name that can't unpack outside its folder.

#### Scenario: Path in a name
- **WHEN** a file's name contains a path
- **THEN** its entry has only the last part of that name

#### Scenario: Repeated name
- **WHEN** two files have the same name
- **THEN** both are in the ZIP, under different names

#### Scenario: Empty name
- **WHEN** a file's name is empty or has nothing usable
- **THEN** it is in the ZIP under a generated name

### Requirement: Receiving files
A received file message SHALL have `has_files` true, and `payload` `{"_bundle": true}` once its content has arrived.

#### Scenario: Arrived
- **WHEN** the content of a file message arrives
- **THEN** it is stored as `files/{id}.zip`, and the message reads as received, with `has_files` true and `payload` `{"_bundle": true}`

#### Scenario: Ordinary message
- **WHEN** a message without files arrives
- **THEN** `has_files` is false, and its download gives bad request

### Requirement: Downloading files
The adapter SHALL return a received message's files as a ZIP with the same bytes that were sent.

#### Scenario: Download
- **WHEN** the receiver downloads a file message
- **THEN** the answer is a ZIP containing each file with the bytes the sender posted

#### Scenario: Not there yet
- **WHEN** the content has not arrived, or was purged
- **THEN** the answer is not found

#### Scenario: Not the receiver's message
- **WHEN** a participant asks for a message it did not receive
- **THEN** the answer is not found

### Requirement: Reply files
A file message SHALL be able to name the message it answers.

#### Scenario: Linked to the original
- **WHEN** a file is sent with `in_reply_to` and a conversation id
- **THEN** the receiver's message has that `in_reply_to` and conversation id

### Requirement: Upload limit
The services SHALL refuse a body over the configured limit, `MAX_UPLOAD_BYTES`, with payload too large.

#### Scenario: Over the limit at the adapter
- **WHEN** a request to the adapter exceeds the limit, with or without a stated length
- **THEN** the answer is payload too large, and nothing is stored

#### Scenario: Over the limit on arrival
- **WHEN** content pushed to a message exceeds the limit
- **THEN** the answer is payload too large, nothing is stored, and the message shows an error

### Requirement: Retention of files
File content SHALL follow the same retention rules as message content.

#### Scenario: Purged
- **WHEN** a file message's content is due for removal
- **THEN** the ZIP is removed from storage, `has_files` stays true, and `payload` reads as null

### Requirement: Large file end to end
A file near the limit SHALL pass through the gateway and connectors unchanged, without the gateway holding it in memory.

#### Scenario: Large file
- **WHEN** an agent sends a file near the limit through the gateway on the local cluster
- **THEN** the receiver downloads the same bytes through the gateway, and the gateway's peak memory stays far below the file's size
