import { state } from './state.js';
import { escapeHtml, renderMarkdown } from './utils.js';
import { loadSession } from './chat.js';
import { getFileAPI } from './api.js';

const overlay = document.getElementById('sidebar-overlay');
const chatMessages = document.getElementById('chat-messages');
const workspaceList = document.getElementById('workspace-list');

export function openSidebar(sidebar) {
    sidebar.classList.add('open');
    overlay.classList.add('active');
}

export function closeAllSidebars() {
    document.querySelectorAll('.sidebar').forEach(s => s.classList.remove('open'));
    overlay.classList.remove('active');
}

export function renderSessionList(sessions, container) {
    container.innerHTML = '';
    sessions.forEach(s => {
        const div = document.createElement('div');
        div.className = `session-item ${s.filepath === state.currentSessionId ? 'active' : ''}`;
        
        const date = new Date(s.mtime * 1000).toLocaleString();
        div.innerHTML = `
            <div class="session-title">${escapeHtml(s.preview)}</div>
            <div class="session-meta">${s.turn_count} messages • ${date}</div>
        `;
        
        div.addEventListener('click', () => loadSession(s.filepath));
        container.appendChild(div);
    });
}

export function scrollToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

export function appendSystemMessage(text) {
    const template = document.getElementById('message-template').content.cloneNode(true);
    const div = template.querySelector('.message');
    div.className = 'message system';
    div.querySelector('.message-content').textContent = text;
    chatMessages.appendChild(div);
    scrollToBottom();
}

export function appendUserMessage(text) {
    const template = document.getElementById('message-template').content.cloneNode(true);
    const div = template.querySelector('.message');
    div.className = 'message user';
    div.querySelector('.message-content').textContent = text;
    chatMessages.appendChild(div);
    scrollToBottom();
}

export function appendAgentMessage(text, thoughts = [], tools = []) {
    const template = document.getElementById('message-template').content.cloneNode(true);
    const div = template.querySelector('.message');
    div.className = 'message agent';
    
    div.querySelector('.message-content').innerHTML = renderMarkdown(text);
    
    const meta = div.querySelector('.message-meta');
    let hasMeta = false;
    
    if (tools && tools.length > 0) {
        hasMeta = true;
        const badgesContainer = div.querySelector('.tools-badges');
        tools.forEach(t => {
            const badge = document.createElement('span');
            badge.className = 'tool-badge';
            badge.innerHTML = `🔧 ${escapeHtml(t.name)}`;
            badge.title = `Args: ${t.args}\nResult: ${t.result}`;
            badgesContainer.appendChild(badge);
        });
    }
    
    if (thoughts && thoughts.length > 0) {
        hasMeta = true;
        const thoughtsContainer = div.querySelector('.thoughts-content');
        thoughtsContainer.innerHTML = thoughts.map(t => escapeHtml(t)).join('\n\n');
    } else {
        div.querySelector('.thoughts-accordion').style.display = 'none';
    }
    
    if (hasMeta) {
        meta.classList.remove('hidden');
    }
    
    chatMessages.appendChild(div);
    scrollToBottom();
}

export function createEmptyAgentMessage() {
    const template = document.getElementById('message-template').content.cloneNode(true);
    const div = template.querySelector('.message');
    div.className = 'message agent';
    
    const content = div.querySelector('.message-content');
    const meta = div.querySelector('.message-meta');
    const badges = div.querySelector('.tools-badges');
    const thoughtsContainer = div.querySelector('.thoughts-content');
    const thoughtsAccordion = div.querySelector('.thoughts-accordion');
    
    thoughtsAccordion.style.display = 'none';
    chatMessages.appendChild(div);
    scrollToBottom();
    
    return { div, content, meta, badges, thoughtsContainer, thoughtsAccordion };
}

export function renderWorkspaceFiles(files) {
    workspaceList.innerHTML = '';
    
    if (files.length === 0) {
        workspaceList.innerHTML = '<div class="message system"><p>Workspace is empty</p></div>';
        return;
    }
    
    files.forEach(file => {
        const el = document.createElement('div');
        el.className = 'workspace-item';
        el.innerHTML = `
            <div class="workspace-filename">📄 ${escapeHtml(file.name)}</div>
            <div class="workspace-size">${(file.size / 1024).toFixed(1)} KB</div>
        `;
        el.addEventListener('click', () => openFilePreview(file.name));
        workspaceList.appendChild(el);
    });
}

export async function openFilePreview(filename) {
    const filePreviewModal = document.getElementById('file-preview-modal');
    const previewFilename = document.getElementById('preview-filename');
    const previewContent = document.getElementById('preview-content');

    try {
        const data = await getFileAPI(filename);
        previewFilename.textContent = data.name;
        previewContent.textContent = data.content;
        filePreviewModal.classList.remove('hidden');
    } catch (e) {
        alert("Could not load file preview: " + e.message);
    }
}
