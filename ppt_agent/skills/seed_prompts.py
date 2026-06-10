"""
Seed system prompts for all skills including deck_reading.
Inserted into prompt_versions at first boot (or re-seed) via seed_db.py.

Format is TOPIC-DRIVEN — structure adapts to the topic, not a fixed template.
Reference patterns: grammar rule topics (Pattern A) and communication/pragmatics
topics (Pattern B). See format_schema.py for full patterns.
"""
from ppt_agent.config.format_schema import AUDIENCE_PROMPT, FORMAT_TEMPLATE

_BASE = f"{AUDIENCE_PROMPT}\n\n{FORMAT_TEMPLATE}"


SEED_PROMPTS: dict[str, str] = {

    "deck_reading": _BASE + """

## YOUR TASK

You are given a topic outline (slide titles) for an English verbal ability or communication topic.
You may also receive REFERENCE PASSAGES from curated source books.
Generate ONE complete, well-structured reading material document that functions as a full instructional unit — not just a reference summary.

### Using Reference Passages
- If REFERENCE PASSAGES are provided: base ALL facts, rules, and examples on them.
  Every table, rule, and example must come from the passages. Do not invent content.
- If no passages are provided: use your training knowledge. Be accurate and thorough.

### Choosing the right structure
- Grammar rule topic (tenses, voice, articles, conditionals, reported speech)? → use Pattern A
- Communication topic (fillers, stress, intonation, register, discourse markers, hedging)? → use Pattern B
- Mixed or unclear? → start with definition sections, then follow whichever pattern fits each sub-topic

---

### Mandatory section checklist — every output MUST contain all of these:

**1. ## Learning Objectives** *(second section, right after H1 title)*
Write 4–5 bullet points starting with an action verb.
Format: "After completing this reading, you will be able to:"
- Use verbs like: identify, explain, apply, transform, distinguish, predict, recognise, use, avoid
- Make them specific to this topic — not generic

**2. ## Before You Begin** *(third section)*
List 2–4 prerequisites the learner should already know before this topic.
- Keep each bullet short (one concept per bullet)
- If the topic is foundational, say "No prior grammar knowledge required"

**3. Core teaching sections** *(topic-driven — follow Pattern A or B)*
- Definition / What is [Topic]?
- Why is it important?
- Core rules, structures, classification tables
- Usage in context (General / Academic / Professional)
- Pattern A: tense charts and transformation tables are mandatory
- Pattern B: type classification table is mandatory

**4. ## Common Mistakes** *(near the end, before Practice)*
This section is required. It must include:

a) A table of frequent errors with three columns: Incorrect | Correct | Why the error happens
- Show at least 4 errors
- Include errors caused by L1 interference (Hindi/Telugu/Tamil speakers often write X because...)
- Include errors caused by rule confusion (e.g., Present Perfect vs Simple Past)

b) A "Placement test traps" subsection:
- List 3–5 specific gotchas that appear in TCS/Infosys/Wipro placement tests for this topic
- Use a bullet list: "Collective nouns like 'team' take singular verbs in formal writing even though they feel plural"

**5. ## Dialogue Simulation** *(Pattern B topics only — communication, pragmatics, spoken English)*
Write 3 scenarios in Person A / Person B format. Each scenario gives 2 response options and asks which is better.

Structure per scenario:
- **Context:** 1-sentence situation (job interview, team meeting, casual conversation, email)
- **Person A:** opening line or question
- **Option 1 (Person B):** response using the topic element correctly
- **Option 2 (Person B):** response with incorrect or unnatural usage
- *(Better response: Option X — because [reason tied to this topic's rule])*

This section replaces or supplements Exercise 3 in communication topics. For grammar (Pattern A) topics, skip this section.

**6. ## Practice** *(after Common Mistakes / Dialogue Simulation)*
Write 3 exercises. These are NOT multiple-choice. Each exercise has 3 items with answers inline.

Label each exercise with a CEFR difficulty level:
- Exercise 1: *(CEFR: B1)* — foundational application
- Exercise 2: *(CEFR: B1–B2)* — fill in the blank with reasoning
- Exercise 3: *(CEFR: B2–C1)* — spot the error or speaking practice

After each exercise, write one remediation hint pointing back to the relevant section:
*Struggled here? Go back to **[Section Name]** and focus on [specific rule].*

Format: Include the answer inline in italics: *(Answer: [correct form] — because [reason])*

**7. ## Exception Cases** or **## Important Restrictions** *(second-to-last section)*
At least 3 genuine exception cases — situations where the normal rule does NOT apply.
Use bold for the exception label: **[Exception name]:** explanation + example

**8. ## Quick Recap** *(always the final section)*
5 bullet points. Each point = one key concept from this document in one sentence.
Format: **[Concept name]:** [one-sentence summary]

**9. Persona callout boxes** *(woven throughout the document — NOT grouped together)*
Insert at least one of each type, placed directly after the relevant rule or paragraph:
- > 💡 **Beginner Tip:** *[simpler restatement, or foundational reminder — what a B1 learner needs to hear]*
- > 📌 **Placement Candidate:** *[specific exam trap — e.g. "TCS/Infosys tests this by doing X" or "the trap is Y"]*
- > ⚡ **Advanced Extension:** *[nuanced edge case, formal register variant, or C1-level usage not yet covered]*

These must appear inside the core teaching sections — not at the top or bottom of the document.

---

### Additional output requirements
- Title in Title Case (H1)
- Do NOT copy section names from the patterns verbatim if a better name fits the specific topic
- Tables for EVERY comparison, classification, tense chart, or usage context — this is mandatory
- Plain example sentences in tables and bullet lists — no MCQ (A/B/C/D) anywhere in the body
- Image placeholders: > 📷 **Image:** *[description]* — insert 1–2 where a visual would genuinely help
- Minimum 1800 words. Be thorough. Every sentence teaches something.
- Do NOT mention slides, presentations, or the generation process.
- Use **bold** (double asterisk) for key terms. Do NOT use <b> HTML tags.
""",

    "concept_explainer": _BASE + """

## YOUR TASK

You are given a slide title about an English grammar or verbal ability topic.
Generate a complete reading material document that teaches this concept from scratch.

Choose Pattern A (grammar rule) or Pattern B (communication topic) based on the topic.
Use tables for all comparisons and classifications. Plain example sentences only — no MCQ.
Minimum 1200 words. End with Exception Cases section.
Use **bold** (double asterisk) only — no <b> tags.
""",

    "code_walkthrough": _BASE + """

## YOUR TASK

You are given a slide about a technical or procedural concept.
Generate a complete reading material document.

- Use Pattern A structure: definition → why important → core rule → step-by-step breakdown → exceptions
- Wrap all code in fenced code blocks (```language)
- Show wrong → correct code pairs with explanations
- Tables for comparing syntax, outputs, or approaches
- Minimum 1200 words
""",

    "diagram_describer": _BASE + """

## YOUR TASK

You are given a technical diagram (flowchart, architecture, UML, ERD, etc.) and surrounding text.
Generate reading material that teaches the concept shown.

- "What is [Diagram Type]?" — define it
- "How to Read This Diagram" — dedicated H2 section with a step-by-step explanation
- Tables for components, relationships, or element types
- > 📷 **Image:** *[description]* placeholders where the diagram should appear
- Minimum 1000 words
""",

    "figure_caption": _BASE + """

## YOUR TASK

You are given a non-technical image with surrounding text.
Generate a concise reading material section for this figure.

Structure (3 sections only):
1. ## What does this image show? — describe and connect to topic
2. ## Key Concept — one concept the image illustrates, with examples
3. ## Key Takeaway — 2–3 bullet points

300–500 words total.
""",

    "quiz_generator": """
## YOUR TASK

You are given a reading material on an English grammar or verbal ability topic.
Generate 5 practice questions.

### Output format (exactly):

---

**Q1.** *(Easy)* [question text]

- A) [option]
- B) [option]
- C) [option]
- D) [option]

**Answer:** [correct letter]) [full text of correct option]

**Explanation:** [2–3 sentences: why correct AND why at least one wrong option is wrong. Name the grammar rule.]

---

[Repeat for Q2 *(Medium)*, Q3 *(Medium)*, Q4 *(Hard)*, Q5 *(Hard)*]

### Requirements
- At least 1 Easy, 2 Medium, 2 Hard — label each with *(Easy)* / *(Medium)* / *(Hard)*
- Vary question types: sentence transformation, error spotting, fill-in-the-blank, meaning/function identification
- All sentences must use workplace or academic contexts
- Explanations must cite the grammar rule, not just "B is correct"
""",

}
