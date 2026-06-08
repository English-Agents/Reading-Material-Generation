"""
Reading material format contract — pure standard markdown, no HTML.

Zero custom tags. Zero <details>/<summary>. Renders correctly in any
markdown renderer and is reliably followed by all LLMs.
"""
from typing import Optional
from pydantic import BaseModel


# ── Pydantic models ────────────────────────────────────────────────────────

class ExampleItem(BaseModel):
    label: str
    context: Optional[str]
    question: str
    options: list[str]
    answer: str
    explanation: str


class SubSectionContent(BaseModel):
    title: str
    definition: str
    examples: list[ExampleItem]
    quick_tip: str


class ReadingMaterialOutput(BaseModel):
    title: str
    overview_text: str
    subsections: list[SubSectionContent]
    strategies: list[str]
    how_to_score_rows: list[dict]
    references: list[str]


# ── Format template ────────────────────────────────────────────────────────

FORMAT_TEMPLATE = """
Produce the reading material in EXACTLY this markdown structure. No deviations.

---
# {TITLE IN ALL CAPS}

## Overview

{2-3 paragraphs introducing the topic and why it matters for placement tests.}

**Topics covered in this material:**
1. {subtopic 1}
2. {subtopic 2}
3. {subtopic 3}
...

---

## Subtopics and Examples

### {Subtopic Name}

{One paragraph defining this subtopic and why it appears in placement tests.}

**Example 1** *(Easy)*

{One or two sentence context — a workplace scenario.}

**Question:** {question text}

- A) {option}
- B) {option}
- C) {option}
- D) {option}

**Answer:** {correct option with full text}

**Explanation:** {2-3 sentences — why the answer is right AND why at least one wrong option is wrong.}

> **Quick Tip:** {one concrete actionable tip for this subtopic}

---

**Example 2** *(Medium)*

{same structure as Example 1}

---

**Example 3** *(Hard)*

{same structure as Example 1}

---

{Repeat ### for each subtopic — minimum 3, maximum 5 subtopics}

---

## How to Prepare

1. {study habit or strategy}
2. {study habit or strategy}
3. {study habit or strategy}
4. {study habit or strategy}
5. {study habit or strategy}

---

## How to Score

| Situation | What to do |
| --- | --- |
| {situation} | {action} |
| {situation} | {action} |
| {situation} | {action} |
| {situation} | {action} |
| {situation} | {action} |

---

## Where to Practise

**Online Platforms**

1. {Resource} — {one-line description}
2. {Resource} — {one-line description}
3. {Resource} — {one-line description}

**Books**

1. *{Title}* by {Author} — {one-line description}
2. *{Title}* by {Author} — {one-line description}
3. *{Title}* by {Author} — {one-line description}
---

STRICT RULES:
- Use ONLY the markdown shown above. No HTML tags whatsoever.
- Every example must use a product team / software workplace scenario
  (sprint planning, bug fix, code review, product launch, team standup, etc.)
- Second-person voice: "you", never "students" or "learners"
- Each question must have exactly 4 options labelled A) B) C) D)
- Explanations must state WHY the correct answer is right AND why at least one wrong option is wrong
- Quick Tips must be actionable in one sentence
- Minimum total output: 1500 words
""".strip()


# ── Audience ───────────────────────────────────────────────────────────────

AUDIENCE_PROMPT = (
    "Audience: beginner-to-intermediate learners preparing for English verbal ability "
    "sections in IT company placement tests (TCS, Infosys, Wipro, Cognizant style). "
    "All examples must use product team / software workplace scenarios "
    "(e.g. sprint retros, bug fixes, pull requests, product launches, team emails). "
    "Tone: conversational but professional, second-person."
)


# ── Tier-1 structural assertions ───────────────────────────────────────────

TIER1_ASSERTIONS = {
    "deck_reading": [
        "## Overview",
        "## Subtopics and Examples",
        "### ",
        "## How to Prepare",
        "## How to Score",
        "## Where to Practise",
        "**Answer:**",
        "**Explanation:**",
        "> **Quick Tip:**",
    ],
}
