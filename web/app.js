import { state } from './state.js';
import { fetchProviders, saveSettingsAPI } from './api.js';
import { openSidebar, closeAllSidebars, appendSystemMessage } from './ui.js';
import { sendMessage, startNewSession, refreshSessions, refreshWorkspace, sendApproval } from './chat.js';

// Setup elements
const providerSelect = document.getElementById('provider-select');
const modelSelect = document.getElementById('model-select');
const apiKeyGroup = document.getElementById('api-key-group');
const apiKeyInput = document.getElementById('api-key-input');
const authTokenInput = document.getElementById('auth-token-input');
const modeSelect = document.getElementById('mode-select');
const reflectionToggle = document.getElementById('reflection-toggle');
const saveSettingsBtn = document.getElementById('save-settings');

const settingsToggle = document.getElementById('settings-toggle');
const closeSettings = document.getElementById('close-settings');
const settingsSidebar = document.getElementById('settings-sidebar');

const sessionsToggle = document.getElementById('sessions-toggle');
const closeSessions = document.getElementById('close-sessions');
const sessionsSidebar = document.getElementById('sessions-sidebar');
const newSessionBtn = document.getElementById('new-session-btn');

const overlay = document.getElementById('sidebar-overlay');
const chatMessages = document.getElementById('chat-messages');

const workspaceToggle = document.getElementById('workspace-toggle');
const workspaceSidebar = document.getElementById('workspace-sidebar');
const closeWorkspace = document.getElementById('close-workspace');
const refreshWorkspaceBtn = document.getElementById('refresh-workspace-btn');
const closePreviewBtn = document.getElementById('close-preview');
const filePreviewModal = document.getElementById('file-preview-modal');

async function init() {
    const savedToken = sessionStorage.getItem('capybara_auth_token');
    if (savedToken && authTokenInput) authTokenInput.value = savedToken;

    await fetchProviders();
    await refreshSessions();
    setupEventListeners();
    
    // Load from localStorage
    const savedSettings = localStorage.getItem('capybara_settings');
    if (savedSettings) {
        try {
            const config = JSON.parse(savedSettings);
            if (config.provider) {
                providerSelect.value = config.provider;
                providerSelect.dispatchEvent(new Event('change'));
            }
            if (config.model) {
                modelSelect.value = config.model;
            }
            if (config.mode) modeSelect.value = config.mode;
            if (config.reflection !== undefined) reflectionToggle.checked = config.reflection;
            
            // Never overwrite an in-memory API key with the intentionally blank
            // persisted placeholder. Credentials remain session-only.
            const { api_key, ...nonSecretConfig } = config;
            saveSettingsAPI(nonSecretConfig).catch(e => console.error("Auto-apply failed", e));
        } catch(e) { console.error("Error loading settings", e); }
    }
    
    // Auto-open settings if no provider selected
    setTimeout(() => {
        if (!providerSelect.value) {
            openSidebar(settingsSidebar);
        }
    }, 500);
}

function setupEventListeners() {
    settingsToggle.addEventListener('click', () => openSidebar(settingsSidebar));
    closeSettings.addEventListener('click', closeAllSidebars);
    
    sessionsToggle.addEventListener('click', () => {
        refreshSessions();
        openSidebar(sessionsSidebar);
    });
    closeSessions.addEventListener('click', closeAllSidebars);
    
    overlay.addEventListener('click', closeAllSidebars);
    
    workspaceToggle.addEventListener('click', () => {
        refreshWorkspace();
        openSidebar(workspaceSidebar);
    });
    closeWorkspace.addEventListener('click', closeAllSidebars);
    refreshWorkspaceBtn.addEventListener('click', refreshWorkspace);
    closePreviewBtn.addEventListener('click', () => filePreviewModal.classList.add('hidden'));

    providerSelect.addEventListener('change', (e) => {
        const provider = e.target.value;
        apiKeyGroup.style.display = (provider === 'openai' || provider === 'gemini') ? 'flex' : 'none';
        
        modelSelect.innerHTML = '';
        if (provider && state.availableProviders[provider]) {
            modelSelect.disabled = false;
            let qwenModel = null;
            state.availableProviders[provider].forEach(model => {
                const opt = document.createElement('option');
                opt.value = model;
                opt.textContent = model;
                if (!qwenModel && model.toLowerCase().includes('qwen')) {
                    qwenModel = model;
                }
                modelSelect.appendChild(opt);
            });
            if (qwenModel) {
                modelSelect.value = qwenModel;
            }
        } else {
            modelSelect.disabled = true;
            modelSelect.innerHTML = '<option value="">Select Provider First...</option>';
        }
    });
    
    saveSettingsBtn.addEventListener('click', async () => {
        if (authTokenInput) {
            sessionStorage.setItem('capybara_auth_token', authTokenInput.value.trim());
        }

        const config = {
            provider: providerSelect.value,
            model: modelSelect.value,
            api_key: apiKeyInput.value,
            mode: modeSelect.value,
            reflection: reflectionToggle.checked
        };
        
        const persistentConfig = {...config, api_key: ''};
        localStorage.setItem('capybara_settings', JSON.stringify(persistentConfig));
        
        try {
            const res = await saveSettingsAPI(config);
            if (res.ok) {
                const btnOriginal = saveSettingsBtn.textContent;
                saveSettingsBtn.textContent = 'Saved! ✓';
                setTimeout(() => {
                    saveSettingsBtn.textContent = btnOriginal;
                    closeAllSidebars();
                }, 1000);
                
                if (chatMessages.children.length === 1 && chatMessages.children[0].classList.contains('intro')) {
                    chatMessages.innerHTML = '';
                    appendSystemMessage("Settings saved. Ready to chat!");
                }
            }
        } catch (e) {
            alert("Failed to save settings: " + e);
        }
    });
    
    const sendButton = document.getElementById('send-button');
    const messageInput = document.getElementById('message-input');
    
    sendButton.addEventListener('click', sendMessage);
    messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    messageInput.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
    });
    
    newSessionBtn.addEventListener('click', startNewSession);
    
    chatMessages.addEventListener('click', (e) => {
        if (e.target.classList.contains('btn-approve')) {
            const approvalId = e.target.dataset.approvalId;
            sendApproval(approvalId, true);
        } else if (e.target.classList.contains('btn-reject')) {
            const approvalId = e.target.dataset.approvalId;
            sendApproval(approvalId, false);
        }
    });
}

// Run
init();
