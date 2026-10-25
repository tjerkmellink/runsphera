"""Provider plug-ins for the LLM coach voice.

Each `_*.py` module here implements the same tiny contract the
`connector` dispatcher consumes:

    is_available() -> bool
    coach_message(system, profile, request, *, model, max_tokens) -> LLMResult | None

Providers are kept module-private (underscore prefix) so the rest of
the app talks only to `runsphera.llm.connector`. To add a new
provider: drop in `_<name>.py`, register it in `connector._PROVIDERS`,
and wire its API key column + UI tab in settings.
"""
