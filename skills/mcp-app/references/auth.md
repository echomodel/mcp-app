# Auth: the identity provider, administrators, and client sign-in

Read this whenever a task touches how callers authenticate to an mcp-app
server: configuring the issuer, naming administrators, deciding whether
`AUTH_AUDIENCE` is needed, setting up the identity provider, explaining a
401 or 403, or connecting an MCP client to a deployment.

This file describes the framework's auth model. All auth-specific
material for this skill lives here so the model can change in one place.
Other references point here instead of repeating it.

## The model in one paragraph

mcp-app is an OAuth 2.1 *resource server* (standard MCP authorization).
An external authorization server (the identity provider, typically
fronting Sign in with Google) signs the user in and issues the access
token. mcp-app validates the token against the issuer's published keys,
maps its email claim to a user record, and publishes a discovery
document so an MCP client finds the issuer from the server URL alone.
mcp-app holds no signing secret, issues no tokens, and never sees a
password. stdio mode has no auth at all: whoever can launch the process
is the user named by `--user`.

There is no other mode. The 1.x shared-secret model (`SIGNING_KEY`,
operator-minted tokens, `tokens create`, `?token=`) does not exist in
2.x. An app that still needs it pins `mcp-app@v1.0.0`
(`framework-version.md`).

## Configuration

Three variables configure a production HTTP deployment. The others are
overrides for unusual setups. None is a secret.

| Var | Required | If missing | Purpose |
|-----|----------|------------|---------|
| `AUTH_ISSUER` | For HTTP | Startup fails | Issuer identifier, exactly as in the token's `iss` claim (trailing slash included if the issuer uses one) |
| `ADMIN_EMAILS` | For HTTP | No administrators; startup warns | Comma-separated emails allowed on `/admin`; each is admitted as a user on first sign-in |
| `AUTH_ADMISSION` | No | `allowlist` | Who else is admitted on first sign-in: `allowlist` (registered users only) or `open` (any email the issuer vouches for) |
| `MAX_USERS` | No | Unlimited | With `open` admission, the record count past which new emails get `403`; administrators are never counted out |
| `APP_USERS_PATH` | No | `~/.local/share/{name}/users/` | Per-user data directory (`runtime-contract.md`) |
| `AUTH_AUDIENCE` | No | Derived from the request `Host` | Value `aud` must contain. Set only for a deployment reached by address rather than hostname, or answering on several hostnames |
| `AUTH_EMAIL_CLAIM` | No | `email` | Claim carrying the user's email; namespaced issuers need the full name (e.g. `https://example.com/email`) |
| `AUTH_JWKS_URI` | No | OpenID discovery | Issuer key set location, if discovery is unavailable |

The same settings can be pinned in code with
`App(auth=OAuthResourceServer(issuer=..., email_claim=...))`. The env vars
exist so one build serves any deployment without a code change; do not
add app-specific auth env vars on top of them.

**`AUTH_ISSUER`** must match the token's `iss` byte for byte. A missing or
extra trailing slash is the usual mistake. The startup log line
`mcp_app.startup auth issuer=... audience=... email_claim=... admin_emails=N admission=... max_users=...`
shows what the server is using.

**`ADMIN_EMAILS`** is the whole admin model. Membership in that variable
is what makes an email an administrator: nothing is stored, there is no
promotion path, and changing the set is a redeploy. Compared lower-cased.
An administrator is admitted as a user on first sign-in (the record is
created then), so a fresh deployment needs no `users add` for its
operator. With it empty the server serves registered users but nobody
can call `/admin` or bootstrap the first user; startup logs a warning.

**The server's own URL is not configured.** The audience a token must
carry and the `resource` the discovery document advertises are both
"this server's public URL", and mcp-app derives it from each request's
`Host` header (scheme from the front door's `X-Forwarded-Proto`, which
`serve` honors; host from `Host`, never `X-Forwarded-Host`). On any
hostname-routed front door (Cloud Run, Kubernetes ingress, API gateway,
reverse proxy) that is the same fact that delivered the request, so
there is nothing to configure and nothing to drift against what the
operator registered at the issuer and what users type.

