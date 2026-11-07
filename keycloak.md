# Identity Setup

This document leads on how Keycloak is set up for the dataspace. #6 scripts the realm setup, and #14 automates what is needed per participant.

The dataspace uses an existing Keycloak, such as the one in the [IndustryFusion DigitalTwin](https://github.com/IndustryFusion/DigitalTwin) stack, and does not deploy its own.

## One-time setup

Do this once per installation:

| Item | Setting |
|---|---|
| Realm | `dataspace` |
| Realm role | `dataspace-admin` |
| Client | `dataspace-admin-cli`: confidential, service account enabled |
| Its service account | Realm role `dataspace-admin`, plus `manage-clients`, `manage-realm` and `manage-users` from `realm-management` |
| Client, optional | `dataspace-ifric-reader`: confidential, service account enabled, no roles. Used to read company details from the IFRIC registry |

Keep client secrets in a Kubernetes Secret or a secret manager, not in the repository.

## Per participant

The management API creates this at registration, for hosted and external participants:

| Item | Setting |
|---|---|
| Realm role | `participant:<participant_id>` |
| Client | Client id equal to `participant_id`, client credentials only |
| Claim mapper | Hardcoded claim `participant_id` with the participant's id |
| Role assignment | The realm role on the client's service account |
| Client attribute | `dataspace.participant_id`, equal to the id. It marks the client as a participant's, so that other clients in a shared realm are left alone. Registering an id equal to a client without it gives `409` |

## What a participant token carries

```json
{
  "iss": "<KEYCLOAK_URL>/realms/dataspace",
  "participant_id": "urn:example:machine-builder-1",
  "realm_access": { "roles": ["participant:urn:example:machine-builder-1"] }
}
```

| Check | By | Requires |
|---|---|---|
| Signature and issuer | Gateway, adapter | RS256 against the realm's signing keys, and an exact issuer match. The audience is not checked |
| `participant_id` claim | Gateway | Present, and registered |
| `participant:<id>` role | Adapter | Matches the adapter's own participant |

A user login is not a substitute. A user's token can be given a `participant_id` claim, which would pass the gateway, but it would not hold the realm role the adapter requires. Agents use the participant's client.

## A token sent to a peer can be replayed

An adapter authenticates to a peer's adapter with its own token, on notifications and capability calls, and the audience isn't checked. So a peer that keeps such a token can use it at the sender's own adapter, as the sender, until it expires. For example, a machine builder could use a factory owner's token at that factory owner's `POST /capabilities/policy`, and approve itself.

Inside the hub the operator runs every adapter, and the traffic stays in the cluster. It matters most for an `adapter_url` or `peer_notify_url` outside the hub. Changing this affects tokens across the platform, so it is recorded here as an open decision.

### External participants

A hosted adapter sends its token to an external participant's adapter on every notification and capability call. So every external participant holds the token of each hosted participant that talks to it, and can use it **from anywhere, at the public gateway**, which routes a token to the adapter of the participant it names. Until the token expires, that reaches the hosted participant's whole agent API:

- Reading its inbox, its sent messages and its conversations, with any participant, and downloading their files.
- Sending messages in its name, to any participant its role allows.
- Changing its capability access, including approving itself.

Tokens last as long as the realm says, five minutes unless changed, and an adapter sends a fresh one when its last has expired. So while the two keep talking, this is continuous.

The same holds in the other direction, and between external participants:

- An external adapter's token reaches a hosted adapter through the hub's gateway, so the hub's operator can see and use it. An operator could anyway, as it holds the realm.
- Two external participants hold each other's tokens. Each could use the other's at its adapter, if it can reach that, and at the gateway's peer routes.

Nothing in the dataspace limits this. **Registering an external participant is a decision to trust it with the tokens of everyone it talks to**, so register only those you would trust with that. Client credentials themselves aren't exposed, and rotating a client's secret doesn't end a token already issued.

## The issuer must match

Services compare a token's issuer exactly with the URL they are configured with. So mint tokens through that same URL. A token minted through a different address for the same Keycloak is refused.

## Participant identifiers

A participant onboarded from the IFRIC registry has a `participant_id` equal to its `company_ifric_id`, with no mapping table. The realm can then be shared with the [IFRIC registry](https://github.com/IndustryFusion/ifric-registry-service-oss), which matches a `participant_id` token against its companies.

Any other participant id must never equal a real `company_ifric_id`, or the registry would treat it as that company.

The dataspace does not check this at registration, so the administrator is responsible for it.

## Sharing the realm with the IFRIC registry

To show company details next to participants, as [management-api.md](management-api.md) describes:

1. Use one realm for both, so that a participant's token can be matched to its company.
2. Create the `dataspace-ifric-reader` client from "One-time setup". `scripts/setup-keycloak.py --with-ifric-reader` does this. It has no roles.
3. Make sure the IFRIC registry verifies tokens against the same Keycloak URL as the dataspace's services. Issuers are compared exactly, so a reader token minted through `KEYCLOAK_URL` is refused by a registry configured with another address for the same Keycloak, and details are then left out.
4. Give the management service `IFRIC_BACKEND_URL`, `IFRIC_READER_CLIENT_ID` and `IFRIC_READER_CLIENT_SECRET`. With [Helm](deploy/README.md), these are `ifric.backendUrl` and, in the secrets file, `secrets.ifricReaderClientId` and `secrets.ifricReaderClientSecret`.
5. Register a company's participant with its `company_ifric_id` as `participant_id`.

If any of these is missing, or the registry can't be reached, reads just leave out the company details.

## Removal

`DELETE /api/participants/{id}` removes the client and the role. See [management-api.md](management-api.md).
