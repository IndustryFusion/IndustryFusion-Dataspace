# MVP Manifest: Agent-to-Agent Communication Through a Dataspace Using EDC

## 1. Project Goal

Build a minimum viable implementation that enables existing agents to communicate across organizational boundaries through a dataspace using Eclipse Dataspace Components (EDC).

The project does not implement the agents themselves. The agents already exist and are capable of interacting with local APIs.

The objective is to provide a standardized, scalable, and governed communication layer between participants without requiring direct API integrations between every pair of participants.

The MVP shall demonstrate:

* Agent A can send a request to Agent B through a dataspace.
* Agent B can receive the request through its local inbox.
* Agent B can send a response through the same mechanism.
* Agent A can receive the response through its local inbox.
* Communication is governed through EDC contracts and policies.
* No direct cross-company API integration exists between agents.
* The same mechanism can be reused for additional participants.

---

# 2. Architectural Principle

The dataspace is not treated as a data marketplace.

Instead, the dataspace is used as a governed communication fabric implementing a bidirectional inbox/outbox pattern.

Each participant exposes:

* an Outbox for messages it wants to send
* an Inbox for messages it receives

Agents never communicate directly.

Agents only interact with their local Dataspace Adapter.

```text
Agent
  │
  ▼
Dataspace Adapter
  │
  ▼
EDC Connector
  │
  ▼
Dataspace
  │
  ▼
Remote EDC Connector
  │
  ▼
Remote Dataspace Adapter
  │
  ▼
Remote Agent
```

---

# 3. MVP Architecture

Two participants are sufficient for the MVP.

```text
Participant A
├── Existing Agent
├── Dataspace Adapter
│   ├── Outbox
│   ├── Inbox
│   └── EDC API Client
├── EDC Control Plane
├── EDC Data Plane
├── PostgreSQL
└── Object Storage

Participant B
├── Existing Agent
├── Dataspace Adapter
│   ├── Outbox
│   ├── Inbox
│   └── EDC API Client
├── EDC Control Plane
├── EDC Data Plane
├── PostgreSQL
└── Object Storage
```

---

# 4. Communication Model

The communication model is symmetric.

## Request Flow

```text
Agent A
 → Outbox A
 → EDC A
 → EDC B
 → Inbox B
 → Agent B
```

## Response Flow

```text
Agent B
 → Outbox B
 → EDC B
 → EDC A
 → Inbox A
 → Agent A
```

Both directions use exactly the same mechanism.

No special response channel is required.

---

# 5. Dataspace Adapter

The Dataspace Adapter is the only component visible to the agents.

Its purpose is to hide EDC complexity and expose a simple messaging interface.

## Responsibilities

### Outbound

* receive messages from the local agent
* store messages
* register EDC assets
* create policies
* create contract definitions
* initiate transfer workflow
* monitor transfer status

### Inbound

* receive transferred messages
* store messages in inbox
* notify local agent
* expose message retrieval API
* track acknowledgements

### EDC Integration

* catalog interaction
* contract negotiation
* transfer initiation
* transfer monitoring
* asset lifecycle management

---

# 6. Inbox / Outbox Model

## Outbox

The Outbox contains messages prepared for transmission.

Each message consists of:

* metadata
* payload reference
* routing information
* policy information

## Inbox

The Inbox contains messages received through the dataspace.

Messages remain available until:

* acknowledged
* expired
* archived

The Inbox acts as the receiving endpoint for all incoming dataspace communication.

---

# 7. Required Infrastructure

## EDC Connector

Per participant:

* EDC Control Plane
* EDC Data Plane
* Management API
* DSP endpoints

## Database

PostgreSQL

Purpose:

* assets
* policies
* contract definitions
* negotiations
* transfer processes
* adapter metadata

## Object Storage

Purpose:

* message payloads
* attachments
* transfer artifacts

Recommended MVP implementation:

* MinIO

