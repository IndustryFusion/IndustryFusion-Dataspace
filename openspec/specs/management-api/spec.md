# management-api Specification

## Purpose
Lets an administrator register, list and remove participants, and provisions what a hosted participant needs to run.

## Requirements

### Requirement: Admin tokens and admin routes

The service SHALL give an administrator a token from Keycloak for client credentials, and SHALL require on each admin route a token with a valid signature, the configured issuer and the realm role `dataspace-admin`.

#### Scenario: Getting a token
- **WHEN** `POST /api/admin/token` is called with valid client credentials
- **THEN** the answer is Keycloak's token response

#### Scenario: Wrong client credentials
- **WHEN** `POST /api/admin/token` is called with a wrong secret
- **THEN** the answer is `401` with `{"detail": ...}`

#### Scenario: Keycloak is unreachable
- **WHEN** `POST /api/admin/token` is called and Keycloak does not answer
- **THEN** the answer is `503`

#### Scenario: No token on an admin route
- **WHEN** any admin route is called without a token, or with one that has a bad signature, a wrong issuer or has expired
- **THEN** the answer is `401`

#### Scenario: A token without the role
- **WHEN** any admin route is called with a valid token that lacks `dataspace-admin`
- **THEN** the answer is `403`, and nothing is changed

#### Scenario: The caller's token is used
- **WHEN** an admin route calls the Keycloak Admin API
- **THEN** it uses the caller's token, and the service keeps no credentials of its own for Keycloak

### Requirement: Registering a hosted participant

`POST /api/participants` SHALL provision a hosted participant in this order: the adapter and connector databases; the Keycloak role, client, claim mapper and role assignment; the Secret, ConfigMap, Deployments and Services in the participants namespace; the registry entry. `adapter_url` and `dsp_url` SHALL come from the participant id, using the slug `sha256(participant_id)[:8]`. A hosted participant registered without `externally_reachable` SHALL be registered as reachable.

#### Scenario: A new hosted participant
- **WHEN** an administrator registers a new hosted participant
- **THEN** each object exists, the registry entry is written last and only when its pods are available, and the answer is the participant record with `client_id` and `client_secret`

#### Scenario: The participant can be used
- **WHEN** two registered participants of compatible types get tokens with their credentials
- **THEN** they exchange a message through the gateway

#### Scenario: Other participants need no change
- **WHEN** a participant is added
- **THEN** existing participants' Kubernetes objects are unchanged, and they find the new one through the registry

#### Scenario: Addresses given for a hosted participant
- **WHEN** a hosted registration gives `adapter_url` or `dsp_url`
- **THEN** the addresses derived from the id are stored instead

#### Scenario: Reaching a hosted participant from outside
- **WHEN** a hosted participant is registered with `externally_reachable` true, and both peer addresses are configured
- **THEN** its `peer_notify_url` is the gateway's peer route for it, and when it is registered with `externally_reachable` false, `peer_notify_url` is `null`

#### Scenario: Reachable by default
- **WHEN** a hosted participant is registered without `externally_reachable`, and both peer addresses are configured
- **THEN** its record has `externally_reachable` true and the gateway's peer route as `peer_notify_url`

#### Scenario: Registered again without the flag
- **WHEN** an existing hosted participant that isn't reachable is registered again without `externally_reachable`, and both peer addresses are configured
- **THEN** it becomes reachable, and its credentials are unchanged

#### Scenario: An external participant without the flag
- **WHEN** an external participant is registered without `externally_reachable`
- **THEN** its record has `externally_reachable` false

#### Scenario: An invalid request
- **WHEN** the request has an unknown `participant_type`, or a `participant_id` that doesn't start with a letter or digit, holds anything but ASCII letters, digits, `.`, `_`, `:` and `-`, is longer than 200 characters, or is `compatible`
- **THEN** the answer is `422`, and nothing is created

### Requirement: Registering an external participant

An external participant SHALL get only the Keycloak and registry steps.

#### Scenario: A new external participant
- **WHEN** an administrator registers a participant with `hosted` false, `adapter_url` and `dsp_url`
- **THEN** its client, role and registry entry exist, no database or Kubernetes object is created, and the answer has its credentials

#### Scenario: Addresses are missing
- **WHEN** an external registration omits `adapter_url` or `dsp_url`
- **THEN** the answer is `422`, and nothing is created

