# RMG — Reading Material Generator

An **agentic, self-improving pipeline** that converts PowerPoint presentations (or Google Slides) into structured, instructionally-complete reading material documents. Upload a deck, get a fully formatted reading material in one LLM call. Reviewers approve or reject it; every rejection triggers automatic prompt optimisation so the system improves over time.

---

## Table of Contents

1. [What It Does](#what-it-does)
2. [Architecture Overview](#architecture-overview)
3. [Tech Stack](#tech-stack)
4. [Project Structure](#project-structure)
5. [How It Works — End to End](#how-it-works--end-to-end)
6. [Source Content Grounding](#source-content-grounding)
7. [Alignment Validator](#alignment-validator)
8. [Book Ingestion Pipeline (RAG)](#book-ingestion-pipeline-rag)
9. [Topic-Driven Format](#topic-driven-format)
10. [Instructional Design Features](#instructional-design-features)
11. [Database Schema](#database-schema)
12. [API Reference](#api-reference)
13. [Environment Variables](#environment-variables)
14. [Local Setup](#local-setup)
15. [Running the Server](#running-the-server)
16. [Frontend](#frontend)
17. [Deployment — Render + Neon + Upstash (Free)](#deployment--render--neon--upstash-free)
18. [Self-Improving Prompt System (DSPy + GEPA)](#self-improving-prompt-system-dspy--gepa)
19. [Shadow A/B Testing](#shadow-ab-testing)
20. [Memory System](#memory-system)
21. [Circuit Breaker & Repair Queue](#circuit-breaker--repair-queue)
22. [Ops Monitoring & Auto-Rollback](#ops-monitoring--auto-rollback)
23. [Eval Pipeline (PromptFoo)](#eval-pipeline-promptfoo)
24. [Running Tests](#running-tests)
25. [Content Quality Guidelines](#content-quality-guidelines)
26. [Guidelines Alignment — Application Cross-Check](#guidelines-alignment--application-cross-check)
27. [Key Design Decisions](#key-design-decisions)

---

## What It Does

| Input | Output |
|---|---|
| `.pptx` file upload | One complete instructional reading material document in Markdown |
| Google Slides URL | One complete instructional reading material document in Markdown |
| Direct `.pptx` URL | One complete instructional reading material document in Markdown |

The generated reading material is **instructionally complete** — not just a content expansion of the slides. Every document includes:

- **Learning Objectives** — action-verb bullets (identify, apply, transform…)
- **Before You Begin** — prerequisite knowledge the learner needs
- **Core teaching sections** — rules, tables, examples (topic-driven)
- **Dialogue Simulation** — Person A / Person B scenarios (communication topics)
- **Common Mistakes** — error table + placement exam traps
- **Practice exercises** — 3 CEFR-labelled exercises with inline answers and remediation hints
- **Exception Cases** — rule-breakers and edge cases
- **Quick Recap** — 5-bullet summary of the whole document
- **Persona callout boxes** — `💡 Beginner Tip`, `📌 Placement Candidate`, `⚡ Advanced Extension`

Minimum output: **1,800 words** per document.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                            UPLOAD                                   │
│   .pptx file  ──┐                                                   │
│   Google Slides ─┼──► slide_parser.py ──► ParsedSlide[]            │
│   Direct URL  ──┘                              │                    │
└────────────────────────────────────────────────┼────────────────────┘
                                                  │
                         ┌────────────────────────▼─────────────────┐
                         │           deck_compiler.py                │
                         │       (ONE LLM call per deck)             │
                         │                                           │
                         │  Slide TITLES only (no body text)         │
                         │         +                                 │
                         │  Source passages  ────────────────────────┤
                         │  (curated manually via UI or auto-        │
                         │   retrieved from books/ via pgvector)     │
                         └────────────────────────┬─────────────────┘
                                                  │
                         ┌────────────────────────▼─────────────────┐
                         │  OpenRouter → anthropic/claude-sonnet-4-6 │
                         │           max_tokens = 8,192              │
                         └────────────────────────┬─────────────────┘
                                                  │
                    ┌─────────────────────────────▼──────────────────────┐
                    │              PostgreSQL (Neon) + pgvector           │
                    │  generations ── source_content ── book_chunks      │
                    └─────────────────────────────┬──────────────────────┘
                                                  │
                    ┌─────────────────────────────▼──────────────────────┐
                    │              React Review UI (served by FastAPI)    │
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
| **Database** | PostgreSQL 16 + pgvector extension (IVFFlat cosine index) — hosted on Neon |
| **ORM** | SQLAlchemy 2.0 async (asyncpg driver) |
| **Cache** | Redis — vision cache (7-day TTL) — hosted on Upstash |
| **Migrations** | Alembic |
| **Prompt Optimisation** | DSPy 3.x — `dspy.ChainOfThought` for G-Eval, `dspy.teleprompt.GEPA` |
| **Eval Pipeline** | PromptFoo (Node.js) + Python subprocess provider |
| **Frontend** | React 19 + Vite + TypeScript + Tailwind CSS v4 + TanStack Query |
| **Markdown Rendering** | `react-markdown` + `remark-gfm` + `rehype-raw` |
| **Book parsing** | `pdfplumber` (PDF), `ebooklib` + `beautifulsoup4` (EPUB), plain text |
| **Deployment** | Render (web service) + Neon (PostgreSQL) + Upstash (Redis) |
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
├── ingest_books.py              # Ingests books from books/ → book_chunks table (RAG)
├── start.sh                     # Render startup script — migrate + seed + uvicorn
├── render.yaml                  # Render deployment blueprint
├── .python-version              # Python 3.11.0 — used by Render build
│
├── books/                       # Drop .pdf / .epub / .txt reference books here
│   └── .gitkeep
│
├── ppt_agent/
│   ├── llm.py                   # Central LLM wrapper — OpenRouter via OpenAI SDK
│   │
│   ├── api/
│   │   ├── main.py              # FastAPI app factory + static file serving (serves React build)
│   │   ├── deps.py              # Dependency injection — get_db(), get_redis()
│   │   ├── generate.py          # POST /generate/file  POST /generate/url
│   │   ├── review.py            # POST /review/{id}/approve|reject|feedback
│   │   ├── source_content.py    # CRUD for source passages (add, list, delete, validate)
│   │   ├── ops.py               # GET /ops/dashboard  GET /ops/alerts + background job
│   │   └── export.py            # POST /export/{deck_id}
│   │
│   ├── config/
│   │   ├── settings.py          # Pydantic-settings — all env vars, URL conversion for Neon SSL
│   │   └── format_schema.py     # Topic-driven format (Pattern A / B) + TIER1_ASSERTIONS
│   │
│   ├── db/
│   │   ├── models.py            # SQLAlchemy ORM — 8 tables
│   │   └── session.py           # Async session factory + get_db_session() context manager
│   │
│   ├── skills/
│   │   ├── deck_compiler.py     # ONE LLM call per deck — builds reading material
│   │   ├── alignment_validator.py  # Per-passage Haiku scoring (pass ≥0.7, warn 0.5–0.69)
│   │   ├── book_retriever.py    # pgvector similarity search over book_chunks (traditional RAG)
│   │   ├── seed_prompts.py      # System prompt text for every skill — full instructional spec
│   │   ├── router.py            # Routes slides to the right skill (legacy per-slide path)
│   │   ├── concept_explainer.py
│   │   ├── code_walkthrough.py
│   │   ├── diagram_describer.py
│   │   ├── figure_caption.py
│   │   ├── quiz_generator.py
│   │   ├── cost_tracker.py
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
│       ├── promptfoo.yaml
│       ├── caption_judge.py
│       ├── run_regression.py
│       ├── test_case_generator.py
│       └── regression_suite/
│           └── auto_generated.yaml
│
├── migrations/
│   └── versions/
│       ├── 0001_initial.py
│       ├── 0002_add_deck_reading.py
│       ├── 0003_source_content.py
│       ├── 0004_schema_fixes.py
│       └── 0005_book_chunks.py
│
├── frontend/
│   └── src/
│       ├── pages/
│       │   ├── UploadPage.tsx
│       │   ├── ReviewPage.tsx
│       │   ├── SourceContentPage.tsx
│       │   └── DashboardPage.tsx
│       ├── components/
│       │   ├── GenerationCard.tsx
│       │   ├── FeedbackModal.tsx
│       │   ├── AlignmentBadge.tsx
│       │   ├── PassageForm.tsx
│       │   └── Layout.tsx
│       └── api/client.ts
│
├── pyproject.toml
├── alembic.ini
├── docker-compose.yml
├── .env.example
└── .gitignore
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
- `title` — slide heading (sent to LLM)
- `body_text` — all text frames (NOT sent to LLM — titles only)
- `speaker_notes`
- `embedded_images` — list of `{base64_data, mime_type, md5}`

### 3. Compile — ONE LLM call
`deck_compiler.py` builds the prompt from:
- **Slide titles only** — body text intentionally excluded
- **Source passages** — curated reference material (manual priority)
- **Book chunks** (optional) — auto-retrieved via pgvector when `USE_BOOK_RETRIEVAL=true` and no manual passages exist

One call to `claude-sonnet-4-6` via OpenRouter, `max_tokens=8192`. Cost ≈ $0.01–0.04 per deck.

### 4. Store
The output is saved as a `Generation` row:
- `skill_type = "deck_reading"`
- `slide_index = -1` (whole deck)
- `status = "pending"`
- `token_cost_usd` from actual token counts

### 5. Review
The React UI fetches the pending generation and renders it as formatted Markdown. Reviewer actions:

| Action | What happens |
|---|---|
| **Approve** | `status → approved`, embedding computed, G-Eval auto-score written |
| **Reject** | `status → rejected`, 13-signal feedback recorded, regression test generated, GEPA triggered |
| **Copy MD** | Copies raw Markdown to clipboard |
| **Open Preview** | Opens in external Markdown preview |

### 6. Self-improve
Every rejection adds a labelled example to GEPA training set. At ≥10 examples, GEPA rewrites the prompt and creates a `candidate` version for shadow A/B testing.

---

## Source Content Grounding

The generation is grounded in curated reference passages — the LLM **cannot invent facts** not present in the passages.

### Source passage budget

| Limit | Value |
|---|---|
| Max chars per passage | 2,000 |
| Max chars per deck | 12,000 (~3,000 tokens) |

### Source content API

| Method | Path | Description |
|---|---|---|
| `GET` | `/source-content/{deck_id}` | List all passages + budget usage |
| `POST` | `/source-content/{deck_id}` | Add a passage (triggers alignment scoring) |
| `DELETE` | `/source-content/{deck_id}/{id}` | Remove a passage |
| `POST` | `/source-content/{deck_id}/validate` | Re-run alignment on all passages |

---

## Alignment Validator

Every source passage is automatically scored for topical relevance using `claude-haiku-4-5`.

| Score | Verdict | Meaning |
|---|---|---|
| ≥ 0.70 | `pass` ✅ | On-topic, suitable for grounding |
| 0.50–0.69 | `warn` ⚠️ | Partially relevant — review before use |
| < 0.50 | `fail` ❌ | Off-topic — replace |

A failing score is advisory only — it does not block generation.

---

## Book Ingestion Pipeline (RAG)

The system uses **Traditional RAG** — embed-retrieve-generate — over a library of ingested grammar and reference books.

### How it works

```
PDF / EPUB / TXT
      ↓
Text Extraction (pdfplumber / ebooklib / plain)
      ↓
Sentence-boundary chunking (~1,500 chars, 150-char overlap)
      ↓
text-embedding-3-small → Vector(1536)
      ↓
Stored in book_chunks (pgvector)
      ↓
At generation: cosine similarity search over combined topic labels
top_k=6, min_similarity=0.35
      ↓
Top chunks injected as reference passages into the LLM prompt
```

### Current RAG type and limitations

| Type | Status |
|---|---|
| Single combined query | ✅ Current implementation |
| Per-topic retrieval | ⚠️ Future improvement — run one query per slide title |
| Re-ranking (cross-encoder) | ⚠️ Not yet implemented |
| HyDE (Hypothetical Document Embeddings) | ⚠️ Not yet implemented |
| Semantic chunking | ⚠️ Fixed 1,500-char chunks currently |

Manual source passages always take priority over book retrieval.

### File naming convention

```
Grammar in Use - Raymond Murphy.pdf
Swan Practical English Usage - Michael Swan.epub
Sentence Stress Notes.txt
```

Format: `Title - Author.ext` — author is auto-extracted after the ` - ` separator.

### CLI

```bash
python ingest_books.py                    # process all new files
python ingest_books.py --list             # show indexed books
python ingest_books.py --file grammar.pdf # process one file
python ingest_books.py --reindex          # force re-process all
```

Set `USE_BOOK_RETRIEVAL=true` in `.env` to activate auto-retrieval.

---

## Topic-Driven Format

The LLM selects the pattern that best fits the topic type.

### Pattern A — Grammar Rule Topics
Active/passive voice, tenses, conditionals, articles, reported speech, etc.

```
# [Title]
## Learning Objectives
## Before You Begin
## What is [Topic]?
## Why is it important?
## [Core Rule / Structure]         ← transformation tables mandatory
## [Topic] in Different Tenses / Contexts
## Where is [Topic] used?          ← General / Academic / Professional table
## Common Mistakes                 ← error table + placement exam traps
## Practice                        ← 3 CEFR-labelled exercises + remediation hints
## Exception Cases
## Quick Recap
```

### Pattern B — Communication / Pragmatics Topics
Fillers, intonation, sentence stress, register, hedging, discourse markers, etc.

```
# [Title]
## Learning Objectives
## Before You Begin
## Quick Examples
## Why is [Topic] important?
## Types of [Topic]                ← classification table mandatory
## Placement / Patterns
## Usage in Context                ← General / Academic / Professional
## Dialogue Simulation             ← 3 Person A / B scenarios
## Common Mistakes                 ← error table + placement exam traps
## Practice                        ← 3 CEFR-labelled exercises + remediation hints
## Exception Cases and Restrictions
## Quick Recap
```

### Format invariants (both patterns)

- H1 title → H2 sections → H3 sub-concepts
- Markdown tables for **all** comparisons — no prose lists for structured data
- `**bold**` for key terms — never `<b>` HTML tags
- Plain example sentences — no MCQ (A/B/C/D) anywhere in the body
- Image placeholders: `> 📷 **Image:** *[description]*`
- Minimum **1,800 words** per document

---

## Instructional Design Features

These features were added to move the system from a "content elaborator" to a genuine instructional unit.

### Learning Objectives
Every document opens with 4–5 action-verb bullets:
```markdown
After completing this reading, you will be able to:
- identify active and passive voice in any sentence
- transform sentences between active and passive voice
- apply the correct form in formal and informal writing
```

### Before You Begin
Prerequisites so learners know what knowledge to bring:
```markdown
Make sure you are comfortable with:
- identifying the subject and object of a sentence
- basic verb forms: base, past simple, past participle
```

### Common Mistakes with Exam Traps
Mandatory error table (≥4 rows) with L1-interference reasons + placement test gotchas:
```markdown
| Incorrect | Correct | Why the error happens |
|---|---|---|
| *The letter was wrote...* | *The letter was written...* | Confusion between past simple and past participle |

**Placement test traps:**
- TCS often tests collective nouns — "team" takes singular verb in formal writing
```

### Practice Exercises (CEFR-labelled)
Three non-MCQ exercises per document with difficulty labels and inline answers:
```markdown
**Exercise 1 — Transform the sentence:** *(CEFR: B1)*
**Exercise 2 — Fill in the blank:** *(CEFR: B1–B2)*
**Exercise 3 — Spot the error:** *(CEFR: B2–C1)*
```

Each exercise ends with a remediation hint:
```markdown
*Struggled here? Go back to **[Section Name]** and focus on [specific rule].*
```

### Dialogue Simulation (Pattern B only)
Three Person A / B conversational scenarios — matches how PPT slides teach communication:
```markdown
**Scenario 1 — Job interview**
> **Context:** Candidate is asked about a gap in their CV.
> **Person A:** "Can you tell me about this gap in your resume?"
> **Option 1:** "Well, um, I was, you know, exploring options..."
> **Option 2:** "I used that time to complete an online course in data analysis."
*(Better response: Option 2 — because fillers weaken professional credibility)*
```

### Persona Callout Boxes
Three types, placed inline after relevant rules (not grouped together):
```markdown
> 💡 **Beginner Tip:** *If you can replace the verb with "was/were done", it is passive voice.*
> 📌 **Placement Candidate:** *TCS NQT tests this by giving two options that look identical — check the agent, not the verb.*
> ⚡ **Advanced Extension:** *In academic writing, passive voice is preferred even when the agent is known.*
```

### Quick Recap
Final section — 5 bullets, one per key concept:
```markdown
## Quick Recap
- **Active voice:** Subject performs the action — agent is clear and upfront.
- **Passive voice:** Subject receives the action — agent is moved to the end or omitted.
```

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
| `output_text` | TEXT | Generated reading material (Markdown) |
| `tokens_in / tokens_out` | INT | Actual token counts |
| `token_cost_usd` | NUMERIC | Calculated cost in USD |
| `eval_score` | NUMERIC(3,2) | 0.0–1.0 quality score |
| `status` | TEXT | `pending \| approved \| rejected \| needs_repair` |
| `is_shadow` | BOOL | True for shadow A/B generations |
| `embedding` | Vector(1536) | pgvector embedding for similarity search |

### `source_content`
| Column | Type | Description |
|---|---|---|
| `id` | UUID PK | |
| `deck_id` | UUID | Which deck this passage belongs to |
| `topic_label` | TEXT | Topic this passage covers |
| `passage_text` | TEXT (≤2000) | Curated reference text |
| `source_title` | TEXT | Book title or source name |
| `page_ref` | TEXT | Page number / section |
| `author` | TEXT | Author of the source |
| `alignment_score` | NUMERIC(4,3) | 0.0–1.0 relevance score from Haiku |
| `alignment_verdict` | TEXT | `pass \| warn \| fail` |
| `alignment_reason` | TEXT | Human-readable reason from the scorer |

### `book_chunks`
| Column | Type | Description |
|---|---|---|
| `id` | UUID PK | |
| `book_title` | TEXT | From filename |
| `author` | TEXT | From filename (after ` - `) |
| `file_name` | TEXT | Original filename — used for dedup |
| `chapter` | TEXT | Chapter or section heading |
| `chunk_text` | TEXT | ~1,500-char text chunk |
| `chunk_index` | INT | Position within the book |
| `embedding` | Vector(1536) | pgvector embedding |

### `prompt_versions`
| Column | Type | Description |
|---|---|---|
| `id` | UUID PK | |
| `skill_type` | TEXT | Which skill this prompt belongs to |
| `parent_id` | UUID FK → self | Links optimised versions to their parent |
| `prompt_text` | TEXT | Full system prompt |
| `status` | TEXT | `candidate \| shadow \| active \| retired` |
| `pass_rate` | NUMERIC | Tier-1 eval pass rate |
| `avg_rubric_score` | NUMERIC | Avg PromptFoo rubric score (1–5) |

### `feedback`
13 signal types:

| Signal | Meaning |
|---|---|
| `too_long` / `too_short` | Length issues |
| `wrong_tone` | Tone doesn't match audience |
| `missing_example` | Missing worked examples |
| `factual_error` | Contains inaccuracies |
| `format_violation` | Format spec not followed |
| `unnecessary_diagram` / `needs_diagram` | Diagram presence issues |
| `unclear_explanation` | Confusing explanation |
| `wrong_difficulty_level` | Level doesn't match learner |
| `missing_common_errors` | No L1-interference error section |
| `missing_correction` | Error shown without correction |
| `diagram_incorrect` | Diagram is factually wrong |

### Other tables
- **`repair_queue`** — failed generations pending retry
- **`pattern_memory`** — learned patterns from reviewer feedback
- **`alerts`** — score drops, queue depth, queue age

---

## API Reference

### Generate

| Method | Path | Description |
|---|---|---|
| `POST` | `/generate/file` | Upload `.pptx` (multipart) |
| `POST` | `/generate/url` | Google Slides or `.pptx` URL |
| `GET` | `/generate/generations` | List — filter by `deck_id`, `status`, `skill_type` |

### Source Content

| Method | Path | Description |
|---|---|---|
| `GET` | `/source-content/{deck_id}` | List passages + budget |
| `POST` | `/source-content/{deck_id}` | Add passage (triggers alignment scoring) |
| `DELETE` | `/source-content/{deck_id}/{id}` | Remove passage |
| `POST` | `/source-content/{deck_id}/validate` | Re-run alignment |

### Review

| Method | Path | Body |
|---|---|---|
| `POST` | `/review/{id}/approve` | `{ reviewer_id, eval_score }` |
| `POST` | `/review/{id}/reject` | `{ reviewer_id, signals: [...] }` |
| `POST` | `/review/{id}/feedback` | `{ reviewer_id, signals: [...] }` |
| `GET` | `/review/repair-queue` | Pending repairs |

### Ops

| Method | Path | Description |
|---|---|---|
| `GET` | `/ops/dashboard` | Per-skill stats |
| `GET` | `/ops/alerts` | Unresolved alerts |
| `POST` | `/ops/alerts/{id}/resolve` | Manually resolve alert |

### Export

| Method | Path | Body |
|---|---|---|
| `POST` | `/export/{deck_id}` | `{ format: "pdf\|docx\|markdown" }` |

### Health

```
GET /healthz  →  { "status": "ok" }
```

---

## Environment Variables

Copy `.env.example` to `.env`:

```env
# LLM — OpenRouter key (sk-or-v1-...) or direct Anthropic key
ANTHROPIC_API_KEY=sk-or-v1-...
LLM_BASE_URL=https://openrouter.ai/api/v1
GENERATION_MODEL=anthropic/claude-sonnet-4-6
ALIGNMENT_MODEL=anthropic/claude-haiku-4-5-20251001

# OpenAI — for text-embedding-3-small
OPENAI_API_KEY=sk-...

# Google Slides — base64-encoded service account JSON
GOOGLE_SERVICE_ACCOUNT_JSON=<base64>

# Database — Neon provides postgresql://...?sslmode=require
# start.sh and settings.py auto-convert to asyncpg + ssl=require
DATABASE_URL=postgresql://user:pass@host/db?sslmode=require

# Redis — Upstash provides rediss:// (double s = TLS)
REDIS_URL=rediss://default:pass@host:6379

# Source content grounding
ALIGNMENT_THRESHOLD=0.7
MAX_SOURCE_CHARS_PER_DECK=12000

# Book retrieval (run ingest_books.py first)
USE_BOOK_RETRIEVAL=false
BOOK_RETRIEVAL_TOP_K=6
BOOKS_DIR=books

# Tuning
MAX_RETRIES=3
PATTERN_CONFIDENCE_THRESHOLD=0.75
SHADOW_PROMOTION_MARGIN=0.05
MIN_EXAMPLES_CONSTANT=20

# CORS
CORS_ORIGINS=*
```

> **Never commit `.env`** — it contains your API keys. `.gitignore` already excludes it.

---

## Local Setup

### Prerequisites
- Python 3.11+
- Node.js 20+
- Docker Desktop

### Step 1 — Start infrastructure
```bash
docker compose up -d
# PostgreSQL 16 (pgvector) on port 5434
# Redis 7 on port 6379
```

### Step 2 — Install Python dependencies
```bash
pip install -e ".[dev]"
```

### Step 3 — Configure environment
```bash
cp .env.example .env
# Add ANTHROPIC_API_KEY and OPENAI_API_KEY at minimum
```

### Step 4 — Run database migrations
```bash
python -m alembic upgrade head
```

### Step 5 — Seed initial prompts
```bash
python seed_db.py
```

### Step 6 — (Optional) Ingest books
```bash
# Drop .pdf/.epub/.txt files into books/, then:
python ingest_books.py
# Set USE_BOOK_RETRIEVAL=true in .env to enable auto-retrieval
```

### Step 7 — Install frontend dependencies
```bash
cd frontend && npm install
```

---

## Running the Server

### Backend
```bash
uvicorn ppt_agent.api.main:app --reload --host 0.0.0.0 --port 8000
```
API: `http://localhost:8000` | Docs: `http://localhost:8000/docs`

### Frontend (dev)
```bash
cd frontend && npm run dev
```
UI: `http://localhost:5173` — Vite proxies API calls to port 8000.

### Updating prompts after format changes
```bash
python reseed_prompts.py
```

---

## Deployment — Render + Neon + Upstash (Free)

**Total cost: $0/month** — three services, all on permanent free tiers.

| What | Provider | Free tier |
|---|---|---|
| Web app (FastAPI + React) | Render | 750 hrs/month |
| PostgreSQL + pgvector | Neon | 512 MB, always on |
| Redis | Upstash | 10k req/day |

FastAPI serves the React build as static files — one URL for everything.

### Step 1 — Neon (PostgreSQL)

1. Sign up at [neon.tech](https://neon.tech) → **Create Project** → name: `rmg`
2. Go to **SQL Editor** → run:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
3. Copy the **Connection String** (looks like `postgresql://user:pass@ep-xxx.neon.tech/neondb?sslmode=require`)

### Step 2 — Upstash (Redis)

1. Sign up at [upstash.com](https://upstash.com) → **Create Database**
2. Name: `rmg-redis`, Region: `us-east-1`
3. Copy the **Redis URL** (looks like `rediss://default:pass@xxx.upstash.io:6379`)

### Step 3 — Render (Web Service)

1. **New + → Blueprint** → select `Reading-Material-Generation` repo → **Apply**
2. After deploy: **Dashboard → rmg-api → Environment** → set:

| Key | Value |
|---|---|
| `DATABASE_URL` | Neon connection string |
| `REDIS_URL` | Upstash Redis URL (starts with `rediss://`) |
| `ANTHROPIC_API_KEY` | OpenRouter key `sk-or-v1-...` |
| `OPENAI_API_KEY` | OpenAI key |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | base64 service account string |

3. **Save Changes** → **Manual Deploy → Deploy latest commit**

### URLs after deployment

```
https://rmg-api.onrender.com          ← your app (React UI)
https://rmg-api.onrender.com/docs     ← FastAPI auto-docs
https://rmg-api.onrender.com/healthz  ← health check
```

> **Note:** Render's free web service spins down after 15 minutes of inactivity. First request after inactivity takes ~30 seconds to wake up.

### SSL note — Neon + asyncpg
Neon provides `?sslmode=require` in the connection string, which is a psycopg2 parameter. `settings.py` automatically converts it:
- asyncpg path: `sslmode=require` → `ssl=require`
- Alembic (psycopg2) path: keeps `sslmode=require`

No manual URL editing needed.

---

## Self-Improving Prompt System (DSPy + GEPA)

### G-Eval Auto-Scoring
On approval, `geval.py` runs `dspy.ChainOfThought` against a `ReadingMaterialQuality` signature and writes a `0.0–1.0` score back to `generations.eval_score`.

### GEPA Prompt Optimisation
On rejection, `prompt_optimizer.py` queries labelled examples. At ≥10 examples, `dspy.teleprompt.GEPA` rewrites the prompt and stores it as a `candidate` version for shadow A/B testing.

### Reseeding Prompts
After editing `format_schema.py` or `seed_prompts.py`:
```bash
python reseed_prompts.py
```

---

## Shadow A/B Testing

Traffic split is **per deck** — `hashlib.md5(deck_id)` → deterministic float. All slides in one deck always go to the same branch.

Promotion check every 15 minutes:
```
shadow_avg_score - active_avg_score >= SHADOW_PROMOTION_MARGIN (0.05)
```
Shadow wins → `active`. Shadow loses → `retired`.

---

## Memory System

- **Similar output retrieval** — top-5 approved past outputs by pgvector cosine similarity, injected as `MemoryContext`
- **Pattern memory** — high-severity feedback upserted as candidates, promoted at `ceil(0.75 × 20) = 15` examples

---

## Circuit Breaker & Repair Queue

`@with_circuit_breaker(skill_type)` wraps each skill:
1. Failure → retry, increment `retry_count`
2. After `MAX_RETRIES` → `status = 'needs_repair'`, insert into `repair_queue`, return `RepairRequired`
3. Router checks `isinstance(result, RepairRequired)` and branches

---

## Ops Monitoring & Auto-Rollback

Background job every 15 minutes:

| Alert | Threshold |
|---|---|
| `score_drop` | Last 100 avg drops ≥ 0.3 vs previous 100 |
| `repair_queue_depth` | Pending repairs ≥ 50 |
| `repair_queue_age` | Oldest pending repair > 24 hours |

On `score_drop`: auto-rollback promotes the parent prompt version back to `active`.

---

## Eval Pipeline (PromptFoo)

### Tier 1 — Deterministic (must all pass)

Checks applied to every `deck_reading` output:

| Check | Assertion |
|---|---|
| Has H2 sections | `## ` present |
| Has markdown tables | `\| --- \|` present |
| Has bold terms | `**` present |
| Learning Objectives | `Learning Objectives` present |
| Before You Begin | `Before You Begin` present |
| Common Mistakes | `Common Mistakes` present |
| Practice exercises | `Practice` present |
| Exception cases | `Exception` present |
| Quick Recap | `Quick Recap` present |

### Tier 2 — LLM Rubric
`caption_judge.py` scores 1–5. Avg must be ≥ 3.5 for promotion eligibility.

```bash
npx promptfoo eval --config ppt_agent/evals/promptfoo.yaml
python -m ppt_agent.evals.run_regression
```

---

## Running Tests

```bash
pytest                     # unit tests only
pytest -m integration      # requires live DB + Redis
pytest ppt_agent/tests/test_api.py -v
```

---

## Content Quality Guidelines

1. Clearly define the target audience, learner profile, and learning objectives before developing material.
2. Understand learners' linguistic, cultural, and educational background and adapt accordingly.
3. Conduct market research on current industry trends, exam patterns, and learner expectations.
4. Refer to authentic reference materials and verify concepts from multiple trusted sources.
5. Plan content structure logically — basic to advanced with clear headings.
6. Ensure difficulty, examples, and explanations align with learner proficiency.
7. Use simple, clear, learner-friendly language with consistent formatting.
8. Keep content manageable through short paragraphs, bullet points, and Quick Recap sections.
9. Include definitions, key points, formulas, and shortcuts.
10. Add practical, real-life, academic, and professional examples.
11. Use contextual scenarios and problem-solving activities.
12. Include CEFR-labelled practice exercises with answers and remediation hints after each section.
13. Identify and explain common learner errors caused by L1 interference.
14. Provide corrective guidance with awareness-based explanations.
15. Use tables, diagrams, and image placeholders for clarity.
16. Cross-check all references, examples, and factual information thoroughly.
17. Review and update material based on learner feedback and changing requirements.

---

## Guidelines Alignment — Application Cross-Check

| # | Guideline | Status | How the application covers it |
|---|---|---|---|
| 1 | Define audience and learning objectives | ✅ | `AUDIENCE_PROMPT` + mandatory `## Learning Objectives` section in every document |
| 2 | Adapt to learner background | ✅ | Persona callout boxes (Beginner Tip / Placement Candidate / Advanced Extension) in every document |
| 3 | Market research | ⚠️ | Manual — system doesn't perform market research; content developer must supply reference books |
| 4 | Verify from trusted sources | ✅ | Source content grounding + alignment validator + human approval workflow |
| 5 | Logical flow | ✅ | Topic-driven format enforces definition → rule → examples → exceptions |
| 6 | Difficulty aligned to proficiency | ✅ | CEFR labels on exercises (B1 / B1–B2 / B2–C1) |
| 7 | Learner-friendly language | ✅ | Prompt enforces plain, second-person, conversational tone |
| 8 | Short paragraphs + revision sections | ✅ | `## Quick Recap` is mandatory in every document |
| 9 | Definitions, key points, shortcuts | ✅ | Every section opens with a definition; key terms in **bold** |
| 10 | Practical examples | ✅ | General / Academic / Professional usage table required |
| 11 | Contextual scenarios | ✅ | `## Dialogue Simulation` with 3 Person A/B scenarios (Pattern B topics) |
| 12 | Practice exercises | ✅ | 3 CEFR-labelled non-MCQ exercises with inline answers in every document |
| 13 | Common errors + L1 interference | ✅ | `## Common Mistakes` table (≥4 rows) with L1 interference reasons — mandatory |
| 14 | Corrective guidance | ✅ | Remediation hints after each exercise; `Exception Cases` section |
| 15 | Visuals and tables | ✅ | Tables mandatory for all comparisons; image placeholders; `needs_diagram` feedback signal |
| 16 | Cross-check accuracy | ✅ | Human review + G-Eval + Tier-1 assertions + alignment validator |
| 17 | Regular review from feedback | ✅ | GEPA optimizer + 13 feedback signals + shadow A/B testing |

### Remaining gaps (architectural work required)

| Gap | What's needed |
|---|---|
| True learner persona routing | Persona selector on upload form + `ConfigInjection.difficulty_level` wired to API |
| Dynamic remediation | Quiz submission endpoint + score storage + follow-up generation |
| Per-topic RAG retrieval | One retrieval query per slide title instead of one combined query |
| External standards (CEFR, Cambridge) | Ingest Cambridge Grammar in Use / ETS reference materials into `books/` |

---

## Key Design Decisions

**One LLM call per deck** — Earlier versions made one call per slide (O(n) cost). Now exactly one call per upload covers all topics coherently.

**Slide titles only — no body text** — Body text is intentionally excluded so the LLM writes fresh content grounded in source passages, not slide bullets.

**Topic-driven format over fixed template** — Pattern A (grammar rule) vs Pattern B (communication) chosen based on the topic. Produces output that matches how grammar textbooks actually look.

**Instructional completeness over content expansion** — Format mandates 7 sections (Objectives → Prerequisites → Teaching → Dialogue → Mistakes → Practice → Recap) so every document functions as a standalone instructional unit, not a reference summary.

**OpenRouter over direct Anthropic** — Any OpenRouter-supported model swappable via env vars. No code changes needed.

**Per-deck shadow determinism** — `hashlib.md5(deck_id)` ensures all slides in one deck always go to the same prompt branch.

**Human reviewer as the quality gate** — G-Eval, alignment scores, and Tier-1 assertions are advisory. A person approves before any material reaches learners.

**Single-service deployment** — FastAPI serves the React build as static files. One Render service = one URL = no CORS configuration needed.

---

## Licence

MIT