## Networking

* local network
* HTTP endpoints
* TLS if feasible

## Logging

Basic application logs for:

* adapter
* connector
* transfer flow

---

# 8. Message Model

Every transferred object is represented as a message.

Example:

```json
{
  "messageId": "msg-001",
  "conversationId": "incident-123",
  "messageType": "request",
  "senderParticipant": "participant-a",
  "receiverParticipant": "participant-b",
  "createdAt": "2026-06-19T10:00:00Z",
  "payloadRef": "object://outbox/msg-001",
  "replyExpected": true
}
```

Response:

```json
{
  "messageId": "msg-002",
  "conversationId": "incident-123",
  "messageType": "response",
  "senderParticipant": "participant-b",
  "receiverParticipant": "participant-a",
  "createdAt": "2026-06-19T10:15:00Z",
  "payloadRef": "object://outbox/msg-002"
}
```

---

# 9. Adapter API

The adapter exposes a simple API to the local agent.

## Outbox

```http
POST /outbox/messages
GET  /outbox/messages/{id}
GET  /outbox/messages/{id}/status
```

## Inbox

```http
GET  /inbox/messages
GET  /inbox/messages/{id}
POST /inbox/messages/{id}/ack
```

Agents never call EDC APIs directly.

---

# 10. EDC Usage Pattern

The dataspace communication layer uses EDC internally.

For every outbound message:

1. Store payload.
2. Register payload as EDC asset.
3. Apply policy.
4. Create contract definition.
5. Negotiate contract with target participant.
6. Start transfer process.
7. Deliver payload into receiver inbox.
8. Mark transfer complete.

The catalog and asset registration are implementation details and are not exposed to agents.

From an agent perspective, communication behaves like sending a message to another participant.

---

# 11. MVP Deployment

Single local deployment.

```text
docker-compose
├── postgres
├── minio
├── edc-a-control-plane
├── edc-a-data-plane
├── edc-b-control-plane
├── edc-b-data-plane
├── adapter-a
└── adapter-b
```

Optional:

```text
├── mock-agent-a
└── mock-agent-b
```

---

# 12. Implementation Plan

## Phase 1 – Define the Communication Model

Deliverables:

* message schema
* routing model
* inbox model
* outbox model
* conversation model

## Phase 2 – Infrastructure Setup

Deploy:

* PostgreSQL
* MinIO
* EDC Connector A
* EDC Connector B

Verify:

* connector health
* connector connectivity

## Phase 3 – Configure EDC

Configure:

* participant IDs
* management APIs
* DSP endpoints
* persistence
* transfer endpoints

Verify:

* contract negotiation works
* transfer process works

## Phase 4 – Build Dataspace Adapter

Implement:

* inbox
* outbox
* EDC client
* message storage
* transfer monitoring
* acknowledgement handling

Verify:

* messages can be submitted
* messages can be received

## Phase 5 – End-to-End Validation

Execute:

```text
Agent A
 → Adapter A
 → EDC A
 → EDC B
 → Adapter B
 → Agent B

Agent B
 → Adapter B
 → EDC B
 → EDC A
 → Adapter A
 → Agent A
```

Validate:

* request delivery
* response delivery
* message tracking
* conversation correlation
* audit logs

---

# 13. Deliverables

* Local EDC deployment
* Dataspace Adapter service
* Message schema
* Inbox/Outbox implementation
* PostgreSQL configuration
* Object storage configuration
* Example request flow
* Example response flow
* Architecture documentation
* Local deployment guide

---

# 14. Definition of Done

The MVP is complete when:

* Two participants are running locally.
* Both participants expose inbox and outbox functionality.
* Agent A can send a message to Agent B.
* Agent B receives the message through its inbox.
* Agent B can send a response.
* Agent A receives the response through its inbox.
* Communication occurs exclusively through EDC.
* No direct participant-specific API integration exists.
* The same pattern can be reused for additional participants without changing the communication architecture.# MVP Manifest: Agent-to-Agent Communication Through a Dataspace Using EDC

