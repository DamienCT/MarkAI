# Changelog — feature/enhancements branch

Date: 2026-04-03

## Bug Fixes

### 1. Product images 404
File proxy treated `products/` as a bucket name instead of a path prefix in the default `markai-assets` bucket. Product images now load correctly in the gallery and product list.

### 2. BC Company dropdown shows wrong default
Showed "Link Later" on load because companies were only fetched when the dropdown opened. Now fetches on component mount so the linked company displays immediately.

### 3. Product image swap not working in content generation
Gemini Vision `replace_product` step failed because it downloaded product images from the wrong bucket. Same root cause as bug 1 — fixed the bucket resolution in the agents service.

### 4. Search Web not returning images
DuckDuckGo scraper broke due to vqd token extraction changes. Rewired the product image search to use the browser worker's Playwright-based Google Image Search with DuckDuckGo as fallback.

### 5. Strategy document tables unreadable
`react-markdown` does not support GitHub-Flavored Markdown tables by default. Added `remark-gfm` plugin to all ReactMarkdown usages so tables render with proper columns and borders.

### 6. Onboarding progress mismatch (7/7 vs 5/7)
Overview banner and onboarding panel counted differently because the panel re-fetched products and competitors independently, starting at 0. Now receives initial data from the parent component so both counts match on first render.

### 7. Model discovery shows 0
Was correct behavior when all models were already known, but confusing to the user. Added `total_from_api` and `total_in_db` to the discovery response with a clear error message when the API key is invalid.

### 8. n8n publish preview workflow error
`responseMode: "lastNode"` incompatible with n8n 2.13+. Changed to `"responseNode"` to work with the Respond to Webhook node.

## New Features

### 9. Preview thumbnails for faster loading
Added `?w=WIDTH&q=QUALITY` query parameters to the file proxy endpoint for on-the-fly image resizing via Pillow. Mockup previews and content images load 3-5x faster using lower-quality thumbnails. Full-resolution images served on click to enlarge.

### 10. Discard content button
Red "Discard Content" button on the content detail page for items with status "In Review" or "Reworking". Shows a confirmation dialog before permanently deleting the content and its calendar item.

### 11. Schedule for publishing
Date and time picker card on the content detail page for items with status "Approved". Sets the status to "scheduled" with the chosen `scheduled_at` timestamp. Date and time auto-populate from the calendar item's existing scheduled date.

### 12. Show scheduled time
Content detail page now shows "Scheduled: date at HH:MM" instead of date only. Kanban cards in Content Studio show the time for scheduled status items.

### 13. Calendar items are clickable
Clicking a content item in the Content Calendar navigates to its content detail page. Works in compact view, full grid view, and the expanded day modal.

### 14. Global brand filter applies to all pages
The sidebar brand selector now auto-filters Approvals, Analytics, Intelligence, and Calendar pages when a brand is selected. Content Studio already had this behavior.

### 15. n8n publish preview workflow
New workflow file `markai-publish-preview.json` that accepts the publish webhook, logs all incoming data in n8n Executions, and responds 200 without publishing anything. Used for inspecting caption, image, hashtags, and channel data before setting up real publishing nodes.

## Tests

### 16. File proxy tests (backend/tests/test_file_proxy.py)
10 tests covering bucket routing, path traversal prevention, content type detection, cache headers, thumbnail resize, and default bucket prefix handling.

### 17. Model discovery tests (backend/tests/test_model_discovery.py)
13 tests covering model ID categorization (GPT-4, DALL-E, embeddings, whisper, TTS, o1), response schema validation, and default values.

### 18. Storage path tests (agents/tests/test_storage_paths.py)
8 tests covering path traversal validation, product image path conventions, and bucket resolution logic.

## Infrastructure

### 19. Azure Pipelines CI (azure-pipelines.yml)
CI pipeline for Azure DevOps that runs three stages in parallel on every push and pull request: backend lint and tests, agents tests, frontend lint and build.

### 20. Test guide (docs/TEST_GUIDE_ENHANCEMENTS.md)
Step-by-step test guide for all changes in this branch with expected behavior for each fix and feature.

## Files Changed

Backend:
- backend/app/api/v1/files.py
- backend/app/api/v1/products.py
- backend/app/schemas/ai_model.py
- backend/app/services/ai_model_service.py
- backend/tests/test_file_proxy.py (new)
- backend/tests/test_model_discovery.py (new)

Agents:
- agents/workflows/content/nodes.py
- agents/tests/test_storage_paths.py (new)

Frontend:
- frontend/package.json
- frontend/package-lock.json
- frontend/src/app/analytics/page.tsx
- frontend/src/app/approvals/page.tsx
- frontend/src/app/brands/[id]/page.tsx
- frontend/src/app/content/[id]/page.tsx
- frontend/src/app/content/calendar/page.tsx
- frontend/src/app/intelligence/page.tsx
- frontend/src/app/intelligence/report/[id]/page.tsx
- frontend/src/app/providers/page.tsx
- frontend/src/components/brand/BrandForm.tsx
- frontend/src/components/brand/BrandOnboarding.tsx
- frontend/src/components/content/CalendarView.tsx
- frontend/src/components/content/KanbanBoardInner.tsx
- frontend/src/components/content/PlatformMockups.tsx
- frontend/src/components/ui/safe-render.tsx

Infrastructure:
- azure-pipelines.yml (new)
- docs/n8n-workflows/markai-publish-preview.json (new)
- docs/TEST_GUIDE_ENHANCEMENTS.md (new)
- docs/CHANGELOG_ENHANCEMENTS.md (new)
