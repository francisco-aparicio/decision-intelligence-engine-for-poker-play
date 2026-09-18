# solver

Decision-intelligence engine for poker: parses PokerStars hand histories,
computes deterministic facts, later layers AI analysis on a stated baseline.

## Commands
- `uv run pytest` — tests
- `uv run ruff check .` / `uv run ruff format .` — lint / format
- `uv add <pkg>` / `uv add --dev <pkg>` — add dependency

## Structure
- `src/solver/models.py` — pydantic models
- `src/solver/parser/pokerstars.py` — parser
- `tests/`, `data/sample_hands/` — tests + fixtures
- `docs/context.md`, `docs/parser-spec.md` — project background, parser spec

## Code style
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html),
- `snake_case` functions/vars, `PascalCase` classes, `UPPER_SNAKE_CASE` constants
- Import modules, not individual names (exception: `from pydantic import BaseModel`-style) — `ruff`'s `I` rule handles ordering
- Google-style docstrings (`Args:`/`Returns:`/`Raises:`) — only when warranted, see below
- All boundary-crossing data is a pydantic `BaseModel`, never a raw dict
- `class X(str, Enum)` for any fixed-value field shared across models
- Type hints everywhere; no bare `Any` without a comment why

## Documentation restraint
Skip a docstring if short, obvious, and not externally visible — Google's
own stated exception, not a shortcut. Comments explain *why*, never *what*;
delete ones that just restate the code.

## Workflow
- Implement against `docs/` specs in their stated order — don't build ahead
  of the current incremental test
- Tests alongside implementation, not after
- `uv run pytest` + `uv run ruff check .` clean before calling something done

## Avoid
- Hardcoding hero's username — it's the `hero_name` parameter
- Letting one malformed hand abort a batch parse — collect failures instead

## Environment
- OneDrive repo path — `.venv` may hit Windows lock errors on `uv sync`;
  fix: `rm -rf .venv && uv sync`
- Python 3.14 via `uv`
