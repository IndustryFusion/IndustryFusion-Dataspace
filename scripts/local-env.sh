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
#
# Brings up a local Kubernetes cluster with the infrastructure the dataspace needs.
# It uses only its own kubeconfig under .local/, so it cannot act on another cluster.
#
# Usage: scripts/local-env.sh up | down | status | check | images | services | helm-secrets

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL="$ROOT/.local"
CLUSTER="${DATASPACE_CLUSTER:-dataspace-local}"
export KUBECONFIG="$LOCAL/kubeconfig"
KEYCLOAK_ISSUER_BASE="http://keycloak-service.iff:8080/auth"
SERVICES="registry gateway dsp-gateway management"
PARTICIPANT_IMAGES="connector adapter"

need() {
  for tool in "$@"; do
    command -v "$tool" >/dev/null || { echo "Missing tool: $tool" >&2; exit 1; }
  done
}

generate_credentials() {
  mkdir -p "$LOCAL"
  chmod 700 "$LOCAL"
  if [ -f "$LOCAL/credentials.env" ]; then
    # An environment made before the management service existed lacks this one.
    grep -q '^ADAPTER_INTERNAL_KEY=' "$LOCAL/credentials.env" ||
      echo "ADAPTER_INTERNAL_KEY=$(openssl rand -hex 24)" >> "$LOCAL/credentials.env"
    return
  fi
  umask 077
  cat > "$LOCAL/credentials.env" <<CREDENTIALS
POSTGRES_USER=dataspace
POSTGRES_PASSWORD=$(openssl rand -hex 24)
S3_ACCESS_KEY=$(openssl rand -hex 12)
S3_SECRET_KEY=$(openssl rand -hex 24)
KEYCLOAK_ADMIN_USER=admin
KEYCLOAK_ADMIN_PASSWORD=$(openssl rand -hex 24)
ADAPTER_INTERNAL_KEY=$(openssl rand -hex 24)
CREDENTIALS
}

apply_secrets() {
  # shellcheck disable=SC1091
  . "$LOCAL/credentials.env"
  local s3config
  s3config=$(printf '{"identities":[{"name":"dataspace","credentials":[{"accessKey":"%s","secretKey":"%s"}],"actions":["Admin","Read","Write","List","Tagging"]}]}' \
    "$S3_ACCESS_KEY" "$S3_SECRET_KEY")
  kubectl -n iff create secret generic infra-credentials \
    --from-literal=postgres-user="$POSTGRES_USER" \
    --from-literal=postgres-password="$POSTGRES_PASSWORD" \
    --from-literal=keycloak-admin-user="$KEYCLOAK_ADMIN_USER" \
    --from-literal=keycloak-admin-password="$KEYCLOAK_ADMIN_PASSWORD" \
    --from-literal=s3-config="$s3config" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
}

# Runs a command with $KEYCLOAK_LOCAL_URL set to a forwarded Keycloak port.
with_keycloak() {
  local port pf_pid
  port=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
  kubectl -n iff port-forward svc/keycloak-service "$port:8080" >/dev/null &
  pf_pid=$!
  trap "kill $pf_pid 2>/dev/null || true; trap - RETURN" RETURN
  for _ in $(seq 1 30); do
    curl -fs -o /dev/null "http://127.0.0.1:$port/auth/realms/master" && break
    sleep 1
  done
  KEYCLOAK_LOCAL_URL="http://127.0.0.1:$port/auth" "$@"
}

setup_realm() {
  # shellcheck disable=SC1091
  . "$LOCAL/credentials.env"
  KEYCLOAK_ADMIN_USER="$KEYCLOAK_ADMIN_USER" KEYCLOAK_ADMIN_PASSWORD="$KEYCLOAK_ADMIN_PASSWORD" \
    python3 "$ROOT/scripts/setup-keycloak.py" --url "$KEYCLOAK_LOCAL_URL" --secret-file "$LOCAL/admin-client-secret"
}

