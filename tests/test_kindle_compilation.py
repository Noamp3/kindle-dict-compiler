import unittest
import sys
from pathlib import Path

# Add root folder to path so we can import modules correctly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build_kindle_dict import extract_lookup_keys, reverse_hebrew_words_in_text

class TestKindleCompilation(unittest.TestCase):

    def test_reverse_hebrew_words_in_text_simple(self):
        """Test simple single line Hebrew word reversal."""
        self.assertEqual(reverse_hebrew_words_in_text("אני שמח מאוד"), "מאוד שמח אני")
        # Mixed LTR and RTL
        self.assertEqual(reverse_hebrew_words_in_text("hola שלום amigo"), "amigo שלום hola")
        # Non-Hebrew unchanged
        self.assertEqual(reverse_hebrew_words_in_text("hello world"), "hello world")

    def test_reverse_hebrew_words_in_text_multiline(self):
        """Test multi-line Hebrew word reversal preserving line ordering and newlines."""
        input_text = "(תואר)\n1. שקוע במחשבות\n2. נדהם"
        expected = "(תואר)\nבמחשבות שקוע 1.\nנדהם 2."
        self.assertEqual(reverse_hebrew_words_in_text(input_text), expected)


    def test_extract_lookup_keys_simple(self):
        """Test simple headwords without complex markup."""
        self.assertEqual(extract_lookup_keys("casa"), ["casa"])
        self.assertEqual(extract_lookup_keys("  perro  "), ["perro"])

    def test_extract_lookup_keys_multiple_delimiters(self):
        """Test headwords containing commas, semicolons, and slashes."""
        # Comma separation
        self.assertEqual(extract_lookup_keys("bueno, -na"), ["bueno", "-na"])
        # Semicolon separation
        self.assertEqual(extract_lookup_keys("andar; camino"), ["andar", "camino"])
        # Slash separation
        self.assertEqual(extract_lookup_keys("abrir/cerrar"), ["abrir", "cerrar"])

    def test_extract_lookup_keys_strip_parentheses(self):
        """Test that text inside parentheses is extracted as secondary keys while stripped from the main key."""
        # Simple parentheses
        self.assertEqual(extract_lookup_keys("creer (להאמין)"), ["creer", "להאמין"])
        # Embedded parenthesis inside list
        keys = extract_lookup_keys("hacer (hago, haces)")
        self.assertIn("hacer", keys)
        self.assertIn("hago", keys)
        self.assertIn("haces", keys)

    def test_extract_lookup_keys_strip_symbols_and_punctuation(self):
        """Test removal of special characters and cleanup of double spaces."""
        self.assertEqual(extract_lookup_keys('dijo "hola"'), ["dijo hola"])
        self.assertEqual(extract_lookup_keys("abrir*"), ["abrir"])
        self.assertEqual(extract_lookup_keys("el  [perro]"), ["el perro"])

    def test_extract_lookup_keys_strip_trailing_senses(self):
        """Test stripping of trailing dictionary sense integers (e.g. 'desalmado 1' -> 'desalmado')."""
        self.assertEqual(extract_lookup_keys("desalmado 1"), ["desalmado"])
        self.assertEqual(extract_lookup_keys("casa 12"), ["casa"])

    def test_extract_lookup_keys_filter_grammar_markers(self):
        """Test that grammatical POS abbreviations are filtered out of index keys."""
        self.assertEqual(extract_lookup_keys("abad n."), ["abad"])
        self.assertEqual(extract_lookup_keys("bueno adj."), ["bueno"])
        self.assertEqual(extract_lookup_keys("adj."), ["adj."]) # Falls back to preserving original indicator

    def test_extract_lookup_keys_single_letter_rules(self):
        """Test that single-letter entries are skipped, unless they are standard Spanish single-letter words (a, o, y) or rescued by fallback."""
        self.assertEqual(extract_lookup_keys("a"), ["a"])
        self.assertEqual(extract_lookup_keys("o"), ["o"])
        self.assertEqual(extract_lookup_keys("y"), ["y"])
        # Rescued by fallback since they are the sole entry word
        self.assertEqual(extract_lookup_keys("b"), ["b"])
        self.assertEqual(extract_lookup_keys("z"), ["z"])
        # Filters out 'b' successfully since 'bueno' is present as a valid key
        self.assertEqual(extract_lookup_keys("bueno, b"), ["bueno"])

    def test_extract_lookup_keys_fallback(self):
        """Test fallback behavior when all keys are filtered out by grammar rules."""
        # Returns raw headword stripped of symbols
        self.assertEqual(extract_lookup_keys("(adj.)"), ["adj."])


if __name__ == "__main__":
    unittest.main()
