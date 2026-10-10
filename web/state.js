export const state = {
    availableProviders: {},
    currentSessionId: null,
    clientSessionToken: sessionStorage.getItem('capybara_client_session') || crypto.randomUUID()
};

sessionStorage.setItem('capybara_client_session', state.clientSessionToken);
