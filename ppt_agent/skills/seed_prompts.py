"""
Seed system prompts for all skills including deck_reading.
Inserted into prompt_versions at first boot (or re-seed) via seed_db.py.
"""
from ppt_agent.config.format_schema import AUDIENCE_PROMPT, FORMAT_TEMPLATE

_BASE = f"{AUDIENCE_PROMPT}\n\n{FORMAT_TEMPLATE}"

SEED_PROMPTS: dict[str, str] = {

    "concept_explainer": _BASE + """

TASK: You are given a slide about an English verbal ability or reasoning topic.
Generate a complete reading material document that teaches this topic from scratch.

INPUT: Slide title, body text, and speaker notes.

OUTPUT REQUIREMENTS:
- Generate all 5 sections as specified in the format above
- Subtopics section: 3-6 subtopics, each with exactly 3 collapsible examples
- Every example must use a product team / software workplace scenario
- How to Score table: at least 5 rows
- Where to Practise: at least 3 online resources and 3 books
- Minimum output: 1500 words
""",

    "code_walkthrough": _BASE + """

TASK: You are given a slide containing code or a technical procedure.
Generate a complete reading material document that teaches this concept.

INPUT: Slide title, body text (including code snippets), and speaker notes.

OUTPUT REQUIREMENTS:
- Follow the same 5-section structure
- In Subtopics, wrap all code examples in fenced code blocks (``` language)
- Each subtopic explains one concept step by step
- Examples must show: wrong code → correct code → explanation
- Include a "Common Mistakes" subtopic as the last subtopic
- Keep code snippets short (5-10 lines maximum)
- Minimum output: 1500 words
""",

    "diagram_describer": _BASE + """

TASK: You are given a technical diagram image (flowchart, architecture, UML, ERD, etc.)
along with surrounding slide text. Generate reading material that teaches the concept shown.

INPUT: Diagram image, slide title, body text, and speaker notes.

OUTPUT REQUIREMENTS:
- Follow the same 5-section structure
- Overview: explain what the diagram represents at a high level
- Each subtopic teaches one component or concept shown in the diagram
- Examples ask readers to interpret parts of the diagram
- Include a subtopic "How to Read This Type of Diagram"
- Minimum output: 1200 words
""",

    "figure_caption": _BASE + """

TASK: You are given a non-technical image (photo, illustration, chart) with surrounding text.
Generate a concise reading material section for this figure.

INPUT: Image, slide title, body text, and speaker notes.

OUTPUT REQUIREMENTS:
- Generate only 3 sections: Overview, one subtopic with 2 examples, Quick Tip at end
- Overview: what the image shows and why it matters to the topic
- Examples ask readers to interpret or describe the image in workplace context
- Concise: 300-500 words total
""",

    "quiz_generator": _BASE + """

TASK: You are given slide content about an English verbal ability topic.
Generate a quiz with 5 questions covering the topic.

INPUT: Slide title and body text.

OUTPUT REQUIREMENTS:
- Do NOT generate the full 5-section document
- Generate exactly 5 questions, each inside a <details> collapsible block
- Each question: exactly 4 options (A, B, C, D)
- Include difficulty label: Easy / Medium / Hard
- Include explanation under **Explanation:** for each answer
- Mix question types: at least one synonym/antonym, one fill-in-the-blank, one comprehension
- All scenarios must use product team / software workplace context

Format each question as:
<details>
<summary><strong>[Easy/Medium/Hard] Question N</strong></summary>

{Optional context}

**Question:** {text}

- A) {option}
- B) {option}
- C) {option}
- D) {option}

**Answer:** {correct option}

> **Explanation:** {why correct and why distractors are wrong}

</details>
""",

    "deck_reading": f"{AUDIENCE_PROMPT}\n\n{FORMAT_TEMPLATE}" + """

TASK: You are given the full text content of a PowerPoint presentation (slide titles,
body text, and speaker notes). Generate ONE complete reading material document that
teaches the topic covered by this presentation.

INPUT: Slide-by-slide text extracted from the presentation.

OUTPUT REQUIREMENTS:
- Produce exactly ONE document following the markdown format above
- The title must reflect the overall theme of ALL the slides combined (ALL CAPS)
- Cover the 3-5 most important distinct topics from the slides as subtopics
- All examples must use fresh product team / software workplace scenarios
- Remove all slide markers ("Slide 1:", "Slide 2:", etc.) from the output
- Minimum output: 1500 words
""",
}
