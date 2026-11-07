/*
 * Copyright (c) 2026 IndustryFusion Foundation
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

// Calls to the management API. An error carries the API's own message, to show to the user.

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function messageFrom(status, body) {
  const detail = body && body.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((entry) => `${(entry.loc || []).slice(1).join('.')}: ${entry.msg}`).join('; ');
  }
  return `The server answered ${status}`;
}

export async function request(method, path, { body, token } = {}) {
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = `Bearer ${token}`;
  let response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, 'The management API could not be reached');
  }
  if (response.status === 204) return null;
  let parsed = null;
  try {
    parsed = await response.json();
  } catch {
    // An answer from a proxy can be anything. The status still says what happened.
  }
  if (!response.ok) throw new ApiError(response.status, messageFrom(response.status, parsed));
  return parsed;
}

export const participantPath = (id) => `/api/participants/${encodeURIComponent(id)}`;

export const fetchToken = (clientId, clientSecret) =>
  request('POST', '/api/admin/token', { body: { client_id: clientId, client_secret: clientSecret } });