### Requirement: Failed provisioning is undone

A failure at any step SHALL undo the steps this request completed, and SHALL NOT remove anything that existed before the request.

#### Scenario: A failure at each step
- **WHEN** creating a database, any Keycloak object, any Kubernetes object, waiting for availability, or writing the registry entry fails for a new participant
- **THEN** the answer is an error, and no database, Keycloak object, Kubernetes object or registry entry of that participant remains

#### Scenario: A failed re-registration
- **WHEN** registering an existing participant again fails at any step
- **THEN** its databases, client, secrets and registry entry remain, and any Kubernetes object the request changed is put back

#### Scenario: A token that expires during the wait
- **WHEN** the caller's token expires while a registration waits for pods, and the wait fails
- **THEN** the service's own credential undoes the Keycloak objects, and none of them remains

#### Scenario: One deadline
- **WHEN** a registration's pods never become available
- **THEN** the answer comes within `PROVISION_READY_SECONDS` plus at most 50 seconds for the undo, naming anything that wasn't undone

#### Scenario: An undo that fails
- **WHEN** undoing a step fails too
- **THEN** the error says that something remains, and `DELETE` removes it

### Requirement: Repeating a registration

Registering an existing participant again SHALL update it, keeping its credentials.

#### Scenario: Setting reachability
- **WHEN** an existing participant is registered again with a different `externally_reachable`
- **THEN** the registry entry is updated, and its client secret and connector API key are unchanged

#### Scenario: A half-finished client
- **WHEN** a client made by an earlier failed registration lacks its claim mapper, service account setting or role assignment
- **THEN** registering completes it, and tokens from it carry the claim and role

#### Scenario: Changing hosting or type
- **WHEN** a registration changes `hosted` or `participant_type` of an existing participant
- **THEN** the answer is `409`, and nothing is changed

#### Scenario: A client that is not a participant's
- **WHEN** the id equals a client in the realm that this service did not create
- **THEN** the answer is `409`, and that client is unchanged

#### Scenario: A slug held by another participant
- **WHEN** a new id has the same slug as an existing participant
- **THEN** the answer is `409`, and the existing objects are unchanged

#### Scenario: Concurrent registrations
- **WHEN** two requests register the same participant at once, and one of them fails
- **THEN** the participant the other one made remains whole

### Requirement: Demo participants

`POST /api/demo` SHALL create the participants named in `DEMO_PARTICIPANTS` through the same steps. `DEMO_PARTICIPANTS` SHALL accept a JSON list of participants or `<id>=<type>` entries separated by commas. Unset or empty, it SHALL mean the three demo companies' IFRIC URNs: one factory owner and two machine builders. A value that can't be used SHALL stop the service at start.

#### Scenario: Creating them
- **WHEN** an administrator calls `POST /api/demo`
- **THEN** the answer lists a record with credentials for each

#### Scenario: Calling it again
- **WHEN** it is called again
- **THEN** the answer lists the same participants with the same credentials

#### Scenario: A fresh installation
- **WHEN** an administrator calls `POST /api/demo` on an installation that doesn't set `DEMO_PARTICIPANTS`
- **THEN** the three default participants are created as hosted and reachable: `urn:ifric:ifx-eur-com-own-42ced491-b35d-41f7-9949-fcbb5fa4dcd9` as a factory owner, and `urn:ifric:ifx-eur-com-nap-37eb511d-49c0-4700-ba17-dee8248f0fb5` and `urn:ifric:ifx-eur-com-nap-2150a82e-ccbb-47d7-be5a-8059906bc253` as machine builders, and the factory owner exchanges a message with each machine builder through the gateway

#### Scenario: The JSON form
- **WHEN** `DEMO_PARTICIPANTS` is a JSON list of objects with `participant_id`, `participant_type` and optionally `externally_reachable`
- **THEN** `POST /api/demo` creates those participants, each with the reachability given or by default reachable

#### Scenario: The comma-separated form
- **WHEN** `DEMO_PARTICIPANTS` is `<id>=<type>` entries separated by commas
- **THEN** `POST /api/demo` creates those participants

#### Scenario: None configured
- **WHEN** `DEMO_PARTICIPANTS` is `[]`
- **THEN** the answer is an empty list

