# helm-deployment Specification

## Purpose
Installs the dataspace on Kubernetes with Helm, from a documented procedure, using the DigitalTwin stack's services or stand-ins chosen by configuration.

## Requirements

### Requirement: Installing from the documented procedure

A fresh cluster with the documented prerequisites SHALL install from the procedure in `helm/README.md`, with services in the namespace `NAMESPACE` names, `dataspace` by default.

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

Configuration SHALL come from `helm/common.yaml`, then `helm/environment/default.yaml`, then an optional values file `DATASPACE_VALUES_FILE` names, then `helm/environment/secrets.yaml` or the file `DATASPACE_SECRETS_FILE` names. `default` SHALL be the only environment. Only an example of the secrets file, listing every secret key, SHALL be committed.

#### Scenario: An environment overrides a common value
- **WHEN** `environment/default.yaml` sets a value that `common.yaml` also sets
- **THEN** the environment's value is used

#### Scenario: An extra values file
- **WHEN** `DATASPACE_VALUES_FILE` names a file that sets a value `environment/default.yaml` also sets
- **THEN** the extra file's value is used

#### Scenario: The only environment
- **WHEN** helmfile lists the environments
- **THEN** `default` is the only one, and `helmfile -e default template` renders every release

#### Scenario: Credentials
- **WHEN** the charts are rendered with real values
- **THEN** credentials appear only in Secrets, and pods read them through secret references

#### Scenario: Nothing private is committed
- **WHEN** the committed files are inspected
- **THEN** they hold no credentials and no environment-specific hosts, and `environment/secrets.yaml` is ignored by git

#### Scenario: Every secret key in the example
- **WHEN** `environment/secrets.yaml.example` is compared with the secret values the charts read
- **THEN** it lists every one of them

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

### Requirement: Layout

The deployment SHALL live in `helm/`, with `bootstrap.sh`, `helmfile.yaml.gotmpl`, `values.yaml.gotmpl`, `common.yaml`, `env.sh`, `README.md`, `environment/default.yaml`, `environment/secrets.yaml.example`, and the charts `common`, `registry`, `gateway`, `dsp-gateway` and `management` under `charts/`. `deploy/helm/` SHALL NOT exist. The charts SHALL read only the values `values.yaml.gotmpl` and the value files give them, never an environment file directly.

#### Scenario: The tree
- **WHEN** the repository is checked out
- **THEN** each of those files and charts exists, and `deploy/helm/` doesn't

#### Scenario: No old paths named
- **WHEN** the documents, scripts and CI are searched for `deploy/helm`
- **THEN** none names it, except archived changes

### Requirement: Environment script

`helm/env.sh` SHALL export `NAMESPACE`, `PARTICIPANTS_NAMESPACE`, `LOCAL_REGISTRY`, `MAIN_REPO`, `MAIN_VERSION`, `HELM_VERSION`, `HELMFILE_VERSION` and `HELM_DIFF_PLUGIN`, keeping a value already set in the shell, even an empty one. Defaults SHALL be `dataspace`, `dataspace-participants`, `k3d-iff.localhost:12345`, `dataspace` and `latest` for the first five. It SHALL hold no secret. Helmfile SHALL stop, naming the variable, if a required one is missing.

#### Scenario: Defaults
- **WHEN** `helm/env.sh` is sourced in a shell that sets none of the variables
- **THEN** each is exported with its default, and the rendered images are `k3d-iff.localhost:12345/dataspace/<name>:latest`

#### Scenario: A value set before
- **WHEN** `LOCAL_REGISTRY` is set, even to empty, before `env.sh` is sourced
- **THEN** it keeps that value

#### Scenario: Images follow the variables
- **WHEN** `LOCAL_REGISTRY`, `MAIN_REPO` or `MAIN_VERSION` is changed
- **THEN** the rendered images, the management API's `MAIN_*` settings and the names `scripts/build-images.sh` lists all change together

#### Scenario: Namespaces follow the variables
- **WHEN** `NAMESPACE` or `PARTICIPANTS_NAMESPACE` is changed
- **THEN** the releases, the in-cluster addresses, the participant RBAC and the network policies use the new namespaces

#### Scenario: Without env.sh
- **WHEN** helmfile runs in a shell where `env.sh` wasn't sourced
- **THEN** it stops, naming a missing variable, and renders nothing

#### Scenario: Pinned tools
- **WHEN** `helm/bootstrap.sh tools` runs
- **THEN** it installs helmfile `HELMFILE_VERSION` after checking its checksum and the helm-diff plugin `HELM_DIFF_PLUGIN`, and stops if Helm is older than `HELM_VERSION` or `HELMFILE_VERSION` has no known checksum

### Requirement: One chart per service

Each of `registry`, `gateway`, `dsp-gateway` and `management` SHALL have its own chart and release of that name, after a `common` release holding the Secret both `registry` and `management` read. Management's service account, RBAC and the participant network policies SHALL be in `management`, and the registry's network policy in `registry`. Each release SHALL need only earlier ones, in today's order.

#### Scenario: Releases and order
- **WHEN** helmfile lists the releases
- **THEN** they are `common`, `registry`, `gateway`, `dsp-gateway` and `management`, where `registry` and `dsp-gateway` need `common`, `gateway` needs `registry`, and `management` needs `registry`, `gateway` and `dsp-gateway`

#### Scenario: Objects in their charts
- **WHEN** each release is rendered
- **THEN** each object is in the release the requirement names, and no object is in two

#### Scenario: Charts lint
- **WHEN** each chart is linted with the environment's values
- **THEN** each passes

### Requirement: Same objects as before the move

The new layout SHALL render the same objects as the old one, apart from labels, with default settings and with the local cluster's settings. A script SHALL check this against a given git revision, and CI SHALL run it against the Pull Request's base.

#### Scenario: Default settings
- **WHEN** the old layout's `default` environment and the new one are rendered with the same image and namespace values and example secrets
- **THEN** the objects match by kind, namespace and name, and are equal apart from their `metadata.labels` and the `app.kubernetes.io/instance` label

#### Scenario: The local cluster's settings
- **WHEN** the old `local` environment and the new `default` with the local cluster's generated values file are rendered
- **THEN** the objects match in the same way

#### Scenario: A difference
- **WHEN** an object differs in any other field, or is missing or extra
- **THEN** the check fails, naming the object and the field

#### Scenario: Nothing to compare
- **WHEN** the given revision has no `deploy/helm`
- **THEN** the check says so and passes

### Requirement: Checked in CI

CI SHALL lint every chart, render the `default` environment with helmfile, check the values rules across charts, and run the layout check.

#### Scenario: A chart that fails
- **WHEN** a change makes a chart fail to lint or render
- **THEN** CI fails