## 1. Project Goal

Build a minimum viable implementation that enables existing agents to communicate across organizational boundaries through a dataspace using Eclipse Dataspace Components (EDC).

The project does not implement the agents themselves. The agents already exist and are capable of interacting with local APIs.

The objective is to provide a standardized, scalable, and governed communication layer between participants without requiring direct API integrations between every pair of participants.

The MVP shall demonstrate:

* Agent A can send a request to Agent B through a dataspace.
* Agent B can receive the request through its local inbox.
* Agent B can send a response through the same mechanism.
* Agent A can receive the response through its local inbox.
* Communication is governed through EDC contracts and policies.
* No direct cross-company API integration exists between agents.
* The same mechanism can be reused for additional participants.

---

# 2. Architectural Principle

The dataspace is not treated as a data marketplace.

Instead, the dataspace is used as a governed communication fabric implementing a bidirectional inbox/outbox pattern.

Each participant exposes:

* an Outbox for messages it wants to send
* an Inbox for messages it receives

Agents never communicate directly.

Agents only interact with their local Dataspace Adapter.

```text
Agent
  │
  ▼
Dataspace Adapter
  │
  ▼
EDC Connector
  │
  ▼
Dataspace
  │
  ▼
Remote EDC Connector
  │
  ▼
Remote Dataspace Adapter
  │
  ▼
Remote Agent
```

---

# 3. MVP Architecture

Two participants are sufficient for the MVP.

```text
Participant A
├── Existing Agent
├── Dataspace Adapter
│   ├── Outbox
│   ├── Inbox
│   └── EDC API Client
├── EDC Control Plane
├── EDC Data Plane
├── PostgreSQL
└── Object Storage

Participant B
├── Existing Agent
├── Dataspace Adapter
│   ├── Outbox
│   ├── Inbox
│   └── EDC API Client
├── EDC Control Plane
├── EDC Data Plane
├── PostgreSQL
└── Object Storage
```

---

# 4. Communication Model

The communication model is symmetric.

## Request Flow

```text
Agent A
 → Outbox A
 → EDC A
 → EDC B
 → Inbox B
 → Agent B
```

## Response Flow

```text
Agent B
 → Outbox B
 → EDC B
 → EDC A
 → Inbox A
 → Agent A
```

Both directions use exactly the same mechanism.

No special response channel is required.

---

# 5. Dataspace Adapter

The Dataspace Adapter is the only component visible to the agents.

Its purpose is to hide EDC complexity and expose a simple messaging interface.

## Responsibilities

### Outbound

* receive messages from the local agent
* store messages
* register EDC assets
* create policies
* create contract definitions
* initiate transfer workflow
* monitor transfer status

### Inbound

* receive transferred messages
* store messages in inbox
* notify local agent
* expose message retrieval API
* track acknowledgements

### EDC Integration

* catalog interaction
* contract negotiation
* transfer initiation
* transfer monitoring
* asset lifecycle management

---

# 6. Inbox / Outbox Model

## Outbox

The Outbox contains messages prepared for transmission.

Each message consists of:

* metadata
* payload reference
* routing information
* policy information

## Inbox

The Inbox contains messages received through the dataspace.

Messages remain available until:

* acknowledged
* expired
* archived

The Inbox acts as the receiving endpoint for all incoming dataspace communication.

---

# 7. Required Infrastructure

## EDC Connector

Per participant:

* EDC Control Plane
* EDC Data Plane
* Management API
* DSP endpoints

## Database

PostgreSQL

Purpose:

* assets
* policies
* contract definitions
* negotiations
* transfer processes
* adapter metadata

## Object Storage

Purpose:

* message payloads
* attachments
* transfer artifacts

Recommended MVP implementation:

* MinIO

## Networking

