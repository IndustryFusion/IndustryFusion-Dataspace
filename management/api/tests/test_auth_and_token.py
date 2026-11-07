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

import pytest
from conftest import OTHER_KEY, make_token

ADMIN_ROUTES = [
    ("POST", "/api/participants", {"participant_id": "a", "participant_type": "factory_owner"}),
    ("POST", "/api/demo", None),
    ("DELETE", "/api/participants/a", None),
    ("GET", "/api/participants/a/credentials", None),
    ("PATCH", "/api/participants/a/capabilities/twin:history", {"default_policy": "auto"}),
    ("POST", "/api/participants/a/approvals", {"consumer_id": "b", "capability": "c", "action": "approve"}),
    ("PATCH", "/api/participants/a/approvals/x", {"action": "reset"}),
]
BAD_TOKENS = {
    "no token": None,
    "not a bearer": "Basic abc",
    "garbage": "Bearer not-a-token",
    "wrong signature": f"Bearer {make_token(key=OTHER_KEY)}",
    "wrong issuer": f"Bearer {make_token(issuer='http://elsewhere/realms/dataspace')}",
    "expired": f"Bearer {make_token(expires_in=-60)}",
    "unknown key": f"Bearer {make_token(kid='other')}",
}


@pytest.mark.parametrize("method,path,body", ADMIN_ROUTES)
@pytest.mark.parametrize("case", BAD_TOKENS)
def test_a_bad_token_gets_401(world, method, path, body, case):
    header = {"Authorization": BAD_TOKENS[case]} if BAD_TOKENS[case] else {}
    answer = world.client.request(method, path, json=body, headers=header)
    assert answer.status_code == 401
    assert "detail" in answer.json()
    assert not world.adapters.calls and not world.kubernetes.calls


@pytest.mark.parametrize("method,path,body", ADMIN_ROUTES)
def test_a_token_without_the_role_gets_403(world, method, path, body):
    header = {"Authorization": f"Bearer {make_token(roles=('participant:a',))}"}
    assert world.client.request(method, path, json=body, headers=header).status_code == 403
    assert not world.adapters.calls and not world.kubernetes.calls


def test_a_token_with_no_roles_at_all_gets_403(world):
    import jwt
    from conftest import ISSUER, SIGNING_KEY

    token = jwt.encode({"iss": ISSUER, "exp": 9999999999}, SIGNING_KEY, algorithm="RS256", headers={"kid": "k1"})
    answer = world.client.post("/api/demo", headers={"Authorization": f"Bearer {token}"})
    assert answer.status_code == 403


def test_signing_keys_unavailable_gives_502(world):
    world.keycloak.up = False
    assert world.client.post("/api/demo", headers=world.admin).status_code == 502


def test_token_route_gives_keycloaks_answer(world):
    answer = world.client.post("/api/admin/token", json={"client_id": "dataspace-admin-cli", "client_secret": "right"})
    assert answer.status_code == 200
    assert answer.json()["access_token"]


def test_token_route_refuses_a_wrong_secret(world):
    answer = world.client.post("/api/admin/token", json={"client_id": "x", "client_secret": "wrong"})
    assert answer.status_code == 401
    assert answer.json() == {"detail": "Wrong client credentials"}


def test_token_route_with_keycloak_down_gives_503(world):
    world.keycloak.up = False
    answer = world.client.post("/api/admin/token", json={"client_id": "x", "client_secret": "right"})
    assert answer.status_code == 503


def test_a_schema_error_does_not_repeat_the_secret(world):
    answer = world.client.post("/api/admin/token", json={"client_secret": "very-secret"})
    assert answer.status_code == 422
    assert "very-secret" not in answer.text


def test_the_callers_token_goes_to_keycloak(world):
    assert world.register().status_code == 200
    assert world.keycloak.seen_tokens
    assert set(world.keycloak.seen_tokens) == {world.admin["Authorization"]}


def test_a_token_with_no_expiry_gets_401(world):
    import jwt
    from conftest import ISSUER, SIGNING_KEY

    claims = {"iss": ISSUER, "realm_access": {"roles": ["dataspace-admin"]}}
    token = jwt.encode(claims, SIGNING_KEY, algorithm="RS256", headers={"kid": "k1"})
    assert world.client.post("/api/demo", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_a_valid_token_under_another_scheme_gets_401(world):
    answer = world.client.post("/api/demo", headers={"Authorization": f"Basic {make_token()}"})
    assert answer.status_code == 401


def test_a_stream_of_unknown_keys_fetches_the_signing_keys_only_once(world):
    fetches = []
    real = world.keycloak.handle

    def counting(request):
        if request.url.path.endswith("/certs"):
            fetches.append(1)
        return real(request)

    world.keycloak.handle = counting
    for _ in range(5):
        header = {"Authorization": f"Bearer {make_token(kid='unknown')}"}
        assert world.client.post("/api/demo", headers=header).status_code == 401
    assert len(fetches) == 1
