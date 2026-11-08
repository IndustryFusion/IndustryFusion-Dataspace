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

import React, { useEffect, useState } from 'react';

import { request } from '../api.js';

const REFRESH_MILLISECONDS = 15000;

const isOk = (component) => component.status === 'ok';
const timeOf = (value) => (typeof value === 'number' ? `${value} ms` : '');
const clockOf = (value) => {
  const when = new Date(value);
  return Number.isNaN(when.getTime()) ? '' : when.toLocaleTimeString();
};

export default function Health() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState(null);
  // Pressing Refresh starts the cycle again: a check at once, and the next one 15 seconds later.
  const [cycle, setCycle] = useState(0);

  useEffect(() => {
    let current = true;
    const load = async () => {
      try {
        const answer = await request('GET', '/api/health');
        if (current) {
          setHealth(answer);
          setError(null);
        }
      } catch (failure) {
        if (current) setError(failure.message);
      }
    };
    load();
    const timer = setInterval(load, REFRESH_MILLISECONDS);
    return () => {
      current = false;
      clearInterval(timer);
    };
  }, [cycle]);

  const healthy = health ? health.components.filter(isOk).length : 0;

  return (
    <section>
      <h2>Health</h2>
      <p>
        <button type="button" onClick={() => setCycle((count) => count + 1)}>
          Refresh
        </button>
      </p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {health && (
        <>
          <p role="status" aria-label="Summary">
            Overall: <span className={`badge ${health.status === 'ok' ? 'ok' : 'bad'}`}>{health.status}</span>{' '}
            {healthy} of {health.components.length} components ok
          </p>
          <p aria-label="Checked at">Checked at {clockOf(health.checked_at)}</p>
          <table>
            <thead>
              <tr>
                <th>Component</th>
                <th>Status</th>
                <th>Response time</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {health.components.map((component) => (
                <tr key={component.name}>
                  <td>{component.name}</td>
                  <td>
                    <span className={`badge ${isOk(component) ? 'ok' : 'bad'}`}>{component.status}</span>
                  </td>
                  <td>{timeOf(component.response_ms)}</td>
                  <td>{component.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
