# Business Central item-card picture coverage

Date: 2026-08-19
Scope: product images only. Nothing was published, scheduled or approved; no
calendar item was touched; no image was overwritten.

---

## TL;DR

**Coverage cannot be measured yet — the BC API rejects our service principal.**
The code is in place and BC is now the first source in both image paths, but it
stays switched off until one Entra grant and one Business Central setup step are
done. Both take about five minutes and need a tenant admin. Until then nothing
changes: sourcing falls through to the supplier site and web search exactly as
before.

Right now **39 of the 40 active products carry a web-search image and 1 has no
image at all — zero come from Business Central.** That is precisely the problem
this work targets.

---

## Why the pictures were never coming from BC

Two separate causes, both now fixed in code:

1. **The Fabric lakehouse does not have them.** `dbo.itemmodule_item` has 142
   columns and not one is a picture/media/image column. An INFORMATION_SCHEMA
   sweep across the whole lakehouse for `%picture%` / `%media%` / `%image%` /
   `%photo%` returns only `accountingmodule_glaccount.picture`. BC stores item
   pictures as Tenant Media blobs, which the mirror does not replicate. So
   `get_product_image_from_bc()` was a stub returning `None`, and every product
   fell straight through to web search.
2. **The backend never even tried.** `_fetch_one_product_image_via_worker` in
   `backend/app/api/v1/products.py` went directly to the browser-worker web
   search. That is the path that actually populated today's photos — hence
   `"source": "web_search"` on 39 of 40.

Item pictures are only reachable through the **Business Central API v2.0**:

```
GET {base}/v2.0/{tenant}/{environment}/api/v2.0/companies
GET .../companies({companyId})/items?$filter=number eq '{sku}'
GET .../companies({companyId})/items({itemId})/picture
GET <pictureContent@odata.mediaReadLink>        -> the image bytes
```

---

## Access probe result (run 2026-08-19, from inside `markai-agents` on the VPS)

| Step | Result |
| --- | --- |
| Token for `https://api.businesscentral.dynamics.com/.default` — FABRIC app | **OK** |
| Token for the same scope — AZURE_AD app | **OK** |
| `roles` claim in either token | **`null`** — no BC application permission is granted |
| `GET /v2.0/{tenant}/Production/api/v2.0/companies` | **401 `Authentication_InvalidCredentials`** |
| `GET .../Sandbox/...` and other names | 404 `NoEnvironment` |

Two useful conclusions:

* The BC environment is named **`Production`**. It returns 401 (auth rejected)
  while every other name returns 404 (`NoEnvironment`), so the environment
  exists and only authorisation is missing.
* The tenant is `33b8e89b-0b2f-42b1-b59c-835bd0c2ce3c`. Both app registrations
  live there and both can mint a BC-audience token, but neither carries a BC
  role, and neither is registered inside BC itself. That produces exactly the
  401 we see.

---

## The exact grant needed (tenant admin, ~5 minutes)

Do this for the **Fabric app**, client ID `47d43367-a8d9-4d61-9c9a-1678a508ebc7`
(it already holds the Fabric SQL grant, so one app covers both). If you would
rather use a separate app registration, create it and set `BC_API_CLIENT_ID` /
`BC_API_CLIENT_SECRET` / `BC_API_TENANT_ID` in `.env` instead.

### Task 1 — Microsoft Entra admin center (https://entra.microsoft.com)

1. **App registrations** → the app with client ID
   `47d43367-a8d9-4d61-9c9a-1678a508ebc7`.
2. **API permissions** → **Add a permission** → **Microsoft APIs** →
   **Dynamics 365 Business Central**.
3. **Application permissions** → tick **`API.ReadWrite.All`** ("Access to APIs
   and webservices") → **Add permissions**.
   *`Automation.ReadWrite.All` is not needed — we only read item pictures.*
4. **Grant admin consent for &lt;tenant&gt;** on that permission. The row must
   show a green "Granted" tick.

Verification: the client-credentials token's `roles` claim must then contain
`API.ReadWrite.All`. While it is `null`, step 4 has not taken effect.

### Task 2 — inside Business Central (the `Production` environment)

1. Search for and open the **Microsoft Entra Applications** page.
2. **New** → in **Client ID** enter `47d43367-a8d9-4d61-9c9a-1678a508ebc7`.
3. **Description**: e.g. `MARKAI product image sync`.
4. Set **State** to **Enabled**.
5. Assign permission sets — read-only is enough: **D365 BASIC** + **D365 READ**.
   (BC refuses to assign **SUPER** to an application; least privilege applies.)

Both tasks are required. Task 1 alone still returns 401, because BC checks its
own Entra Applications table as well.

Reference: [Using Service to Service Authentication](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/administration/automation-apis-using-s2s-authentication)

---

## Candidate set — what will be probed once access works

40 active products, every one of which already carries a BC item No., so all 40
are probeable.

| BC company | Active products | With a BC item No. | Already have an image |
| --- | ---: | ---: | ---: |
| Naturespan | 25 | 25 | 25 |
| Food-Cosmetic | 15 | 15 | 14 |
| **Total** | **40** | **40** | **39** |

Current image provenance:

| Source | Products |
| --- | ---: |
| `web_search` | 39 |
| none | 1 |
| `business_central` | **0** |

BC companies seen in the lakehouse but with no active products right now:
Healthspan, Medical-Ortho, Auto-Chem, Admin, theshop.

---

## How to get the real number after the grant

```
scp scripts/bc-image-coverage.py markai:/tmp/
ssh markai 'docker cp /tmp/bc-image-coverage.py markai-agents:/tmp/ \
    && docker exec markai-agents python /tmp/bc-image-coverage.py'
```

It is read-only: it lists, per company, which item Nos. have a picture on their
BC item card and which do not, and writes nothing to the database, MinIO or BC.
If access is still missing it stops after a single rejected call and says so.

**No existing image has been or will be overwritten by that script.** To adopt
the BC pictures once the count looks right, use the existing
`POST /api/v1/products/{id}/fetch-images` (or `batch-fetch-images`) endpoints —
they now try BC first, store the picture under
`products/{product_id}/gallery/bc_{item_no}.{ext}`, keep the previous web image
in the gallery, and promote the BC picture to primary.

---

## What the code does while access is missing

Nothing breaks. Every BC failure mode — missing credentials, 401, no picture on
the card, HTTP error — returns `None`, and sourcing continues to the supplier
website and then web search.

One detail worth knowing: the first 401 trips a **15-minute circuit breaker**
keyed on tenant+client+environment. A 600-product sync therefore makes **one**
doomed BC call, not 600. That is visible in the probe output above — it aborted
after the first product with `BC_PROBE=ABORTED (access lost mid-run)`.
