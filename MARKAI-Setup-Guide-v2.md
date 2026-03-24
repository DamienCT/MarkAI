# MARKAI — Service Setup Guide (v2)

## What You Need to Set Up Manually

This guide covers everything that requires manual configuration before the coding agent can build. The coding agent handles all code — you handle accounts, registrations, and secrets.

---

## 1. Microsoft Entra ID — SSO App (You Already Have This)

Confirm the following settings on your existing Entra ID app registration:

**App Registration → Authentication:**
- Redirect URI: `https://markai.yourdomain.com/api/auth/callback/azure-ad`
- Local dev redirect: `http://localhost:3000/api/auth/callback/azure-ad`
- Implicit grant: Enable **ID tokens**
- Supported account types: Single tenant

**App Registration → API permissions:**
- `Microsoft Graph` → `User.Read` (Delegated)
- `Microsoft Graph` → `openid`, `profile`, `email` (Delegated)

**App Registration → Token configuration (recommended):**
- Add optional claims: `email`, `preferred_username` (ID token)

**Values for `.env`:**
```
AZURE_AD_TENANT_ID=       → Overview → Directory (tenant) ID
AZURE_AD_CLIENT_ID=       → Overview → Application (client) ID
AZURE_AD_CLIENT_SECRET=   → Certificates & secrets → Client secret Value
```

---

## 2. Microsoft Entra ID — Fabric / Power BI App

A **separate** app registration for querying Fabric Lakehouse (Business Central tables in `lh_bronze`).

### Create the App Registration

1. **Azure Portal → Microsoft Entra ID → App registrations → New registration**
2. Name: `MARKAI-Fabric-Reader`
3. Supported account types: Single tenant
4. Redirect URI: Leave blank (daemon app)
5. Click **Register**

### Configure API Permissions

1. **API permissions → Add a permission → Power BI Service**
2. Select **Application permissions** (not Delegated)
3. Add: `Dataset.Read.All`, `Workspace.Read.All`
4. Click **Grant admin consent for [your tenant]**

### Create Client Secret

1. **Certificates & secrets → New client secret**
2. Description: `MARKAI Fabric Access`, Expiry: 24 months
3. Copy the **Value** immediately

### Grant Workspace Access in Fabric

1. Go to **Power BI Service** (app.powerbi.com)
2. Navigate to the workspace containing `lh_bronze`
3. **Manage access** → Add `MARKAI-Fabric-Reader` as Viewer or Contributor

### Find IDs

In Power BI Service, navigate to the `lh_bronze` SQL analytics endpoint. The URL contains:
`https://app.powerbi.com/groups/{WORKSPACE_ID}/datasets/{DATASET_ID}`

**Values for `.env`:**
```
FABRIC_TENANT_ID=         → Same as main tenant ID
FABRIC_CLIENT_ID=         → MARKAI-Fabric-Reader → Application (client) ID
FABRIC_CLIENT_SECRET=     → Client secret Value
FABRIC_WORKSPACE_ID=      → From Power BI URL
FABRIC_DATASET_ID=        → From Power BI URL
FABRIC_LAKEHOUSE_NAME=lh_bronze
```

---

## 3. OpenAI API Key (You Already Have This)

Confirm key has access to: `gpt-4o`, `gpt-4o-mini`, `text-embedding-3-small`, `dall-e-3`

```
OPENAI_API_KEY=sk-your-key
```

---

## 4. Social Platform API Setup

**These tokens are now stored in `.env` AND per-brand in the database via the admin portal.** The `.env` values serve as defaults; each brand can override with its own tokens.

### Instagram / Facebook (Meta Business Suite)

1. https://developers.facebook.com → Create app (type: Business)
2. Add **Instagram Graph API** and **Pages API** products
3. Generate a **long-lived page access token** (60-day, or use system user for permanent)
4. Get your **Facebook Page ID** and **Instagram Business Account ID**:
   - Page ID: Go to your Facebook Page → About → Page ID
   - Instagram ID: `GET /me/accounts` → find page → `GET /{page-id}?fields=instagram_business_account`

```
META_ACCESS_TOKEN=your-long-lived-token
META_PAGE_ID=your-facebook-page-id
META_INSTAGRAM_ACCOUNT_ID=your-instagram-business-account-id
```

### LinkedIn

