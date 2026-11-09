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
# Prepares a cluster for the dataspace, and removes it again. See helm/README.md.
# It acts on the cluster that KUBECONFIG points at, and shows which one before changing anything.
# tools only checks Helm and installs helmfile and the helm-diff plugin, and touches no cluster.
#
# Usage: helm/bootstrap.sh tools | up | down

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS="$HERE/.tools"
# shellcheck source-path=SCRIPTDIR source=env.sh
source "$HERE/env.sh"
SERVICES_NAMESPACE="$NAMESPACE"
export PATH="$TOOLS:$PATH"

# The checksum of each helmfile release this script will download. Another version needs its checksum added here.
helmfile_sha256() {
  case "$1" in
    0.169.2) echo 34a5ca9c5fda733f0322f7b12a2959b7de4ab125bcf6531337751e263b027d58 ;;
    *) return 1 ;;
  esac
}

# Whether version $1 is at least $2, comparing major, minor and patch.
at_least() {
  local IFS=.
  # shellcheck disable=SC2206
  local have=($1) want=($2) index
  for index in 0 1 2; do
    if [ "${have[index]:-0}" -gt "${want[index]:-0}" ]; then return 0; fi
    if [ "${have[index]:-0}" -lt "${want[index]:-0}" ]; then return 1; fi
  done
  return 0
}

need() {
  for tool in "$@"; do
    command -v "$tool" >/dev/null || { echo "Missing tool: $tool" >&2; exit 1; }
  done
}

install_tools() {
  need kubectl helm curl sha256sum tar
  local current_helm
  current_helm=$(helm version --template '{{.Version}}' 2>/dev/null)
  current_helm="${current_helm#v}"
  current_helm="${current_helm%%+*}"
  if ! at_least "$current_helm" "$HELM_VERSION"; then
    echo "Helm $current_helm is older than HELM_VERSION, $HELM_VERSION. Install a newer Helm." >&2
    exit 1
  fi
  echo "Helm $current_helm"

  if command -v helmfile >/dev/null; then
    echo "helmfile is present: $(command -v helmfile), $(helmfile --version 2>/dev/null | head -1)"
  else
    local sha256
    sha256=$(helmfile_sha256 "$HELMFILE_VERSION") || {
      echo "No checksum is known for helmfile $HELMFILE_VERSION, so it isn't downloaded. Add it to helm/bootstrap.sh." >&2
      exit 1
    }
    mkdir -p "$TOOLS"
    local archive="$TOOLS/helmfile.tgz"
    curl -fsSL -o "$archive" \
      "https://github.com/helmfile/helmfile/releases/download/v$HELMFILE_VERSION/helmfile_${HELMFILE_VERSION}_linux_amd64.tar.gz"
    echo "$sha256  $archive" | sha256sum -c - >/dev/null
    tar -xzf "$archive" -C "$TOOLS" helmfile
    rm -f "$archive"
    echo "Installed helmfile $HELMFILE_VERSION in $TOOLS. Add it to PATH to run helmfile yourself."
  fi

  # helmfile diff and helmfile apply need it. A version already installed is left as it is.
  local installed
  installed=$(helm plugin list 2>/dev/null | awk '$1 == "diff" { print $2 }')
  if [ -n "$installed" ]; then
    echo "helm-diff $installed is present"
  else
    local verify=()
    case "$current_helm" in 3.*) ;; *) verify=(--verify=false) ;; esac
    helm plugin install https://github.com/databus23/helm-diff --version "v$HELM_DIFF_PLUGIN" "${verify[@]}" >/dev/null
    echo "Installed helm-diff $HELM_DIFF_PLUGIN"
  fi
}

up() {
  install_tools
  echo "Cluster: $(kubectl config current-context)"
  for namespace in "$SERVICES_NAMESPACE" "$PARTICIPANTS_NAMESPACE"; do
    kubectl create namespace "$namespace" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
    kubectl label namespace "$namespace" app.kubernetes.io/part-of=dataspace --overwrite >/dev/null
  done
  echo "Namespaces are ready: $SERVICES_NAMESPACE, $PARTICIPANTS_NAMESPACE"
}

down() {
  need kubectl helmfile
  echo "Cluster: $(kubectl config current-context)"
  local left
  left=$(kubectl -n "$PARTICIPANTS_NAMESPACE" get deployments -l app.kubernetes.io/managed-by=dataspace-management \
    -o name 2>/dev/null | wc -l)
  if [ "$left" -gt 0 ]; then
    echo "Note: $left participant Deployments remain. Their databases, buckets and Keycloak clients stay behind," >&2
    echo "as they are outside these namespaces. Use DELETE /api/participants/{id} first to remove those too." >&2
  fi
  (cd "$HERE" && helmfile -e default destroy)
  kubectl -n "$PARTICIPANTS_NAMESPACE" delete deployments,services,secrets,configmaps \
    -l app.kubernetes.io/managed-by=dataspace-management --ignore-not-found --wait=true >/dev/null 2>&1 || true
  kubectl delete namespace "$PARTICIPANTS_NAMESPACE" "$SERVICES_NAMESPACE" --ignore-not-found --wait=true
  echo "The dataspace is removed from this cluster."
  echo "What stays, as it is outside these namespaces: the registry database with its entries, participants' databases,"
  echo "buckets and Keycloak clients, the realm, and PostgreSQL, S3 storage and Keycloak themselves."
}

case "${1:-}" in
  tools) install_tools ;;
  up) up ;;
  down) down ;;
  *) echo "Usage: $0 tools | up | down" >&2; exit 2 ;;
esac
