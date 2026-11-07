//
// Copyright (c) 2026 IndustryFusion Foundation
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//   http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
//
package org.industryfusion.dataspace.connector;

import java.io.IOException;
import java.net.MalformedURLException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.text.ParseException;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.nimbusds.jose.JOSEException;
import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.jwk.source.JWKSourceBuilder;
import com.nimbusds.jose.proc.BadJOSEException;
import com.nimbusds.jose.proc.JWSVerificationKeySelector;
import com.nimbusds.jose.proc.SecurityContext;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.proc.DefaultJWTClaimsVerifier;
import com.nimbusds.jwt.proc.DefaultJWTProcessor;
import org.eclipse.edc.spi.EdcException;
import org.eclipse.edc.spi.iam.ClaimToken;
import org.eclipse.edc.spi.iam.IdentityService;
import org.eclipse.edc.spi.iam.TokenParameters;
import org.eclipse.edc.spi.iam.TokenRepresentation;
import org.eclipse.edc.spi.iam.VerificationContext;
import org.eclipse.edc.spi.monitor.Monitor;
import org.eclipse.edc.spi.result.Result;

/**
 * Gets this participant's token, and checks a counterparty's as an adapter checks a peer's: RS256 from the realm's
 * keys, the exact issuer, an expiry, and a participant_id claim with its participant role. The audience isn't checked.
 */
class KeycloakIdentityService implements IdentityService {

    static final String PARTICIPANT_CLAIM = "participant_id";
    private static final String BEARER = "Bearer ";
    private static final Duration MARGIN = Duration.ofSeconds(30);
    private static final Duration TIMEOUT = Duration.ofSeconds(10);

    private final String issuer;
    private final String clientId;
    private final String clientSecret;
    private final ObjectMapper mapper;
    private final Monitor monitor;
    private final HttpClient http = HttpClient.newBuilder().connectTimeout(TIMEOUT).build();
    private final DefaultJWTProcessor<SecurityContext> processor = new DefaultJWTProcessor<>();
    private String token;
    private Instant expires = Instant.MIN;

    KeycloakIdentityService(
            String issuer, String clientId, String clientSecret, ObjectMapper mapper, Monitor monitor) {
        this.issuer = issuer;
        this.clientId = clientId;
        this.clientSecret = clientSecret;
        this.mapper = mapper;
        this.monitor = monitor;
        var keys = keySource(issuer + "/protocol/openid-connect/certs");
        processor.setJWSKeySelector(new JWSVerificationKeySelector<>(JWSAlgorithm.RS256, keys));
        processor.setJWTClaimsSetVerifier(new DefaultJWTClaimsVerifier<>(
                new JWTClaimsSet.Builder().issuer(issuer).build(), Set.of("exp", PARTICIPANT_CLAIM)));
    }

    private static com.nimbusds.jose.jwk.source.JWKSource<SecurityContext> keySource(String address) {
        try {
            return JWKSourceBuilder.<SecurityContext>create(URI.create(address).toURL()).retrying(true).build();
        } catch (MalformedURLException error) {
            throw new EdcException("The Keycloak address isn't usable: " + address, error);
        }
    }

    @Override
    public synchronized Result<TokenRepresentation> obtainClientCredentials(TokenParameters parameters) {
        if (token == null || Instant.now().isAfter(expires)) {
            try {
                fetchToken();
            } catch (IOException | InterruptedException | RuntimeException error) {
                if (error instanceof InterruptedException) {
                    Thread.currentThread().interrupt();
                }
                monitor.warning("Could not get this connector's token", error);
                return Result.failure("Could not get this connector's token: " + error.getMessage());
            }
        }
        return Result.success(TokenRepresentation.Builder.newInstance().token(token).build());
    }

    private void fetchToken() throws IOException, InterruptedException {
        var form = "grant_type=client_credentials&client_id=" + encoded(clientId) + "&client_secret="
                + encoded(clientSecret);
        var request = HttpRequest.newBuilder(URI.create(issuer + "/protocol/openid-connect/token"))
                .timeout(TIMEOUT)
                .header("Content-Type", "application/x-www-form-urlencoded")
                .POST(HttpRequest.BodyPublishers.ofString(form))
                .build();
        var answer = http.send(request, HttpResponse.BodyHandlers.ofString());
        if (answer.statusCode() != 200) {
            throw new EdcException("Keycloak gave " + answer.statusCode());
        }
        var body = mapper.readTree(answer.body());
        token = body.required("access_token").asText();
        expires = Instant.now().plusSeconds(body.required("expires_in").asLong()).minus(MARGIN);
    }

    private static String encoded(String value) {
        return URLEncoder.encode(value, StandardCharsets.UTF_8);
    }

    @Override
    public Result<ClaimToken> verifyJwtToken(TokenRepresentation representation, VerificationContext context) {
        var given = representation.getToken();
        if (given == null || given.isBlank()) {
            return Result.failure("No token");
        }
        JWTClaimsSet claims;
        try {
            claims = processor.process(given.startsWith(BEARER) ? given.substring(BEARER.length()) : given, null);
        } catch (ParseException | BadJOSEException | JOSEException error) {
            return Result.failure("Invalid token: " + error.getMessage());
        }
        try {
            var participant = claims.getStringClaim(PARTICIPANT_CLAIM);
            if (participant == null || participant.isBlank() || !holdsRole(claims.getJSONObjectClaim("realm_access"), participant)) {
                return Result.failure("The token doesn't belong to a participant");
            }
            return Result.success(ClaimToken.Builder.newInstance().claim(PARTICIPANT_CLAIM, participant).build());
        } catch (ParseException error) {
            return Result.failure("Invalid token: " + error.getMessage());
        }
    }

    private static boolean holdsRole(Map<String, Object> realmAccess, String participant) {
        var roles = realmAccess == null ? null : realmAccess.get("roles");
        return roles instanceof List<?> list && list.contains("participant:" + participant);
    }
}