1. https://www.linkedin.com/developers → Create app
2. Request **Share on LinkedIn** and **Sign In with LinkedIn** products
3. Under **Auth** tab, generate an OAuth 2.0 access token with scopes: `w_member_social`, `r_organization_social`
4. Get your **Organization ID** from your LinkedIn company page URL

```
LINKEDIN_ACCESS_TOKEN=your-token
LINKEDIN_ORG_ID=your-org-numeric-id
```

### Adding Platform Credentials Per Brand (Post-Deployment)

In the admin portal under **Brand → Settings → Social Credentials**, you can set brand-specific tokens. This allows different brands to post to different Facebook pages / Instagram accounts / LinkedIn orgs. The `.env` values are used as fallback defaults.

---

## 5. VPS / Server Preparation

**Minimum specs:** 8 GB RAM (16 GB recommended), 4 vCPUs, 100 GB SSD, Ubuntu 24.04 LTS

```bash
sudo apt update && sudo apt upgrade -y
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
sudo apt install docker-compose-plugin -y
docker --version && docker compose version
mkdir -p /opt/markai && cd /opt/markai
```

**DNS records (A records pointing to VPS IP):**
- `markai.yourdomain.com` → frontend
- `api.markai.yourdomain.com` → backend
- `n8n.yourdomain.com` → n8n (social publishing UI)
- `grafana.yourdomain.com` → grafana

**Firewall:** Open ports 80 and 443 only. All internal traffic uses Docker network.

---

## 6. LangSmith Account (Optional but Recommended)

1. https://smith.langchain.com → Create free account
2. Create project: `markai`
3. **Settings → API Keys → Create API Key**

```
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls-your-key
LANGCHAIN_PROJECT=markai
```

Free tier: 5,000 traces/month.

---

## 7. Notification Setup

### Slack Webhook (Recommended)

1. https://api.slack.com/apps → Create New App → Incoming Webhooks
2. Create webhook for your channel

```
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../xxx
```

### Email (Optional)

```
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=notifications@yourdomain.com
SMTP_PASSWORD=your-password
```

---

## 8. n8n Setup (Minimal — Social Publishing Only)

n8n's role is reduced to **three workflows** that handle social platform API calls. After the system is running:

1. Access n8n at `https://n8n.yourdomain.com`
2. Create your admin account
3. **No credentials to set up in n8n** — all tokens are passed in the webhook payload from FastAPI
4. Import the three workflow JSONs (see n8n Workflows document)
5. Activate all three workflows

That's it. n8n receives publish instructions from FastAPI, makes the social API call, and reports back. All scheduling, engagement pulling, and error handling happen inside FastAPI.

---

## 9. Business Central Table Discovery

After the system is running:

```bash
docker compose exec backend python scripts/bc-table-discovery.py
```

Review the output, then update `.env`:

```bash
BC_TABLE_ITEMS=items
BC_TABLE_ITEM_CATEGORIES=item_categories
BC_TABLE_VENDORS=vendors
BC_TABLE_ITEM_ATTRIBUTES=item_attributes
BC_TABLE_ITEM_PICTURES=item_pictures
BC_TABLE_SALES_PRICES=sales_prices
BC_TABLE_ITEM_LEDGER_ENTRIES=item_ledger_entries
```

Restart backend after updating, then trigger initial BC sync from the admin portal.

---

## 10. RTX 4090 GPU Machine (Optional — Later)

Not needed for V1. When ready:
1. Install Ollama: `curl -fsSL https://ollama.com/install.sh | sh`
2. Pull models: `ollama pull llama3`
3. Uncomment local provider in LiteLLM config

---

## Pre-Flight Checklist

- [ ] Entra ID SSO app with correct redirect URIs
- [ ] Entra ID Fabric app with Power BI Service permissions + admin consent
- [ ] Fabric workspace ID and dataset ID noted
- [ ] OpenAI API key active
- [ ] Meta (Facebook/Instagram) access token + page ID + Instagram account ID
- [ ] LinkedIn access token + org ID
- [ ] VPS with Docker installed
- [ ] DNS records created and propagated
- [ ] `.env` file populated with all values
- [ ] (Optional) LangSmith account
- [ ] (Optional) Slack webhook
- [ ] (Optional) SMTP credentials

Once complete, hand the Implementation Plan to your coding agent and start Phase 1.
