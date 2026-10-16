// Auth-side helpers. No config, database or network is opened by this module.
export const DASHBOARD_SIGNED_OUT_COOKIE = '__Host-law100-dashboard-signed-out';

// Only this host/path and a single opaque flow binding may return from Auth.
export function dashboardReauthBinding(value) {
  if (typeof value !== 'string') return null;
  return /^https:\/\/dashboard\.law100\.xyz\/_auth\/login\?reauth=([A-Za-z0-9_-]{43})$/.exec(value)?.[1] ?? null;
}

export function authContentSecurityPolicy(applications, issuer) {
  const origins = new Set([new URL(issuer).origin]);
  for (const app of Object.values(applications)) origins.add(new URL(`https://${app.host}`).origin);
  return `default-src 'none'; style-src 'self'; script-src 'self'; connect-src 'self'; font-src 'self'; img-src 'self' data:; form-action 'self' ${[...origins].join(' ')}; frame-ancestors 'none'; base-uri 'none'`;
}

// The caller must already have verified same-origin + the app's session CSRF.
// Dashboard logout is app-local. Preserve legacy semantics for other clients.
export function revokeApplicationLogin(run, app, appSessionId, centralSessionId) {
  if (app === 'dashboard') run('DELETE FROM app_sessions WHERE id=? AND app=?', appSessionId, app);
  else run('DELETE FROM sessions WHERE id=?', centralSessionId);
}
