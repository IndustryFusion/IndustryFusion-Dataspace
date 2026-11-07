# Spec Delta

## Purpose

Defines how a participant running its own adapter and connector exchanges messages, files and capability requests with hosted participants.

## ADDED Requirements

### Requirement: DSP gateway routes
The DSP gateway SHALL map `/{slug}/api/v1/dsp/{path}` to port 8082 and `/{slug}/api/v1/public/{path}` to port 8084 of `connector-{slug}` in `PARTICIPANTS_NAMESPACE`, with no authentication of its own, and SHALL answer `/health`.

#### Scenario: A DSP call
- **WHEN** a request arrives on a slug's DSP path
- **THEN** that connector's DSP port gets the method, path, query, headers and body, and its answer is returned

#### Scenario: A public call
- **WHEN** a request arrives on a slug's public path
- **THEN** that connector's public port gets it

#### Scenario: Not a slug
- **WHEN** the slug isn't eight hexadecimal characters
- **THEN** the answer is not found, and nothing is forwarded

#### Scenario: Leaving the prefix
- **WHEN** a path holds a `..` segment, written plainly or encoded
- **THEN** the answer is not found, and nothing is forwarded

#### Scenario: Other ports
- **WHEN** a request names anything other than the two prefixes
- **THEN** the answer is not found, and no control or management port can be reached

#### Scenario: A connector that doesn't answer
- **WHEN** the connector can't be reached
- **THEN** the answer is service unavailable

### Requirement: Optional Ingress for the DSP gateway
The Helm chart SHALL offer an Ingress for the DSP gateway, off by default.

#### Scenario: Off
- **WHEN** it isn't enabled
- **THEN** no Ingress for the DSP gateway is rendered

#### Scenario: On
- **WHEN** it is enabled with a host
- **THEN** an Ingress routes that host to the DSP gateway's Service

### Requirement: Addresses of a reachable hosted participant
A hosted participant with `externally_reachable` SHALL announce addresses that work from outside the cluster: `peer_notify_url` through the gateway's peer route, and `dsp_url`, the adapter's advertised DSP address and the connector's callback and public addresses through the DSP gateway. Its `adapter_url` SHALL stay the adapter's real address.

#### Scenario: Registering reachable
- **WHEN** a hosted participant is registered with `externally_reachable` true
- **THEN** its record has the peer route as `peer_notify_url`, the DSP gateway's form as `dsp_url`, and the adapter's real address as `adapter_url`

#### Scenario: Not reachable
- **WHEN** a hosted participant is registered without it
- **THEN** its record has `peer_notify_url` null and the connector's real address as `dsp_url`, and its connector announces that address

#### Scenario: Changing it
- **WHEN** a participant is registered again with a different `externally_reachable`
- **THEN** its adapter and connector run with the new addresses

#### Scenario: Peer address not configured
- **WHEN** a hosted participant asks for `externally_reachable`, and the service has no public address for the gateway or the DSP gateway
- **THEN** the answer is `422`, and nothing is changed

### Requirement: Content reaches a reachable hosted adapter through the peer route
A hosted adapter with a peer address SHALL name it as the destination for content, with a transfer token valid for that one message, and SHALL refuse a wrong token.

#### Scenario: Destination
- **WHEN** a hosted adapter with a peer address starts a transfer
- **THEN** the destination is the peer route for this message, with the token in a header

#### Scenario: No peer address
- **WHEN** an adapter has no peer address
- **THEN** the destination is its own address

#### Scenario: A wrong token
- **WHEN** content arrives with a token that doesn't match, or that belongs to another message
- **THEN** the answer is unauthorized, and the message doesn't change

### Requirement: Capability calls use the peer address
An adapter SHALL make capability calls to a provider's `peer_notify_url` where it is set, and otherwise to its `adapter_url`.

#### Scenario: Provider with a peer address
- **WHEN** the provider has `peer_notify_url`
- **THEN** the call goes there

#### Scenario: Provider with only a peer address
- **WHEN** the provider has `peer_notify_url` and no `adapter_url`
- **THEN** the call succeeds, where it gave `503` before

#### Scenario: Provider with neither
- **WHEN** the provider has neither
- **THEN** the answer is `503`

### Requirement: Self-hosted demo
Manifests and scripts SHALL deploy and remove two self-hosted participants, each in its own namespace with its own PostgreSQL, S3 storage, adapter and connector, and a NetworkPolicy limiting traffic to the public routes, with `REGISTRY_URL` at the management API's read routes.

#### Scenario: Deploying
- **WHEN** the deploy script runs against a local environment
- **THEN** both participants run, and are registered as not hosted

#### Scenario: Removing
- **WHEN** the undeploy script runs
- **THEN** their namespaces and registrations are gone, and hosted participants are untouched

#### Scenario: The policy is active
- **WHEN** a pod in a demo namespace tries a hosted adapter, a hosted connector, the registry or the shared PostgreSQL
- **THEN** the connection fails, and the gateway, the DSP gateway, the management API and Keycloak can be reached

#### Scenario: Ports closed from outside
- **WHEN** a hosted pod tries a demo connector's management or control port
- **THEN** the connection fails

### Requirement: Exchange between external and hosted participants
With the NetworkPolicy active, messages, files and capability requests SHALL pass in both directions between an external and a hosted participant.

#### Scenario: Message from external to hosted
- **WHEN** an external agent sends a message through its own adapter
- **THEN** the hosted agent reads it through the gateway

#### Scenario: Message from hosted to external
- **WHEN** a hosted agent sends a message through the gateway
- **THEN** the external agent reads it from its own adapter

#### Scenario: Files in both directions
- **WHEN** either side sends files
- **THEN** the other downloads the same bytes

#### Scenario: Capability request to a hosted provider
- **WHEN** an external agent asks a hosted provider for access, and the provider approves
- **THEN** the external agent's access check shows `approved`

#### Scenario: Capability request to an external provider
- **WHEN** a hosted agent asks an external provider for access, and the provider approves
- **THEN** the hosted agent's access check shows `approved`

#### Scenario: Crossing steps
- **WHEN** both sides send `close` at the same time
- **THEN** both settle on the lower id's outcome, as `protocol.md` describes

### Requirement: Hosted-only installations
Hosted participants SHALL exchange messages and files with no use of the DSP gateway when none is `externally_reachable`.

#### Scenario: DSP gateway stopped
- **WHEN** the DSP gateway isn't running, and two hosted participants that aren't reachable exchange a message and a file
- **THEN** both arrive

### Requirement: Contract suite covers external flows
The contract suite SHALL run the external participants' flows against a deployment that has external participants.

#### Scenario: With the demo
- **WHEN** the suite runs with the demo up
- **THEN** the flows run, and none is listed as not run

#### Scenario: Without it
- **WHEN** the suite runs with no external participant available
- **THEN** the flows are listed as not run, saying how to bring them up

#### Scenario: A failure in a flow
- **WHEN** an external flow's answer is wrong
- **THEN** the run fails

### Requirement: Documents state the external exposure
`management-api.md` SHALL cover onboarding an external participant, and `keycloak.md` SHALL state what a peer can do with the token it receives from an adapter.

#### Scenario: Onboarding
- **WHEN** an operator reads `management-api.md`
- **THEN** it says what to register, what the participant runs, which addresses its adapter uses, and what registering it trusts it with

#### Scenario: Exposure
- **WHEN** a reader follows `keycloak.md` for an external participant
- **THEN** it says that a peer holding a sender's token can use it at the public gateway as the sender, until it expires, and what that reaches