**`AUTH_AUDIENCE`** pins the audience when the derived URL is wrong: the
service is reached by IP, or several hostnames route to it. The
exposure of leaving it derived is small and bounded: an attacker would
need a user's valid token for another mcp-app server behind the same
issuer *and* a way to deliver it to this server under a hostname it
answers to; token lifetime bounds the window. Mention the pin when a
deployment is reached by address; don't push it otherwise.

## What a client sees

| Situation | Response | Meaning |
|---|---|---|
| No token, or invalid (bad signature, wrong `iss`/`aud`, expired, no email claim) | `401` + `WWW-Authenticate: Bearer error="invalid_token", ..., resource_metadata="<base>/.well-known/oauth-protected-resource"` | Authenticate. A standard client follows the pointer, learns the issuer, runs the flow |
| Valid token, email not registered | `403`, no challenge | Identity established; not admitted. Register the user; re-authenticating cannot help |
| Valid token, registered email | Normal MCP response | `current_user` set |
| Valid token, email in `ADMIN_EMAILS`, not registered | Normal MCP response; record created | Operator bootstrap |
| Valid token, unknown email, `AUTH_ADMISSION=open` | Normal MCP response; record created, or `403` "not accepting new users" once `MAX_USERS` is reached | Open admission |
| `GET /.well-known/oauth-protected-resource` | `200` `{"resource": "<base>/", "authorization_servers": [issuer], "bearer_methods_supported": ["header"]}` | Public discovery document; `resource` is the URL the request arrived at |
| `?token=...` on any request | Ignored; `401` as above | Only the `Authorization` header is read |

Per request the identity middleware: takes the bearer token from the
`Authorization` header; verifies the signature against the issuer's JWKS
(fetched from OpenID discovery or `AUTH_JWKS_URI`, cached, refetched once
on an unknown `kid`, asymmetric algorithms only); checks `iss` ==
`AUTH_ISSUER`, `aud` contains the request's base URL (or
`AUTH_AUDIENCE`), and `exp`; reads `AUTH_EMAIL_CLAIM`; loads the user
record for that email (lower-cased) and sets `current_user`.

**The user journey:** the user enters the server URL in their MCP client
and nothing else. The client's first request gets the 401, reads the
discovery document, reads the issuer's own metadata, registers itself
(dynamic client registration, or a client ID metadata document if the
issuer supports it), sends the user to sign in (Google, via the issuer),
and comes back with a token. mcp-app sees only the token. The client
refreshes it itself; no token is ever pasted anywhere.

## Who can sign in

- **Administrators** (`ADMIN_EMAILS`): admitted on first sign-in, may call
  `/admin`.
- **Registered users**: anyone an administrator registered via
  `POST /admin/users`, with an optional profile.
- **Everyone else**: under `AUTH_ADMISSION=allowlist` (default) the issuer
  signs them in and mcp-app answers `403`; under `open` they are admitted
  and registered on their first request, until `MAX_USERS` records exist.
  Open admission suits data-owning apps; an API-proxy app's users still
  need a profile before their first tool call, so until users can supply
  their own backend credentials, open admission only creates empty records.
  Recommend `MAX_USERS` whenever admission is open.

Revoking a user (`DELETE /admin/users/{email}`, `users revoke`) deletes
the record; the next request with their token is a `403`. Re-registering
admits them again. There is nothing else to revoke on this side: the
issuer owns the tokens.

## Admin-only tools

The framework registers `usage_report` on every app. Over HTTP it is
listed and callable only for an `ADMIN_EMAILS` entry; to any other user
it is absent from `tools/list` and a call fails as an unknown tool. Over
stdio the local user is the operator and sees it. This is the hook
per-user tool visibility hangs off; app tools are not filtered per user
today.

## Admin access on a deployment

