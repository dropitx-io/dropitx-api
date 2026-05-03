# Hosting Platform Comparison for DropItX API

**Date:** 2026-05-02
**Scope:** 8 alternative platforms for FastAPI (Python 3.12+, uvicorn) hosting
**Current:** Render free tier (cold starts, limited compute)

---

## Executive Summary

**Ranked recommendation:** Koyeb (free tier) > Railway ($5/mo) > Hetzner + Coolify ($3-5/mo, self-managed) > Fly.io ($2-6/mo) > Northflank (free sandbox) > DigitalOcean App Platform ($5/mo) > Vercel (ELIMINATED).

For immediate zero-cost migration from Render: **Koyeb**. For predictable paid production: **Railway Hobby**. For maximum control at lowest cost: **Hetzner CX23 + Coolify**.

---

## Architecture Fit Assessment

DropItX API requirements that constrain platform choice:

| Requirement | Implication |
|---|---|
| JWKS cache (long-lived in-memory) | No serverless. Need persistent process or accept cache misses on every cold start |
| Supabase admin client (singleton) | Same as above -- cold starts re-initialize, adding latency |
| uvicorn ASGI | Must support Dockerfile or native Python process |
| CORS via `ALLOWED_ORIGINS` env var | Need stable domain or easy custom domain |
| `asyncio.to_thread()` for Supabase sync client | Thread pool needs real CPU, not serverless function |
| Low traffic (personal/small team) | Free or cheap tiers are viable |

**Critical constraint:** This app is fundamentally incompatible with serverless/FaaS platforms. Long-lived in-process state (JWKS cache, Supabase client instances) means persistent compute is required.

---

## Comparison Table

| Platform | Free Tier | Cold Starts | Python/FastAPI | Min Paid Cost | Custom Domain | Deployment | Bandwidth |
|---|---|---|---|---|---|---|---|
| **Koyeb** | 1 web service, 512MB, 0.1 vCPU, always-on | None (always-on) | Dockerfile native | $5/mo (2 vCPU, 4GB) | Yes (free) | Git/Docker | 100GB free |
| **Railway** | $5 trial credit (one-time) | None (always-on) | Dockerfile / Nixpacks | $5/mo Hobby (includes $5 usage) | Yes (free) | Git/Docker | Usage-based |
| **Fly.io** | None for new customers (since Oct 2024) | None (VM always-on) | Dockerfile native | ~$2-6/mo (shared VM) | Yes (free) | Docker/CLI | 160GB free |
| **DO App Platform** | Static sites only | None (persistent) | Dockerfile / Buildpack | $5/mo (512MB, 1 vCPU) | Yes (free) | Git/Docker | Included |
| **Vercel** | Serverless functions | **YES - every request** | Edge/Serverless only (limited) | $20/mo Pro | Yes | Git | 100GB free |
| **Northflank** | Sandbox: 2 services, 512MB ea | None (always-on) | Dockerfile native | ~$10/mo (1 vCPU, 1GB) | Yes (paid plan) | Git/Docker | 100GB free |
| **Hetzner Cloud** | None | None (VPS always-on) | Full OS control (Docker) | EUR 3.49/mo (CX23: 2 vCPU, 4GB) | Yes (free, bring own) | Manual/Docker/SSH | 20TB included |
| **Coolify** | Free software | None (always-on) | Docker native (runs on your VPS) | VPS cost only (~EUR 3.49/mo on Hetzner) | Yes (auto SSL) | Git/Docker | VPS bandwidth |

---

## Platform Deep-Dive

### 1. Koyeb -- RECOMMENDED (Free Tier)

- **Free tier:** 1 web service, 512MB RAM, 0.1 vCPU (shared), always-on, no credit card required
- **Why it fits:** Always-on compute = JWKS cache and Supabase client stay warm. Dockerfile deployment matches current workflow. No cold starts.
- **Scaling:** Paid tier at $5/mo gets 2 vCPU, 4GB RAM. Generous upgrade path.
- **Gotchas:** 0.1 vCPU is very limited. May struggle under concurrent `asyncio.to_thread()` calls. Free tier limited to 1 service (no separate staging).
- **Sources:** koyeb.com/pricing (official), community docs

