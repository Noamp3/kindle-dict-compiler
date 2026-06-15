from __future__ import annotations

import json
from pathlib import Path

DEFAULT_CONFIG = {
    "work_dir": "work",
    "model": "gemma-4-31b-it",
    "source_lang": {
        "name": "Spanish",
        "code": "es"
    },
    "target_lang": {
        "name": "Hebrew",
        "code": "he"
    },
    "fields": {
        "headword": "headword_es",
        "definition_source": "definition_en",
        "definition_target": "definition_he",
        "examples_source": "examples_en",
        "examples_target": "examples_he"
    },
    "grammar_markers": [
        "n.", "adj.", "v.", "adv.", "prep.", "f.", "m.", "pl.", "sing.", "pron.", "conj.", "art.", "sufijo", "prefijo",
        "n", "adj", "v", "adv", "prep", "f", "m", "pl", "sing"
    ],
    "kindle": {
        "title": "Spanish Hebrew Dictionary",
        "creator": "Granada University",
        "publisher": "Antigravity Dictionary Builder",
        "subject": "Dictionaries",
        "description": "Spanish-Hebrew Dictionary compiled from Granada University dictionary",
        "identifier": "es-he-dict-granada"
    }
}


class Config:
    def __init__(self, config_path: str | Path = "config.json"):
        self.path = Path(config_path)
        self.data = DEFAULT_CONFIG.copy()
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    user_data = json.load(f)
                    self.data.update(user_data)
            except Exception as e:
                print(f"Warning: Failed to load config.json, using default configuration. Error: {e}")

    @property
    def source_lang_name(self) -> str:
        return self.data["source_lang"]["name"]

    @property
    def source_lang_code(self) -> str:
        return self.data["source_lang"]["code"]

    @property
    def target_lang_name(self) -> str:
        return self.data["target_lang"]["name"]

    @property
    def target_lang_code(self) -> str:
        return self.data["target_lang"]["code"]

    @property
    def headword_field(self) -> str:
        return self.data["fields"]["headword"]

    @property
    def definition_source_field(self) -> str:
        return self.data["fields"]["definition_source"]

    @property
    def definition_target_field(self) -> str:
        return self.data["fields"]["definition_target"]

    @property
    def examples_source_field(self) -> str:
        return self.data["fields"].get("examples_source", "examples_en")

    @property
    def examples_target_field(self) -> str:
        return self.data["fields"].get("examples_target", "examples_he")

    @property
    def grammar_markers(self) -> list[str]:
        return self.data["grammar_markers"]

    @property
    def kindle_title(self) -> str:
        return self.data["kindle"]["title"]

    @property
    def kindle_creator(self) -> str:
        return self.data["kindle"]["creator"]

    @property
    def kindle_publisher(self) -> str:
        return self.data["kindle"]["publisher"]

    @property
    def kindle_subject(self) -> str:
        return self.data["kindle"]["subject"]

    @property
    def kindle_description(self) -> str:
        return self.data["kindle"]["description"]

    @property
    def kindle_identifier(self) -> str:
        return self.data["kindle"]["identifier"]

    @property
    def work_dir(self) -> str:
        return self.data["work_dir"]

    @property
    def model(self) -> str:
        return self.data["model"]


# Single global instance for easy import across scripts
config = Config()
