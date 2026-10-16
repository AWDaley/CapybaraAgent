import { state } from './state.js';
import { startNewSessionAPI, loadSessionAPI, sendApprovalAPI, getWorkspaceAPI, loadSessionsAPI, getAuthHeaders } from './api.js';
import { 
    appendSystemMessage, appendUserMessage, appendAgentMessage, 
    createEmptyAgentMessage, scrollToBottom, closeAllSidebars, 
    renderWorkspaceFiles, renderSessionList
} from './ui.js';
import { escapeHtml, renderMarkdown } from './utils.js';

export async function startNewSession() {
    try {
        await startNewSessionAPI();
        state.currentSessionId = null;
        document.getElementById('chat-messages').innerHTML = '';
        appendSystemMessage("Started a new chat.");
        closeAllSidebars();
        await refreshSessions();
    } catch (e) {
        console.error("Failed to start new session", e);
    }
}

export async function refreshSessions() {
    try {
        const sessions = await loadSessionsAPI();
        const sessionList = document.getElementById('session-list');
        renderSessionList(sessions, sessionList);
    } catch (e) {
        console.error("Failed to load sessions", e);
    }
}

export async function loadSession(filepath) {
    try {
        const res = await loadSessionAPI(filepath);
        const data = await res.json();
        
        if (res.ok) {
            state.currentSessionId = filepath;
            document.getElementById('chat-messages').innerHTML = '';
            
            if (data.memory.length === 0) {
                 appendSystemMessage("Empty session loaded.");
            }
            
            data.memory.forEach(msg => {
                if (msg.role === 'user') {
                    appendUserMessage(msg.content);
                } else if (msg.role === 'agent') {
                    appendAgentMessage(msg.content, null, null);
                }
            });
            
            closeAllSidebars();
            await refreshSessions();
            scrollToBottom();
        }
    } catch (e) {
        console.error("Failed to load session", e);
    }
}

