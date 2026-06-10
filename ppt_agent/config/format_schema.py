"""
Reading material format contract.

Format is TOPIC-DRIVEN, not fixed-section. Structure adapts to what best explains
the specific topic. Derived from real sample materials:

  Sample 1 — Active/Passive Voice (grammar rule topic):
    Rule structure → definition → tense tables → transformation steps → exception cases

  Sample 2 — Fillers & Sentence Stress (communication/pragmatics topic):
    Definition → why important → type classification tables → placement patterns →
    context examples (General / Academic / Professional) → exception cases

Invariants across ALL topics:
  - H1 title, H2 topic-appropriate section names, H3 sub-concepts
  - Tables for comparisons, types, patterns, and usage contexts
  - Bold (**) for key terms and structure formulas
  - Plain example sentences — NO MCQ / A)B)C)D) format in body
  - Context-layered examples (General / Academic / Professional) where relevant
  - "Exception Cases" or "Restrictions" section at the end
  - <img> tags only for real S3 URLs (added manually); use blockquote placeholders for LLM output
"""
from typing import Optional
from pydantic import BaseModel


# ── ConfigInjection ────────────────────────────────────────────────────────

class ConfigInjection(BaseModel):
    """Per-request generation configuration injected into the system prompt."""
    audience: str = (
        "beginner-to-intermediate learners preparing for English verbal ability "
        "sections in IT company placement tests (TCS, Infosys, Wipro, Cognizant style)"
    )
    tone: str = "conversational but professional, second-person"
    difficulty_level: str = "mixed"
    length: str = "standard"
    include_diagrams: bool = False
    l1_influence_flag: bool = False
    l1_language: Optional[str] = None
    schema_version: str = "1.0"


# ── Pydantic output contract ───────────────────────────────────────────────

class ReadingMaterialSchema(BaseModel):
    """Minimal contract — actual output is a markdown string."""
    title: str
    sections: list[str]
    has_tables: bool
    has_examples: bool
    has_exception_section: bool
    word_count: int


# ── Audience default ───────────────────────────────────────────────────────

AUDIENCE_PROMPT = (
    "Audience: beginner-to-intermediate learners preparing for English verbal ability "
    "sections in IT company placement tests (TCS, Infosys, Wipro, Cognizant style). "
    "Use simple, clear language. Second-person voice: write 'you', never 'students' or 'learners'. "
    "Tone: conversational but professional. "
    "Do NOT use multiple-choice questions (A/B/C/D) in the body — use plain example sentences only. "
    "Use markdown tables generously for comparisons, types, patterns, and usage contexts."
)


# ── Format template ────────────────────────────────────────────────────────
#
# This is a GUIDE, not a fixed template. The LLM must choose the sections and
# structure that best explain the specific topic. Two reference patterns are
# provided below. Use whichever fits — or combine both — based on the topic.

