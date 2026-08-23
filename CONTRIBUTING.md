# Contributing to Semantic Organizer

Welcome! We appreciate your help to make Semantic Organizer better.

## Development Setup

We use `uv` for dependency management and environments.

1. Clone the repo
2. Run `uv sync` to set up the `.venv` and install dependencies.
3. Run `pytest` to run tests. (Tests use mock LLM responses so you don't need a local server running)
4. Run `ruff check .` for linting.

## Architecture

Please review `docs/architecture.md` to understand the system pipeline before contributing.
