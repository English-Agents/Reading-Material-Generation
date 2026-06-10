# RMG — Reading Material Generator

An **agentic, self-improving pipeline** that converts PowerPoint presentations (or Google Slides) into structured reading material documents. Upload a deck, get a fully formatted, reviewable reading material in one LLM call. Reviewers approve or reject it; every rejection triggers automatic prompt optimisation so the system improves over time.

---

## Table of Contents

1. [What It Does](#what-it-does)
2. [Architecture Overview](#architecture-overview)
3. [Tech Stack](#tech-stack)
4. [Project Structure](#project-structure)
5. [How It Works — End to End](#how-it-works--end-to-end)
6. [Source Content Grounding](#source-content-grounding)
7. [Alignment Validator](#alignment-validator)
8. [Book Ingestion Pipeline](#book-ingestion-pipeline)
9. [Topic-Driven Format](#topic-driven-format)
10. [Database Schema](#database-schema)
11. [API Reference](#api-reference)
12. [Environment Variables](#environment-variables)
13. [Local Setup](#local-setup)
14. [Running the Server](#running-the-server)
15. [Frontend](#frontend)
16. [Self-Improving Prompt System (DSPy + GEPA)](#self-improving-prompt-system-dspy--gepa)
17. [Shadow A/B Testing](#shadow-ab-testing)
18. [Memory System](#memory-system)
19. [Circuit Breaker & Repair Queue](#circuit-breaker--repair-queue)
20. [Ops Monitoring & Auto-Rollback](#ops-monitoring--auto-rollback)
21. [Eval Pipeline (PromptFoo)](#eval-pipeline-promptfoo)
22. [Running Tests](#running-tests)
23. [Content Quality Guidelines](#content-quality-guidelines)
24. [Markdown Conversion Guidelines](#markdown-conversion-guidelines)
25. [Guidelines Alignment — Application Cross-Check](#guidelines-alignment--application-cross-check)
26. [Key Design Decisions](#key-design-decisions)

---

## What It Does

| Input | Output |
|---|---|
| `.pptx` file upload | One complete reading material document in Markdown |
| Google Slides URL | One complete reading material document in Markdown |
| Direct `.pptx` URL | One complete reading material document in Markdown |

The generated reading material is **topic-driven**, not a fixed template. The LLM chooses a format appropriate to the topic type:

- **Grammar rule topics** (active/passive voice, tenses, articles) — definition → rule → transformation table → exceptions
- **Communication topics** (fillers, intonation, sentence stress) — definition → usage examples table → types → placement → register (General / Academic / Professional) → exceptions

All outputs use:
- H1 title, H2/H3 sections, markdown tables for every comparison
- `**bold**` for key terms (never `<b>` HTML)
- Plain example sentences — no MCQ questions
- A mandatory exception/restriction section at the end
- Image placeholders as visible blockquotes: `> 📷 **Image:** *[description]*` (replace with real `<img>` S3 URLs before publishing)

After generation, a human reviewer approves or rejects the output. Rejections feed into an automatic prompt optimiser that improves future generations.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                            UPLOAD                                   │
│   .pptx file  ──┐                                                   │
│   Google Slides ─┼──► slide_parser.py ──► ParsedSlide[]            │
│   Direct URL  ──┘                              │                    │
└────────────────────────────────────────────────┼─────────────────── ┘
                                                  │
                         ┌────────────────────────▼─────────────────┐
                         │           deck_compiler.py                │
                         │       (ONE LLM call per deck)             │
                         │                                           │
                         │  Slide TITLES only (no body text)         │
                         │         +                                 │
                         │  Source passages  ─────────────────────── ┤
                         │  (curated manually via UI or auto-        │
                         │   retrieved from books/ via pgvector)     │
                         └────────────────────────┬─────────────────┘
                                                  │
                         ┌────────────────────────▼─────────────────┐
                         │    OpenRouter → anthropic/claude-sonnet-4-6│
                         │           max_tokens = 8,192              │
                         └────────────────────────┬─────────────────┘
                                                  │
                    ┌─────────────────────────────▼──────────────────────┐
                    │              PostgreSQL + pgvector                  │
                    │  generations ── source_content ── book_chunks      │
                    └─────────────────────────────┬──────────────────────┘
                                                  │
                    ┌─────────────────────────────▼──────────────────────┐
                    │              React Review UI                        │
                    │  Approve ────────────► embed output                │
                    │  Reject  ──┬──────────► record feedback            │
                    │            └──────────► GEPA optimizer             │
                    │  Source passages ──── alignment badge + budget bar │
                    └────────────────────────────────────────────────────┘
```

**Background systems running at all times:**
- **Ops job** (every 15 min) — shadow A/B promotion, alert checks, auto-rollback
- **G-Eval scorer** — auto-scores approved outputs via DSPy ChainOfThought
- **Repair queue** — retries failed generations up to `MAX_RETRIES` times
- **Alignment validator** — scores each source passage against its topic on upload

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Backend API** | FastAPI + Uvicorn (async) |
| **LLM — generation** | OpenRouter → `anthropic/claude-sonnet-4-6` via OpenAI-compatible SDK |
| **LLM — alignment scoring** | OpenRouter → `anthropic/claude-haiku-4-5-20251001` |
| **Embeddings** | OpenAI `text-embedding-3-small` (1536 dimensions) |
| **Database** | PostgreSQL 16 + pgvector extension (IVFFlat cosine index) |
| **ORM** | SQLAlchemy 2.0 async (asyncpg driver) |
| **Cache** | Redis 7 — vision cache (7-day TTL), app-level Redis pool |
| **Migrations** | Alembic |
| **Prompt Optimisation** | DSPy 3.x — `dspy.ChainOfThought` for G-Eval, `dspy.teleprompt.GEPA` |
| **Eval Pipeline** | PromptFoo (Node.js) + Python subprocess provider |
| **Frontend** | React 18 + Vite + TypeScript + Tailwind CSS + TanStack Query |
| **Markdown Rendering** | `react-markdown` + `remark-gfm` + `rehype-raw` |
| **Book parsing** | `pdfplumber` (PDF), `ebooklib` + `beautifulsoup4` (EPUB), plain text |
| **Containerisation** | Docker Compose (postgres + redis) |
| **Testing** | pytest + pytest-asyncio + fakeredis |

---

## Project Structure

```
d:\RMG\
│
├── slide_parser.py              # Parses .pptx → list[ParsedSlide]
├── slide_classifier.py          # Classifies slide type (CONCEPT / CODE / DIAGRAM etc.)
├── seed_db.py                   # Seeds initial prompt versions into the database
├── reseed_prompts.py            # Updates existing prompt versions after format changes
├── ingest_books.py              # Ingests books from books/ → book_chunks table
│
├── books/                       # Drop your .pdf / .epub / .txt books here
│   └── .gitkeep
│
├── ppt_agent/
│   ├── llm.py                   # Central LLM wrapper — OpenRouter via OpenAI SDK
│   │
│   ├── api/
│   │   ├── main.py              # FastAPI app factory + lifespan (Redis pool, ops job)
│   │   ├── deps.py              # Dependency injection — get_db(), get_redis()
│   │   ├── generate.py          # POST /generate/file  POST /generate/url
│   │   ├── review.py            # POST /review/{id}/approve|reject|feedback
│   │   ├── source_content.py    # CRUD for source passages (add, list, delete, validate)
│   │   ├── ops.py               # GET /ops/dashboard  GET /ops/alerts + background job
│   │   └── export.py            # POST /export/{deck_id}
│   │
│   ├── config/
│   │   ├── settings.py          # Pydantic-settings — all env vars in one place
│   │   └── format_schema.py     # Topic-driven format spec (Pattern A / Pattern B)
│   │
│   ├── db/
│   │   ├── models.py            # SQLAlchemy ORM — 8 tables
│   │   └── session.py           # Async session factory + get_db_session() context manager
│   │
│   ├── skills/
│   │   ├── deck_compiler.py     # ONE LLM call per deck — builds reading material
│   │   ├── alignment_validator.py  # Per-passage Haiku scoring (pass ≥0.7, warn 0.5–0.69)
│   │   ├── book_retriever.py    # pgvector similarity search over book_chunks
│   │   ├── router.py            # Routes slides to the right skill (legacy per-slide path)
│   │   ├── concept_explainer.py # Skill: explain a concept slide
│   │   ├── code_walkthrough.py  # Skill: walk through a code slide
│   │   ├── diagram_describer.py # Skill: describe a technical diagram
│   │   ├── figure_caption.py    # Skill: caption a non-technical image
│   │   ├── quiz_generator.py    # Skill: generate quiz questions
│   │   ├── seed_prompts.py      # System prompt text for every skill
│   │   ├── cost_tracker.py      # Token cost calculation (USD per call)
│   │   ├── shadow.py            # Shadow A/B testing — per-deck traffic split
│   │   └── circuit_breaker.py   # Retry decorator — failed skill → repair queue
│   │
│   ├── memory/
│   │   ├── prompt_store.py      # CRUD for prompt_versions — get_active, promote, retire, rollback
│   │   ├── generation_store.py  # pgvector similarity search on approved outputs
│   │   ├── feedback_store.py    # Record feedback signals per generation
│   │   ├── pattern_store.py     # Upsert + promote pattern_memory candidates
│   │   ├── retrieval.py         # embed_text() + retrieve_context() → MemoryContext
│   │   └── types.py             # MemoryContext, SimilarOutput, ReviewerPref dataclasses
│   │
│   ├── image/
│   │   └── pipeline.py          # Vision pipeline — Redis cache + LLM image analysis
│   │
│   ├── integrations/
│   │   └── google_slides.py     # Export Google Slides → PPTX via Drive API v3
│   │
│   ├── optimizer/
│   │   ├── geval.py             # DSPy G-Eval scorer (0.0–1.0 quality score)
│   │   └── prompt_optimizer.py  # GEPA optimizer — runs when ≥10 labelled examples exist
│   │
│   └── evals/
│       ├── promptfoo.yaml       # PromptFoo eval config
│       ├── caption_judge.py     # PromptFoo Python subprocess provider
│       ├── run_regression.py    # Run PromptFoo + write results to DB
│       ├── test_case_generator.py  # Auto-generate regression tests on rejection
│       └── regression_suite/
│           └── auto_generated.yaml  # Growing test case library
│
├── migrations/
│   ├── env.py                   # Alembic env — strips +asyncpg for sync migrations
│   ├── script.py.mako
│   └── versions/
│       ├── 0001_initial.py      # All core tables + pgvector IVFFlat index
│       ├── 0002_add_deck_reading.py   # Adds deck_reading to skill_type CHECK
│       ├── 0003_source_content.py     # source_content table + alignment columns
│       ├── 0004_schema_fixes.py       # alignment_reason column + 13 feedback signals
│       └── 0005_book_chunks.py        # book_chunks table with Vector(1536)
│
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── UploadPage.tsx          # Drag-and-drop PPTX upload + Google Slides URL
│   │   │   ├── ReviewPage.tsx          # Generated material review + source passages link
│   │   │   ├── SourceContentPage.tsx   # Add/view/delete source passages, budget bar
│   │   │   └── DashboardPage.tsx       # Per-skill stats, alerts, repair queue
│   │   ├── components/
│   │   │   ├── GenerationCard.tsx      # Renders markdown, Copy MD, Open Preview buttons
│   │   │   ├── FeedbackModal.tsx       # 13-signal rejection feedback picker
│   │   │   ├── AlignmentBadge.tsx      # pass/warn/fail badge with score tooltip
│   │   │   ├── PassageForm.tsx         # Collapsible form to add a source passage
│   │   │   └── Layout.tsx
│   │   └── api/client.ts              # Typed axios wrapper for all API endpoints
│   └── ...
│
├── render.yaml                  # Render.com deployment — all services defined
├── start.sh                     # Render startup script — migrate + seed + uvicorn
├── docker-compose.yml           # PostgreSQL 16 (pgvector) + Redis 7
├── pyproject.toml               # Python dependencies + pytest config
├── alembic.ini
├── .env.example                 # Template — copy to .env and fill in secrets
└── .gitignore                   # .env excluded — never commit secrets
```

---

## How It Works — End to End

### 1. Upload
```
POST /generate/file   (multipart/form-data, .pptx, max 50 MB)
POST /generate/url    (Google Slides URL or direct .pptx URL)
```

### 2. Parse
`slide_parser.py` extracts from every slide:
- `title` — slide heading
- `body_text` — all text frames concatenated (NOT sent to the LLM — titles only)
- `speaker_notes` — presenter notes
- `embedded_images` — list of `{base64_data, mime_type, md5}`

### 3. Compile — ONE LLM call
`deck_compiler.py` builds the prompt from:
- **Slide titles only** — body text is intentionally excluded to prevent raw PPT content from leaking into the output
- **Source passages** — curated reference material added by content developers (see [Source Content Grounding](#source-content-grounding))
- **Book chunks** (optional) — auto-retrieved from ingested books when `USE_BOOK_RETRIEVAL=true`

One call to `claude-sonnet-4-6` via OpenRouter with `max_tokens=8192`. Cost ≈ $0.01–0.03 per deck.

### 4. Store
The output is saved as a `Generation` row with:
- `skill_type = "deck_reading"`
- `slide_index = -1` (whole deck)
- `status = "pending"`
- `token_cost_usd` calculated from actual token counts

### 5. Review
The React UI fetches the pending `deck_reading` generation and renders it as formatted Markdown. The reviewer can:

| Action | What happens |
|---|---|
| **Approve** | `status → approved`, embedding computed in background, G-Eval auto-score written |
| **Reject** | `status → rejected`, feedback signals recorded, regression test generated, GEPA optimizer triggered |
| **Copy MD** | Copies the raw Markdown to clipboard |
| **Open Preview** | Opens the Markdown in an external preview tool |

### 6. Self-improve
- Every rejection adds a labelled example to the GEPA training set
- When ≥ 10 labelled examples exist, the GEPA optimizer rewrites the `deck_reading` prompt and stores it as a `candidate` prompt version
- The ops background job promotes shadow versions that beat the active version by ≥ 5%

---

## Source Content Grounding

The generation is grounded in curated reference passages — the LLM **cannot invent facts** not present in the provided passages.

### How it works

1. A content developer opens the **Source Passages** page for a deck (`/source/:deckId`)
2. They add passages from grammar books, official style guides, or other trusted sources
3. Each passage is immediately scored by the **Alignment Validator** (see below)
4. At generation time, all passages for the deck are injected into the prompt as the sole factual basis
5. A **budget bar** in the UI shows how much of the 12,000-character limit is used

### Source passage budget

| Limit | Value |
|---|---|
| Max chars per passage | 2,000 |
| Max chars per deck (all passages combined) | 12,000 (~3,000 tokens) |

Exceeding the deck budget raises a `SourceBudgetExceeded` error before the LLM call. The UI shows the budget bar turning red and the generation button is blocked.

### Source content API

| Method | Path | Description |
|---|---|---|
| `GET` | `/source-content/{deck_id}` | List all passages for a deck |
| `POST` | `/source-content/{deck_id}` | Add a passage (triggers alignment scoring) |
| `DELETE` | `/source-content/{passage_id}` | Remove a passage |
| `POST` | `/source-content/{deck_id}/validate` | Re-run alignment scoring on all passages |

---

## Alignment Validator

Every source passage is automatically scored for topical relevance before it is used in generation.

### Scoring

The validator calls `anthropic/claude-haiku-4-5-20251001` with the passage text and the topic label. It returns a score `0.0–1.0` and a human-readable reason.

| Score | Verdict | Badge colour | Meaning |
|---|---|---|---|
| ≥ 0.70 | `pass` | Green | Passage is on-topic and suitable |
| 0.50–0.69 | `warn` | Yellow | Partially relevant — review before use |
| < 0.50 | `fail` | Red | Off-topic — consider replacing |

### In the UI

The **AlignmentBadge** component shows the verdict and score on each passage card. Hovering reveals the full reason from the model.

### Non-blocking

A failing alignment score does **not** block generation. It is advisory only — the content developer decides whether to keep or replace the passage.

---

## Book Ingestion Pipeline

Add your own grammar books, style guides, or reference texts to the `books/` folder. The system will extract, chunk, embed, and store them for automatic retrieval during generation.

### Supported formats

| Format | Extractor |
|---|---|
| `.pdf` | `pdfplumber` — text extracted per page |
| `.epub` | `ebooklib` + `BeautifulSoup` — text extracted per chapter |
| `.txt` / `.md` | Direct read with section detection |

### File naming convention

Name your files as `Title - Author.ext` so metadata is auto-extracted:

```
Grammar in Use - Raymond Murphy.pdf
Swan Practical English Usage - Michael Swan.epub
Sentence Stress Notes.txt
```

### Running the ingestion script

```bash
# Process all new files in books/
python ingest_books.py

# See what is already indexed
python ingest_books.py --list

# Process a single file
python ingest_books.py --file "Grammar in Use - Raymond Murphy.pdf"

# Force re-process all files
python ingest_books.py --reindex
```

The script:
1. Extracts text from each book
2. Splits into ~1,500-char overlapping chunks at sentence boundaries
3. Skips files already indexed (by filename)
4. Embeds each chunk via `text-embedding-3-small`
5. Stores chunks in the `book_chunks` table with pgvector embeddings

### Enabling auto-retrieval

Set `USE_BOOK_RETRIEVAL=true` in your `.env`. When a deck has **no manually curated passages**, the system will automatically retrieve the top-6 most relevant book chunks using pgvector cosine similarity and inject them as the reference passages for generation.

If manual passages exist, book retrieval is skipped — manual passages always take priority.

---

## Topic-Driven Format

The output format is not a rigid template. The LLM selects the pattern that best fits the topic.

### Pattern A — Grammar Rule Topics
Used for: active/passive voice, reported speech, conditionals, articles, tenses, etc.

```
# [Topic Title]
## Definition
## Grammar Rule
   | Tense | Active | Passive |  (transformation table)
## How to Form It
## Common Uses
## Exceptions and Restrictions
```

### Pattern B — Communication/Pragmatics Topics
Used for: fillers, intonation, sentence stress, register, hedging, discourse markers, etc.

```
# [Topic Title]
## What Is It?
## Types / Categories     (with examples table)
## Placement and Usage
## General / Academic / Professional Usage
## Exceptions and Restrictions
```

### Format invariants (apply to both patterns)

- H1 title, H2/H3 sections, horizontal rules between major sections
- Markdown tables for **all** comparisons — no prose lists for structured data
- `**bold**` for key terms — never `<b>` HTML tags
- Plain example sentences — no MCQ or quiz items
- Exception/restriction section mandatory at the end
- Image placeholder format: `> 📷 **Image:** *[description of image needed here]*`
- Minimum ~1,200 words per document

---

## Database Schema

### `generations`
| Column | Type | Description |
|---|---|---|
| `id` | UUID PK | Generation ID |
| `deck_id` | UUID | Groups all generations for one upload |
| `skill_type` | TEXT | `deck_reading`, `concept_explainer`, etc. |
| `slide_index` | INT | `-1` for deck-level, `0+` for per-slide |
| `prompt_version_id` | UUID FK | Which prompt was used |
| `output_text` | TEXT | The generated reading material (Markdown) |
| `tokens_in / tokens_out` | INT | Actual token counts from the API response |
| `token_cost_usd` | NUMERIC | Calculated cost in USD |
| `eval_score` | NUMERIC(3,2) | 0.0–1.0 quality score (manual or G-Eval) |
| `status` | TEXT | `pending \| approved \| rejected \| needs_repair` |
| `is_shadow` | BOOL | True for shadow A/B test generations |
| `embedding` | Vector(1536) | pgvector embedding for similarity search |

### `source_content`
| Column | Type | Description |
|---|---|---|
| `id` | UUID PK | |
| `deck_id` | UUID | Which deck this passage belongs to |
| `topic_label` | TEXT | The topic or subtopic this passage covers |
| `source_title` | TEXT | Book title or source name |
| `page_ref` | TEXT | Page number / section reference |
| `passage_text` | TEXT (≤2000) | The curated reference text |
| `author` | TEXT | Author of the source |
| `alignment_score` | NUMERIC(4,3) | 0.0–1.0 relevance score from Haiku |
| `alignment_verdict` | TEXT | `pass \| warn \| fail` |
| `alignment_reason` | TEXT | Human-readable reason from the scorer |

### `book_chunks`
| Column | Type | Description |
|---|---|---|
| `id` | UUID PK | |
| `book_title` | TEXT | Extracted from filename |
| `author` | TEXT | Extracted from filename (after ` - `) |
| `file_name` | TEXT | Original filename — used for dedup |
| `chapter` | TEXT | Chapter or section heading |
| `chunk_text` | TEXT | ~1,500-char text chunk |
| `chunk_index` | INT | Position of chunk within the book |
| `embedding` | Vector(1536) | pgvector embedding for similarity search |

### `prompt_versions`
| Column | Type | Description |
|---|---|---|
| `id` | UUID PK | |
| `skill_type` | TEXT | Which skill this prompt belongs to |
| `parent_id` | UUID FK → self | Links optimised versions to their parent |
| `prompt_text` | TEXT | Full system prompt text |
| `status` | TEXT | `candidate \| shadow \| active \| retired` |
| `pass_rate` | NUMERIC | Tier-1 eval pass rate (0–1) |
| `avg_rubric_score` | NUMERIC | Average PromptFoo rubric score (1–5) |

### `feedback`
Stores structured signals from reviewers. Thirteen signal types:

| `signal_type` | Meaning |
|---|---|
| `too_long` | Output is too long |
| `too_short` | Output is too short |
| `wrong_tone` | Tone doesn't match audience |
| `missing_example` | Missing worked examples |
| `factual_error` | Contains factual mistakes |
| `format_violation` | Format spec not followed |
| `unnecessary_diagram` | Diagram added where not needed |
| `needs_diagram` | Should have a diagram |
| `unclear_explanation` | Explanation is confusing |
| `wrong_difficulty_level` | Level doesn't match the learner profile |
| `missing_common_errors` | No common error / L1-interference section |
| `missing_correction` | Error shown but correction not provided |
| `diagram_incorrect` | Diagram content is factually wrong |

### `repair_queue`
Tracks failed generations. A generation moves here when its `retry_count` reaches `MAX_RETRIES`.

### `pattern_memory`
Learned patterns from reviewer feedback. Promoted to `active` when `example_count` reaches `ceil(PATTERN_CONFIDENCE_THRESHOLD × MIN_EXAMPLES_CONSTANT)`.

### `alerts`
System-level alerts for score drops, deep repair queues, and old unresolved repairs.

---

## API Reference

### Generate

| Method | Path | Description |
|---|---|---|
| `POST` | `/generate/file` | Upload a `.pptx` file (multipart) |
| `POST` | `/generate/url` | Google Slides or `.pptx` URL |
| `GET` | `/generate/generations` | List generations — filter by `deck_id`, `status`, `skill_type` |

**Response — `GenerateResponse`**
```json
{
  "deck_id": "uuid",
  "slide_count": 24,
  "deck_generation_id": "uuid"
}
```

### Source Content

| Method | Path | Description |
|---|---|---|
| `GET` | `/source-content/{deck_id}` | List all passages for a deck |
| `POST` | `/source-content/{deck_id}` | Add a passage (triggers alignment scoring immediately) |
| `DELETE` | `/source-content/{passage_id}` | Remove a passage |
| `POST` | `/source-content/{deck_id}/validate` | Re-run alignment scoring on all passages |

**Add passage body**
```json
{
  "topic_label": "Active Voice",
  "passage_text": "The active voice is used when...",
  "source_title": "Grammar in Use",
  "page_ref": "42",
  "author": "Raymond Murphy"
}
```

### Review

| Method | Path | Body |
|---|---|---|
| `POST` | `/review/{id}/approve` | `{ "reviewer_id": "string", "eval_score": 0.0–1.0 }` |
| `POST` | `/review/{id}/reject` | `{ "reviewer_id": "string", "signals": [...] }` |
| `POST` | `/review/{id}/feedback` | `{ "reviewer_id": "string", "signals": [...] }` |
| `GET` | `/review/repair-queue` | Lists pending repair items |

**Feedback signal shape**
```json
{
  "signal_type": "missing_common_errors",
  "severity": 2,
  "section_id": "active-voice",
  "reviewer_note": "No L1 interference examples for Indian English learners"
}
```

### Ops

| Method | Path | Description |
|---|---|---|
| `GET` | `/ops/dashboard` | Per-skill stats — counts, avg score, avg cost, active prompt |
| `GET` | `/ops/alerts` | Unresolved alerts (`?resolved=true` for resolved) |
| `POST` | `/ops/alerts/{id}/resolve` | Manually resolve an alert |

### Export

| Method | Path | Body |
|---|---|---|
| `POST` | `/export/{deck_id}` | `{ "format": "pdf\|docx\|markdown" }` |

### Health

| Method | Path |
|---|---|
| `GET` | `/healthz` |

---

## Environment Variables

Copy `.env.example` to `.env` and fill in the values:

```env
# LLM — OpenRouter key (sk-or-v1-...) or direct Anthropic key
ANTHROPIC_API_KEY=sk-or-v1-...
LLM_BASE_URL=https://openrouter.ai/api/v1
GENERATION_MODEL=anthropic/claude-sonnet-4-6
ALIGNMENT_MODEL=anthropic/claude-haiku-4-5-20251001

# OpenAI — for text-embedding-3-small (book ingestion + similarity search)
OPENAI_API_KEY=sk-...

# Google Slides — base64-encoded service account JSON
# Service account needs Drive API read access
GOOGLE_SERVICE_ACCOUNT_JSON=<base64>

# Database
DATABASE_URL=postgresql+asyncpg://rmg:rmg@localhost:5434/rmgdb

# Redis
REDIS_URL=redis://localhost:6379/0

# Source content grounding
ALIGNMENT_THRESHOLD=0.7         # below this score → "fail" verdict
MAX_SOURCE_CHARS_PER_DECK=12000 # total chars across all passages per deck

# Book retrieval (requires running ingest_books.py first)
USE_BOOK_RETRIEVAL=false         # set true to auto-retrieve from books/
BOOK_RETRIEVAL_TOP_K=6           # max chunks to retrieve per deck
BOOKS_DIR=books                  # relative path to your books folder

# Tuning
MAX_RETRIES=3
PATTERN_CONFIDENCE_THRESHOLD=0.75
SHADOW_PROMOTION_MARGIN=0.05
MIN_EXAMPLES_CONSTANT=20

# Shadow A/B config per skill (optional)
SHADOW_CONFIG_JSON={"concept_explainer":{"traffic_pct":0.2,"min_slides":50}}

# CORS — comma-separated, or * for open
CORS_ORIGINS=*
```

> **Never commit `.env`** — it contains your API keys and the service account private key. The `.gitignore` already excludes it.

---

## Local Setup

### Prerequisites
- Python 3.11+
- Node.js 20+ (for frontend and PromptFoo)
- Docker Desktop

### Step 1 — Start infrastructure

```bash
docker compose up -d
```

This starts:
- **PostgreSQL 16** with pgvector on port `5434`
- **Redis 7** on port `6379`

### Step 2 — Install Python dependencies

```bash
pip install -e ".[dev]"
```

### Step 3 — Configure environment

```bash
cp .env.example .env
# Edit .env — add ANTHROPIC_API_KEY and OPENAI_API_KEY at minimum
```

### Step 4 — Run database migrations

```bash
python -m alembic upgrade head
```

This creates all tables and the pgvector IVFFlat index.

### Step 5 — Seed initial prompts

```bash
python seed_db.py
```

This inserts the initial `active` prompt versions for all skill types into `prompt_versions`.

### Step 6 — (Optional) Ingest books

Drop any `.pdf`, `.epub`, or `.txt` grammar/reference books into the `books/` folder, then:

```bash
python ingest_books.py
```

After ingestion, set `USE_BOOK_RETRIEVAL=true` in `.env` to enable automatic retrieval.

### Step 7 — Install frontend dependencies

```bash
cd frontend
npm install
```

---

## Running the Server

### Backend (FastAPI)

```bash
uvicorn ppt_agent.api.main:app --reload --host 0.0.0.0 --port 8000
```

Or use the installed script:

```bash
rmg-server
```

API: `http://localhost:8000` | Docs: `http://localhost:8000/docs`

### Frontend (React)

```bash
cd frontend
npm run dev
```

UI: `http://localhost:5173`

Vite proxies all `/generate`, `/review`, `/ops`, `/export`, `/source-content` requests to port 8000.

---

## Frontend

### Upload Page (`/`)
- Drag-and-drop `.pptx` upload or Google Slides URL input
- Shows a spinner while generation runs
- Redirects to `/review/{deck_id}` on success

### Review Page (`/review/:deckId`)
- Fetches the `deck_reading` generation for the deck
- Renders the full Markdown output using `react-markdown` + `remark-gfm` + `rehype-raw`
- **Copy MD** button — copies raw Markdown to clipboard
- **Open Preview** link — opens the Markdown in the external preview tool
- **Source passages** link — navigates to `/source/:deckId` to manage reference passages
- **Approve** button — optionally override eval score (0–1)
- **Reject** button — opens FeedbackModal with 13 signal types

### Source Content Page (`/source/:deckId`)
- Budget bar — green/yellow/red based on character usage vs 12,000-char limit
- Lists all passages with **AlignmentBadge** (pass/warn/fail + score)
- Hover over badge to see the scorer's reason
- **Delete** button per passage
- **+ Add reference passage** — collapsible form with fields: topic label, passage text (2,000-char max with countdown), source title, page reference, author

### Dashboard Page (`/dashboard`)
- Per-skill stats table: total generations, approved, rejected, repair count, avg score, avg cost
- `deck_reading` row highlighted — it is the primary skill used by the system
- Open alerts list and repair queue depth

---

## Self-Improving Prompt System (DSPy + GEPA)

### G-Eval Auto-Scoring

When a generation is approved, `geval.py` runs in the background:

1. Configures DSPy with the OpenRouter LLM
2. Runs `dspy.ChainOfThought` against a `ReadingMaterialQuality` signature
3. Returns a float `0.0–1.0` and a reasoning string
4. Writes the score back to `generations.eval_score`

### GEPA Prompt Optimisation

When a generation is rejected, `prompt_optimizer.py` runs in the background:

1. Queries all labelled `deck_reading` generations (approved = 1.0, rejected = 0.0)
2. If fewer than 10 examples — skips (not enough signal)
3. If ≥ 10 examples — runs `dspy.teleprompt.GEPA` using `GEPAFeedbackMetric` as the reward signal
4. Stores the result as a new `PromptVersion` with `status = 'candidate'`
5. The ops background job picks it up and promotes it to `shadow` for A/B testing

### Reseeding Prompts

If you change `format_schema.py` or `seed_prompts.py`, run:

```bash
python reseed_prompts.py
```

This updates all existing `active` prompt versions in the database without inserting duplicates.

---

## Shadow A/B Testing

Each new prompt candidate goes through shadow testing before becoming active:

1. **Traffic split** — determined **per deck** using `hashlib.md5(deck_id)` → deterministic float. All slides in one deck always go to the same branch.

2. **Config** — per-skill traffic percentage and minimum slide count set in `SHADOW_CONFIG_JSON`:
   ```json
   {"deck_reading": {"traffic_pct": 0.2, "min_slides": 50}}
   ```

3. **Promotion** — every 15 minutes the ops background job compares:
   ```
   shadow_avg_score - active_avg_score >= SHADOW_PROMOTION_MARGIN (default 0.05)
   ```
   - Shadow wins → promoted to `active`, old active → `retired`
   - Shadow loses → `retired`

Shadow generations are stored with `is_shadow = True` and excluded from the review UI.

---

## Memory System

### Similar Output Retrieval
`retrieval.py` embeds slide content using `text-embedding-3-small`, then queries pgvector for the top-5 most similar **approved** past outputs. These are injected as `MemoryContext` into skill prompts for the legacy per-slide path.

### Pattern Memory
High-severity feedback signals (`severity >= 2` with a reviewer note) are upserted as `pattern_memory` candidates. When a pattern's `example_count` reaches:
```
ceil(PATTERN_CONFIDENCE_THRESHOLD × MIN_EXAMPLES_CONSTANT)
= ceil(0.75 × 20) = 15
```
it is promoted to `active` and injected into future prompts as a learned constraint.

---

## Circuit Breaker & Repair Queue

Each skill call is wrapped with `@with_circuit_breaker(skill_type)`:

1. First failure → retry immediately, increment `retry_count`
2. After `MAX_RETRIES` (default 3) failures → set `status = 'needs_repair'`, insert into `repair_queue`, return `RepairRequired` dataclass
3. The router checks `isinstance(result, RepairRequired)` and branches accordingly
4. Repair queue is visible in the dashboard and via `GET /review/repair-queue`

---

## Ops Monitoring & Auto-Rollback

The `ops_background_job()` runs every 15 minutes inside the FastAPI lifespan.

### Alert Conditions

| Alert Type | Threshold |
|---|---|
| `score_drop` | Last 100 avg score drops ≥ 0.3 vs previous 100 |
| `repair_queue_depth` | Pending repairs ≥ 50 |
| `repair_queue_age` | Oldest pending repair > 24 hours |

### Auto-Rollback

If a `score_drop` alert is open and the skill has a parent prompt version:
1. `prompt_store.rollback(skill_type)` promotes the parent back to `active`
2. Current active → `retired`
3. Alert marked `resolved = True`

Alerts can also be manually resolved via `POST /ops/alerts/{id}/resolve`.

---

## Eval Pipeline (PromptFoo)

PromptFoo runs two tiers of evaluation:

### Tier 1 — Deterministic (must all pass)

Minimal topic-agnostic checks that apply to any `deck_reading` output:
- Must contain `## ` (H2 sections)
- Must contain `| --- |` (at least one markdown table)
- Must contain `**` (bold terms used)
- Must contain `Exception` (exception section present)
- Minimum length: 1,200 characters

### Tier 2 — LLM Rubric
`caption_judge.py` is a Python subprocess provider that:
1. Reads JSON from stdin (PromptFoo format)
2. Calls the LLM synchronously to score the output 1–5
3. Writes `{"output": ..., "score": ..., "pass": ...}` to stdout

Average Tier 2 score must be ≥ 3.5 for a prompt to be eligible for promotion.

### Running Evals

```bash
# Via PromptFoo directly
npx promptfoo eval --config ppt_agent/evals/promptfoo.yaml

# Or via the regression runner (writes results back to DB)
python -m ppt_agent.evals.run_regression
```

---

## Running Tests

```bash
# All unit tests (no DB/Redis required)
pytest

# With integration tests (requires running DB + Redis)
pytest -m integration

# Specific file
pytest ppt_agent/tests/test_api.py -v
```

**Test coverage:**
- `test_slide_parser.py` — PPTX parsing with synthetic files
- `test_circuit_breaker.py` — retry logic and RepairRequired return
- `test_memory.py` — pgvector similarity search (integration)
- `test_image_pipeline.py` — vision pipeline with mocked LLM
- `test_api.py` — all API routes via `httpx.AsyncClient(ASGITransport)`
- `test_evals.py` — PromptFoo provider JSON in/out

---

## Content Quality Guidelines

These are the content standards that every generated reading material must meet. They are enforced through the system prompt (`format_schema.py`), the reviewer approval workflow, and the GEPA optimizer.

1. Clearly define the target audience, learner profile, and learning objectives before developing the material.
2. Understand the learners' linguistic, cultural, educational, and exposure background, and adapt the teaching approach accordingly instead of using the same method for all learners.
3. Conduct proper market research to understand current industry trends, learner expectations, and exam or job-related requirements.
4. Refer to authentic and reliable reference materials, and verify concepts using multiple trusted sources before creating the content.
5. Plan the content structure carefully and maintain a logical flow by progressing from basic concepts to advanced topics using clear headings and subheadings.
6. Ensure the difficulty level, explanations, and examples align with the learner's proficiency, curriculum, assessment pattern, or skill requirement.
7. Use simple, clear, concise, and learner-friendly language with proper grammatical accuracy and consistent formatting throughout the material.
8. Keep the content organised and manageable through short paragraphs, bullet points, summaries, and quick revision sections.
9. Include definitions, key points, formulas, shortcuts, and concept explanations wherever necessary for better understanding and retention.
10. Add practical, real-life, academic, and professional application-based examples so learners understand why, what, and where a concept is used.
11. Use contextual scenarios, case-based situations, and problem-solving activities to encourage critical thinking, analytical reasoning, and practical application.
12. Include practice exercises, activities, and assessment-oriented questions after each section to reinforce learning outcomes.
13. Identify common learner difficulties and errors caused by first-language influence, direct translation methods, limited exposure, or incorrect usage patterns, and explain why learners are likely to make those mistakes.
14. Provide corrective guidance, awareness-based explanations, and practical usage examples to help learners recognise errors and develop natural, context-appropriate English communication skills.
15. Use visuals, charts, tables, or diagrams wherever necessary to improve comprehension, engagement, and content clarity.
16. Cross-check all references, examples, explanations, answers, and factual information thoroughly to ensure accuracy, consistency, and overall content quality.
17. Regularly review, update, and revise the material based on learner feedback, updated research, and changing academic or industry requirements.

---

## Markdown Conversion Guidelines

These standards govern how content is structured, formatted, and rendered in Markdown across the review UI and exported files.

1. Understand the purpose, target platform, and formatting requirements before starting the Markdown conversion process.
2. Maintain the original meaning, structure, and logical flow of the content during conversion.
3. Use proper Markdown syntax consistently for headings, subheadings, bullet points, numbered lists, tables, links, code blocks, and emphasis formatting.
4. Ensure clear hierarchy and readability by using appropriate heading levels and spacing throughout the document.
5. Keep the formatting clean, organised, and visually consistent across all sections.
6. Verify that all lists, indentation, alignment, and nested formatting render correctly after conversion.
7. Preserve important content elements such as examples, tables, formulas, notes, warnings, and highlighted points without distortion.
8. Ensure hyperlinks, references, embedded resources, and navigation elements function properly after conversion.
9. Optimise the document for readability across different platforms, editors, and devices that support Markdown rendering.
10. Cross-check the converted Markdown output for formatting errors, broken structure, missing content, or rendering inconsistencies.
11. Ensure grammatical accuracy, proper spacing, and consistent terminology throughout the converted material.
12. Follow standardised naming conventions, file organisation practices, and documentation guidelines wherever applicable.
13. Review and test the final Markdown file in a Markdown-preview to confirm proper rendering and usability.

---

## Guidelines Alignment — Application Cross-Check

### Content Quality Guidelines

| # | Guideline | Status | How the application covers it |
|---|---|---|---|
| 1 | Define target audience and learning objectives | ✅ | `AUDIENCE_PROMPT` specifies the learner profile and language level; `ConfigInjection` supports per-deck audience overrides |
| 2 | Adapt to learner background | ⚠️ | Audience profile is a default — no per-deck variation for different learner levels yet |
| 3 | Market research on industry trends | ⚠️ | Must be done manually before uploading the source deck — the system does not perform market research |
| 4 | Verify concepts from trusted sources | ✅ | Source content grounding forces all facts to come from curated passages; alignment validator scores relevance; human reviewer approves before publishing |
| 5 | Logical flow — basic to advanced | ✅ | Topic-driven format enforces: definition → rule/types → examples → exceptions as a logical progression |
| 6 | Difficulty aligned to proficiency | ✅ | Audience prompt specifies language proficiency level; examples must match that level |
| 7 | Simple, learner-friendly language | ✅ | Prompt enforces plain, direct language appropriate to the audience |
| 8 | Short paragraphs, summaries, revision sections | ⚠️ | Tables and short paragraphs enforced; no dedicated Quick Recap section yet |
| 9 | Definitions, key points, shortcuts | ✅ | Every section opens with a definition; key terms in **bold** throughout |
| 10 | Practical, professional examples | ✅ | Examples use real-world contexts from the audience's domain |
| 11 | Contextual scenarios, analytical thinking | ✅ | Plain example sentences must show context — not just isolated grammar forms |
| 12 | Practice exercises after each section | ⚠️ | No mandatory practice exercises in the current format — reviewer can flag with `missing_example` |
| 13 | Common learner errors — L1 interference | ⚠️ | `missing_common_errors` feedback signal exists; Exception section covers some; dedicated Common Errors section not yet enforced |
| 14 | Corrective guidance in explanations | ✅ | Exception section shows what NOT to do alongside correct forms |
| 15 | Visuals, charts, tables | ✅ | Tables mandatory for all comparisons; image placeholders for diagrams; reviewer can flag with `needs_diagram` |
| 16 | Cross-check accuracy before publishing | ✅ | Human Approve/Reject workflow + G-Eval auto-scoring + Tier-1 structural assertions + alignment validator |
| 17 | Regular review based on feedback | ✅ | GEPA optimizer rewrites prompts on rejection; 13 feedback signals feed pattern memory; Shadow A/B validates improvements |

### Markdown Conversion Guidelines

| # | Guideline | Status | How the application covers it |
|---|---|---|---|
| 1 | Understand purpose and platform | ✅ | Format spec is purpose-built for the review UI; topic-driven pattern chosen per topic type |
| 2 | Maintain meaning and logical flow | ✅ | `deck_compiler.py` uses all slide titles to maintain the original deck's logical progression |
| 3 | Consistent Markdown syntax | ✅ | `#` / `##` / `###`, tables, `**bold**`, `*italic*`, `> blockquote` all explicitly required; `<b>` HTML explicitly forbidden |
| 4 | Clear hierarchy with spacing | ✅ | H1 → H2 → H3 hierarchy with `---` dividers between major sections |
| 5 | Clean, consistent formatting | ✅ | Both Pattern A and Pattern B have consistent section sequences |
| 6 | Verify lists and tables render correctly | ⚠️ | `remark-gfm` handles GFM tables and lists; human reviewer must confirm rendering before approving |
| 7 | Preserve examples, tables, notes | ✅ | Tables, bold terms, and image placeholders all explicitly preserved |
| 8 | Hyperlinks for references | ⚠️ | Source titles shown in the prompt but not formatted as clickable links in the output |
| 9 | Readable across platforms | ✅ | Pure Markdown — zero HTML (except user-inserted `<img>` S3 tags) — most portable format |
| 10 | Check for structural errors | ✅ | `TIER1_ASSERTIONS` validates H2 sections, table syntax, bold terms, and exception section presence |
| 11 | Grammar accuracy and terminology | ⚠️ | Reviewer can reject with `factual_error` or `unclear_explanation`; no automated grammar checker pre-review |
| 12 | Naming conventions | ✅ | `skill_type` naming is consistent; section headings follow the same pattern per topic type |
| 13 | Test in Markdown preview | ✅ | `GenerationCard` is a live rendered preview — reviewer sees the final output; external preview tool available via "Open Preview" button |

### Known Gaps — Planned Improvements

| Priority | Gap | Planned Fix |
|---|---|---|
| High | No mandatory Common Errors section (Guideline 13) | Enforce `## Common Errors` in the seed prompt with 3–5 L1-interference examples and corrections |
| Medium | No Quick Recap section (Guideline 8) | Add `## Quick Recap` with one-line takeaway per section at the end of each document |
| Medium | Source titles not clickable links in output | Update prompt rule so reference attributions use `[Title](URL)` Markdown format |
| Low | Audience profile not configurable per deck | Expose `ConfigInjection.audience` field in the upload form |

---

## Key Design Decisions

### One LLM call per deck
Earlier versions made one call per slide — O(n) cost and latency. The current architecture makes **exactly one call** per deck upload. Slides provide topic structure; the LLM writes the reading material as a coherent whole rather than stitching per-slide fragments.

### Slide titles only — no body text
The PPT body text is intentionally excluded from the prompt. The LLM should write fresh, grounded content — not paraphrase bullet points from slides. All factual content must come from curated source passages. This forces the human content developer to supply the factual grounding.

### Topic-driven format over fixed template
The original design used a rigid template (Overview → Subtopics → How to Prepare etc.) that did not suit grammar or communication topics. The current approach instructs the LLM to choose between Pattern A (grammar rule) and Pattern B (communication/pragmatics) based on the topic, producing output that matches how grammar textbooks actually look.

### Source grounding + alignment scoring
Adding reference passages before generating is optional but strongly recommended. The alignment validator (Haiku) runs on upload — not at generation time — keeping generation fast while giving the content developer immediate feedback on whether their passages are relevant.

### Book retrieval as a fallback, not a default
Auto-retrieval from ingested books (`USE_BOOK_RETRIEVAL=true`) is disabled by default. It activates only when no manual passages exist. This prevents book text from silently overriding carefully chosen passages. Manual always wins.

### OpenRouter instead of direct Anthropic
The LLM wrapper uses the OpenAI SDK pointed at `https://openrouter.ai/api/v1`. Any OpenRouter-supported model can be swapped in via `GENERATION_MODEL` and `ALIGNMENT_MODEL` env vars — no code changes needed.

### Per-deck shadow determinism
Shadow traffic split uses `hashlib.md5(deck_id)` — not per-request randomness. This ensures all slides within one deck always go to the same prompt version, making A/B comparisons meaningful.

### Human reviewer as the quality gate
Every generated document sits in `pending` status until a human approves it. G-Eval score, alignment score, and Tier-1 assertions are all advisory — none auto-approve. Factual accuracy, common-error coverage, and language quality are verified by a person before any material reaches learners.

---

## Licence

MIT
