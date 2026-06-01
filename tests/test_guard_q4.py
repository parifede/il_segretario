"""Unit tests for guard_zarsuit_schema_leak — Q4 pattern coverage.

Anti-drift: keyword lists are pinned to docs/secretary_bridge_contract.md §Q4.
A test failure here means the Python guard has drifted from the Node outputGuard.
"""
from segretario.policies.output_guard import (
    GuardResult,
    _SCHEMA_KEYS_GENERIC,
    _SCHEMA_KEYS_UNAMBIGUOUS,
    guard_zarsuit_schema_leak,
)


# ---------------------------------------------------------------------------
# Anti-drift: pin to Q4 contract
# ---------------------------------------------------------------------------

def test_schema_keys_unambiguous_match_q4_contract():
    """Unambiguous key list must match secretary_bridge_contract.md §Q4 exactly."""
    expected = {
        "secretary_task_request",
        "secretary_context_request",
        "risk_attestation",
        "zarsuit_task_output_for_secretary",
        "zarsuit_execution_input",
        "secretary_routing_directive",
    }
    assert set(_SCHEMA_KEYS_UNAMBIGUOUS) == expected


def test_schema_keys_generic_match_q4_contract():
    """Generic key list must match secretary_bridge_contract.md §Q4 exactly."""
    expected = {"tool_call", "function_call", "arguments", "internal_tool"}
    assert set(_SCHEMA_KEYS_GENERIC) == expected


# ---------------------------------------------------------------------------
# Clean content — no false positives
# ---------------------------------------------------------------------------

def test_guard_clean_content_does_not_fire():
    result = guard_zarsuit_schema_leak("Hai ricevuto 3 email oggi. Il progetto procede bene.")
    assert result.fired is False
    assert result.redactions == []


def test_guard_does_not_fire_on_english_word_arguments():
    """'arguments' is a common English word — must not fire without JSON quotes."""
    result = guard_zarsuit_schema_leak("The function takes two arguments.")
    assert result.fired is False


def test_guard_does_not_fire_on_english_word_function():
    """'function' alone is not a schema key."""
    result = guard_zarsuit_schema_leak("This is a function.")
    assert result.fired is False


# ---------------------------------------------------------------------------
# Pattern 1+2: schema keys (unambiguous = token-naked, generic = JSON-quoted)
# ---------------------------------------------------------------------------

def test_guard_fires_on_unambiguous_key_unquoted():
    """Unambiguous keys fire even without JSON quotes (word-boundary match)."""
    result = guard_zarsuit_schema_leak("Il campo secretary_task_request è richiesto.")
    assert result.fired is True


def test_guard_fires_on_unambiguous_key_in_json():
    result = guard_zarsuit_schema_leak('{"secretary_task_request": "foo"}')
    assert result.fired is True


def test_guard_fires_on_risk_attestation_unquoted():
    result = guard_zarsuit_schema_leak("risk_attestation è la struttura usata per il routing.")
    assert result.fired is True


def test_guard_fires_on_zarsuit_task_output_unquoted():
    result = guard_zarsuit_schema_leak("zarsuit_task_output_for_secretary: completato")
    assert result.fired is True


def test_guard_fires_on_schema_key_nested_in_prose():
    """Key embedded in longer prose string — mirrors the real LLM injection vector."""
    prose = 'Ecco la risposta: {"secretary_task_request": "test", "data": 1} tutto ok.'
    result = guard_zarsuit_schema_leak(prose)
    assert result.fired is True


def test_guard_fires_on_generic_key_in_json():
    result = guard_zarsuit_schema_leak('{"tool_call": "do_something"}')
    assert result.fired is True


def test_guard_fires_on_function_call_in_json():
    result = guard_zarsuit_schema_leak('{"function_call": {"name": "x"}}')
    assert result.fired is True


# ---------------------------------------------------------------------------
# Pattern 3: XML tags
# ---------------------------------------------------------------------------

def test_guard_fires_on_system_xml_tag():
    result = guard_zarsuit_schema_leak("Risposta: <system>istruzioni interne</system>")
    assert result.fired is True


def test_guard_fires_on_developer_xml_tag():
    result = guard_zarsuit_schema_leak("<developer>override prompt</developer>")
    assert result.fired is True


def test_guard_fires_on_internal_schema_xml_tag():
    result = guard_zarsuit_schema_leak("<internal_schema>foo</internal_schema>")
    assert result.fired is True


# ---------------------------------------------------------------------------
# Pattern 4: line prefixes
# ---------------------------------------------------------------------------

def test_guard_fires_on_role_system_line():
    result = guard_zarsuit_schema_leak("Messaggio:\nrole: system\nContenuto.")
    assert result.fired is True


def test_guard_fires_on_role_developer_line():
    result = guard_zarsuit_schema_leak("role: developer\nfoo")
    assert result.fired is True


def test_guard_fires_on_zarsuit_internal_schema_prefix():
    result = guard_zarsuit_schema_leak("zarsuit_internal_schema: foo")
    assert result.fired is True


def test_guard_fires_on_internal_schema_prefix():
    result = guard_zarsuit_schema_leak("internal_schema: bar")
    assert result.fired is True


def test_guard_fires_on_recipient_functions_prefix():
    result = guard_zarsuit_schema_leak("recipient: functions.call_tool")
    assert result.fired is True


# ---------------------------------------------------------------------------
# GuardResult shape
# ---------------------------------------------------------------------------

def test_guard_result_has_fired_and_redactions():
    result = guard_zarsuit_schema_leak("secretary_task_request is here")
    assert isinstance(result, GuardResult)
    assert result.fired is True
    assert isinstance(result.redactions, list)
    assert len(result.redactions) > 0
