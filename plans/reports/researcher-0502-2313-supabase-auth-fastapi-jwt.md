# Research: Supabase Auth for FastAPI JWT Verification

**Date:** 2026-05-02
**Status:** Complete
**Sources:** Supabase official docs (6 pages), project codebase analysis (4 files)

---

## A) Email/Password Auth

**Does Supabase provide this out-of-the-box?** Yes. Supabase Auth service (GoTrue-based) handles signup, login, password reset, email verification entirely server-side. No backend code needed.

**What the frontend does:**
```js
// Signup
const { data, error } = await supabase.auth.signUp({
  email: 'user@example.com',
  password: 'securepassword'
})

// Login
const { data, error } = await supabase.auth.signInWithPassword({
  email: 'user@example.com',
  password: 'securepassword'
})
```

Supabase Auth creates a row in `auth.users`, sends confirmation email (configurable), issues JWT on successful login.

**Backend changes:** None. DropItX API already verifies JWTs via `core/security.py:verify_supabase_jwt()`. Email/password users produce the same JWT structure as any other auth method.

---

## B) Social Login (OAuth)

**How it works:** Supabase Auth acts as OAuth relayer. Flow:

1. Frontend calls `supabase.auth.signInWithOAuth({ provider: 'google' })`
2. Supabase redirects user to provider consent screen
3. User authorizes -> provider redirects to `https://<project-ref>.supabase.co/auth/v1/callback`
4. Supabase Auth exchanges code for tokens, creates/updates `auth.users` row, issues Supabase JWT
5. Frontend receives session with access token + refresh token

**Configuration needed (Supabase Dashboard only):**
- Enable provider under Authentication > Providers
- Set OAuth app credentials (client ID, secret) from Google Cloud Console / GitHub Settings
- Configure redirect URLs under Authentication > URL Configuration

**Supported providers:** Google, GitHub, Apple, Facebook, Twitter/X, Discord, Twitch, Spotify, LinkedIn, Slack, and 20+ more.

**Two flows:**
- **Implicit flow** (default): Token returned in URL hash. Simpler, client-side only.
- **PKCE flow** (server-side): Authorization code exchanged at callback endpoint. More secure for SSR apps.

**Backend changes:** None. OAuth login produces the same JWT as email/password.

---

## C) JWT Verification — Same JWT for All Methods?

**Yes. All auth methods produce identical JWT structure.** Supabase Auth always signs JWTs with RS256 using the same JWKS key pair regardless of how the user authenticated.

**JWT structure (consistent across all methods):**
```
header:  { "alg": "RS256", "typ": "JWT", "kid": "<key-id>" }
payload: {
  "sub": "<user-uuid>",        // user ID — primary identifier
  "email": "<email>",
  "role": "authenticated",
  "aud": "<supabase-url>",     // verified in core/security.py
  "iss": "<supabase-url>",
  "exp": <timestamp>,
  "iat": <timestamp>,
  "app_metadata": { "provider": "email"|"google"|"github"|... },
  "user_metadata": { ... }
}
```

**Why existing verification works for all methods:**
- `verify_supabase_jwt()` in `core/security.py` validates RS256 signature against JWKS from `{supabase_url}/auth/v1/.well-known/jwks.json`
- Same JWKS endpoint serves keys for all auth methods
- `kid` header matches the same signing key regardless of `app_metadata.provider`
- Audience check (`aud = supabase_url`) is provider-agnostic
- `sub` claim is always a UUID from `auth.users` table — same table for all auth methods

**JWKS cache:** 10-minute TTL (`_JWKS_TTL = 600`). Matches Supabase Edge cache duration. Safe — key rotation is rare and cached entries expire quickly enough.

---

## D) Backend Changes for Social Login vs Email/Password?

**Zero backend changes needed.**

DropItX API is properly architected as a pure JWT verifier. The auth method is opaque to the backend:

1. `get_current_user()` extracts Bearer token -> calls `verify_supabase_jwt()` -> returns `User(id=sub, email=email)`
2. It does not inspect `app_metadata.provider` or any auth-method-specific claims
3. The User dataclass only carries `id` and `email` — both are universal across all auth methods

**If you ever need to know the auth provider** (analytics, conditional logic):
- Available in `app_metadata.provider` claim
- Accessible via `payload.get("app_metadata", {}).get("provider")` in `verify_supabase_jwt()` return value
- Currently not extracted in `get_current_user()` — by design, since it's not needed

---

## Recommendation

**No action required.** The existing JWT verification pipeline (`core/security.py` + `app/dependencies.py`) is auth-method-agnostic by design. Adding Google/GitHub/social login is purely a frontend + Supabase Dashboard configuration task. The backend already handles JWTs from any Supabase Auth method correctly.

---

## Source Credibility

| Source | Type | Reliability |
|--------|------|-------------|
| Supabase Auth Overview (official docs) | Primary | High |
| Supabase JWT docs (official) | Primary | High |
| Supabase Auth Architecture (official) | Primary | High |
| Google provider setup (official) | Primary | High |
| GitHub provider setup (official) | Primary | High |
| `core/security.py` code analysis | Direct | High |
| `app/dependencies.py` code analysis | Direct | High |

---

## Limitations

- Did not research SSO/SAML (enterprise feature, likely not needed for DropItX)
- Did not research magic link / phone OTP flows (same conclusions apply, but not explicitly verified)
- Did not test JWT payload differences empirically — conclusions based on Supabase official documentation and architecture design
- Refresh token handling is frontend-only; backend implications not covered (not relevant since backend only validates access tokens)
