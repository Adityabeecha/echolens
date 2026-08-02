from __future__ import annotations

import pytest

from echolens.llm.client import coerce_to_schema

ARRAY_SCHEMA = {
    "type": "object",
    "properties": {
        "evidence": {"type": "array", "items": {"type": "object"}},
        "hypothesis_updates": {"type": "array", "items": {"type": "object"}},
        "note": {"type": "string"},
    },
}


def test_a_dict_where_an_array_was_declared_becomes_a_list():
    out = coerce_to_schema({"evidence": {"ref": "r1", "snippet": "s"}}, ARRAY_SCHEMA)
    assert isinstance(out["evidence"], list)
    assert out["evidence"][:5] == [{"ref": "r1", "snippet": "s"}]


def test_a_numbered_object_becomes_a_list_in_order():
    out = coerce_to_schema(
        {"evidence": {"0": {"ref": "a"}, "1": {"ref": "b"}}}, ARRAY_SCHEMA)
    assert [e["ref"] for e in out["evidence"]] == ["a", "b"]


def test_a_single_wrapped_list_is_unwrapped_not_nested():
    out = coerce_to_schema({"evidence": {"evidence": [{"ref": "a"}]}}, ARRAY_SCHEMA)
    assert out["evidence"] == [{"ref": "a"}]


def test_null_where_an_array_was_declared_becomes_empty():
    assert coerce_to_schema({"evidence": None}, ARRAY_SCHEMA)["evidence"] == []


def test_a_correct_list_is_left_alone():
    rows = [{"ref": "a"}, {"ref": "b"}]
    assert coerce_to_schema({"evidence": rows}, ARRAY_SCHEMA)["evidence"] == rows


def test_non_array_fields_are_untouched():
    out = coerce_to_schema({"note": "hello"}, ARRAY_SCHEMA)
    assert out["note"] == "hello"


def test_a_non_dict_response_does_not_crash():
    assert coerce_to_schema([], ARRAY_SCHEMA) == {}
    assert coerce_to_schema(None, ARRAY_SCHEMA) == {}


def test_the_coerced_result_is_always_sliceable():
    for bad in ({"ref": "x"}, {"0": {"ref": "x"}}, None, "text", 7):
        out = coerce_to_schema({"evidence": bad}, ARRAY_SCHEMA)
        out["evidence"][:5]


def test_the_update_node_survives_a_dict_shaped_evidence_field():
    from echolens.investigator.prompts import UPDATE_SCHEMA

    out = coerce_to_schema(
        {"evidence": {"ref": "review 1", "snippet": "battery dies",
                      "supports": ["H1"], "contradicts": []},
         "hypothesis_updates": {"id": "H1", "likelihood": "moderate_support"}},
        UPDATE_SCHEMA)
    assert isinstance(out["evidence"], list)
    assert isinstance(out["hypothesis_updates"], list)
    out["evidence"][:5]


def test_the_client_coerces_before_returning(monkeypatch):
    from echolens.llm import openai_client as oc

    class _Resp:
        def __init__(self):
            self.usage = type("U", (), {"prompt_tokens": 10, "completion_tokens": 5})()
            msg = type("M", (), {"content": '{"evidence": {"ref": "r1"}}'})()
            self.choices = [type("C", (), {"message": msg})()]

    fake = type("F", (), {"create": lambda self, **kw: _Resp()})()
    monkeypatch.setattr(oc, "OpenAI", lambda **kw: type("X", (), {
        "chat": type("Y", (), {"completions": fake})(),
        "timeout": kw.get("timeout"), "max_retries": kw.get("max_retries"),
    })())
    r = oc.OpenAIClient(model="m").complete_json("s", "u", ARRAY_SCHEMA, "a")
    assert isinstance(r.parsed["evidence"], list)
