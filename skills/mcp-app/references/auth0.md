# Auth0 as the identity provider: the commands, not the clicks

Read this when an app's issuer is an Auth0 tenant: setting one up for the
first app, adding another app to it, or diagnosing a sign-in that fails
at the issuer. `auth.md` is the provider-neutral contract this fulfils;
every step here is one of its numbered items. Everything is a Management
API call through the `auth0` CLI, so it is repeatable and reviewable.
The Auth0 MCP server covers only APIs, Actions and clients; tenant
settings, connections, grants and CIMD need the CLI.

## Prerequisites

- The `auth0` CLI (Homebrew: `brew tap auth0/auth0-cli && brew install
  auth0/auth0-cli/auth0`), logged in once per machine with `auth0 login`
  **as a user** (browser; the credential lands in the OS keychain and
  renews itself). For CI or Terraform use **as a machine** with a client
  scoped to what the job needs.
- `auth0 api <get|post|patch|delete> <path> [--data '<json>']` is the
  whole interface below; `jq` or `python3 -m json.tool` to read output.
- Never paste a Management API token into chat, a file or a shell line.

## Once per tenant

1. **Dynamic client registration** on, so clients without CIMD can still
   register (Claude falls back to it):
   `auth0 api patch tenants/settings --data '{"flags":{"enable_dynamic_client_registration":true}}'`
2. **Resource parameter profile** so Auth0 honors the `resource` an MCP
   client sends when it sends no `audience` (on by default on new
   tenants; confirm): `auth0 api get tenants/settings | grep resource_parameter_profile`
   should read `compatibility`.
3. **CIMD** advertised, and the MCP clients' published identities
   registered once (manual CIMD registration; the "dynamic CIMD" toggle
   is early access and not needed):
   ```bash
   auth0 api patch tenants/settings --data '{"client_id_metadata_document_supported": true}'
   auth0 api post clients/cimd/register --data '{"external_client_id": "https://claude.ai/oauth/mcp-oauth-client-metadata"}'
   auth0 api post clients/cimd/register --data '{"external_client_id": "https://claude.ai/oauth/claude-code-client-metadata"}'
   ```
   Register updates an existing manual CIMD client, so re-running is safe.
   One client then serves every user of that MCP client, and no
   application is created per connection.
4. **The login connection** (Google here), enabled for the default app
   and **promoted to domain level** so third-party (DCR and CIMD) clients
   may use it; the dashboard has no switch for the promotion:
   ```bash
   auth0 api get "connections?strategy=google-oauth2"        # id, or create: auth0 apis ... / dashboard once
   auth0 api patch "connections/<connection-id>" --data '{"is_domain_connection": true}'
   ```
   Unused connections (the username-password database) off for every
   app: `auth0 api patch "connections/<id>" --data '{"enabled_clients": []}'`.
5. **The email claim.** Auth0 refuses standard claim names in access
   tokens, so a post-login Action writes the email under a namespaced
   name; the app sets `AUTH_EMAIL_CLAIM` to it. Create, deploy, **and
   bind** the Action (an unbound Action does nothing):
   ```bash
   auth0 api post actions/actions --data '{"name":"Add email to access token","supported_triggers":[{"id":"post-login","version":"v3"}],"runtime":"node22","code":"exports.onExecutePostLogin = async (event, api) => { const ns = \"https://example.com/\"; if (event.user.email) { api.accessToken.setCustomClaim(`${ns}email`, event.user.email); } };"}'
   auth0 api post "actions/actions/<action-id>/deploy"
   auth0 api patch actions/triggers/post-login/bindings --data '{"bindings":[{"ref":{"type":"action_id","value":"<action-id>"},"display_name":"Add email to access token"}]}'
   ```
   The Action is tenant-wide: every API on the tenant sees the same
   claim name, so pick a namespace that is not one app's.
6. **Default audience** (belt and braces beside the resource profile):
   `auth0 api patch tenants/settings --data '{"default_audience": "https://your-service/"}'`
   is per tenant, so it can name only one API; rely on the resource
   profile for the others.

## Once per app

1. **The API record**, identifier exactly the URL users type, trailing
   slash included, refresh tokens on:
   ```bash
   auth0 api post resource-servers --data '{"name":"my-app","identifier":"https://your-service/","signing_alg":"RS256","allow_offline_access":true,"skip_consent_for_verifiable_first_party_clients":true}'
   ```
2. **Default user-delegated access for third-party clients.** Required:
   DCR and CIMD clients are strict-mode third-party applications and get
   "not authorized to access resource server" at `/authorize` without it,
   whatever the API's user policy says. As the dashboard creates it
   (Applications > APIs > the API > Settings > Default Permissions for
   Third-Party Applications > User-delegated Access = Authorized):
   ```bash
   auth0 api post client-grants --data '{"audience":"https://your-service/","scope":[],"subject_type":"user","default_for":"third_party_clients"}'
   auth0 api get "client-grants?audience=https%3A%2F%2Fyour-service%2F"     # confirm default_for: third_party_clients
   ```
3. Deploy with `AUTH_ISSUER=https://<tenant>/` (trailing slash; it is the
   token's `iss`), `ADMIN_EMAILS`, and `AUTH_EMAIL_CLAIM` set to the
   Action's claim name. Then `my-app-admin probe`, and sign in from an MCP
   client.

## Verify and diagnose

- `curl https://<tenant>/.well-known/oauth-authorization-server` must
  show `client_id_metadata_document_supported: true`, `none` among
  `token_endpoint_auth_methods_supported`, `registration_endpoint`, and
  `S256`.
- `auth0 logs list --number 20` after a failed sign-in: type `f` rows
  carry the reason. "Client … is not authorized to access resource
  server" is the missing per-app grant above; "too_many_entities" on
  registration is the application cap.
- `auth0 apps list` should stay at the first-party apps plus one CIMD
  entry per MCP client; a growing list of third-party "Claude" apps
  means CIMD isn't advertised and DCR is registering per connection.
  Delete the strays once CIMD is on; a deleted client breaks only the
  connections that used it, which re-register on the next connect.
- An administrator's access token for `/admin` calls (registering a
  user under the allowlist policy) comes from a first-party native app
  the CLI logs you into in a browser:
  `auth0 apps create --name "CLI Login Testing" --type native --callbacks http://localhost:8484`
  once, then `auth0 test login <that-client-id> --audience https://your-service/ --json`
  and pipe the token straight into the request; never print it.

## Traps

| Trap | Effect | Fix |
|---|---|---|
| Free plan allows 10 applications and DCR clients count | Registration fails for everyone new once the cap is hit | CIMD (above), delete DCR strays |
| Third-party default access missing on the API | Generic "Oops" page right after the client registers | Per-app step 2 |
| Action created and deployed but not bound | Tokens carry no email; every sign-in ends in `401` | Bind it to `post-login` |
| `AUTH_ISSUER` without the trailing slash | `iss` mismatch, `401` after sign-in | Copy the `issuer` from the tenant's metadata |
| Email claim namespace named after one app | The second app on the tenant reads another product's claim name | Choose a neutral namespace before the second app |
| Deleting a client a user's connection relies on | That user must remove and re-add the connector | Delete only after CIMD is in place |