**Fit score: 9/10** -- Best free-tier option for this architecture.

### 2. Railway -- RECOMMENDED (Paid Tier)

- **Pricing:** Hobby plan $5/mo includes $5 usage credit. Usage-based beyond that. No free tier (trial only).
- **Why it fits:** Always-on instances, native Dockerfile/Nixpacks, excellent DX (Git push to deploy), stable custom domains.
- **Scaling:** Auto-scales with usage. $5 covers small production workload easily.
- **Gotchas:** Usage-based billing can surprise if traffic spikes. No true free tier. Execution time + memory billed.
- **Sources:** railway.app/pricing (official), community

**Fit score: 8/10** -- Best paid option for DX and simplicity.

### 3. Hetzner Cloud + Coolify -- Best Value (Self-Managed)

- **Pricing:** Hetzner CX23 = EUR 3.49/mo (2 vCPU, 4GB RAM, 40GB NVMe). Coolify = free software.
- **Why it fits:** Massive compute for the price. 2 vCPU + 4GB is 10x what any PaaS offers at $5/mo. Full OS control. Coolify adds Heroku-like DX (Git push deploy, auto SSL, web UI).
- **Setup effort:** Install Coolify on Hetzner VPS (~15 min one-time), then use web UI or Git push for deploys.
- **Gotchas:** You own the server. OS patches, firewall config, Coolify updates are your responsibility. No managed SSL termination (Coolify handles Let's Encrypt automatically though). Server in EU (Germany/Finland) -- consider latency if users are in US.
- **Sources:** hetzner.com/cloud/pricing (official), coolify.io (official)

**Fit score: 8/10** -- Best raw value, but requires ops willingness.

### 4. Fly.io -- Decent but No Free Tier

- **Pricing:** PAYG only. Shared-cpu-1x (256MB) ~$1.94/mo. shared-cpu-1x (512MB) ~$3.87/mo. Add ~$2/mo for IPv4 if needed.
- **Why it fits:** Docker-native, always-on VMs, global edge routing, good CLI tooling.
- **Gotchas:** No free tier for new customers since Oct 2024. Requires credit card. IPv4 is extra ($2/mo). Billing complexity (volume fees, bandwidth overages). Fly.io has had stability incidents in 2024.
- **Sources:** fly.io/pricing (official), community forums, status page

**Fit score: 6/10** -- Good tech, but pricing opacity and no free tier are deterrents.

### 5. Northflank -- Viable Free Sandbox

- **Free tier:** Sandbox with 2 services, 512MB RAM each, always-on. No credit card.
- **Why it fits:** Always-on containers, Dockerfile support, includes observability (metrics, logs).
- **Gotchas:** Sandbox has resource limits and may be throttled. Custom domains require paid plan. Smaller community, less documentation. EU-based only currently.
- **Sources:** northflank.com/pricing (official)

**Fit score: 6/10** -- Functional free tier but limited growth path.

### 6. DigitalOcean App Platform -- Overpriced for This Use Case

- **Pricing:** Free tier = static sites only (no Python). Basic tier = $5/mo (512MB, 1 vCPU container).
- **Why it fits:** Standard PaaS, Dockerfile support, managed infra, good docs.
- **Gotchas:** At $5/mo you get less compute than Railway or Hetzner. No free tier for dynamic apps. Platform has had slow deployment times reported.
- **Sources:** digitalocean.com/pricing/app-platform (official)

**Fit score: 5/10** -- Nothing wrong, but outcompeted on price/features by Railway and Koyeb.

### 7. Vercel -- ELIMINATED

- **Why eliminated:** Serverless architecture. Each request runs in an isolated function. JWKS cache (`cache=True` on PyJWKClient) will never persist between requests. Supabase client re-initialized every invocation. `asyncio.to_thread()` has limited thread pool in serverless. Python support is limited (Vercel's Python runtime is designed for simple serverless functions, not ASGI apps).
- **Serverless cold starts:** 500ms-2s per invocation for Python. Compounds with JWKS fetch + Supabase init.
- **Verdict:** Architecturally incompatible. Do not use.

**Fit score: 0/10** -- Fundamental architecture mismatch.

---

## Trade-Off Matrix

| Dimension | Koyeb Free | Railway $5 | Hetzner+Coolify $3.5 | Fly.io $4 | DO App $5 |
|---|---|---|---|---|---|
| Compute (vCPU) | 0.1 shared | Variable | 2 dedicated | 1 shared | 1 shared |
| RAM | 512MB | Variable | 4GB | 512MB | 512MB |
| Cold starts | None | None | None | None | None |
| DX (deploy ease) | High | Highest | Medium | High | High |
| Ops burden | Zero | Zero | Medium | Low | Zero |
| Scaling ceiling | Medium | High | Very high | High | Medium |
| Predictable cost | Yes (free) | Mostly | Yes (fixed) | No (usage) | Yes (fixed) |
| Long-lived conn support | Full | Full | Full | Full | Full |

---

## Ranked Recommendation

### Tier 1: Migrate Immediately (Zero Cost)

**1. Koyeb Free Tier**
- Move from Render free to Koyeb free. Same Dockerfile, better compute, no cold starts.
- Risk: 0.1 vCPU may feel slow under concurrent load. Monitor and upgrade to paid if needed.
- Migration effort: ~1 hour (create Koyeb app, point env vars, update custom domain).

### Tier 2: Ready for Production ($5/mo)

**2. Railway Hobby**
- Best DX of any paid option. Git push deploys, generous $5 included usage, zero ops.
- Migration effort: ~30 min. Almost identical to Render workflow.

**3. Hetzner CX23 + Coolify**
- Best raw value: 2 vCPU, 4GB RAM for EUR 3.49/mo. But you manage the server.
- Migration effort: ~2-3 hours (provision VPS, install Coolify, configure Docker deploy).

### Tier 3: Acceptable Alternatives

**4. Fly.io** -- Good technology, pricing opacity is the main concern.
**5. Northflank** -- Functional free sandbox, limited growth path.
**6. DigitalOcean App Platform** -- Fine but overpriced vs competitors.

### Eliminated

**7. Vercel** -- Serverless architecture fundamentally incompatible with this app's long-lived connection requirements.

---

## Migration Path (Recommended)

1. **Now:** Deploy to Koyeb free tier. Validate all endpoints work. Keep Render as fallback.
2. **If Koyeb free is sufficient:** Done. Monitor for performance limits.
3. **If needing more compute:** Upgrade Koyeb to paid ($5/mo) OR migrate to Railway ($5/mo).
4. **If wanting maximum control:** Set up Hetzner + Coolify for EUR 3.49/mo.

---

## Unresolved Questions

- **Koyeb 0.1 vCPU real-world benchmark needed:** Will `asyncio.to_thread()` + Supabase sync calls feel sluggish under concurrent load? Only testing will confirm.
- **Hetzner EU latency:** If DropItX users are primarily in US/Asia, Hetzner's EU-only locations may add ~100-150ms latency. US locations (Ashburn, Hillsboro) are available at same price.
- **Railway usage billing ceiling:** At what traffic level does the $5 credit run out? Need real usage data to predict.
- **Coolify maintenance burden:** How often do Coolify updates require intervention? Unknown without community reports.

---

## Sources

- Koyeb: koyeb.com/pricing (official pricing page)
- Railway: railway.app/pricing (official pricing page)
- Fly.io: fly.io/pricing (official pricing page)
- DigitalOcean: digitalocean.com/products/app-platform (official)
- Vercel: vercel.com/pricing (official pricing page)
- Northflank: northflank.com/pricing (official pricing page)
- Hetzner: hetzner.com/cloud/pricing (official pricing page, accessed 2026-05-02)
- Coolify: coolify.io (official homepage, open-source, free software)
