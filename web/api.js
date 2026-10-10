import { state } from './state.js';

export function getAuthHeaders() {
    const headers = { 'X-Capybara-Session': state.clientSessionToken };
    const token = sessionStorage.getItem('capybara_auth_token');
    if (token) {
        headers.Authorization = `Bearer ${token}`;
    }
    return headers;
}

export async function fetchProviders() {
    try {
        const res = await fetch('/api/providers', {
            headers: getAuthHeaders()
        });
        if (!res.ok) throw new Error(`Provider fetch failed: ${res.status}`);
        state.availableProviders = await res.json();
    } catch (e) {
        console.error("Failed to fetch providers", e);
    }
}

export async function saveSettingsAPI(config) {
    return await fetch('/api/config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', ...getAuthHeaders()},
        body: JSON.stringify(config)
    });
}

export async function startNewSessionAPI() {
    return await fetch('/api/sessions/new', {
        method: 'POST',
        headers: getAuthHeaders()
    });
}

export async function loadSessionAPI(filepath) {
    return await fetch('/api/sessions/load', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', ...getAuthHeaders()},
        body: JSON.stringify({filepath})
    });
}

export async function loadSessionsAPI() {
    const res = await fetch('/api/sessions', {
        headers: getAuthHeaders()
    });
    if (!res.ok) throw new Error(`Sessions fetch failed: ${res.status}`);
    return await res.json();
}

export async function sendApprovalAPI(approvalId, approved) {
    return await fetch('/api/chat/approve', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', ...getAuthHeaders()},
        body: JSON.stringify({approval_id: approvalId, approved: approved})
    });
}

export async function getWorkspaceAPI() {
    const res = await fetch('/api/workspace', {
        headers: getAuthHeaders()
    });
    if (!res.ok) throw new Error("Failed to load workspace");
    return await res.json();
}

export async function getFileAPI(filename) {
    const response = await fetch(`/api/workspace/file?name=${encodeURIComponent(filename)}`, {
        headers: getAuthHeaders()
    });
    if (!response.ok) throw new Error("File not found");
    return await response.json();
}
