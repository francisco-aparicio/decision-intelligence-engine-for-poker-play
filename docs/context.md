# Project Context

## Goal
Data Scientist/ML Engineer (EDP) building Applied AI career credibility.
~60 hours over 2–3 months, ~70% building / 30% deliberate theory — one
flagship project as the curriculum, learning theory just-in-time rather
than via courses.

## Why poker
A Poker AI Coach / Session Intelligence System: genuine domain interest,
real personal data, and the technical problem naturally requires the exact
skills below. Framed professionally as "AI Decision Analysis System —
Poker Domain," not a gambling app.

## Learning topics (this project is the curriculum for)
0. LLM fundamentals — conceptual only
1. **LLM application engineering** — DEEP (APIs, structured outputs, tool
   calling, model selection, cost/latency)
2. RAG & retrieval — STRONG
3. **Agents & workflows** — DEEP
4. **Evals & reliability** — DEEP (intended differentiator)
5. **Production AI engineering** — STRONG (typing, testing, APIs,
   deployment, observability)

Deprioritized: training/fine-tuning LLMs, transformer math, framework
mastery, further traditional ML/Spark.

## Working principle
AI coding assistants implement; architecture, key decisions, debugging,
and trade-offs stay mine. Test: *could I rebuild and explain this
component without the assistant?* If not, it isn't learned deeply enough.

## System design
Two layers, kept separate: deterministic facts (parsed hands, calculated
stats, rule-based comparison against my own stated NL2 strategy baseline)
feed an LLM analysis layer that judges — never computes facts itself. e.g.
the system detects "BTN opened K6s, baseline says K7s+" deterministically;
the LLM answers "was that deviation reasonable given the context?"

## Current status
Environment set up and committed (`uv`, `solver` package, pydantic/pytest/
ruff). Hand data model finalized. Parser architecture defined — see
`docs/parser-spec.md` for the implementation spec, currently being built.