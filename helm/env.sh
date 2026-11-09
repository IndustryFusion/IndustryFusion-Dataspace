#!/usr/bin/env bash
#
# Copyright (c) 2026 IndustryFusion Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

# Settings for helmfile and scripts/build-images.sh. Source it before either:
#
#   source helm/env.sh
#
# A variable already set in the shell keeps its value, even an empty one, so
#   LOCAL_REGISTRY=registry.example.com:5000 MAIN_VERSION=1.2.3 source helm/env.sh
# changes the images for both. Nothing here is secret. See helm/README.md.

# Where the services run, and where the management API creates participants.
export NAMESPACE="${NAMESPACE-dataspace}"
export PARTICIPANTS_NAMESPACE="${PARTICIPANTS_NAMESPACE-dataspace-participants}"

# The images: [<LOCAL_REGISTRY>/]<MAIN_REPO>/<name>:<MAIN_VERSION>. Empty LOCAL_REGISTRY means no prefix.
export LOCAL_REGISTRY="${LOCAL_REGISTRY-k3d-iff.localhost:12345}"
export MAIN_REPO="${MAIN_REPO-dataspace}"
export MAIN_VERSION="${MAIN_VERSION-latest}"

# The tools helm/bootstrap.sh checks and installs: the oldest Helm it accepts, and the versions it installs.
export HELM_VERSION="${HELM_VERSION-3.14.0}"
export HELMFILE_VERSION="${HELMFILE_VERSION-0.169.2}"
export HELM_DIFF_PLUGIN="${HELM_DIFF_PLUGIN-3.15.11}"
