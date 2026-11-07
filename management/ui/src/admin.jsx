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

// Admin mode. The client secret stays in this component's memory only, as tokens are fetched and refreshed with it.
// It is never written to any browser storage, so reloading the page leaves admin mode.

import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';

import { ApiError, fetchToken, request } from './api.js';

const REFRESH_MARGIN_SECONDS = 30;
const AdminContext = createContext(null);

export const useAdmin = () => useContext(AdminContext);

export function AdminProvider({ children }) {
  const credentials = useRef(null);
  const token = useRef(null);
  const timer = useRef(null);
  const [active, setActive] = useState(false);
  const [ended, setEnded] = useState(null);

  const stop = useCallback(() => {
    clearTimeout(timer.current);
    credentials.current = null;
    token.current = null;
    setEnded(null);
    setActive(false);
  }, []);

  const refresh = useCallback(async () => {
    const { clientId, clientSecret } = credentials.current;
    const answer = await fetchToken(clientId, clientSecret);
    token.current = answer.access_token;
    clearTimeout(timer.current);
    const seconds = Math.max((answer.expires_in || 60) - REFRESH_MARGIN_SECONDS, 5);
    timer.current = setTimeout(() => {
      refresh().catch((failure) => {
        stop();
        setEnded(`Admin mode ended, as its token could not be renewed: ${failure.message}`);
      });
    }, seconds * 1000);
  }, [stop]);

  const start = useCallback(
    async (clientId, clientSecret) => {
      credentials.current = { clientId, clientSecret };
      setEnded(null);
      try {
        await refresh();
      } catch (error) {
        credentials.current = null;
        throw error;
      }
      setActive(true);
    },
    [refresh],
  );

  useEffect(() => () => clearTimeout(timer.current), []);

  // Use the token for a call, and fetch a new one once if the server says it has expired.
  const call = useCallback(
    async (method, path, body) => {
      try {
        return await request(method, path, { body, token: token.current });
      } catch (error) {
        if (error instanceof ApiError && error.status === 401 && credentials.current) {
          await refresh();
          return request(method, path, { body, token: token.current });
        }
        throw error;
      }
    },
    [refresh],
  );

  return <AdminContext.Provider value={{ active, ended, start, stop, call }}>{children}</AdminContext.Provider>;
}

export function AdminBar() {
  const { active, ended, start, stop } = useAdmin();
  const [open, setOpen] = useState(false);
  const [clientId, setClientId] = useState('dataspace-admin-cli');
  const [secret, setSecret] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  if (active) {
    return (
      <div className="admin-bar">
        <span className="badge ok">Admin mode</span>
        <button type="button" onClick={stop}>
          Leave admin mode
        </button>
      </div>
    );
  }
  if (!open) {
    return (
      <div className="admin-bar">
        {ended && (
          <span role="alert" className="error">
            {ended}
          </span>
        )}
        <button type="button" onClick={() => setOpen(true)}>
          Admin mode
        </button>
      </div>
    );
  }
  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await start(clientId, secret);
      setSecret('');
      setOpen(false);
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="admin-bar" onSubmit={submit} autoComplete="off">
      <label>
        Client id
        <input value={clientId} onChange={(event) => setClientId(event.target.value)} required />
      </label>
      <label>
        Client secret
        <input
          type="password"
          value={secret}
          autoComplete="off"
          onChange={(event) => setSecret(event.target.value)}
          required
        />
      </label>
      <button type="submit" disabled={busy}>
        Enter
      </button>
      <button type="button" onClick={() => setOpen(false)}>
        Cancel
      </button>
      {error && (
        <span role="alert" className="error">
          {error}
        </span>
      )}
    </form>
  );
}
