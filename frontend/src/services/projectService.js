import { API, TOKEN_KEY } from '../config/api';

function headers() {
  return {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${localStorage.getItem(TOKEN_KEY) || ''}`,
  };
}

async function request(url, options = {}) {
  const res = await fetch(url, { ...options, headers: { ...headers(), ...(options.headers || {}) } });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.error) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

export function listProjects() {
  return request(API.PROJECTS_API);
}

export function createProject(name, description = '') {
  return request(API.PROJECTS_API, {
    method: 'POST',
    body: JSON.stringify({ name, description }),
  });
}

export function getProject(id) {
  return request(`${API.PROJECTS_API}/${encodeURIComponent(id)}`);
}

export function updateProject(id, name, description = '') {
  return request(`${API.PROJECTS_API}/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify({ name, description }),
  });
}

export function deleteProject(id) {
  return request(`${API.PROJECTS_API}/${encodeURIComponent(id)}`, { method: 'DELETE' });
}
