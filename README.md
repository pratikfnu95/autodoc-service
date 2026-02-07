# autodoc-service

Minimal Flask webhook service to:
1. Receive GitHub `push` events
2. Check if push is on `main`
3. Discover all `.py` scripts at `head` and compare with changes
4. Generate structured, enterprise-style technical docs per script via DeepSeek
5. Keep Confluence in sync:
   - create page for new script
   - update page when script changes
   - delete page when script is removed

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Health check:

```bash
curl http://localhost:5000/health
```

## GitHub webhook setup

- Payload URL: `http://<your-host>/webhook/github`
- Content type: `application/json`
- Event: `Just the push event`
- Secret: same as `GITHUB_WEBHOOK_SECRET` in `.env`

For your repo `https://github.com/pratik03071995/AgenticPOC.git`:

1. Open `AgenticPOC` on GitHub
2. Go to `Settings` -> `Webhooks` -> `Add webhook`
3. Set:
   - Payload URL: `https://<your-public-url>/webhook/github`
   - Content type: `application/json`
   - Secret: same value as `GITHUB_WEBHOOK_SECRET` in this service `.env`
   - Events: `Just the push event`
   - Active: checked

If running Flask locally, expose it first (example):

```bash
ngrok http 5000
```

Then use the `https://...ngrok.../webhook/github` URL as payload URL.

## GitHub token setup

Create a fine-grained token for account `pratik03071995` with:
- Repository access: `AgenticPOC` (or selected repos)
- Permission: `Contents: Read-only`

Put it in this service `.env`:

```env
GITHUB_TOKEN=your_github_token
```

## Validate DeepSeek first (before Confluence)

Keep Confluence disabled initially:

```env
ENABLE_CONFLUENCE=false
```

When a push webhook is processed, response JSON includes:
- `results[]` (one item per changed python script)
- `results[].deepseek.status` and `results[].deepseek.summary`
- `results[].confluence.status` (`published`, `updated`, `skipped`, or `failed`)

After DeepSeek is working, enable Confluence:

```env
ENABLE_CONFLUENCE=true
```

### Local testing shortcut

If you want to test with `curl` without computing GitHub signature:

1. Set `ALLOW_UNSIGNED_WEBHOOKS=true` in `.env`
2. Restart Flask app

## Step-by-step plan

- Step 1 (this commit): basic working scaffold
- Step 2: add GitHub token/private repo support + better error handling
- Step 3: add logging + retries + idempotency
- Step 4: add tests and Docker