#### Scenario: A value that can't be used
- **WHEN** `DEMO_PARTICIPANTS` is JSON that isn't a list of such objects, an entry has an unknown key, an unknown type or an id that registration would refuse, an id appears twice, or a comma-separated entry has no `=`
- **THEN** the service stops at start with a non-zero status, and its log names `DEMO_PARTICIPANTS` and the problem

### Requirement: Removing a participant

`DELETE /api/participants/{id}` SHALL remove the registry entry, the Keycloak client and role, and for a hosted participant the pods, every other Kubernetes object, the databases and the bucket.

#### Scenario: Removing a hosted participant
- **WHEN** an administrator deletes a hosted participant
- **THEN** the answer is `204`, and no object of it remains in the registry, Keycloak, the participants namespace, PostgreSQL or storage

#### Scenario: Removing an external participant
- **WHEN** an administrator deletes an external participant
- **THEN** its registry entry, client and role are removed

#### Scenario: Registration followed by removal leaves nothing
- **WHEN** two participants are registered, exchange a message and are deleted
- **THEN** the participants namespace is empty of their objects, and their databases are gone

#### Scenario: An unknown participant
- **WHEN** nothing is found for the id
- **THEN** the answer is `404`

#### Scenario: A step fails
- **WHEN** one removal step fails
- **THEN** the other steps still run, the answer is `502` naming the step, and repeating the call finishes the removal

#### Scenario: A client that is not a participant's
- **WHEN** the id equals a client this service did not create
- **THEN** that client is not removed

### Requirement: Participant reads and credentials

The read routes SHALL return registry records without a token. `GET /api/participants/{id}/credentials` SHALL require `dataspace-admin`.

#### Scenario: Reads
- **WHEN** `GET /api/participants`, `/api/participants/{id}` or `/api/participants/compatible/{id}` is called without a token
- **THEN** the answer holds the records with the published fields, or `404` for an unknown id

#### Scenario: Registry unavailable
- **WHEN** the registry does not answer
- **THEN** the answer is `503`

#### Scenario: Credentials
- **WHEN** an administrator reads the credentials of a participant
- **THEN** the answer has `client_id` and `client_secret`

#### Scenario: Credentials of something else
- **WHEN** the id is not a registered participant, or its client was not created by this service
- **THEN** the answer is `404`

### Requirement: Capability administration

The capability routes SHALL act on a hosted participant's adapter with the internal key, which SHALL never be sent to an external participant's address.

#### Scenario: Reading capabilities
- **WHEN** `GET /api/participants/{id}/capabilities` is called without a token
- **THEN** the answer holds the capabilities with their default policy, and the approvals

#### Scenario: Changing a default
- **WHEN** an administrator patches a capability's `default_policy`
- **THEN** later access checks use it

#### Scenario: Recording a decision
- **WHEN** an administrator posts an approval for a compatible, registered consumer
- **THEN** the consumer's access check shows it

#### Scenario: A consumer not allowed
- **WHEN** the consumer is unregistered or of an incompatible role
- **THEN** the answer is `404` or `403`

#### Scenario: Resetting
- **WHEN** an administrator patches an approval with `reset`
- **THEN** the consumer's access goes back to the default

#### Scenario: Deciding a resolved request
- **WHEN** an administrator patches an approval that is already resolved with `approve` or `deny`
- **THEN** the answer is `409`

#### Scenario: An external participant
- **WHEN** a capability route names an external participant
- **THEN** the answer is `409`, and no call goes to its address

#### Scenario: An adapter that does not answer
- **WHEN** the adapter can't be reached
- **THEN** the answer is `503`

#### Scenario: An admin check
- **WHEN** a patch or post on these routes has no admin token
- **THEN** the answer is `401`, and the adapter is not called

### Requirement: Policy view

`GET /api/policy?fo=&mb=` SHALL show capability access for a factory owner and a machine builder in both directions, to an administrator. Each entry SHALL have its provider, consumer, data classification, status, source and the conversation its decision was made in. An external provider's capabilities SHALL be read through the gateway's peer route with a token of the consumer, and where they can't be read, the provider SHALL be listed under `unavailable` with a reason.

#### Scenario: A hosted pair
- **WHEN** an administrator calls it for two hosted participants
- **THEN** each capability appears with its provider, consumer, `data_classification`, status, source and `conversation_id`

