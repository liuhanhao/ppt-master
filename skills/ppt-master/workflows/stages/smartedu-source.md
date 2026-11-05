---
description: Generate source-intake stage that turns a basic.smartedu.cn courseware link into a local materials directory plus source.md, then hands the materials to the active Generate runtime.
---

# SmartEdu Source Stage

> Source acquisition inside the active Generate profile's source intake. It turns a `basic.smartedu.cn` link into a local materials directory (superboard vector source, images, videos, audio, companion PDFs) and a `source.md` extracted from the courseware PDF, then hands those materials to the active Generate runtime (Default or Quick) as ordinary sources. It makes no page, design, or deck decision — the Generate authority downstream owns planning and authoring.

## When to Run

| Input | Action |
|---|---|
| A `basic.smartedu.cn` link — syncClassroom (`activityId=`), prepare (`resourceId=`), or quality course (`courseId=`) | Run this stage, then continue the profile's source preparation with its outputs |
| Any other URL, file, or topic | Use the profile's ordinary source conversion; this stage does not apply |

The stage runs inside Generate Step 1 (Default) or §2 (Quick) before `source_to_md.py` conversion. It is a source-preparation stage, not a route or a generation profile.

## Token

- Detail JSON and the superboard vector source are login-free.
- Images, video, audio, and the PDF transcripts need a token (HTTP 401 without one).
- `fetch_materials.py` scans Chrome/Edge/Safari LevelDB first; when found it writes `<mat_dir>/token.txt`. Otherwise pass `--token "$(cat <other-mat-dir>/token.txt)"`, or ask the user to log in to smartedu in a browser and rerun.
- A token is roughly 112 characters and valid for about 7 days. `--token` values are never persisted; only auto-scanned tokens land in `token.txt`.

## Step 1: Collect materials

```bash
python3 ${SKILL_DIR}/scripts/smartedu/fetch_materials.py "<smartedu-url>" ./<stem>-素材 \
        --token "$(cat <other-mat-dir>/token.txt)"
```

Produces under `<mat_dir>`:

- `superboard/extracted/*.json` — vector source (kept as archive; not consumed by Generate)
- `images/` — page media including `ImageFill` backgrounds
- `video/` / `audio/` — embedded media if present
- `course.json` — the detail JSON (drives the next step)

Images are located by scanning every superboard page shape and `document.json`'s `resourceTable`; a missing token leaves them undownloaded but does not fail the stage — report the shortfall and continue with the PDF text.

## Step 2: Download companion PDFs + the courseware PDF

```bash
python3 ${SKILL_DIR}/scripts/smartedu/fetch_pdfs.py <mat_dir> ./<stem> \
        --token "$(cat <other-mat-dir>/token.txt)"
```

Produces `<stem>-教学设计.pdf`, `<stem>-学习任务单.pdf`, `<stem>-作业练习.pdf`, and `<mat_dir>/source.pdf` (the courseware transcript, the fixed name `source_to_md.py` reads). A multi-hour link needs `--lesson lesson_1` to scope to one hour.

## Step 3: Extract the animation reference

```bash
python3 ${SKILL_DIR}/scripts/smartedu/extract_animations.py <mat_dir>
```

Writes `<mat_dir>/animations_ref.md`: per-page ordered animation rows (element text, effect, trigger, duration) derived from the superboard `animationList`, keyed by `Page N` matching `source.md`'s `<!-- Page N -->` markers.

**Reference, not replica**: the anchors are superboard shape ids, not the regenerated page's top-level groups, so the file states *what moves and in which order* — never a spid-to-group mapping. It is not `animations.json` and does not participate in export.

| Runtime | How the reference is consumed |
|---|---|
| Default | Strategist records each page's motion intent in `design_spec.md §IX` `Motion suggestion`; Executor and `customize-animations` decide whether a unit earns realization |
| Quick | The main agent reads it at the §2 motion gate and decides per page whether a unit earns animation |

This is optional but recommended: a page with no row keeps the ordinary defaults; a row never forces motion, and per-element animation still stays off unless the page benefits.

## Step 4: Convert the courseware to source markdown

```bash
python3 ${SKILL_DIR}/scripts/source_to_md.py <mat_dir>/source.pdf
```

Writes `<mat_dir>/source.md` plus a `source.conversion_profile.json` sidecar. This is the deck's text authority — the Strategist (Default) or the main agent (Quick) reads it, not the superboard JSON.

## Step 5: Hand off to the active Generate runtime

Continue the profile's source preparation with the collected materials as ordinary inputs:

```bash
python3 ${SKILL_DIR}/scripts/project_manager.py init <project_name>
python3 ${SKILL_DIR}/scripts/project_manager.py import-sources <project_path> \
    <mat_dir>/source.md <mat_dir>/source.pdf <mat_dir>/images \
    <stem>-教学设计.pdf <stem>-学习任务单.pdf <stem>-作业练习.pdf
```

Then proceed with the selected profile's planning and authoring steps. The superboard JSON, `course.json`, `animations_ref.md`, and media under `video/` / `audio/` stay in the materials directory; read `animations_ref.md` from there during planning or the motion gate, and do not pass it to `import-sources`.

**Superboard is archive, not source**: Generate reconstructs from `source.md` (text) and `images/` (media); it never reads the superboard JSON for content. If the user instead wants a pixel-faithful, animation-preserving rebuild of the original courseware, that is the separate `smartedu-pptx` `superboard2pptx` pipeline, not this stage.

## ✅ Complete

- [x] `fetch_materials.py` ran; `images/` downloaded or shortfall reported
- [x] `fetch_pdfs.py` ran; `source.pdf` and companion PDFs present
- [x] `extract_animations.py` wrote `animations_ref.md` (when the courseware defines motion)
- [x] `source_to_md.py` wrote `source.md` beside `source.pdf`
- [x] Materials imported into the project; the active Generate runtime resumes
- [ ] **Next**: continue planning or direct SVG authoring under the selected profile
