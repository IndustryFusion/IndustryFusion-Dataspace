# image-build Specification

## Purpose
One script builds the dataspace images and pushes them under the registry, repository and version an operator chooses, with the names the chart renders.

## Requirements

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

### Requirement: Choosing what to build

The script SHALL build all six images by default, or only the images named as arguments. With `--build-only` it SHALL build and name them without pushing. With `--list` it SHALL print the full names without building.

#### Scenario: Named images
- **WHEN** an operator runs `./scripts/build-images.sh adapter connector`
- **THEN** only `adapter` and `connector` are built and pushed

#### Scenario: Build only
- **WHEN** an operator runs `./scripts/build-images.sh --build-only`
- **THEN** all six images exist locally under their full names, and nothing is pushed

#### Scenario: Listing
- **WHEN** an operator runs `./scripts/build-images.sh --list` with some settings
- **THEN** it prints the six full names for those settings, and builds and pushes nothing

#### Scenario: An unknown name
- **WHEN** an argument is not one of the six names or an option
- **THEN** the script exits non-zero before building, naming the argument and listing the valid names

### Requirement: Clear progress and failures

The script SHALL print the full names of its targets before it starts. It SHALL stop at the first failed build or push, with a non-zero exit code and a message naming the image and the step.

#### Scenario: Targets shown first
- **WHEN** the script starts
- **THEN** its first output lists the full name of each target

#### Scenario: A failed build
- **WHEN** an image fails to build
- **THEN** the script exits non-zero, names that image and the build step, and builds no further image

#### Scenario: A failed push
- **WHEN** a push fails, such as to a registry that can't be reached
- **THEN** the script exits non-zero, naming that image and the push step, and pushes no further image

#### Scenario: No Docker
- **WHEN** `docker` can't be found
- **THEN** the script exits non-zero before building, saying so

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
