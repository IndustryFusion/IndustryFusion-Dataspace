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

export default function Health() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState(null);

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
  }, []);

  return (
    <section>
      <h2>Health</h2>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {health && (
        <>
          <p>
            Overall: <span className={`badge ${health.status === 'ok' ? 'ok' : 'bad'}`}>{health.status}</span>
          </p>
          <table>
            <thead>
              <tr>
                <th>Component</th>
                <th>Status</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {health.components.map((component) => (
                <tr key={component.name}>
                  <td>{component.name}</td>
                  <td>
                    <span className={`badge ${component.status === 'ok' ? 'ok' : 'bad'}`}>{component.status}</span>
                  </td>
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
