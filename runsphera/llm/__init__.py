"""LLM commentary layer — wraps the rules-based recommendation with Claude's voice.

Public entrypoint: `commentary.daily_coach_message(conn, recommendation, todays_workout)`
which returns a personalized message or None (when the LLM is unavailable, the
caller falls back to the rules-based headline).
"""
