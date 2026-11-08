# image-build Specification

## Purpose
One script builds the dataspace images and pushes them under the registry, repository and version an operator chooses, with the names the chart renders.

## Requirements

### Requirement: Building and pushing the images

`scripts/build-images.sh` SHALL build `gateway`, `dsp-gateway`, `registry`, `management` with the UI built in, `adapter` and `connector`, and push each as `<REGISTRY>/<REPO>/<name>:<VERSION>`. `REGISTRY`, `REPO` and `VERSION` SHALL default to `k3d-iff.localhost:12345`, `dataspace` and `latest`.

#### Scenario: No settings
- **WHEN** an operator runs `./scripts/build-images.sh` without settings or a config file
- **THEN** all six images are built and pushed as `k3d-iff.localhost:12345/dataspace/<name>:latest`

#### Scenario: Chosen registry, repository and version
- **WHEN** an operator runs `REGISTRY=<host> REPO=<repo> VERSION=1.2.3 ./scripts/build-images.sh` against a local registry
- **THEN** the registry holds `<host>/<repo>/<name>:1.2.3` for all six

#### Scenario: The management image has the UI
- **WHEN** the pushed `management` image is started
- **THEN** it serves the management UI

### Requirement: Configuration file and precedence

The script SHALL take `REGISTRY`, `REPO` and `VERSION` from the shell first, then from an optional config file, then from the defaults. The config file SHALL be `scripts/build-images.env`, or the file `BUILD_IMAGES_CONFIG` names, and SHALL be read as `KEY=value` lines, not run. The default file SHALL be git-ignored, and a committed example SHALL show the keys.

#### Scenario: Values from the file
- **WHEN** the config file sets `REGISTRY`, `REPO` and `VERSION`, and the shell doesn't
- **THEN** the images are named with the file's values

#### Scenario: A shell variable overrides the file
- **WHEN** the file sets `VERSION=1.0.0` and the shell sets `VERSION=2.0.0`
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

The names the script gives SHALL be those a chart rendered with `images.registry=<REGISTRY>`, `images.repo=<REPO>` and `images.version=<VERSION>` references, including the participant images the management API names from them. An empty `REGISTRY` SHALL mean no prefix, as in the chart, and SHALL be refused for pushing. An empty `REPO` or `VERSION` SHALL be refused.

#### Scenario: The chart references exactly the pushed images
- **WHEN** the chart is rendered with the same `images.*` values as the script
- **THEN** the four fixed services' images, and the `adapter` and `connector` names from `MAIN_REGISTRY`, `MAIN_REPO` and `MAIN_VERSION`, are exactly the six names the script lists

#### Scenario: An empty registry
- **WHEN** `REGISTRY` is empty and `--build-only` is given
- **THEN** the images are named `<REPO>/<name>:<VERSION>`

#### Scenario: An empty registry when pushing
- **WHEN** `REGISTRY` is empty and the script would push
- **THEN** it exits non-zero before building, saying a registry is needed to push

#### Scenario: An empty repository or version
- **WHEN** `REPO` or `VERSION` is empty
- **THEN** the script exits non-zero before building, naming the setting

### Requirement: Checked in CI and documented

CI SHALL run shellcheck on the script, run it with `--build-only`, and check its names against the chart. `deploy/README.md` SHALL describe building and pushing with the script and setting the matching `images.*` values.

#### Scenario: CI
- **WHEN** a Pull Request is opened
- **THEN** CI fails if shellcheck reports a problem, a build-only run fails, or the names differ from the chart's

#### Scenario: The deployment guide
- **WHEN** an operator reads "What you need first" in `deploy/README.md`
- **THEN** it explains how to build and push the images with the script, and how to set `images.registry`, `images.repo` and `images.version` to match, and it no longer says that the project doesn't publish images