* local network
* HTTP endpoints
* TLS if feasible

## Logging

Basic application logs for:

* adapter
* connector
* transfer flow

---

# 8. Message Model

Every transferred object is represented as a message.

Example:

```json
{
  "messageId": "msg-001",
  "conversationId": "incident-123",
  "messageType": "request",
  "senderParticipant": "participant-a",
  "receiverParticipant": "participant-b",
  "createdAt": "2026-06-19T10:00:00Z",
  "payloadRef": "object://outbox/msg-001",
  "replyExpected": true
}
```

Response:

```json
{
  "messageId": "msg-002",
  "conversationId": "incident-123",
  "messageType": "response",
  "senderParticipant": "participant-b",
  "receiverParticipant": "participant-a",
  "createdAt": "2026-06-19T10:15:00Z",
  "payloadRef": "object://outbox/msg-002"
}
```

---

# 9. Adapter API

The adapter exposes a simple API to the local agent.

## Outbox

```http
POST /outbox/messages
GET  /outbox/messages/{id}
GET  /outbox/messages/{id}/status
```

## Inbox

```http
GET  /inbox/messages
GET  /inbox/messages/{id}
POST /inbox/messages/{id}/ack
```

Agents never call EDC APIs directly.

---

# 10. EDC Usage Pattern

The dataspace communication layer uses EDC internally.

For every outbound message:

1. Store payload.
2. Register payload as EDC asset.
3. Apply policy.
4. Create contract definition.
5. Negotiate contract with target participant.
6. Start transfer process.
7. Deliver payload into receiver inbox.
8. Mark transfer complete.

The catalog and asset registration are implementation details and are not exposed to agents.

From an agent perspective, communication behaves like sending a message to another participant.

---

# 11. MVP Deployment

Single local deployment.

```text
docker-compose
├── postgres
├── minio
├── edc-a-control-plane
├── edc-a-data-plane
├── edc-b-control-plane
├── edc-b-data-plane
├── adapter-a
└── adapter-b
```

Optional:

```text
├── mock-agent-a
└── mock-agent-b
```

---

# 12. Implementation Plan

## Phase 1 – Define the Communication Model

Deliverables:

* message schema
* routing model
* inbox model
* outbox model
* conversation model

## Phase 2 – Infrastructure Setup

Deploy:

* PostgreSQL
* MinIO
* EDC Connector A
* EDC Connector B

Verify:

* connector health
* connector connectivity

## Phase 3 – Configure EDC

Configure:

* participant IDs
* management APIs
* DSP endpoints
* persistence
* transfer endpoints

Verify:

* contract negotiation works
* transfer process works

## Phase 4 – Build Dataspace Adapter

Implement:

* inbox
* outbox
* EDC client
* message storage
* transfer monitoring
* acknowledgement handling

Verify:

* messages can be submitted
* messages can be received

## Phase 5 – End-to-End Validation

Execute:

```text
Agent A
 → Adapter A
 → EDC A
 → EDC B
 → Adapter B
 → Agent B

Agent B
 → Adapter B
 → EDC B
 → EDC A
 → Adapter A
 → Agent A
```

Validate:

* request delivery
* response delivery
* message tracking
* conversation correlation
* audit logs

---

# 13. Deliverables

* Local EDC deployment
* Dataspace Adapter service
* Message schema
* Inbox/Outbox implementation
* PostgreSQL configuration
* Object storage configuration
* Example request flow
* Example response flow
* Architecture documentation
* Local deployment guide

---

# 14. Definition of Done

The MVP is complete when:

* Two participants are running locally.
* Both participants expose inbox and outbox functionality.
* Agent A can send a message to Agent B.
* Agent B receives the message through its inbox.
* Agent B can send a response.
* Agent A receives the response through its inbox.
* Communication occurs exclusively through EDC.
* No direct participant-specific API integration exists.
* The same pattern can be reused for additional participants without changing the communication architecture.