#### Scenario: The conversation of a decision
- **WHEN** a consumer's request for a capability named a conversation, and the provider decided it
- **THEN** that entry's `conversation_id` is the conversation, and an entry without a decision has `conversation_id` null

#### Scenario: Without an admin token
- **WHEN** it is called without an admin token, for any pair
- **THEN** the answer is `401`, and nothing is read from an adapter

#### Scenario: An external side with an admin token
- **WHEN** an administrator calls it for a pair with an external side whose adapter is reachable through the gateway
- **THEN** the external side's capabilities appear with the hosted side's, with the consumer's status for each, read through the gateway's peer route with the consumer's token, and nothing goes to the external adapter with the internal key

#### Scenario: An external side without a token
- **WHEN** either side is external and the call has no admin token
- **THEN** the answer is `401`, and no token is asked for

#### Scenario: Two external sides
- **WHEN** both sides are external, and both adapters are reachable through the gateway
- **THEN** both directions appear

#### Scenario: An external provider that can't be read
- **WHEN** the external adapter can't be reached, refuses the token, or gives an answer of the wrong shape, or the consumer has no client
- **THEN** the answer is `200`, the hosted side is shown, the external side is listed in `unavailable`, and `unavailable_reasons` gives the reason for it

#### Scenario: Nothing secret in the answer
- **WHEN** an external side is read, or fails to be read
- **THEN** the answer and the log hold no client secret and no token

#### Scenario: A wrong pair
- **WHEN** a side is unregistered, or the two aren't a factory owner and a machine builder
- **THEN** the answer is `404` or `422`

### Requirement: Health

`GET /api/health` SHALL report each component without a token, with the time of the check and each component's response time.

#### Scenario: All healthy
- **WHEN** every component answers
- **THEN** the answer is `200`, with status `ok` for each

#### Scenario: A component is down
- **WHEN** a component doesn't answer
- **THEN** the answer is still `200`, that component has a status other than `ok` with a detail message, and the detail holds no credentials

#### Scenario: Timing
- **WHEN** the health is read
- **THEN** the answer has `checked_at`, and each configured component has `response_ms`, the whole milliseconds its probe took, including one that failed

#### Scenario: Not configured
- **WHEN** a component has no address configured
- **THEN** its status is `not configured`, and its `response_ms` is null

#### Scenario: A connector that doesn't answer
- **WHEN** the connector can't be reached
- **THEN** the answer is service unavailable

### Requirement: Reachability without peer addresses

A hosted participant that is to be reachable, by default or by asking, SHALL be registered as not reachable when `GATEWAY_PEER_URL` or `DSP_GATEWAY_PEER_URL` isn't configured, and the answer SHALL say so.

#### Scenario: Peer addresses missing
- **WHEN** a hosted participant is registered with `externally_reachable` true or without it, and a peer address isn't configured
- **THEN** the answer is a success, its record has `externally_reachable` false, `peer_notify_url` null and the connector's own `dsp_url`, and `warnings` says it isn't reachable from outside and names the missing setting

#### Scenario: The demo without peer addresses
- **WHEN** `POST /api/demo` is called and a peer address isn't configured
- **THEN** the participants are created as not reachable, and each record has the warning

#### Scenario: Reads have no warning
- **WHEN** such a participant is read afterwards
- **THEN** its record has `externally_reachable` false, and no `warnings`

#### Scenario: Nothing to warn about
- **WHEN** a participant is registered and nothing was changed from what was asked
- **THEN** the answer has `warnings` empty

### Requirement: Basic credentials are treated as no token
The service SHALL treat an `Authorization` header whose scheme isn't `Bearer` as no token: a read SHALL give the public view, and a change SHALL give `401`, as without a header. A `Bearer` token that is malformed, invalid or without `dataspace-admin` SHALL be refused as today.

#### Scenario: A read with basic credentials
- **WHEN** `GET /api/participants` or `GET /api/participants/{id}` is called with `Authorization: Basic …`
- **THEN** the answer is the public view, as without a token

#### Scenario: A change with basic credentials
- **WHEN** an admin route, such as `POST /api/participants`, is called with `Authorization: Basic …`
- **THEN** the answer is `401`, and nothing is changed

#### Scenario: A bearer token that isn't an admin's
- **WHEN** a read is called with a `Bearer` token that is invalid or lacks `dataspace-admin`
- **THEN** it is refused with `401` or `403`, as today
