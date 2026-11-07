## ADDED Requirements

### Requirement: Installing from the documented procedure

A fresh cluster with the documented prerequisites SHALL install from the procedure in `deploy/README.md`, with services in namespace `dataspace`.

#### Scenario: A fresh install
- **WHEN** an operator follows the procedure on a new cluster that has the dependencies and images
- **THEN** every pod reaches ready, with no manual step beyond the documented ones

#### Scenario: Repeating the procedure
- **WHEN** the procedure is run again without changes
- **THEN** it succeeds, and no pod restarts

#### Scenario: A release order that lets pods start
- **WHEN** releases are installed in order
- **THEN** no pod waits on something a later release creates

#### Scenario: A missing secret
- **WHEN** a required value is missing from the secrets file
- **THEN** the install stops with a message naming it

### Requirement: Layered values and secrets

Configuration SHALL come from common values, then an environment's values, then a secrets file of which only an example is committed.

#### Scenario: An environment overrides a common value
- **WHEN** an environment file sets a value that the common file also sets
- **THEN** the environment's value is used

#### Scenario: Credentials
- **WHEN** the chart is rendered with real values
- **THEN** credentials appear only in Secrets, and pods read them through secret references

#### Scenario: Nothing private is committed
- **WHEN** the committed files are inspected
- **THEN** they hold no credentials and no environment-specific hosts, and the secrets file is ignored by git

### Requirement: Dependencies by configuration

PostgreSQL, S3 storage and Keycloak SHALL be external, by default in namespace `iff`, and reached only through configured addresses.

#### Scenario: Default addresses
- **WHEN** no address is overridden
- **THEN** services use `acid-cluster.iff`, `seaweedfs.iff` and `keycloak-service.iff`

#### Scenario: No fixed cluster IPs
- **WHEN** the chart is rendered
- **THEN** no object holds an IP address

#### Scenario: A different Keycloak
- **WHEN** `dependencies.keycloak.url` is changed
- **THEN** every service, and each participant created later, uses it for both issuer and keys

### Requirement: Ingress

The chart SHALL offer an Ingress for the gateway and one for management, with body sizes that agree with `MAX_UPLOAD_BYTES` and `MAX_JSON_BYTES`, and an optional cert-manager setting.

#### Scenario: Body sizes come from the limits
- **WHEN** the limits are changed
- **THEN** the services' variables and the Ingress annotations change together

#### Scenario: Limits that make no sense
- **WHEN** the upload limit is below the JSON limit
- **THEN** rendering fails

#### Scenario: An upload at the limit
- **WHEN** an agent uploads a request of exactly `MAX_UPLOAD_BYTES` through the Ingress
- **THEN** it is accepted and delivered, with the same bytes

#### Scenario: An upload over the limit
- **WHEN** an agent uploads one byte more through the Ingress
- **THEN** the answer is `413`

#### Scenario: A JSON body over its limit
- **WHEN** a body over `MAX_JSON_BYTES` is sent to another gateway route through the Ingress
- **THEN** the answer is `413` with the contract's body

#### Scenario: A registration through the Ingress
- **WHEN** a registration waits for its pods
- **THEN** the Ingress doesn't time it out within the configured wait

#### Scenario: Certificates
- **WHEN** TLS is enabled with a cluster issuer
- **THEN** each Ingress has the cert-manager annotation and a TLS section for its host

#### Scenario: Off by default
- **WHEN** the Ingress isn't enabled
- **THEN** no Ingress object is rendered

### Requirement: RBAC for management

The management API SHALL have only the rights provisioning needs, only in the participants namespace.

#### Scenario: Onboarding a participant
- **WHEN** a participant is registered on an install
- **THEN** its objects are created in `dataspace-participants`, and it exchanges messages with another

#### Scenario: Rights outside the namespace
- **WHEN** management's service account tries to act in another namespace
- **THEN** it is refused

#### Scenario: Other services
- **WHEN** another service's pod starts
- **THEN** it has no service account token mounted

### Requirement: Uninstalling

The documented removal SHALL leave no resources in the two namespaces.

#### Scenario: Uninstalling with participants
- **WHEN** the operator runs the documented removal, with a participant still there
- **THEN** both namespaces are gone with everything in them, and the script has said what stays outside them

#### Scenario: Installing again
- **WHEN** the procedure is followed again after removal
- **THEN** it succeeds
