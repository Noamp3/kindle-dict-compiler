import unittest
import sys
from pathlib import Path

# Add root folder to path so we can import modules correctly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from import_translated_batch import (
    post_process_definition,
    _clean_string_value,
    repair_mojibake_text,
    _parse_json_line,
    _repair_line_with_schema,
    validate,
    config
)

class TestImportValidation(unittest.TestCase):

    def test_post_process_definition_pos_expansion(self):
        """Test expansion of abbreviated grammatical markers (POS tags)."""
        self.assertEqual(post_process_definition("(תא') בית"), "(תואר) בית")
        self.assertEqual(post_process_definition("(תא' ) בית"), "(תואר) בית")
        self.assertEqual(post_process_definition("(ת') בית"), "(תואר הפועל) בית")
        self.assertEqual(post_process_definition("(סלנג) בית"), "(דיבורי) בית")

    def test_post_process_definition_arabic_homoglyphs(self):
        """Test conversion of accidental Arabic homoglyph characters back to Hebrew."""
        # 'ب' is Arabic Beh, should be 'ב' Hebrew Bet
        # 'ت' is Arabic Teh, should be 'ת' Hebrew Tav
        # 'م' is Arabic Meem, should be 'מ' Hebrew Mem
        arabic_text = "بنت م"
        hebrew_repaired = post_process_definition(arabic_text)
        self.assertEqual(hebrew_repaired, "בנת מ")

    def test_post_process_definition_em_dash_cleanup(self):
        """Test cleanup of em-dashes preceding list markers."""
        self.assertEqual(
            post_process_definition("(תואר) — 1. בית"),
            "(תואר)\n1.\u200e בית"
        )
        self.assertEqual(
            post_process_definition("(תואר) – 1. בית"),
            "(תואר)\n1.\u200e בית"
        )

    def test_post_process_definition_list_separation(self):
        """Test that parenthesized tags are separated from list number 1 with a newline."""
        self.assertEqual(
            post_process_definition("(זכר) 1. בית"),
            "(זכר)\n1.\u200e בית"
        )

    def test_post_process_definition_newline_before_subsequent_senses(self):
        """Test that list numbers 2. and upwards are preceded by a newline for clean division."""
        text = "1. בית 2. חדר 3. דירה"
        repaired = post_process_definition(text)
        self.assertIn("1. בית\n2. חדר\n3. דירה", repaired.replace("\u200e", ""))

    def test_post_process_definition_lrm_isolator(self):
        """Test that Left-to-Right Marks (\u200e) are inserted to guard RTL/LTR digits from visual flipping."""
        self.assertEqual(post_process_definition("1. בית"), "1.\u200e בית")
        self.assertEqual(post_process_definition("א. חדר"), "א.\u200e חדר")

    def test_clean_string_value(self):
        """Test cleaning string formatting and quotes."""
        self.assertEqual(_clean_string_value('"בית"'), "בית")
        self.assertEqual(_clean_string_value("'בית'"), "בית")
        self.assertEqual(_clean_string_value('בית,'), "בית")
        self.assertEqual(_clean_string_value('בית\\nחדר'), "בית\nחדר")

    def test_repair_mojibake_text(self):
        """Test CP1252 mojibake string recovery."""
        # Hebrew 'שלום' encoded in UTF-8 but parsed as CP1252 gives '×©×××'
        mojibake = "×©×\x9c×\x95×\x9d"
        repaired = repair_mojibake_text(mojibake)
        self.assertEqual(repaired, "שלום")

    def test_parse_json_line_valid(self):
        """Test parsing normal valid JSON lines."""
        line = '{"entry_id": 1, "headword_es": "abad", "definition_he": "אב מנזר"}'
        parsed = _parse_json_line(line)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["entry_id"], 1)
        self.assertEqual(parsed["headword_es"], "abad")
        self.assertEqual(parsed["definition_he"], "אב מנזר")

    def test_parse_json_line_malformed_repair(self):
        """Test parsing and repairing malformed JSON objects using best-effort schema recovery."""
        # Key quotes missing, commas misplaced, trailing garbage
        malformed = '{entry_id: 10, headword_es: "casa", definition_he: "(נקבה) בית", examples_he: "ex" }'
        parsed = _parse_json_line(malformed)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["entry_id"], 10)
        self.assertEqual(parsed["headword_es"], "casa")
        self.assertEqual(parsed["definition_he"], "(נקבה) בית")

    def test_validate_gate_clean(self):
        """Test that valid rows pass without errors."""
        rows = [
            (1, {"entry_id": 1, "headword_es": "abad", "definition_he": "אב מנזר", "examples_he": ""})
        ]
        source_map = {1: "abad"}
        errors = validate(rows, source_map)
        self.assertEqual(errors, [])

    def test_validate_gate_missing_fields(self):
        """Test that validation flags missing fields."""
        rows = [
            (1, {"entry_id": 1, "headword_es": "abad"})
        ]
        source_map = {1: "abad"}
        errors = validate(rows, source_map)
        self.assertTrue(any("missing fields" in err for err in errors))

    def test_validate_gate_duplicate_ids(self):
        """Test duplicate entry ID detection."""
        rows = [
            (1, {"entry_id": 1, "headword_es": "abad", "definition_he": "אב מנזר", "examples_he": ""}),
            (2, {"entry_id": 1, "headword_es": "casa", "definition_he": "בית", "examples_he": ""})
        ]
        source_map = {1: "abad"}
        errors = validate(rows, source_map)
        self.assertTrue(any("duplicate entry_id" in err for err in errors))

    def test_validate_gate_forbidden_short_pos(self):
        """Test detection of forbidden short POS abbreviations."""
        rows = [
            (1, {"entry_id": 1, "headword_es": "abad", "definition_he": "ז' אב מנזר", "examples_he": ""})
        ]
        source_map = {1: "abad"}
        errors = validate(rows, source_map)
        self.assertTrue(any("uses forbidden shortened POS tags" in err for err in errors))

    def test_validate_gate_hallucination_repeats(self):
        """Test detection of character or phrase repetition loops."""
        # Character loop
        rows_char = [
            (1, {"entry_id": 1, "headword_es": "abad", "definition_he": "אב מנזרררררר", "examples_he": ""})
        ]
        source_map = {1: "abad"}
        errors = validate(rows_char, source_map)
        self.assertTrue(any("repeating character/phrase hallucination loop" in err for err in errors))

        # Phrase loop
        rows_phrase = [
            (1, {"entry_id": 1, "headword_es": "abad", "definition_he": "אב מנזר אב מנזר אב מנזר אב מנזר אב מנזר", "examples_he": ""})
        ]
        errors = validate(rows_phrase, source_map)
        self.assertTrue(any("repeating character/phrase hallucination loop" in err for err in errors))

    def test_validate_gate_forbidden_scripts(self):
        """Test scanner for foreign scripts (Cyrillic, Hindi, CJK, etc.)."""
        # Hindi letter present in definition
        rows = [
            (1, {"entry_id": 1, "headword_es": "abad", "definition_he": "אב מנזר देवनागरी", "examples_he": ""})
        ]
        source_map = {1: "abad"}
        errors = validate(rows, source_map)
        self.assertTrue(any("contains forbidden foreign script characters" in err for err in errors))


if __name__ == "__main__":
    unittest.main()
