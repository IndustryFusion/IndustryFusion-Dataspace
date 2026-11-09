# Spec Delta

## Purpose

The local cluster deploys the services with the same charts and environment as any other installation.

## ADDED Requirements

### Requirement: Services deployed with the charts

`scripts/local-env.sh services` SHALL build and load the images, then deploy the `default` environment with helmfile, passing the local hosts and settings in a generated values file and the credentials in a generated secrets file, both in `.local/` and not committed. The local images SHALL keep the names `dataspace/<name>:dev`.

#### Scenario: Deploying the services
- **WHEN** a contributor runs `scripts/local-env.sh up` and then `scripts/local-env.sh services`
- **THEN** the five releases are installed in `dataspace`, every pod reaches ready, and the local end-to-end checks pass

#### Scenario: Generated files
- **WHEN** `services` has run
- **THEN** `.local/helm-values.yaml` holds the local hosts and settings, `.local/helm-secrets.yaml` holds the credentials, and git ignores both

#### Scenario: Repeating it
- **WHEN** `services` is run again after a code change
- **THEN** the new images are loaded and the services restart with them

#### Scenario: Only its own cluster
- **WHEN** the contributor's shell points at another cluster
- **THEN** `services` deploys only to the local cluster, through its own kubeconfig
