# <Rubric title>
Version: 1.0

<!--
GitCrawl clause.md template. Copy this file, fill it in, then run:
  gitcrawl plan my_clause.md -o my_plan.yaml

Rules the parser enforces:
- One "## Pillar: <name>" section per pillar. Names must be distinct.
- Every pillar has a "Weight: N%" line. Weights across pillars must add up to 100%.
- "Focus:" is optional, one line.
- "### Criteria": one "- " bullet per statement to evaluate. Write each as something that can
  be checked or judged ("CI runs on every pull request"), not a vague theme ("CI quality").
- "### Bands": "- low-high: description" bullets covering 0-10 with no gaps or overlaps.
- "### Hard rules" (optional): deterministic limits, written as
    "- If <condition>, score is at most <N>."   or
    "- If <condition>, the pillar is not assessed."
  The planner turns these into checkable rules; you see and approve them in the plan.
-->

## Pillar: <Pillar name>
Weight: 100%
Focus: <what this pillar is about, in one line>

### Criteria
- <criterion>
- <criterion>

### Bands
- 0-2: <what a very poor repository looks like>
- 3-5: <below average>
- 6-8: <good>
- 9-10: <excellent>

### Hard rules
- If <condition>, score is at most <N>.