FORMAT_TEMPLATE = """
## HOW TO STRUCTURE THE READING MATERIAL

The format is TOPIC-DRIVEN. Choose the section names and structure that best explain THIS topic.
Do not follow a fixed template. Instead, follow the patterns shown below.

### Non-negotiable rules (must be followed for every topic):
1. H1 (#) for the title only. H2 (##) for main sections. H3 (###) for sub-concepts.
2. Use **bold** (double asterisk) for key terms, structure formulas, and fillers/stress markers. Do NOT use <b> HTML tags.
3. Use markdown tables (| col |) for ALL comparisons, classifications, tense charts, placement patterns, and usage examples. Tables are essential.
4. Use plain example sentences — NOT MCQ / A) B) C) D) format anywhere in the body.
5. Where a diagram or visual would help, insert: > 📷 **Image:** *[one-sentence description of what the image should show]*
6. Minimum output: 1800 words. Every sentence must teach something.
7. Persona callout boxes — insert at least one of each type, placed directly after the relevant rule or paragraph (not grouped at the top or bottom):
   - > 💡 **Beginner Tip:** *[simpler restatement, or foundational reminder of what the learner needs to know first]*
   - > 📌 **Placement Candidate:** *[exam trap, elimination strategy, or test-specific pattern — e.g. "TCS often tests X by doing Y"]*
   - > ⚡ **Advanced Extension:** *[nuanced edge case, formal register variant, or C1-level usage the document hasn't covered yet]*

### Mandatory sections (must appear in every document, in this order):

| Order | Section | Position |
|---|---|---|
| 1 | Learning Objectives | Second section (right after title) |
| 2 | Before You Begin | Third section |
| 3–N | Core teaching sections | Middle (topic-driven — use Pattern A or B) |
| N+1 | Common Mistakes | Near end |
| N+2 | Practice | Before exception cases |
| N+3 | Exception Cases / Important Restrictions | Second-to-last |
| N+4 | Quick Recap | Always the final section |

---

### PATTERN A — Grammar Rule Topics (e.g., Active/Passive Voice, Tenses, Articles, Conditionals)

# [Title]

## Learning Objectives
After completing this reading, you will be able to:
- [action verb] [concept] — e.g., "identify active and passive voice in any sentence"
- [action verb] [concept] — e.g., "transform sentences between active and passive voice"
- [action verb] [concept] — e.g., "apply the correct tense in formal and informal writing"
- [action verb] [concept]
- [action verb] [concept]

## Before You Begin
Make sure you are comfortable with:
- [prerequisite 1] — e.g., "identifying the subject and object of a sentence"
- [prerequisite 2] — e.g., "basic verb forms: base, past simple, past participle"
- [prerequisite 3]

---

## What is [Topic]?
[1–2 paragraphs defining the concept. For paired concepts (Active vs Passive), use H3 for each.]

### [Sub-concept A]
[Definition + plain example sentences.]

### [Sub-concept B]
[Definition + plain example sentences.]

> 📷 **Image:** *[description]*

## Why is [Topic] important?
[2–3 paragraphs: everyday use, formal writing, placement test relevance.]

## [Core Rule or Structure]
[Explain the rule in plain language.]

**Structure:** [formula in bold]

**Examples:**
- [example sentence] *(label in italics)*
- [example sentence]

## [Topic] in Different [Tenses / Contexts / Patterns]
[Table — this is mandatory for grammar rule topics.]

| [Col 1] | [Col 2] | [Col 3] |
|---|---|---|
| [row] | [row] | [row] |

## Where is [Topic] used?
[Table: Context / Sentence / Why this form]

| Context | Example sentence | Why this form is used |
|---|---|---|
| Formal email | [example] | [reason] |
| Spoken English | [example] | [reason] |
| Academic writing | [example] | [reason] |

## [Additional concept sections as needed]
[Repeat pattern: explanation paragraph + table or examples.]

---

## Common Mistakes

These are the most frequent errors learners make with [Topic], especially in placement tests.

| Incorrect | Correct | Why the error happens |
|---|---|---|
| [wrong sentence] | [right sentence] | [L1 interference / rule confusion] |
| [wrong sentence] | [right sentence] | [reason] |
| [wrong sentence] | [right sentence] | [reason] |

**Placement test traps:**
- [Specific exam trap 1 — e.g., "Collective nouns like 'team' or 'committee' take singular verbs in formal writing even though they feel plural"]
- [Specific exam trap 2]
- [Specific exam trap 3]

## Practice

Try these exercises to check your understanding. Answers are inline after each item.

**Exercise 1 — Transform the sentence:** *(CEFR: B1)*
Rewrite each sentence using [the target form]:
1. [sentence to transform]
   *(Answer: [correct transformed sentence])*
2. [sentence to transform]
   *(Answer: [correct transformed sentence])*
3. [sentence to transform]
   *(Answer: [correct transformed sentence])*

*Struggled here? Go back to **[Section Name]** and re-read the [specific rule or formula].*

**Exercise 2 — Fill in the blank:** *(CEFR: B1–B2)*
Choose the correct word or form to complete each sentence:
1. [sentence with blank] *(Answer: [correct option] — because [reason])*
2. [sentence with blank] *(Answer: [correct option] — because [reason])*
3. [sentence with blank] *(Answer: [correct option] — because [reason])*

*Struggled here? Focus on the **[specific contrast]** table in the **[Section Name]** section.*

**Exercise 3 — Spot the error:** *(CEFR: B2–C1)*
Each sentence below has one grammatical error. Identify and correct it:
1. [sentence with error] *(Error: [what it is] → Correction: [correct form])*
2. [sentence with error] *(Error: [what it is] → Correction: [correct form])*
3. [sentence with error] *(Error: [what it is] → Correction: [correct form])*

*Struggled here? Review the **Common Mistakes** table above — the error pattern will be listed there.*

## Exception Cases
At least 3 exceptions or rule-breakers — cases where the usual rule does NOT apply.

- **[Exception 1]:** [explanation + example]
- **[Exception 2]:** [explanation + example]
- **[Exception 3]:** [explanation + example]

## Quick Recap
- **[Key concept 1]:** [one-sentence summary]
- **[Key concept 2]:** [one-sentence summary]
- **[Key concept 3]:** [one-sentence summary]
- **[Key concept 4]:** [one-sentence summary]
- **[Key concept 5]:** [one-sentence summary]

---

### PATTERN B — Communication / Pragmatics Topics (e.g., Fillers, Sentence Stress, Intonation, Register)

# [Title]

## Learning Objectives
After completing this reading, you will be able to:
- [action verb] [concept]
- [action verb] [concept]
- [action verb] [concept]
- [action verb] [concept]
- [action verb] [concept]

## Before You Begin
Make sure you are comfortable with:
- [prerequisite 1]
- [prerequisite 2]

---

[1–2 sentence introduction defining the concept and why it matters in real communication.]

## Quick Examples
[Lead with a quick examples table so the reader immediately grasps what it looks like.]

| Focus | Example | What it shows |
|---|---|---|
| [concept] | **[word/phrase in bold]** rest of sentence | [what it does] |

## Why is [Topic] important?
[Short paragraph + bullet list of functions in spoken and written English.]

## Types of [Topic]
[Classification table — the core section for pragmatics topics.]

| Type | What it does | Common examples | Example sentence |
|---|---|---|---|
| [type] | [function] | [list] | **[word]**, sentence |

## [Placement / Patterns / How it works]
[Table showing position, pattern, or stress placement.]

| Position / Pattern | Example | Why it is used |
|---|---|---|
| [position] | **[word]**, sentence | [reason] |

## Usage in Context

### General / Everyday usage
| Situation | Example | Effect |
|---|---|---|
| [situation] | **[marked word]** in sentence | [explanation] |

### Academic usage
| Situation | Example | Effect |
|---|---|---|

### Professional / Workplace usage
| Situation | Example | Effect |
|---|---|---|

---

## Dialogue Simulation

Read each conversation and decide which response is better. Explain why.

**Scenario 1 — [Context: e.g., job interview / team meeting / casual conversation]**

> **Context:** [1-sentence situation — who is speaking, where, and what is happening]
>
> **Person A:** "[opening line or question]"
>
> **Option 1 (Person B):** "[Response using the topic element correctly]"
>
> **Option 2 (Person B):** "[Response with incorrect or unnatural usage]"

*(Better response: Option [X] — because [reason tied directly to this topic's rule])*

---

**Scenario 2 — [Context]**

> **Context:** [situation]
>
> **Person A:** "[opening line]"
>
> **Option 1 (Person B):** "[Response]"
>
> **Option 2 (Person B):** "[Response]"

*(Better response: Option [X] — because [reason])*

---

**Scenario 3 — [Context]**

> **Context:** [situation]
>
> **Person A:** "[opening line]"
>
> **Option 1 (Person B):** "[Response]"
>
> **Option 2 (Person B):** "[Response]"

*(Better response: Option [X] — because [reason])*

---

## Common Mistakes

| Incorrect usage | Correct usage | Why the error happens |
|---|---|---|
| [wrong example] | [right example] | [reason] |
| [wrong example] | [right example] | [reason] |
| [wrong example] | [right example] | [reason] |

**Placement test traps:**
- [Exam trap 1 specific to this topic]
- [Exam trap 2]

## Practice

**Exercise 1 — Identify and label:** *(CEFR: B1)*
Read each sentence. Identify the [topic element] and describe what function it serves:
1. "[sentence]"
   *(Answer: [topic element] = "[word/phrase]" — function: [explanation])*
2. "[sentence]"
   *(Answer: ...)*
3. "[sentence]"
   *(Answer: ...)*

*Struggled here? Re-read the **Types of [Topic]** table and notice the function column.*

**Exercise 2 — Fill in the blank:** *(CEFR: B1–B2)*
Complete each sentence with an appropriate [topic element]:
1. [sentence with blank] *(Answer: [correct option] — because [reason])*
2. [sentence with blank] *(Answer: [correct option] — because [reason])*
3. [sentence with blank] *(Answer: [correct option] — because [reason])*

*Struggled here? Review the **Placement / Patterns** section — the position rules will guide your choice.*

**Exercise 3 — Speaking practice:** *(CEFR: B2)*
Read these sentences aloud. Notice how [stressing / pausing / using fillers] changes the meaning:
1. "[sentence variant A]" vs "[sentence variant B]"
   *(What changes: [explanation of the difference in meaning or effect])*
2. "[sentence variant A]" vs "[sentence variant B]"
   *(What changes: [explanation])*
3. "[sentence variant A]" vs "[sentence variant B]"
   *(What changes: [explanation])*

*Struggled here? Go back to the **Dialogue Simulation** scenarios and re-read why Option [X] was better.*

## Exception Cases and Restrictions
Cases where the usual rule breaks — at least 3.

| Case | Example | Why it happens |
|---|---|---|
| [case] | [example] | [reason] |

## Quick Recap
- **[Key concept 1]:** [one-sentence summary]
- **[Key concept 2]:** [one-sentence summary]
- **[Key concept 3]:** [one-sentence summary]
- **[Key concept 4]:** [one-sentence summary]
- **[Key concept 5]:** [one-sentence summary]

---
""".strip()


# ── Tier-1 structural assertions (used by caption_judge.py) ───────────────
# Kept minimal because section names vary by topic.

TIER1_ASSERTIONS = {
    "deck_reading": [
        "## ",                      # at least one H2 section
        "| --- |",                  # at least one markdown table
        "**",                       # bold terms used
        "Learning Objectives",      # objectives section present
        "Before You Begin",         # prerequisites present
        "Common Mistakes",          # misconception section present
        "Practice",                 # exercises present
        "Exception",                # exception cases present
        "Quick Recap",              # summary present
    ],
    "concept_explainer": [
        "## ",
        "| --- |",
        "**",
        "Common Mistakes",
        "Quick Recap",
    ],
}
