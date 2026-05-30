# DropItX — Competitor Feature Gap Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Add all missing features to close the gap with WeTransfer, SendAnywhere, and other file sharing competitors.

**Architecture:** Backend adds multi-file + general file support, download limits, custom expiration, QR codes, bulk zip download, comments, version history. Frontend adds corresponding UI for all features.

**Tech Stack:** FastAPI (backend), Next.js 16 + Supabase (frontend), Supabase Storage + Postgres (data).

---

## Workstream A: Backend (dropitx-be)

### Task A1: Multi-file Upload Endpoint
- **File:** `app/internal/upload.py` — add `POST /api/upload/batch`
- Accept `List[UploadFile]`, create a `share_group` record linking multiple shares
- New DB table: `share_groups` (id, slug, user_id, created_at)
- Add `group_id` column to `shares` table
- Each file gets its own slug + storage_path, grouped under one URL
- Return group slug + individual file URLs

### Task A2: General File Type Support
- **File:** `app/internal/upload.py` — expand `_ALLOWED_TYPES`
- Add common types: PDF, images, video, audio, archives, documents
- Remove HTML/MD-only restriction
- Store file type in `mime_type`, skip `extract_text` for non-text files
- Max size varies by type (50MB text, 500MB general)

### Task A3: Download Limit
- **File:** `models/share.py` — add `max_downloads` field
- **File:** `app/public/shares.py` — check download count before serving
- New column `max_downloads INT DEFAULT NULL` on `shares`
- New column `download_count INT DEFAULT 0` on `shares`
- Increment on each download, return 410 Gone when exceeded
- **File:** `app/internal/upload.py` — accept `max_downloads` param

### Task A4: Custom Expiration
- **File:** `app/internal/upload.py` — accept `expires_in` param (1h, 6h, 24h, 7d, 30d, custom)
- **File:** `app/internal/publish.py` — same
- Update share creation to set `expires_at` based on user choice
- Default stays 30 days

### Task A5: QR Code Generation
- **File:** `app/public/qrcode.py` — new endpoint `GET /api/qr/{slug}`
- Use `qrcode` library to generate PNG QR code for share URL
- Return image/png response with caching headers

### Task A6: Bulk Download (Zip)
- **File:** `app/public/shares.py` — new endpoint `GET /api/download/group/{group_slug}`
- Fetch all files in the group from Supabase Storage
- Zip in memory, stream response with `application/zip`
- Set Content-Disposition filename to group slug

### Task A7: Comments/Feedback
- **File:** `app/public/comments.py` — new router
- New table: `share_comments` (id, share_slug, user_id nullable, author_name, content, created_at)
- `GET /api/comments/{slug}` — list comments (paginated)
- `POST /api/comments/{slug}` — add comment (optional auth)
- Rate limited

### Task A8: Version History
- **File:** `app/internal/publish.py` — on update, save old version
- New table: `share_versions` (id, share_slug, content_text, storage_path, version_num, created_at)
- `GET /api/shares/{slug}/versions` — list versions
- `GET /api/shares/{slug}/versions/{num}` — get specific version
- Auto-increment version number

### Task A9: Migration File
- **File:** `supabase/migrations/` — new migration for all new tables/columns
- `share_groups`, `share_comments`, `share_versions` tables
- `max_downloads`, `download_count`, `group_id` columns on `shares`

---

## Workstream B: Frontend (dropitx)

### Task B1: Multi-file Upload UI
- **File:** `components/multi-file-upload.tsx` — new component
- Drag-and-drop zone accepting multiple files
- Show file list with progress bars
- Single "Upload All" button → calls batch endpoint
- Display group share URL after upload

### Task B2: General File Upload Support
- **File:** Update upload zone to accept all file types
- Show file type icons (PDF, image, video, etc.)
- File size validation per type
- Preview for images, PDF; icon for others

### Task B3: Download Limit Setting
- **File:** `components/editor-publish-bar.tsx` — add max_downloads input
- **File:** `components/multi-file-upload.tsx` — same
- Optional field: "Max downloads" (unlimited by default)

### Task B4: Custom Expiration Selector
- **File:** `components/expiration-select.tsx` — new component
- Options: 1 hour, 6 hours, 24 hours, 7 days, 30 days, custom date
- Add to publish bar and upload form

### Task B5: QR Code Display
- **File:** `components/qr-code-button.tsx` — new component
- Button on share page → opens modal with QR code image
- Fetch from `/api/qr/{slug}`
- Copy QR as image button

### Task B6: Bulk Download Button
- **File:** `components/bulk-download-button.tsx`
- On group share page: "Download All" button
- Calls `/api/download/group/{slug}`, triggers browser download

### Task B7: Upload Progress Bar
- **File:** `components/upload-progress.tsx` — new component
- Use XMLHttpRequest or fetch with progress events
- Show percentage, speed, ETA
- Animated progress bar

### Task B8: Comments Section
- **File:** `components/comments-section.tsx` — new component
- Display on share page below content
- Comment form (name + content for anonymous, just content for authed)
- Paginated comment list with timestamps

### Task B9: Version History UI
- **File:** `components/version-history.tsx` — new component
- On dashboard share detail: version list
- Click to view old version in diff view or read-only
- Restore button to revert

### Task B10: Download Page Redesign
- **File:** Update share page (`/s/[slug]`) to show:
  - File type icon + file info
  - Download button with count remaining
  - QR code button
  - Comments below
  - Group file list with individual download buttons
