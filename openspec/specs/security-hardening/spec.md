# security-hardening Specification

## Purpose
Closes the known gaps between participants, and between the hub's components.

## Requirements

### Requirement: Internal routes need a token
`GET /internal/payload/{id}` and `POST /internal/inbox-receive/{id}` SHALL need a token good for that route and that message, which the adapter gives to the connector that has to call it.

#### Scenario: No credentials
- **WHEN** a pod without a token reads a payload or pushes content
- **THEN** the answer is unauthorized, nothing is returned, and the message doesn't change

#### Scenario: Another message's token
- **WHEN** a call has a token made for another message
- **THEN** the answer is unauthorized

#### Scenario: The other route's token
- **WHEN** a call has the token made for the other route, for the same message
- **THEN** the answer is unauthorized

#### Scenario: A real transfer
- **WHEN** two connectors carry a message
- **THEN** it arrives with its own tokens, as files and as JSON

### Requirement: NetworkPolicies
The deployment SHALL ship NetworkPolicies, so that adapters, connectors and the registry are reachable only from the components that need them.

#### Scenario: A pod elsewhere
- **WHEN** a pod in another namespace tries an adapter, a connector or the registry
- **THEN** the connection fails

#### Scenario: A connector's management port
- **WHEN** a connector tries another connector's management port
- **THEN** the connection fails

#### Scenario: The DSP gateway
- **WHEN** the DSP gateway calls a connector's DSP port
- **THEN** the connection succeeds, and it can't reach the management or control ports

#### Scenario: The registry
- **WHEN** the gateway, management or an adapter calls the registry
- **THEN** it answers

#### Scenario: Optional
- **WHEN** `networkPolicy.enabled` is false
- **THEN** the chart renders none

### Requirement: A database user per participant
Each hosted participant SHALL have its own PostgreSQL user, owning its own databases, which no other participant's user can connect to.

#### Scenario: Its own database
- **WHEN** a participant's adapter and connector start
- **THEN** they use its own user

#### Scenario: Another's database
- **WHEN** one participant's user connects to another's database
- **THEN** it is refused

#### Scenario: Registering again
- **WHEN** a participant is registered again
- **THEN** it keeps its user and password

#### Scenario: Removal
- **WHEN** a participant is removed
- **THEN** its user is gone

#### Scenario: A failed registration
- **WHEN** a later step of a registration fails
- **THEN** a user it made is removed

### Requirement: An S3 identity per participant
With the storage's IAM address configured, each hosted participant SHALL have its own S3 identity, limited to its own bucket for what it can read, write and list directly, and other identities SHALL be kept. Without one, participants SHALL share the configured identity, and the service SHALL log that.

#### Scenario: Its own bucket
- **WHEN** a participant's adapter stores and reads content
- **THEN** it does so with its own identity

#### Scenario: Another's bucket
- **WHEN** one participant's identity directly reads, writes or lists another's bucket
- **THEN** it is refused

#### Scenario: A copy from another's bucket, a known gap
- **WHEN** one participant's identity copies an object it can name from another's bucket into its own, with `CopyObject` or `UploadPartCopy`
- **THEN** this version of the storage doesn't refuse it, and the security check reports that as a known gap, not as a pass. The criterion is only partly met until a maintainer decides

#### Scenario: Others in the list
- **WHEN** an identity is added or removed
- **THEN** every other entry stays, and the administrator's still works

#### Scenario: At the same time
- **WHEN** several participants register at once
- **THEN** every one has its identity

#### Scenario: Removal
- **WHEN** a participant is removed
- **THEN** its identity no longer works

#### Scenario: No IAM address
- **WHEN** no IAM address is configured
- **THEN** participants use the configured identity, and the list isn't touched

### Requirement: An internal key per participant
Each hosted participant SHALL have its own internal key, which only management and that adapter hold, replacing the shared key.

#### Scenario: Its own key
- **WHEN** management calls an adapter's internal capability routes
- **THEN** it uses that participant's key

#### Scenario: Another's key
- **WHEN** one participant's key is given to another's adapter
- **THEN** the answer is unauthorized

#### Scenario: Registering again
- **WHEN** a participant is registered again
- **THEN** it keeps its key

### Requirement: Connector identity
A connector SHALL present a token from its participant's Keycloak client on the DSP, and SHALL check the signature, issuer, expiry, `participant_id` claim and participant role of the one it receives, using that identity as its counterparty.

#### Scenario: Real participants
- **WHEN** two participants' connectors exchange a message
- **THEN** it completes, with each knowing the other by its participant id

#### Scenario: No token or a mock token
- **WHEN** a DSP call has no token, or the mock identity's
- **THEN** it is refused

#### Scenario: Another signer
- **WHEN** a DSP call has a token signed by another key or issuer
- **THEN** it is refused

#### Scenario: No participant role
- **WHEN** a DSP call has a token from the realm that isn't a participant's
- **THEN** it is refused

#### Scenario: Claiming to be someone else
- **WHEN** a consumer negotiates with a participant at a connector that belongs to another participant
- **THEN** the negotiation doesn't complete, and the message ends with status `error`

### Requirement: Public management reads
Unauthenticated management reads SHALL expose only what `management-api.md` documents as public.

#### Scenario: Capabilities
- **WHEN** `GET /api/participants/{id}/capabilities` or `GET /api/policy` has no admin token
- **THEN** the answer is unauthorized

#### Scenario: A hosted participant in a public read
- **WHEN** a participant read has no admin token
- **THEN** a hosted participant has `adapter_url` null, and `dsp_url` null unless it is reachable

#### Scenario: An external participant in a public read
- **WHEN** a participant read has no admin token
- **THEN** an external participant keeps its addresses

#### Scenario: With an admin token
- **WHEN** a participant read has an admin token
- **THEN** the whole record is returned

#### Scenario: External adapters
- **WHEN** an external adapter uses these reads as its registry
- **THEN** it finds each peer's address

### Requirement: Management Ingress needs an allowlist
The chart SHALL refuse to render a management Ingress without an allowlist.

#### Scenario: No allowlist
- **WHEN** the Ingress is enabled without `ingress.management.allowFrom`
- **THEN** rendering fails, naming the setting

#### Scenario: An allowlist
- **WHEN** it is given
- **THEN** the Ingress carries it

### Requirement: Everything still works with this active
The end-to-end message and external participant tests SHALL pass with all of the above active.

#### Scenario: Contract suite
- **WHEN** the contract suite runs on a deployment with policies, tokens, identities and per-participant credentials active
- **THEN** it passes, with the external flows run
