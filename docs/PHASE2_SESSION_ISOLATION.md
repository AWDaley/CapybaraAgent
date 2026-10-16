# Phase 2: Browser ownership and isolated agent state

The browser no longer supplies its session UUID in `X-Capybara-Session`.
The server issues an opaque UUID signed with HMAC-SHA256 in the HttpOnly
`capybara_sid` cookie, with `SameSite=Strict`. A forged cookie causes
a new empty browser session rather than access to another session.

For durable session ownership across restarts set
`CAPYBARA_SESSION_SECRET` to a stable, high-entropy secret of at least
32 characters. Without it, signing keys are generated at process start;
old cookies are invalidated on restart, although their on-disk data remains.

When deployed behind **actual HTTPS**, also set
`CAPYBARA_SECURE_COOKIE=1` so that browsers send the cookie only over
HTTPS. The environment variable does **not** provide TLS by itself.
Continue using `CAPYBARA_AUTH_TOKEN` as a separate access control when
binding beyond loopback. This is browser-session separation, **not** a
multi-user account and permissions system.

Each browser session now has:
- Its own workspace in `data/sessions/clients/<session-uuid>/workspace`.
- Its own conversation/session files and knowledge-store JSON.
- Its own REPL state (though model-driven REPL execution remains disabled in
  safe mode), approval requests, and runtime context.
- File tools, verification, pipelines, and workspace previews bound to that
  same workspace.

Tool calls run on a thread pool, so the request's trusted workspace context is
explicitly propagated to worker threads. Direct filesystem tools still validate
paths and symlinks. These protections apply to the browser entrypoints; a
programmer can still opt into the separate, unsafe CLI development runtime
when `CAPYBARA_UNSAFE_LOCAL_EXEC=1`.

The browser's `remember` and `recall` tools are explicitly bound to its
own knowledge store. The SSL verification policy can only be changed through
trusted process configuration, not by writing an agent memory fact.

**Migration:** Older browser sessions identified only by unsigned client UUID
headers are not automatically imported into newly signed browser sessions.
Data remains on disk; restoration requires a trusted administrator migration.
Do not automatically give a new browser access to old UUID-named directories.

**Remaining limitations:** This feature has not undergone third-party
penetration testing. Shared OS account permissions, plugin-specific storage,
browser-device compromise, container isolation, data retention, process
restarts, and remote HTTPS authentication still require deployment controls.
The standard-library HTTP server is not a substitute for a production reverse
proxy or a dedicated application server.
