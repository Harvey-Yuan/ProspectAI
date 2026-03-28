"""
Unit tests for Browser Agent — pure function tests, no mocks.
Tests parsing, validation, CSV writing, prompt building.
"""

import csv
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from browserAgent.agent import parse_enriched_lead, validate_enriched_lead, save_enriched_csv
from browserAgent.prompts import build_user_message, mcp_tools_to_llm_tools
from state import EnrichedLead
from tests.browserAgent.conftest import SAMPLE_ENRICHED_JSON


# ── parse_enriched_lead ──────────────────────────────────────────────────────

class TestParseEnrichedLead:
    def test_valid_json(self):
        result = parse_enriched_lead(SAMPLE_ENRICHED_JSON)
        assert result is not None
        assert result["company_name"] == "COBRE CERRILLOS S A COCESA"
        assert result["contact_name"] == "Juan Pérez"
        assert result["email"] == "contacto@cocesa.cl"

    def test_markdown_fenced_json(self):
        fenced = f"```json\n{SAMPLE_ENRICHED_JSON}\n```"
        result = parse_enriched_lead(fenced)
        assert result is not None
        assert result["company_name"] == "COBRE CERRILLOS S A COCESA"

    def test_json_with_surrounding_text(self):
        content = f"Here is the result:\n{SAMPLE_ENRICHED_JSON}\nDone."
        result = parse_enriched_lead(content)
        assert result is not None
        assert result["email"] == "contacto@cocesa.cl"

    def test_invalid_json_returns_none(self):
        assert parse_enriched_lead("not json at all") is None

    def test_empty_string_returns_none(self):
        assert parse_enriched_lead("") is None


# ── validate_enriched_lead ───────────────────────────────────────────────────

class TestValidateEnrichedLead:
    def test_valid_lead(self):
        data = json.loads(SAMPLE_ENRICHED_JSON)
        result = validate_enriched_lead(data)
        assert result is not None
        assert result["company_name"] == "COBRE CERRILLOS S A COCESA"
        assert result["contact_name"] == "Juan Pérez"

    def test_missing_contact_name_returns_none(self):
        data = json.loads(SAMPLE_ENRICHED_JSON)
        data["contact_name"] = ""
        assert validate_enriched_lead(data) is None

    def test_missing_company_name_returns_none(self):
        data = json.loads(SAMPLE_ENRICHED_JSON)
        data["company_name"] = ""
        assert validate_enriched_lead(data) is None

    def test_no_contact_channel_returns_none(self):
        data = json.loads(SAMPLE_ENRICHED_JSON)
        data["email"] = None
        data["phone"] = None
        data["contact_form_url"] = None
        assert validate_enriched_lead(data) is None

    def test_only_phone_is_valid(self):
        data = {
            "company_name": "Test Co",
            "contact_name": "Jane",
            "email": None,
            "phone": "+1234",
            "contact_form_url": None,
        }
        result = validate_enriched_lead(data)
        assert result is not None
        assert result["phone"] == "+1234"

    def test_only_contact_form_is_valid(self):
        data = {
            "company_name": "Test Co",
            "contact_name": "Jane",
            "email": None,
            "phone": None,
            "contact_form_url": "https://example.com/contact",
        }
        result = validate_enriched_lead(data)
        assert result is not None

    def test_none_input_returns_none(self):
        assert validate_enriched_lead(None) is None


# ── save_enriched_csv ────────────────────────────────────────────────────────

class TestSaveEnrichedCSV:
    def test_writes_valid_csv(self, sample_enriched_lead: EnrichedLead, tmp_path: Path):
        with patch("browserAgent.agent.OUTPUT_DIR", tmp_path):
            csv_path = save_enriched_csv([sample_enriched_lead])
            assert Path(csv_path).exists()
            with open(csv_path, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            assert len(rows) == 1
            assert rows[0]["company_name"] == "COBRE CERRILLOS S A COCESA"
            assert rows[0]["email"] == "contacto@cocesa.cl"

    def test_empty_list_writes_header_only(self, tmp_path: Path):
        with patch("browserAgent.agent.OUTPUT_DIR", tmp_path):
            csv_path = save_enriched_csv([])
            with open(csv_path, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            assert len(rows) == 0


# ── build_user_message ───────────────────────────────────────────────────────

class TestBuildUserMessage:
    def test_includes_company_info(self):
        msg = build_user_message("COCESA", "Chile", "8544491090", "CONDUCTOR")
        assert "COCESA" in msg
        assert "Chile" in msg
        assert "8544491090" in msg
        assert "CONDUCTOR" in msg

    def test_optional_fields_omitted(self):
        msg = build_user_message("COCESA", "Chile")
        assert "COCESA" in msg
        assert "HS code" not in msg


# ── mcp_tools_to_llm_tools ──────────────────────────────────────────────────

class TestMCPToolsConversion:
    def test_converts_to_openai_format(self):
        mcp_tools = [
            {
                "name": "browser_navigate",
                "description": "Navigate to a URL",
                "input_schema": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            },
        ]
        result = mcp_tools_to_llm_tools(mcp_tools)
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "browser_navigate"
        assert result[0]["function"]["parameters"]["properties"]["url"]["type"] == "string"
