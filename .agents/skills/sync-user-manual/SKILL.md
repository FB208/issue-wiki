---
name: sync-user-manual
description: Preview and synchronize this issue-wiki repository's 使用说明 Markdown documents, matching website folders and document filenames, uploading only locally referenced images, and creating or updating remote content through the deployed admin API. Use when Codex is asked to sync, upload, publish, refresh, or check the 使用说明 documentation on the deployed website.
---

# Sync User Manual

Synchronize `使用说明/` with the deployed issue-wiki website through the deterministic script in `scripts/sync_manual.py`.

## Workflow

1. Work from the repository root.
2. Require `.agents/skills/sync-user-manual/.env.local`. If it is missing, ask the user to copy `.env.example` and fill in the deployed API URL and administrator credentials. Never read the repository-root `.env` or `.env.secrets`.
3. Run the preview command:

   ```powershell
   python .agents/skills/sync-user-manual/scripts/sync_manual.py
   ```

4. Report the preview counts and every validation or duplicate conflict. Do not continue when preview fails.
5. Obtain explicit user confirmation before writing to the deployed website.
6. After confirmation, run:

   ```powershell
   python .agents/skills/sync-user-manual/scripts/sync_manual.py --apply
   ```

7. Report the completed, skipped, and failed operations. Never retry a failed write automatically; a later full rerun is idempotent.

## Safety Rules

- Treat preview login as read-only access. Do not use `--apply` unless the user explicitly confirms the displayed plan.
- Never print passwords, bearer tokens, or authorization headers.
- Never delete remote documents, folders, uploads, comments, or likes.
- Stop before writes when local validation or remote duplicate detection fails.
- Keep `.env.local` and `.sync-state.local.json` untracked.
- Do not contact a production deployment while developing or testing this skill unless the user explicitly requests it.

## Deterministic Behavior

- Map directories below `使用说明/` to website folders; do not create a `使用说明` wrapper folder or image-only folders.
- Match a document by normalized target folder path plus its complete filename stem.
- Preserve unrelated remote content. Synchronize only matched items' content and ordering.
- Upload only referenced local JPG, JPEG, PNG, GIF, or WebP files. Reuse URLs by SHA-256 from the local state file.
- Leave remote, absolute-site, data, and anchor image URLs unchanged.