`/admin` accepts the identity provider's access token for an email in
`ADMIN_EMAILS` — the same kind of token an MCP client obtains. The admin
CLI drives `/admin` only against the local store (`connect local`); its
remote mode supports `health`, `probe` and `register` and does not yet
sign in, so remote `users`, `tools` and `safe-tool` exit with a message
saying so. A device-code `login` is planned; the token slot
(`access_token` in `setup.json`) already exists and nothing writes it.

Until then, on a deployment:

- The common case needs no admin call: the operator is in
  `ADMIN_EMAILS` and is admitted on first sign-in from their MCP client.
- To register another user, call `POST /admin/users` with an
  administrator's access token obtained from the identity provider
  (most providers can issue a test token for a registered API from
  their dashboard):
  ```bash
  curl -X POST https://your-service/admin/users \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"email": "alice@example.com", "profile": {"<field>": "<value>"}}'
  ```
- The MCP admin tools server (`mcp-app admin-tools`) takes the same
  `access_token` argument for its user-management tools.

Say this plainly when an operator asks to add a user to a deployment; do
not invent a `tokens` command or a signing key.

## Setting up the identity provider

Generic steps; provider UIs differ. Confirm each with the operator.

1. **An API (resource)** whose identifier is the server's public URL,
   exactly as users type it, trailing slash included. This is what tokens
   carry as `aud` and what mcp-app derives from `Host`. Refresh tokens
   ("offline access") on.
2. **The login method** users should see (Sign in with Google is a
   common choice); unused methods such as password login off.
3. **Client identification with the server URL alone**: client ID
   metadata documents (CIMD) where the issuer supports them, else
   dynamic client registration (DCR). Confirm: `curl
   <issuer>/.well-known/oauth-authorization-server` must advertise CIMD
   (`client_id_metadata_document_supported: true` plus `none` in
   `token_endpoint_auth_methods_supported`, which is what Claude requires
   to pick CIMD) or list `registration_endpoint`, and list `S256` in
   `code_challenge_methods_supported`. Prefer CIMD: under DCR every fresh
   connection registers a new client at the issuer, which clutters the
   tenant and hits application caps on free plans.
4. **The user's email in access tokens.** If the issuer namespaces custom
   claims, set `AUTH_EMAIL_CLAIM` to the full claim name.
5. **A default audience**, if the issuer needs one to issue JWT (not
   opaque) access tokens when a client sends `resource` rather than
   `audience`: set it to the API identifier.
6. **Default access for third-party clients.** Issuers that treat
   dynamically registered or CIMD clients as third-party applications
   (Auth0 does) refuse them at `/authorize` until the API grants them
   default user-delegated access. The symptom is a generic error page from
   the issuer before any login page; the issuer's logs say "not authorized
   to access resource server".

Then deploy with `AUTH_ISSUER` and `ADMIN_EMAILS`, run
`my-solution-admin probe` (`operate.md`), and sign in from an MCP client.
A worked provider, with the commands rather than the clicks: `auth0.md`.

## Putting a server into an MCP client

`register` prints these for the connected deployment (`operate.md`). No
credential appears in any of them:

```bash
# Claude Code
claude mcp add --transport http -s user my-solution https://your-service/

# Antigravity CLI (agy): one user-level config, no scopes
agy mcp add my-solution https://your-service/
```

```
# Claude.ai and Claude mobile: Settings > Connectors > Add custom connector
https://your-service/
```

Each client signs the user in with the identity provider on first use.
stdio registrations carry nothing either; identity is `--user`.

## Apps with their own `extra_routes`

Routes an app adds via `extra_routes` get no identity middleware; the URL
itself must be the credential (a short-lived signed URL verified in the
handler, `authoring.md`). The app signs those URLs with a secret it owns;
mcp-app has none to lend it.

## Testing without an issuer

`OAuthResourceServer(..., jwks={"keys": [...]})` takes a static key set, so
tests sign tokens with a generated RSA key and run the whole stack
in-process. `mcp_app.testing.issuer.TestIssuer` does exactly that and the
`oauth_env` fixture wires it to the `App`; `testing.md` Step 2 is the
worked example.
