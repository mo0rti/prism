"""The token registry: redaction, the saved-file scan and in-place scrubbing."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prism_e2e.tokens import REDACTION, TokenRegistry  # noqa: E402

HUMAN = "h" * 20 + "-HUMAN_TOKEN_VALUE-" + "9" * 5
AGENT = "a" * 20 + "-AGENT_TOKEN_VALUE-" + "8" * 5


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tokens = TokenRegistry()
        self.tokens.add("human", HUMAN)
        self.tokens.add("claude", AGENT)

    def test_redact_replaces_every_occurrence_of_every_token(self):
        text = f"Authorization: Bearer {HUMAN} and again {HUMAN}; agent {AGENT}"
        redacted = self.tokens.redact(text)
        self.assertNotIn(HUMAN, redacted)
        self.assertNotIn(AGENT, redacted)
        self.assertEqual(redacted.count(REDACTION), 3)

    def test_a_token_that_is_too_short_to_track_safely_is_refused(self):
        with self.assertRaises(ValueError):
            self.tokens.add("weak", "short")

    def test_labels_in_reports_which_tokens_appear(self):
        self.assertEqual(self.tokens.labels_in(f"x{AGENT}y".encode()), ["claude"])
        self.assertEqual(self.tokens.labels_in(b"nothing here"), [])

    def test_scan_tree_finds_a_token_in_any_file_and_names_it_by_label_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "transcripts").mkdir()
            (root / "transcripts" / "clean.txt").write_text("no secrets", encoding="utf-8")
            (root / "transcripts" / "leak.jsonl").write_text(f'{{"auth": "{HUMAN}"}}', encoding="utf-8")
            (root / "logs.bin").write_bytes(b"\x00\x01" + AGENT.encode() + b"\x02")
            hits = self.tokens.scan_tree(root)
        self.assertEqual(hits, [("logs.bin", ["claude"]), ("transcripts/leak.jsonl", ["human"])])
        self.assertNotIn(HUMAN, repr(hits))

    def test_scan_tree_skips_the_installed_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "work" / "venv").mkdir(parents=True)
            (root / "work" / "venv" / "big.bin").write_bytes(HUMAN.encode())
            self.assertEqual(self.tokens.scan_tree(root, skip=[root / "work" / "venv"]), [])
            self.assertEqual(len(self.tokens.scan_tree(root)), 1)

    def test_scrub_file_removes_the_token_in_place(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "leak.txt"
            path.write_text(f"before {HUMAN} after", encoding="utf-8")
            self.tokens.scrub_file(path)
            self.assertEqual(path.read_text(encoding="utf-8"), f"before {REDACTION} after")
            self.assertEqual(self.tokens.scan_tree(Path(folder)), [])


if __name__ == "__main__":
    unittest.main()