export async function sendMessage() {
    const messageInput = document.getElementById('message-input');
    const typingIndicator = document.getElementById('typing-indicator');
    
    const text = messageInput.value.trim();
    if (!text) return;
    
    const intro = document.querySelector('#chat-messages .intro');
    if (intro) intro.remove();
    
    appendUserMessage(text);
    messageInput.value = '';
    messageInput.style.height = 'auto';
    
    typingIndicator.classList.remove('hidden');
    scrollToBottom();
    
    const { content, meta, badges, thoughtsContainer, thoughtsAccordion } = createEmptyAgentMessage();
    
    try {
        const response = await fetch('/api/chat/stream', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', ...getAuthHeaders()},
            body: JSON.stringify({message: text})
        });
        
        typingIndicator.classList.add('hidden');
        
        if (!response.ok) {
            const data = await response.json();
            content.innerHTML = `Error: ${data.error}`;
            return;
        }
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let currentToolBadge = null;
        let sseBuffer = '';
        
        while (true) {
            const {value, done} = await reader.read();
            if (done) break;
            
            sseBuffer += decoder.decode(value, {stream: true});
            const lines = sseBuffer.split('\n');
            sseBuffer = lines.pop();
            
            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                try {
                    const event = JSON.parse(line.slice(6));
                    
                    if (event.type === 'thought') {
                        meta.classList.remove('hidden');
                        thoughtsAccordion.style.display = 'block';
                        thoughtsContainer.innerHTML += escapeHtml(event.content) + '\n\n';
                        scrollToBottom();
                    } 
                    else if (event.type === 'tool_start') {
                        meta.classList.remove('hidden');
                        currentToolBadge = document.createElement('span');
                        currentToolBadge.className = 'tool-badge running';
                        currentToolBadge.innerHTML = `🔧 ${escapeHtml(event.name)}`;
                        badges.appendChild(currentToolBadge);
                        scrollToBottom();
                    }
                    else if (event.type === 'tool_result') {
                        if (currentToolBadge) {
                            currentToolBadge.classList.remove('running');
                            currentToolBadge.title = `Args: ${event.args || 'N/A'}\nResult: ${event.result}`;
                            currentToolBadge = null;
                        }
                    }
                    else if (event.type === 'answer') {
                        content.innerHTML = renderMarkdown(event.content);
                        scrollToBottom();
                    }
                    else if (event.type === 'approval_needed') {
                        const card = document.createElement('div');
                        card.className = 'approval-card';
                        card.id = `approval-card-${event.id}`;
                        card.innerHTML = `
                            <div class="approval-title">⚠️ Dangerous Tool Detected</div>
                            <div class="approval-details">
                                <strong>Tool:</strong> ${escapeHtml(event.tool)}<br>
                                <strong>Args:</strong> ${escapeHtml(event.args)}
                            </div>
                            <div class="approval-actions">
                                <button class="primary-button btn-approve" data-approval-id="${event.id}">✅ Approve</button>
                                <button class="secondary-button btn-reject" data-approval-id="${event.id}">❌ Reject</button>
                            </div>
                        `;
                        content.appendChild(card);
                        
                        if (currentToolBadge) {
                            currentToolBadge.classList.remove('running');
                        }
                        scrollToBottom();
                    }
                    else if (event.type === 'error') {
                        meta.classList.remove('hidden');
                        thoughtsAccordion.style.display = 'block';
                        
                        const errorNode = document.createTextNode(`⚠️ Error: ${event.content}\n\n`);
                        thoughtsContainer.appendChild(errorNode);
                        
                        const contentBreak = document.createElement('br');
                        const contentError = document.createElement('span');
                        contentError.style.color = '#ffaa00';
                        contentError.textContent = `⚠️ ${event.content}`;
                        content.appendChild(contentBreak);
                        content.appendChild(contentError);
                        
                        scrollToBottom();
                    }
                    else if (event.type === 'outcome') {
                        const labels = {
                            verified: 'Verified against declared acceptance checks',
                            completed_unverified: 'Completed — independent verification unavailable',
                            failed: 'Task failed verification',
                            escalated: 'Task escalated',
                            waiting_for_user: 'Waiting for user input'
                        };
                        const outcome = document.createElement('div');
                        outcome.className = 'verification-outcome';
                        outcome.textContent = labels[event.status] || 'Verification status unavailable';
                        content.appendChild(outcome);
                        scrollToBottom();
                    }
                    else if (event.type === 'done') {
                        if (event.tokens_used) {
                            const tc = document.getElementById('token-counter');
                            if (tc) {
                                tc.textContent = `Total Tokens: ~${event.tokens_used}`;
                            }
                        }
                        refreshWorkspace();
                    }
                } catch (e) {
                    console.error("Error parsing SSE event:", e, line);
                }
            }
        }
    } catch (e) {
        typingIndicator.classList.add('hidden');
        content.innerHTML = `Connection error: ${escapeHtml(e.message)}.<br><br>`;
        const retryBtn = document.createElement('button');
        retryBtn.className = 'primary-button';
        retryBtn.textContent = 'Retry';
        retryBtn.onclick = () => {
            document.getElementById('message-input').value = text;
            content.innerHTML = 'Retrying...';
            sendMessage();
        };
        content.appendChild(retryBtn);
    }
}

export async function sendApproval(approvalId, approved) {
    const card = document.getElementById(`approval-card-${approvalId}`);
    if (card) {
        card.style.opacity = '0.5';
        card.style.pointerEvents = 'none';
        
        const statusDiv = document.createElement('div');
        statusDiv.style.marginTop = '0.5rem';
        statusDiv.style.fontWeight = 'bold';
        statusDiv.style.color = approved ? 'var(--accent-teal)' : '#ff4444';
        statusDiv.textContent = approved ? 'Approved. Resuming...' : 'Rejected. Resuming...';
        card.appendChild(statusDiv);
    }
    
    try {
        await sendApprovalAPI(approvalId, approved);
    } catch (e) {
        console.error("Failed to send approval", e);
    }
}

export async function refreshWorkspace() {
    try {
        const data = await getWorkspaceAPI();
        renderWorkspaceFiles(data.files);
    } catch (e) {
        console.error("Failed to load workspace", e);
    }
}
