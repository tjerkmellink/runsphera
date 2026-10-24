# Runner's diary

> Free-text notes per day or per run, optional mood emoji, three editing surfaces, single source of truth in the `diary_entries` table.

## Purpose

A coach needs to know how the runner *felt*, not just how fast they ran. The diary captures the qualitative side — soreness, sleep, life stress, weather, race plans — and surfaces it back to the LLM coach as recent context. Three entry types exist, all in one table:

1. **Freestanding entries** — a daily note tied to a date, no other anchor.
2. **Activity-linked entries** — tied to a specific completed run (`activity_id`).
3. **Workout-linked entries** — tied to a specific planned workout (`plan_workout_id`). Scaffolded but not yet used in the UI.

## How it works (user view)

### Dashboard — Today's note

A small editor card on the dashboard (below the coach banner). One freestanding entry per date. Mood emoji optional. Saving with an empty body and no mood deletes the entry.

### Run-detail modal — How did it go?

Open any recent run from the dashboard. The modal shows the standard per-run detail (HR zones, splits, Garmin's feel + RPE) plus an inline diary editor titled "How did it go?". One entry per `activity_id` — re-saving updates.

### Diary timeline — `/diary`

The dedicated `/diary` route shows every entry as a vertical timeline:
- **Top-of-page form** for adding (or backfilling) an entry on any date. Date picker capped at today; same mood dial + textarea as elsewhere.
- **Vertical accent-colored line** with one dot per entry. Newest at the top, oldest at the bottom. Week markers are muted dividers.
- **Inline edit** — a small ✎ button on each card swaps it into an edit form. ✕ cancels, Save commits. Empty body + no mood deletes (consistent with the upsert pattern).
- Entries linked to an activity show a "Run" badge with the activity name; entries linked to a planned workout show a "Planned" badge with the workout's color stripe.

## How it works (implementation)

### Modules

- [running_coach/diary.py](../running_coach/diary.py) — all CRUD + label helpers. Key functions:
  - `upsert_for_activity(conn, activity_id, body, mood, entry_date=None)` — used by the run-detail modal.
  - `upsert_for_date(conn, entry_date, body, mood)` — used by the dashboard's Today's note and the `/diary` backfill form.
  - `update_entry(conn, entry_id, body, mood)` — used by the timeline inline edit.
  - `list_entries(conn, limit=200)` — joined query returning entries with linked activity / workout details.
  - `group_by_iso_week(entries)` — for the timeline's weekly markers.
  - `get_entry_with_links(conn, entry_id)` — single-row version of `list_entries` shape.
  - Plus mood emoji + Garmin feel/RPE label helpers (`mood_emoji`, `mood_label`, `garmin_feel_label`, `garmin_rpe_label`).

### Templates

- [diary.html](../running_coach/web/templates/diary.html) — the `/diary` page (backfill form + timeline).
- [_diary_entry_card.html](../running_coach/web/templates/_diary_entry_card.html) — one entry in display mode.
- [_diary_entry_edit.html](../running_coach/web/templates/_diary_entry_edit.html) — one entry in edit mode.
- [_today_note_editor.html](../running_coach/web/templates/_today_note_editor.html) — the dashboard freestanding-entry editor.
- [_run_diary_editor.html](../running_coach/web/templates/_run_diary_editor.html) — the "How did it go?" form in the run-detail modal.

### Routes

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/diary` | Render the timeline + backfill form. |
| `POST` | `/diary/new` | Backfill or add a freestanding entry for any date. Validates `fromisoformat`; rejects empty body + no mood. |
| `POST` | `/diary/today` | Save the dashboard's Today's note (returns the editor partial). |
| `POST` | `/runs/{activity_id}/diary` | Save from the run-detail modal (returns the diary partial). |
| `GET` | `/diary/entries/{id}` | Display partial — used by HTMX to cancel an edit. |
| `GET` | `/diary/entries/{id}/edit` | Edit-form partial — swapped in when ✎ is clicked. |
| `POST` | `/diary/entries/{id}` | Save an in-place edit. Empty body + no mood deletes. |

### DB

```
diary_entries
─ id              INTEGER  PRIMARY KEY AUTOINCREMENT
─ entry_date      TEXT     ISO date, required
─ body            TEXT     required (non-empty after .strip())
─ mood            INTEGER  1..5 (1=💀, 5=😄), nullable
─ activity_id     INTEGER  FK to activities, nullable, ON DELETE SET NULL
─ plan_workout_id INTEGER  FK to plan_workouts, nullable, ON DELETE SET NULL
─ created_at      TEXT
─ updated_at      TEXT
```

Indexes on `entry_date` and `activity_id`.

**Uniqueness pattern:** there is no DB-level unique constraint, but the upsert helpers enforce one freestanding entry per date (where `activity_id IS NULL AND plan_workout_id IS NULL`) and one entry per `activity_id`. Workout-linked entries don't have a uniqueness rule yet because nothing creates them.

### Cache invalidation

Every diary write invalidates today's `llm_cache` entry, since the LLM profile block includes the last 5 diary entries. Editing a 2-year-old entry will *also* drop today's cache — slightly over-eager, acceptable since cache regeneration costs cents.

## Configuration

None. Mood values are fixed 1–5, the cap on `list_entries` is hardcoded at 200 (plenty for current scale).

## Known limitations

- **No deletion UI besides "empty + save".** Convention is consistent across all three editors but hidden until you read the hint text in edit mode.
- **One entry per `activity_id`.** Re-saving updates the existing row. There's no history of edits — the previous text is lost. Mitigation: be careful before saving.
- **No search.** With 200+ entries the timeline scrolls forever. A search box / date jumper would help.
- **`plan_workout_id` entries don't show on the dashboard.** The dashboard only renders today's freestanding entry. A "How will you approach today's workout?" prompt on the today's-workout card could fill this gap.
- **Week marker for empty weeks lingers.** If you delete the only entry in a week via the timeline edit, the week's marker stays on screen until the next page reload. Cosmetic.
- **No export.** SQLite-only. To back up, copy `data/running_coach.db` or `SELECT * FROM diary_entries`.

## Verification

1. **Dashboard today's note.** Type a sentence + pick a mood in the dashboard editor. Save. The card should show "Saved ✓" and the body should round-trip. Open `/diary` — the entry should appear at the top of the timeline.
2. **Backfill.** On `/diary`, pick a past date (e.g. yesterday), type something, save. The entry should slot into the timeline in chronological position.
3. **Edit.** Click ✎ on any entry. The card should swap to an edit form with the existing body + mood pre-selected. Change the body, save. The card swaps back showing the updated text.
4. **Cancel.** Click ✎, then ✕. The card returns to display mode unchanged.
5. **Delete via empty save.** Click ✎, clear the body, set mood to "—", save. The card disappears.
6. **Cache flush.** Save any entry, then reload `/`. The coach banner should regenerate (different phrasing than before — the cache was dropped).

## Future improvements

- **Per-day-prompt for today's workout.** A "How will you approach today's workout?" inline editor under the today's-workout card, persisted as a `plan_workout_id`-linked entry.
- **Search + date jump on `/diary`.** Filter by mood, free-text search, jump-to-date control.
- **Edit history.** Keep the previous body + timestamp in a sibling table on each update. Adds noise; only worth it if the diary becomes a true journal.
- **Tags.** Free-text tags (`#race`, `#injury`, `#nutrition`) for grouping across weeks.
- **Export.** A "Download as Markdown" button on `/diary` that emits one section per week.

---

*Last updated: 2026-05-16*
