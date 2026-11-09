# Spec Delta

## Purpose

The build script reads the same image variables as the charts, from the shell, where `helm/env.sh` sets them. There is no config file.

## MODIFIED Requirements

### Requirement: Building and pushing the images

`scripts/build-images.sh` SHALL build `gateway`, `dsp-gateway`, `registry`, `management` with the UI built in, `adapter` and `connector`, and push each as `<LOCAL_REGISTRY>/<MAIN_REPO>/<name>:<MAIN_VERSION>`. It SHALL read `LOCAL_REGISTRY`, `MAIN_REPO` and `MAIN_VERSION` from the shell only, with defaults `k3d-iff.localhost:12345`, `dataspace` and `latest` when unset. If `REGISTRY`, `REPO` or `VERSION` is set, the script SHALL say that it reads the new names.

#### Scenario: No settings
- **WHEN** an operator runs `./scripts/build-images.sh` with none of the three variables set
- **THEN** all six images are built and pushed as `k3d-iff.localhost:12345/dataspace/<name>:latest`

#### Scenario: Chosen registry, repository and version
- **WHEN** an operator runs `LOCAL_REGISTRY=<host> MAIN_REPO=<repo> MAIN_VERSION=1.2.3 ./scripts/build-images.sh` against a local registry
- **THEN** the registry holds `<host>/<repo>/<name>:1.2.3` for all six

#### Scenario: After sourcing env.sh
- **WHEN** an operator runs `source helm/env.sh` and then the script
- **THEN** the images are named from the variables `env.sh` exported

#### Scenario: An old variable name
- **WHEN** `REGISTRY`, `REPO` or `VERSION` is set
- **THEN** the script prints that it reads `LOCAL_REGISTRY`, `MAIN_REPO` and `MAIN_VERSION` instead, and doesn't use the old value

#### Scenario: The management image has the UI
- **WHEN** the pushed `management` image is started
- **THEN** it serves the management UI

### Requirement: Names that match the chart

The names the script gives SHALL be those the charts render from the same `LOCAL_REGISTRY`, `MAIN_REPO` and `MAIN_VERSION`, including the participant images the management API names from them. An empty `LOCAL_REGISTRY` SHALL mean no prefix, as in the charts, and SHALL be refused for pushing. An empty `MAIN_REPO` or `MAIN_VERSION` SHALL be refused.

#### Scenario: The chart references exactly the pushed images
- **WHEN** the `default` environment is rendered with the same three variables as the script
- **THEN** the four fixed services' images, and the `adapter` and `connector` names from `MAIN_REGISTRY`, `MAIN_REPO` and `MAIN_VERSION`, are exactly the six names the script lists

#### Scenario: An empty registry
- **WHEN** `LOCAL_REGISTRY` is empty and `--build-only` is given
- **THEN** the images are named `<MAIN_REPO>/<name>:<MAIN_VERSION>`

#### Scenario: An empty registry when pushing
- **WHEN** `LOCAL_REGISTRY` is empty and the script would push
- **THEN** it exits non-zero before building, saying a registry is needed to push

#### Scenario: An empty repository or version
- **WHEN** `MAIN_REPO` or `MAIN_VERSION` is empty
- **THEN** the script exits non-zero before building, naming the setting

### Requirement: Checked in CI and documented

CI SHALL run shellcheck on the script, run it with `--build-only`, and check its names against the charts. `helm/README.md` SHALL describe building and pushing with the script, and setting `LOCAL_REGISTRY`, `MAIN_REPO` and `MAIN_VERSION` through `helm/env.sh`.

#### Scenario: CI
- **WHEN** a Pull Request is opened
- **THEN** CI fails if shellcheck reports a problem, a build-only run fails, or the names differ from the charts'

#### Scenario: The deployment guide
- **WHEN** an operator reads `helm/README.md`
- **THEN** it explains how to build and push the images with the script, and how `env.sh` sets the three variables for both the script and the charts

## REMOVED Requirements

### Requirement: Configuration file and precedence
**Reason**: `helm/env.sh` is now the only place to set `LOCAL_REGISTRY`, `MAIN_REPO` and `MAIN_VERSION`, for both the charts and the script, so a second file for the same values is dropped.
**Migration**: Move any values from `scripts/build-images.env` to the shell, for example by editing or sourcing `helm/env.sh`. `scripts/build-images.env.example` is removed.
