# Spec Delta

## Purpose

The build script reads the same image variables as the charts, from `helm/env.sh` or the shell.

## MODIFIED Requirements

### Requirement: Building and pushing the images

`scripts/build-images.sh` SHALL build `gateway`, `dsp-gateway`, `registry`, `management` with the UI built in, `adapter` and `connector`, and push each as `<LOCAL_REGISTRY>/<MAIN_REPO>/<name>:<MAIN_VERSION>`. `LOCAL_REGISTRY`, `MAIN_REPO` and `MAIN_VERSION` SHALL default to `k3d-iff.localhost:12345`, `dataspace` and `latest`. If `REGISTRY`, `REPO` or `VERSION` is set, the script SHALL say that it reads the new names.

#### Scenario: No settings
- **WHEN** an operator runs `./scripts/build-images.sh` without settings or a config file
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

### Requirement: Configuration file and precedence

The script SHALL take `LOCAL_REGISTRY`, `MAIN_REPO` and `MAIN_VERSION` from the shell first, then from an optional config file, then from the defaults. The config file SHALL be `scripts/build-images.env`, or the file `BUILD_IMAGES_CONFIG` names, and SHALL be read as `KEY=value` lines, not run. The default file SHALL be git-ignored, and a committed example SHALL show the keys.

#### Scenario: Values from the file
- **WHEN** the config file sets `LOCAL_REGISTRY`, `MAIN_REPO` and `MAIN_VERSION`, and the shell doesn't
- **THEN** the images are named with the file's values

#### Scenario: A shell variable overrides the file
- **WHEN** the file sets `MAIN_VERSION=1.0.0` and the shell sets `MAIN_VERSION=2.0.0`
- **THEN** the images are tagged `2.0.0`, and the file's other values are used

#### Scenario: The file is not run
- **WHEN** the config file has a line that isn't `KEY=value` for one of the three keys, such as a command
- **THEN** the script stops before building, naming the file and the line, and the line is not run

#### Scenario: A named file that is missing
- **WHEN** `BUILD_IMAGES_CONFIG` names a file that doesn't exist
- **THEN** the script stops before building and names the file

#### Scenario: The file is not committed
- **WHEN** an operator creates `scripts/build-images.env`
- **THEN** git ignores it, and `scripts/build-images.env.example` shows the three keys

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
- **THEN** it explains how to build and push the images with the script, how `env.sh` sets the three variables for both the script and the charts, and how the config file relates to `env.sh`
