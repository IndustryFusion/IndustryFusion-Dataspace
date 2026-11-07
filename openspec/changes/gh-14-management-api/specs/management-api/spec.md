## ADDED Requirements

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

`POST /api/participants` SHALL provision a hosted participant in this order: the adapter and connector databases; the Keycloak role, client, claim mapper and role assignment; the Secret, ConfigMap, Deployments and Services in the participants namespace; the registry entry. `adapter_url` and `dsp_url` SHALL come from the participant id, using the slug `sha256(participant_id)[:8]`.

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
- **WHEN** a hosted participant is registered with `externally_reachable` true
- **THEN** its `peer_notify_url` is the gateway's peer route for it, and otherwise it is `null`

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

`POST /api/demo` SHALL create the participants named in `DEMO_PARTICIPANTS` through the same steps.

#### Scenario: Creating them
- **WHEN** an administrator calls `POST /api/demo`
- **THEN** the answer lists a record with credentials for each

#### Scenario: Calling it again
- **WHEN** it is called again
- **THEN** the answer lists the same participants with the same credentials

#### Scenario: None configured
- **WHEN** `DEMO_PARTICIPANTS` is empty
- **THEN** the answer is an empty list

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

`GET /api/policy?fo=&mb=` SHALL show capability access for a factory owner and a machine builder in both directions.

#### Scenario: A hosted pair
- **WHEN** it is called for two hosted participants without a token
- **THEN** each capability appears with its provider, consumer, status and source

#### Scenario: An external side without a token
- **WHEN** either side is external and the call has no admin token
- **THEN** the answer is `401`

#### Scenario: An external side with an admin token
- **WHEN** either side is external and the call has an admin token
- **THEN** the hosted side's capabilities are shown, and the external side is listed under `unavailable`

#### Scenario: A wrong pair
- **WHEN** a side is unregistered, or the two aren't a factory owner and a machine builder
- **THEN** the answer is `404` or `422`

### Requirement: Health

`GET /api/health` SHALL report each component without a token.

#### Scenario: All healthy
- **WHEN** every component answers
- **THEN** the answer is `200`, with status `ok` for each

#### Scenario: A component is down
- **WHEN** a component doesn't answer
- **THEN** the answer is still `200`, that component has a status other than `ok` with a detail message, and the detail holds no credentials
