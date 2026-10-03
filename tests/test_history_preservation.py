"""Reading the history list must not delete another tab's empty conversation."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from open_llm_vtuber.chat_history_manager import get_history_list


class HistoryPreservationTests(unittest.TestCase):
    def test_listing_is_nondestructive_including_active_empty_history(self):
        with TemporaryDirectory() as directory:
            empty = Path(directory) / "still-active.json"
            saved = Path(directory) / "saved.json"
            empty.write_text(
                json.dumps([{"role": "metadata", "timestamp": "2026-10-02T00:00:00"}]),
                encoding="utf-8",
            )
            saved.write_text(
                json.dumps(
                    [
                        {
                            "role": "human",
                            "content": "fixture",
                            "timestamp": "2026-10-01T00:00:00",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            before = {path.name: path.read_bytes() for path in (empty, saved)}
            with patch(
                "open_llm_vtuber.chat_history_manager._ensure_conf_dir",
                return_value=directory,
            ):
                histories = get_history_list("profile")
                self.assertEqual([item["uid"] for item in histories], ["saved"])
                self.assertEqual(
                    {path.name: path.read_bytes() for path in (empty, saved)}, before
                )
