# Test Guide — feature/enhancements branch

Branch: `feature/enhancements`
Date: 2026-04-03

---

## Bug Fixes

### 1. Product images not loading
Where: Brands > Products tab > any product with images
Test: Open a product's image gallery. Images that previously showed broken placeholders should now load correctly.
Expected: Product images display in the gallery and as thumbnails in the product list.

### 2. BC Company dropdown shows wrong default
Where: Brands > Edit Brand > Business Central tab
Test: Open a brand that already has a BC company linked (e.g., Healthspan with Barcode.mu). The dropdown should immediately show the linked company, not "Link Later".
Expected: Linked company name visible on first render without needing to click the dropdown.

### 3. Product image swap missing in content
Where: Content Studio > open any content item with a product
Test: Trigger new content generation for a product that has gallery images. The generated image should include the real product photo (swapped via Gemini Vision) instead of a generic lifestyle image.
Note: Only applies to newly generated content. Existing content will not change retroactively.

### 4. Slow content mockup preview
Where: Content Studio > open any content > Preview tab
Test: The mockup image should load noticeably faster than before. A lower-quality thumbnail loads first for the inline preview. Clicking to enlarge (in Platform Previews) shows the full-resolution image.
Expected: Preview loads in under 1-2 seconds instead of 5-10 seconds.

### 5. Search Web not returning images
Where: Brands > Products > click image icon on a product > Search Web button
Test: Click "Search Web" on a product that has no images. It should find and save product images from the web.
Expected: 1-3 images appear in the gallery after search completes.

### 6. Strategy document tables unreadable
Where: Intelligence tab > Content Calendar Strategy > View Full Report
Test: Scroll to the Yearly Overview table and monthly theme tables in the strategy document.
Expected: Markdown tables render as proper formatted tables with columns and borders, not raw pipe characters.

### 7. Onboarding progress mismatch (7/7 vs 5/7)
Where: Brands > any brand > Overview tab > click the setup progress banner
Test: Compare the count on the overview banner with the count inside the onboarding panel.
Expected: Both numbers match (e.g., both show 7/7 or both show 5/7).

### 8. Model discovery shows 0
Where: AI Providers page > Discover Models button
Test: Click "Discover Models". Check the result message.
Expected: Shows how many models were fetched from the OpenAI API and the total available in the database. If the API key is invalid, a clear error message appears: "OpenAI API returned 0 models - check your OPENAI_API_KEY."

---

## New Features

### 9. Global brand filter applies to all tabs
Where: Sidebar brand dropdown (top-left, e.g., select "Medical-Johnson")
Test: Select a specific brand in the sidebar, then navigate to each of these pages:
- Content Studio (already worked before)
- Calendar
- Approvals
- Analytics
- Intelligence
Expected: Each page automatically filters to show only the selected brand's data without needing to manually set a filter.

### 10. Discard content button
Where: Content Studio > open a content item with status "In Review" or "Reworking"
Test: Look for the red "Discard Content" button on the right sidebar.
Steps:
1. Click the button
2. Confirm the dialog
3. Verify the content is removed and you are redirected to Content Studio
Expected: Content and its calendar item are permanently deleted.

### 11. Schedule for publishing
Where: Content Studio > open a content item with status "Approved"
Test: Look for the "Schedule for Publishing" card on the right sidebar.
Steps:
1. Select a date (must be today or later)
2. Select a time (defaults to 09:00)
3. Click "Schedule & Publish"
4. Verify the status changes to "scheduled" in the calendar
Expected: Content moves to "scheduled" status. The publish checker will dispatch it to n8n at the scheduled time (checks every 15 minutes).

### 12. Calendar items are clickable
Where: Calendar page > any content item on the calendar
Test: Click a content item displayed on the calendar grid.
Expected: Navigates to the content detail page for that item. Works in compact view, full grid view, and the expanded day modal.

### 13. n8n publish preview workflow
Where: n8n dashboard
Steps:
1. Import docs/n8n-workflows/markai-publish-preview.json into n8n
2. Activate the workflow
3. Approve and schedule a content item in the app
4. Wait for the publish checker to dispatch (up to 15 minutes)
5. Check n8n Executions tab
Expected: The execution shows the incoming data: content_id, channel, caption, hashtags, image_url, brand_name. Nothing is actually published.
Note: The calendar item status will stay at "publishing" since the preview workflow does not call back to the app.

### 14. Azure Pipelines CI
Where: Azure DevOps > Pipelines
Steps:
1. Go to Pipelines > New Pipeline
2. Select Azure Repos Git > MARK AI repo
3. It auto-detects azure-pipelines.yml > click Run
Expected: Three stages run in parallel: Backend (lint + tests), Agents (tests), Frontend (lint + build). All should pass.

---

## Files Changed

Backend:
- backend/app/api/v1/files.py (bucket routing fix, thumbnail resize)
- backend/app/api/v1/products.py (Search Web rewired to browser worker)
- backend/app/schemas/ai_model.py (discovery response schema)
- backend/app/services/ai_model_service.py (discovery diagnostics)

Agents:
- agents/workflows/content/nodes.py (product image download bucket fix)

Frontend:
- frontend/package.json + package-lock.json (added remark-gfm)
- frontend/src/app/content/[id]/page.tsx (discard, schedule, thumbnail)
- frontend/src/app/content/calendar/page.tsx (brand filter, item click)
- frontend/src/app/approvals/page.tsx (brand filter)
- frontend/src/app/analytics/page.tsx (brand filter)
- frontend/src/app/intelligence/page.tsx (brand filter)
- frontend/src/app/intelligence/report/[id]/page.tsx (remark-gfm tables)
- frontend/src/app/providers/page.tsx (discovery diagnostics UI)
- frontend/src/app/brands/[id]/page.tsx (onboarding props)
- frontend/src/components/brand/BrandForm.tsx (BC dropdown fix)
- frontend/src/components/brand/BrandOnboarding.tsx (initial data props)
- frontend/src/components/content/CalendarView.tsx (click navigation)
- frontend/src/components/content/PlatformMockups.tsx (thumbnail URLs)
- frontend/src/components/ui/safe-render.tsx (remark-gfm)

Tests:
- backend/tests/test_file_proxy.py (10 tests)
- backend/tests/test_model_discovery.py (13 tests)
- agents/tests/test_storage_paths.py (8 tests)

Infrastructure:
- azure-pipelines.yml (CI pipeline for ADO)
- docs/n8n-workflows/markai-publish-preview.json (preview workflow)