check_token() {
  local issuer
  issuer=$(curl -fsS "$KEYCLOAK_LOCAL_URL/realms/dataspace/protocol/openid-connect/token" \
      -d grant_type=client_credentials -d client_id=dataspace-admin-cli \
      --data-urlencode "client_secret=$(cat "$LOCAL/admin-client-secret")" \
    | python3 -c 'import base64, json, sys
token = json.load(sys.stdin)["access_token"].split(".")[1]
print(json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))["iss"])')
  echo "Token issuer: $issuer"
  [ "$issuer" = "$KEYCLOAK_ISSUER_BASE/realms/dataspace" ] || { echo "Issuer mismatch" >&2; return 1; }
}

up() {
  need kind kubectl openssl python3 curl
  generate_credentials
  if ! kind get clusters | grep -qx "$CLUSTER"; then
    kind create cluster --name "$CLUSTER" --kubeconfig "$KUBECONFIG"
  fi
  kubectl apply -f "$ROOT/deploy/local/namespaces.yaml" >/dev/null
  apply_secrets
  kubectl apply -f "$ROOT/deploy/local/infra.yaml" >/dev/null
  kubectl -n iff rollout status deploy/acid-cluster --timeout=300s
  kubectl -n iff rollout status deploy/seaweedfs --timeout=300s
  kubectl -n iff rollout status deploy/keycloak-service --timeout=420s
  with_keycloak setup_realm
  with_keycloak check_token
  echo "Local environment is ready. Use: KUBECONFIG=$KUBECONFIG kubectl get pods -A"
}

# Builds the images and loads them into the cluster.
images() {
  need docker kind
  for service in $SERVICES $PARTICIPANT_IMAGES; do
    if [ "$service" = management ]; then
      docker build -q -t "dataspace/$service:dev" -f "$ROOT/management/api/Dockerfile" "$ROOT/management" >/dev/null
    else
      docker build -q -t "dataspace/$service:dev" "$ROOT/$service" >/dev/null
    fi
    kind load docker-image --name "$CLUSTER" "dataspace/$service:dev" >/dev/null
  done
}

# Writes a secrets file for deploy/helm from this environment's credentials, and prints its path.
helm_secrets() {
  generate_credentials
  # shellcheck disable=SC1091
  . "$LOCAL/credentials.env"
  (umask 077; cat > "$LOCAL/helm-secrets.yaml") <<SECRETS
secrets:
  postgres:
    user: "$POSTGRES_USER"
    password: "$POSTGRES_PASSWORD"
  s3:
    accessKey: "$S3_ACCESS_KEY"
    secretKey: "$S3_SECRET_KEY"
  adapterInternalKey: "$ADAPTER_INTERNAL_KEY"
  adminClientSecret: "$(cat "$LOCAL/admin-client-secret")"
SECRETS
  echo "$LOCAL/helm-secrets.yaml"
}

# Builds the service images, loads them into the cluster and deploys them.
services() {
  need docker kind kubectl openssl
  generate_credentials
  # shellcheck disable=SC1091
  . "$LOCAL/credentials.env"
  kubectl -n dataspace create secret generic service-credentials \
    --from-literal=postgres-user="$POSTGRES_USER" \
    --from-literal=postgres-password="$POSTGRES_PASSWORD" \
    --from-literal=s3-access-key="$S3_ACCESS_KEY" \
    --from-literal=s3-secret-key="$S3_SECRET_KEY" \
    --from-literal=adapter-internal-key="$ADAPTER_INTERNAL_KEY" \
    --from-literal=admin-client-secret="$(cat "$LOCAL/admin-client-secret")" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  images
  kubectl apply -f "$ROOT/deploy/local/services.yaml" >/dev/null
  for service in $SERVICES; do
    kubectl -n dataspace rollout restart "deploy/$service" >/dev/null
    kubectl -n dataspace rollout status "deploy/$service" --timeout=180s
  done
}

down() {
  need kind
  kind delete cluster --name "$CLUSTER" --kubeconfig "$KUBECONFIG" || true
  rm -rf "$LOCAL"
}

status() {
  need kubectl
  kubectl get pods -n iff
  kubectl get pods -n dataspace
  kubectl get pods -n dataspace-participants
}

case "${1:-}" in
  up) up ;;
  down) down ;;
  status) status ;;
  check) need kubectl curl python3; with_keycloak check_token ;;
  images) images ;;
  services) services ;;
  helm-secrets) helm_secrets ;;
  *) echo "Usage: $0 up | down | status | check | images | services | helm-secrets" >&2; exit 2 ;;
esac
