import unittest
import sys
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

# Add root folder to path so we can import modules correctly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import prepare_translation_batches
import translate_batches
import merge_translated_batches
import build_kindle_dict


class TestPipelineIntegration(unittest.TestCase):

    def setUp(self):
        # Create a temporary directory structure for our mock data and outputs
        self.test_dir = Path(tempfile.mkdtemp())
        self.work_dir = self.test_dir / "work"
        self.work_dir.mkdir()
        
        # Paths for input database
        self.input_jsonl = self.work_dir / "dictionary_entries.jsonl"
        self.source_batches_dir = self.work_dir / "translation_batches"
        self.translated_batches_dir = self.work_dir / "translated_batches"
        self.merged_jsonl = self.work_dir / "dictionary_es_he.jsonl"
        self.merged_csv = self.work_dir / "dictionary_es_he.csv"
        self.kindle_source_dir = self.work_dir / "kindle_source"
        self.env_file = self.test_dir / ".env"

        # Write dummy API key in env file
        self.env_file.write_text("GEMINI_API_KEY=mock_key\n", encoding="utf-8")

        # Create 3 mock Spanish-English entries with/without examples
        self.mock_entries = [
            {
                "entry_id": 1,
                "headword_es": "abad",
                "definition_en": "I. m. abbot\nII. priest",
                "examples_en": "el abad reza"
            },
            {
                "entry_id": 2,
                "headword_es": "casa",
                "definition_en": "f. house",
                "examples_en": "la casa es grande"
            },
            {
                "entry_id": 3,
                "headword_es": "perro",
                "definition_en": "m. dog",
                "examples_en": "el perro corre"
            }
        ]

        with self.input_jsonl.open("w", encoding="utf-8") as f:
            for entry in self.mock_entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def tearDown(self):
        # Remove the temporary test directory
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("translate_batches.load_google_key", return_value="mock_key")
    @patch("translate_batches.call_google_api")
    def test_end_to_end_pipeline(self, mock_call_api, mock_load_key):
        """Test the entire dictionary processing and compilation pipeline end-to-end."""
        
        # 1. Step: Split entries into batches of size 2
        # Sys argv patch for prepare_translation_batches
        prepare_argv = [
            "prepare_translation_batches.py",
            str(self.input_jsonl),
            "--output-dir", str(self.source_batches_dir),
            "--batch-size", "2"
        ]
        with patch.object(sys, "argv", prepare_argv):
            exit_code = prepare_translation_batches.main()
            self.assertEqual(exit_code, 0)

        # Assert that two batches were generated
        self.assertTrue((self.source_batches_dir / "batch_0001.jsonl").exists())
        self.assertTrue((self.source_batches_dir / "batch_0002.jsonl").exists())
        self.assertTrue((self.source_batches_dir / "manifest.json").exists())

        # 2. Step: Mock translate_batches.call_google_api to return valid Hebrew JSONL chunks
        # Batch 1 (entries 1 and 2)
        batch1_translation = (
            '{"entry_id": 1, "headword_es": "abad", "definition_he": "(זכר) 1. אב מנזר\\n2. כומר", "examples_he": "אב המנזר מתפלל"}\n'
            '{"entry_id": 2, "headword_es": "casa", "definition_he": "(נקבה) בית", "examples_he": "הבית גדול"}\n'
        )
        # Batch 2 (entry 3)
        batch2_translation = (
            '{"entry_id": 3, "headword_es": "perro", "definition_he": "(זכר) כלב", "examples_he": "הכלב רץ"}\n'
        )

        mock_call_api.side_effect = [batch1_translation, batch2_translation]

        # Sys argv patch for translate_batches
        translate_argv = [
            "translate_batches.py",
            "--source-dir", str(self.source_batches_dir),
            "--translated-dir", str(self.translated_batches_dir),
            "--delay", "0.0",
            "--env-file", str(self.env_file)
        ]
        with patch.object(sys, "argv", translate_argv):
            exit_code = translate_batches.main()
            self.assertEqual(exit_code, 0)

        # Verify that translated canonical files exist
        self.assertTrue((self.translated_batches_dir / "batch_0001.jsonl").exists())
        self.assertTrue((self.translated_batches_dir / "batch_0002.jsonl").exists())

        # 3. Step: Merge translated batches into a single unified JSONL/CSV
        merge_argv = [
            "merge_translated_batches.py",
            "--input-dir", str(self.translated_batches_dir),
            "--jsonl", str(self.merged_jsonl),
            "--csv", str(self.merged_csv)
        ]
        with patch.object(sys, "argv", merge_argv):
            exit_code = merge_translated_batches.main()
            self.assertEqual(exit_code, 0)

        # Verify merged outputs exist and contain all 3 entries
        self.assertTrue(self.merged_jsonl.exists())
        self.assertTrue(self.merged_csv.exists())

        with self.merged_jsonl.open("r", encoding="utf-8") as f:
            merged_rows = [json.loads(line.strip()) for line in f if line.strip()]
        self.assertEqual(len(merged_rows), 3)
        self.assertEqual(merged_rows[0]["entry_id"], 1)
        self.assertEqual(merged_rows[1]["entry_id"], 2)
        self.assertEqual(merged_rows[2]["entry_id"], 3)
        
        # Verify LRM was injected in definition_he for 1. אב מנזר
        self.assertIn("1.\u200e אב מנזר", merged_rows[0]["definition_he"])

        # 4. Step: Compile into Kindle source packages (XHTML, OPF, NCX)
        build_argv = [
            "build_kindle_dict.py",
            "--input", str(self.merged_jsonl),
            "--output-dir", str(self.kindle_source_dir)
        ]
        with patch.object(sys, "argv", build_argv):
            exit_code = build_kindle_dict.main()
            self.assertEqual(exit_code, 0)

        # Assert compilation output files exist
        book_html = self.kindle_source_dir / "part_001.html"
        content_opf = self.kindle_source_dir / "content.opf"
        toc_ncx = self.kindle_source_dir / "toc.ncx"

        self.assertTrue(book_html.exists())
        self.assertTrue(content_opf.exists())
        self.assertTrue(toc_ncx.exists())

        # Read part_001.html and verify layout features
        html_content = book_html.read_text(encoding="utf-8")
        
        # Check for essential tags and structures
        self.assertIn("<mbp:frameset>", html_content)
        self.assertIn("<idx:entry", html_content)
        self.assertIn('dir="rtl"', html_content)
        
        # Check that definition and examples are wrapped in block-level RTL divs with explicit inline styles
        self.assertIn('class="definition"', html_content)
        self.assertIn('class="example"', html_content)
        self.assertIn('style="direction: rtl; text-align: right; unicode-bidi: embed;', html_content)
        
        # Check correct visual translations mapped
        self.assertIn("מנזר אב", html_content)
        self.assertIn("גדול הבית", html_content)
        self.assertIn("רץ הכלב", html_content)


if __name__ == "__main__":
    unittest.main()
