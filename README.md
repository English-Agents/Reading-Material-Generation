# RMG — Reading Material Generator

An **agentic, self-improving pipeline** that converts PowerPoint presentations (or Google Slides) into structured reading material documents. Upload a deck, get a fully formatted, reviewable reading material in one LLM call. Reviewers approve or reject it; every rejection triggers automatic prompt optimisation via DSPy/GEPA so the system improves over time.

---

## Table of Contents

1. [What It Does](#what-it-does)
2. [Architecture Overview](#architecture-overview)
3. [Tech Stack](#tech-stack)
4. [Project Structure](#project-structure)
5. [How It Works — End to End](#how-it-works--end-to-end)
6. [Database Schema](#database-schema)
7. [API Reference](#api-reference)
8. [Environment Variables](#environment-variables)
9. [Local Setup](#local-setup)
10. [Running the Server](#running-the-server)
11. [Frontend](#frontend)
12. [Self-Improving Prompt System (DSPy + GEPA)](#self-improving-prompt-system-dspy--gepa)
13. [Shadow A/B Testing](#shadow-ab-testing)
14. [Memory System](#memory-system)
15. [Circuit Breaker & Repair Queue](#circuit-breaker--repair-queue)
16. [Ops Monitoring & Auto-Rollback](#ops-monitoring--auto-rollback)
17. [Eval Pipeline (PromptFoo)](#eval-pipeline-promptfoo)
18. [Running Tests](#running-tests)
19. [Content Quality Guidelines](#content-quality-guidelines)
20. [Markdown Conversion Guidelines](#markdown-conversion-guidelines)
21. [Guidelines Alignment — Application Cross-Check](#guidelines-alignment--application-cross-check)
22. [Key Design Decisions](#key-design-decisions)

---

## What It Does

| Input | Output |
|---|---|
| `.pptx` file upload | One complete reading material document in Markdown |
| Google Slides URL | One complete reading material document in Markdown |
| Direct `.pptx` URL | One complete reading material document in Markdown |

The generated reading material covers:
- **Overview** — what the topic is and why it matters
- **Subtopics & Examples** — 3–6 subtopics with Easy / Medium / Hard worked examples in workplace scenarios
- **How to Prepare** — step-by-step study advice
- **How to Score** — a table of common situations and strategies
- **Where to Practise** — online platforms and books

After generation, a human reviewer approves or rejects the output. Rejections are fed into an automatic prompt optimiser that improves future generations.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         UPLOAD                                  │
│   .pptx file  ──┐                                               │
│   Google Slides ─┼──► slide_parser.py ──► ParsedSlide[]        │
│   Direct URL  ──┘                              │                │
└───────────────────────────────────────────────┼─────────────────┘
                                                 │
                                    ┌────────────▼────────────┐
                                    │    deck_compiler.py      │
                                    │  (ONE LLM call per deck) │
                                    │  text-only prompt with   │
                                    │  all slide content       │
                                    └────────────┬────────────┘
                                                 │
                                    ┌────────────▼────────────┐
                                    │   OpenRouter / Claude    │
                                    │  anthropic/claude-       │
                                    │  sonnet-4-6              │
                                    └────────────┬────────────┘
                                                 │
                              ┌──────────────────▼───────────────────┐
                              │          PostgreSQL + pgvector        │
                              │  generations table  (status=pending)  │
                              └──────────────────┬───────────────────┘
                                                 │
                              ┌──────────────────▼───────────────────┐
                              │         React Review UI               │
                              │   Approve ─────────► embed output    │
                              │   Reject  ──┬───────► record feedback │
                              │             └───────► GEPA optimizer  │
                              └──────────────────────────────────────┘
```

**Background systems running at all times:**
- **Ops job** (every 15 min) — shadow A/B promotion, alert checks, auto-rollback
- **G-Eval scorer** — auto-scores approved outputs via DSPy ChainOfThought
- **Repair queue** — retries failed generations up to `MAX_RETRIES` times

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Backend API** | FastAPI + Uvicorn (async) |
| **LLM** | OpenRouter → `anthropic/claude-sonnet-4-6` via OpenAI-compatible SDK |
| **Embeddings** | OpenAI `text-embedding-3-small` (1536 dimensions) |
| **Database** | PostgreSQL 16 + pgvector extension (IVFFlat cosine index) |
| **ORM** | SQLAlchemy 2.0 async (asyncpg driver) |
| **Cache** | Redis 7 — vision cache (7-day TTL), app-level Redis pool |
| **Migrations** | Alembic |
| **Prompt Optimisation** | DSPy 3.x — `dspy.ChainOfThought` for G-Eval, `dspy.teleprompt.GEPA` |
| **Eval Pipeline** | PromptFoo (Node.js) + Python subprocess provider |
| **Frontend** | React 18 + Vite + TypeScript + Tailwind CSS + TanStack Query |
| **Markdown Rendering** | `react-markdown` + `remark-gfm` + `rehype-raw` |
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
│
├── ppt_agent/
│   ├── llm.py                   # Central LLM wrapper — OpenRouter via OpenAI SDK
│   │
│   ├── api/
│   │   ├── main.py              # FastAPI app factory + lifespan (Redis pool, ops job)
│   │   ├── deps.py              # Dependency injection — get_db(), get_redis()
│   │   ├── generate.py          # POST /generate/file  POST /generate/url
│   │   ├── review.py            # POST /review/{id}/approve|reject|feedback
│   │   ├── ops.py               # GET /ops/dashboard  GET /ops/alerts + background job
│   │   └── export.py            # POST /export/{deck_id}
│   │
│   ├── config/
│   │   ├── settings.py          # Pydantic-settings — all env vars in one place
│   │   └── format_schema.py     # The FORMAT_TEMPLATE — pure markdown output spec
│   │
│   ├── db/
│   │   ├── models.py            # SQLAlchemy ORM — 6 tables
│   │   └── session.py           # Async session factory + get_db_session() context manager
│   │
│   ├── skills/
│   │   ├── deck_compiler.py     # ONE LLM call per deck — builds reading material
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
│   ├── evals/
│   │   ├── promptfoo.yaml       # PromptFoo eval config
│   │   ├── caption_judge.py     # PromptFoo Python subprocess provider
│   │   ├── run_regression.py    # Run PromptFoo + write results to DB
│   │   ├── test_case_generator.py  # Auto-generate regression tests on rejection
│   │   └── regression_suite/
│   │       └── auto_generated.yaml  # Growing test case library
│   │
│   └── tests/
│       ├── conftest.py
│       ├── test_api.py
│       ├── test_circuit_breaker.py
│       ├── test_evals.py
│       ├── test_image_pipeline.py
│       ├── test_memory.py
│       └── test_slide_parser.py
│
├── migrations/
│   ├── env.py                   # Alembic env — strips +asyncpg for sync migrations
│   ├── script.py.mako
│   └── versions/
│       ├── 0001_initial.py      # All 6 tables + pgvector IVFFlat index
│       └── 0002_add_deck_reading.py  # Adds deck_reading to skill_type CHECK constraint
│
├── frontend/                    # React review UI (see Frontend section)
│   ├── src/
│   │   ├── pages/
│   │   │   ├── UploadPage.tsx   # Drag-and-drop PPTX upload + Google Slides URL
│   │   │   ├── ReviewPage.tsx   # Show generated reading material, Approve / Reject
│   │   │   └── DashboardPage.tsx  # Per-skill stats, alerts, repair queue
│   │   ├── components/
│   │   │   ├── GenerationCard.tsx   # Renders markdown output with Approve/Reject
│   │   │   ├── FeedbackModal.tsx    # Signal picker for rejection feedback
│   │   │   └── Layout.tsx
│   │   └── api/client.ts        # Typed axios wrapper for all API endpoints
│   └── ...
│
├── render.yaml                  # Render.com deployment — all 4 services defined
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
- `body_text` — all text frames concatenated
- `speaker_notes` — presenter notes
- `embedded_images` — list of `{base64_data, mime_type, md5}`

### 3. Compile — ONE LLM call
`deck_compiler.py` concatenates all slide titles, body text, and speaker notes into a single prompt block and makes **one** call to `claude-sonnet-4-6` via OpenRouter with `max_tokens=8192`. No per-slide generation — this keeps cost and latency low.

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

### 6. Self-improve
- Every rejection adds a labelled example to the GEPA training set
- When ≥ 10 labelled examples exist, the GEPA optimizer rewrites the `deck_reading` prompt and stores it as a `candidate` prompt version
- The ops background job promotes shadow versions that beat the active version by ≥ 5% (`SHADOW_PROMOTION_MARGIN`)

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
Stores structured signals from reviewers:

| `signal_type` | Meaning |
|---|---|
| `too_long` | Output is too long |
| `too_short` | Output is too short |
| `wrong_tone` | Tone doesn't match audience |
| `missing_example` | Missing worked examples |
| `factual_error` | Contains factual mistakes |
| `format_violation` | Format template not followed |
| `unnecessary_diagram` | Diagram added where not needed |
| `needs_diagram` | Should have a diagram |
| `unclear_explanation` | Explanation is confusing |

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
  "signal_type": "too_short",
  "severity": 2,
  "section_id": "overview",
  "reviewer_note": "Only one sentence in the overview"
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

# OpenAI — only needed for text-embedding-3-small
OPENAI_API_KEY=sk-...

# Google Slides — base64-encoded service account JSON
# Service account needs Drive API read access
GOOGLE_SERVICE_ACCOUNT_JSON=<base64>

# Database
DATABASE_URL=postgresql+asyncpg://rmg:rmg@localhost:5434/rmgdb

# Redis
REDIS_URL=redis://localhost:6379/0

# Tuning
MAX_RETRIES=3
PATTERN_CONFIDENCE_THRESHOLD=0.75
SHADOW_PROMOTION_MARGIN=0.05
MIN_EXAMPLES_CONSTANT=20

# Shadow A/B config per skill
SHADOW_CONFIG_JSON={"concept_explainer":{"traffic_pct":0.2,"min_slides":50},"code_walkthrough":{"traffic_pct":0.2,"min_slides":100},"diagram_describer":{"traffic_pct":0.3,"min_slides":40},"figure_caption":{"traffic_pct":0.3,"min_slides":40}}
```

> **Never commit `.env`** — it contains your API keys. The `.gitignore` already excludes it.

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
# Edit .env — add your ANTHROPIC_API_KEY at minimum
```

### Step 4 — Run database migrations

```bash
alembic upgrade head
```

This creates all 6 tables and the pgvector IVFFlat index.

### Step 5 — Seed initial prompts

```bash
python seed_db.py
```

This inserts the initial `active` prompt versions for all 6 skill types into `prompt_versions`.

### Step 6 — Install frontend dependencies

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

The API is available at `http://localhost:8000`.
Interactive docs: `http://localhost:8000/docs`

### Frontend (React)

```bash
cd frontend
npm run dev
```

The UI is available at `http://localhost:5173`.

Vite proxies all `/generate`, `/review`, `/ops`, `/export` requests to the FastAPI server at port 8000.

---

## Frontend

Three pages:

### Upload Page (`/`)
- Drag-and-drop `.pptx` upload
- Google Slides URL input
- Shows a spinner while generation runs (20–40 seconds)
- Redirects to `/review/{deck_id}` on success

### Review Page (`/review/:deckId`)
- Fetches the `deck_reading` generation for the deck
- Renders the full Markdown output using `react-markdown` + `remark-gfm`
- **Approve** button — optionally override eval score (0–1)
- **Reject** button — opens FeedbackModal to select signals
- Shows G-Eval score in the card header once computed
- Export buttons (PDF, DOCX, Markdown) enabled only after approval

### Dashboard Page (`/dashboard`)
- Per-skill stats table: total generations, approved, rejected, repair count, avg score, avg cost
- Open alerts list
- Repair queue depth

---

## Self-Improving Prompt System (DSPy + GEPA)

### G-Eval Auto-Scoring

When a generation is approved, `geval.py` runs in the background:

1. Configures DSPy with the OpenRouter LLM
2. Runs `dspy.ChainOfThought` against a `ReadingMaterialQuality` signature
3. Returns a float `0.0–1.0` and a reasoning string
4. Writes the score back to `generations.eval_score`

This means every approved output gets an objective quality score without reviewer effort.

### GEPA Prompt Optimisation

When a generation is rejected, `prompt_optimizer.py` runs in the background:

1. Queries all labelled `deck_reading` generations (approved = 1.0, rejected = 0.0)
2. If fewer than 10 examples exist — skips (not enough signal)
3. If ≥ 10 examples — runs `dspy.teleprompt.GEPA`:
   - Uses `GEPAFeedbackMetric` as the reward signal
   - Produces a rewritten system prompt
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

1. **Traffic split** — determined **per deck** (not per slide) using `hashlib.md5(deck_id)` → deterministic float. All slides in one deck always go to the same branch.

2. **Config** — per-skill traffic percentage and minimum slide count set in `SHADOW_CONFIG_JSON`:
   ```json
   {"concept_explainer": {"traffic_pct": 0.2, "min_slides": 50}}
   ```

3. **Promotion** — every 15 minutes the ops background job compares:
   ```
   shadow_avg_score - active_avg_score >= SHADOW_PROMOTION_MARGIN (default 0.05)
   ```
   - If the shadow wins → promoted to `active`, old active → `retired`
   - If it loses → shadow → `retired`

Shadow generations are stored with `is_shadow = True` and excluded from the review UI.

---

## Memory System

The memory layer powers two things: **similar output retrieval** and **pattern promotion**.

### Similar Output Retrieval
When generating (legacy per-slide path), `retrieval.py`:
1. Embeds the slide content using `text-embedding-3-small`
2. Queries pgvector for the top-5 most similar **approved** past outputs using cosine distance
3. Returns them as `MemoryContext` — injected into the skill prompt

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
3. The router checks `isinstance(result, RepairRequired)` and branches
4. Repair queue is visible in the dashboard and via `GET /review/repair-queue`

---

## Ops Monitoring & Auto-Rollback

The `ops_background_job()` runs every 15 minutes inside the FastAPI lifespan:

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
4. Logged as a warning

Alerts can also be manually resolved via `POST /ops/alerts/{id}/resolve`.

---

## Eval Pipeline (PromptFoo)

PromptFoo runs two tiers of evaluation:

### Tier 1 — Deterministic (must all pass)
Per-skill checks run without any LLM call:
- `concept_explainer` — must contain `key_terms`, length > 200, no `"I cannot"`
- `code_walkthrough` — must contain ` ``` `, length > 100
- `diagram_describer` — must contain `relationships`, `key_elements`
- `figure_caption` — length between 20–300 characters
- `quiz_generator` — must contain `question`, `answer`

### Tier 2 — LLM Rubric
`caption_judge.py` is a Python subprocess provider that:
1. Reads JSON from stdin (PromptFoo format)
2. Calls the LLM synchronously to score the output 1–5
3. Writes `{"output": ..., "score": ..., "pass": ...}` to stdout

Average Tier 2 score must be ≥ 3.5 for a prompt to be eligible for promotion.

### Running Evals

```bash
npx promptfoo eval --config ppt_agent/evals/promptfoo.yaml
```

Or trigger via the regression runner:

```bash
python ppt_agent/evals/run_regression.py
```

Results are written back to the `prompt_versions` table.

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
| 1 | Define target audience and learning objectives | ✅ | `AUDIENCE_PROMPT` specifies beginner-to-intermediate learners targeting TCS/Infosys/Wipro/Cognizant placement tests |
| 2 | Adapt to learner background | ⚠️ | Audience is hardcoded — no per-deck variation for different learner levels |
| 3 | Market research on industry trends | ⚠️ | Must be done manually before uploading the source deck — the system does not perform market research |
| 4 | Verify concepts from trusted sources | ⚠️ | "Where to Practise" lists real resources; content accuracy must be verified by the human reviewer before approving |
| 5 | Logical flow — basic to advanced | ✅ | `FORMAT_TEMPLATE` enforces: Overview → Subtopics (Easy → Medium → Hard) → Prepare → Score → Practise |
| 6 | Difficulty aligned to proficiency | ✅ | Easy / Medium / Hard examples enforced per subtopic; placement test audience profile is hardcoded |
| 7 | Simple, learner-friendly language | ✅ | Prompt enforces conversational but professional second-person voice throughout |
| 8 | Short paragraphs, summaries, revision sections | ⚠️ | Numbered lists and tables are used; no dedicated Key Takeaways or Quick Recap section |
| 9 | Definitions, key points, shortcuts | ⚠️ | Each subtopic opens with a definition paragraph and Quick Tip; no standalone Key Points block |
| 10 | Practical, professional examples | ✅ | Every example must use sprint / bug fix / code review / product launch scenarios — hardcoded rule |
| 11 | Contextual scenarios, analytical thinking | ✅ | Every MCQ has a workplace scenario + explanation of why the correct answer is right and why distractors are wrong |
| 12 | Practice exercises after each section | ⚠️ | Three MCQs per subtopic are included; no open-ended or non-MCQ practice activities |
| 13 | Common learner errors — L1 interference | ❌ | No Common Errors section exists in the current format template |
| 14 | Corrective guidance in explanations | ✅ | `FORMAT_TEMPLATE` rule: every explanation must state why the correct answer is right and why at least one wrong option is wrong |
| 15 | Visuals, charts, tables | ⚠️ | How to Score is a table; Quick Tips use styled blockquotes; no concept diagrams or visual grammar aids |
| 16 | Cross-check accuracy before publishing | ✅ | Human Approve / Reject workflow + G-Eval auto-scoring + Tier-1 structural assertions |
| 17 | Regular review based on feedback | ✅ | GEPA optimizer rewrites prompts on rejection; feedback signals feed pattern memory; Shadow A/B validates improvements |

### Markdown Conversion Guidelines

| # | Guideline | Status | How the application covers it |
|---|---|---|---|
| 1 | Understand purpose and platform | ✅ | `FORMAT_TEMPLATE` is purpose-built for the review UI and placement test audience |
| 2 | Maintain meaning and logical flow | ✅ | `deck_compiler.py` faithfully represents all slide content in the prompt |
| 3 | Consistent Markdown syntax | ✅ | `#` / `##` / `###`, numbered lists, tables, `**bold**`, `*italic*`, `> blockquote` all explicitly defined in the template |
| 4 | Clear hierarchy with spacing | ✅ | `#` title → `##` sections → `###` subtopics → `---` dividers throughout |
| 5 | Clean, consistent formatting | ✅ | Every subtopic follows identical structure: definition → Example 1/2/3 → Quick Tip |
| 6 | Verify lists and tables render correctly | ⚠️ | `remark-gfm` handles GFM tables and lists; human reviewer must confirm rendering before approving |
| 7 | Preserve examples, tables, notes | ✅ | MCQ structure, How to Score table, and `> **Quick Tip:**` blockquotes are all preserved |
| 8 | Hyperlinks for references | ❌ | "Where to Practise" resources are plain text — not formatted as clickable Markdown links |
| 9 | Readable across platforms | ✅ | Pure Markdown — zero HTML — the most portable format possible |
| 10 | Check for structural errors | ✅ | `TIER1_ASSERTIONS` validates all 9 required section markers are present before a generation is stored |
| 11 | Grammar accuracy and terminology | ⚠️ | Reviewer can reject with `factual_error` or `unclear_explanation`; no automated grammar checker runs pre-review |
| 12 | Naming conventions and file organisation | ✅ | `skill_type` naming is consistent; all sections always use the same heading names |
| 13 | Test in Markdown preview | ✅ | `GenerationCard` is a live rendered preview — reviewer sees the final output before approving |

### Known Gaps — Planned Improvements

| Priority | Gap | Planned Fix |
|---|---|---|
| High | No Common Errors section (Guideline 13) | Add `## Common Errors` section to `FORMAT_TEMPLATE` listing 3–5 typical L1-interference mistakes with corrections |
| High | No Key Points block per subtopic (Guideline 9) | Add a `> **Key Points:**` summary after each subtopic definition, before Example 1 |
| Medium | "Where to Practise" links are plain text (Markdown Guideline 8) | Change prompt rule so resources use `[Name](URL)` Markdown link format |
| Medium | No Quick Recap at end of document (Guideline 8) | Add a `## Quick Recap` section with one bullet takeaway per subtopic |

---

## Key Design Decisions

### One LLM call per deck (not per slide)
Earlier versions made one call per slide, then a final compilation call — N+1 total. This was slow (minutes) and expensive. The current architecture makes **exactly one call** per deck upload, reducing both cost and latency by an order of magnitude.

### Pure Markdown output (no HTML)
The `FORMAT_TEMPLATE` in `format_schema.py` uses only standard Markdown — no `<details>`, `<summary>`, or custom JSX components. LLMs follow plain Markdown much more reliably than HTML-hybrid formats.

### OpenRouter instead of direct Anthropic
The LLM wrapper in `llm.py` uses the OpenAI SDK pointed at `https://openrouter.ai/api/v1`. This means:
- Any OpenRouter-supported model can be swapped in via the `GENERATION_MODEL` env var
- No code changes needed to switch providers

### Per-deck shadow determinism
Shadow traffic split uses `hashlib.md5(deck_id)` — not per-request randomness. This ensures all slides within one deck always go to the same prompt version, making A/B comparisons meaningful.

### DSPy GEPA only when ≥10 examples
Running the optimizer with fewer examples produces noisy, overfitted prompts. The 10-example floor ensures the optimizer has enough signal to improve rather than just memorise.

### Human reviewer as the quality gate
Every generated document sits in `pending` status until a human approves it. The G-Eval score is advisory only — it does not auto-approve. This ensures content guidelines (especially factual accuracy and common-error coverage) are verified by a person before any material reaches learners.

---

## Licence

MIT
