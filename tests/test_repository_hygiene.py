"""Tracked text files carry no personal absolute path."""

from pathlib import Path
import re
import subprocess
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]

# Names that stand for "a user" rather than a person (compared in lower case).
NEUTRAL_NAMES = {
    "example", "runneradmin", "runner", "user", "username", "yourname", "your-name",
    "you", "name", "public", "default", "all users",
}
# A name that is itself a placeholder or an expression, such as <name>, %USERPROFILE%, $USER or {user}.
PLACEHOLDER_MARKERS = ("<", "%", "$", "{", "~", "*")

NAME = r"[^\\/\s\"'`,;:()\[\]]+"
WINDOWS_USER = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]+Users[\\/]+(" + NAME + r")", re.IGNORECASE)
POSIX_USER = re.compile(r"(?<![\w.~$%{}:-])/(?:home|Users)/(" + NAME + r")/")
WORKSPACE_PROJECTS = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]+(?:[^\s\"'`]*?[\\/]+)?Workspace[\\/]+Projects(?![A-Za-z0-9_-])", re.IGNORECASE)


def _is_neutral(name):
    return name.lower() in NEUTRAL_NAMES or name.startswith(PLACEHOLDER_MARKERS)


def personal_path_hits(line):
    """Return the personal absolute paths found in one line of text."""
    hits = []
    for match in WINDOWS_USER.finditer(line):
        if not _is_neutral(match.group(1)):
            hits.append(match.group(0))
    for match in POSIX_USER.finditer(line):
        if not _is_neutral(match.group(1)):
            hits.append(match.group(0))
    for match in WORKSPACE_PROJECTS.finditer(line):
        hits.append(match.group(0))
    return hits


def _tracked_files():
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, check=False, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return [name for name in result.stdout.decode("utf-8", "replace").split("\0") if name]


class PersonalPathMatcherTests(unittest.TestCase):
    # Samples are assembled from pieces so this file does not hold a personal path itself.
    BACKSLASH = "\\"
    DRIVE = "C" + ":"

    def path(self, *parts, sep=None):
        return (sep or self.BACKSLASH).join(parts)

    def test_windows_user_folders_are_flagged_with_either_slash_and_any_case(self):
        for sep in ("\\", "/", "\\\\"):
            for drive in ("C:", "c:", "D:"):
                for folder in ("Users", "users", "USERS"):
                    line = f"see {drive}{sep}{folder}{sep}jsmith{sep}project for details"
                    with self.subTest(line=line):
                        self.assertEqual([f"{drive}{sep}{folder}{sep}jsmith"], personal_path_hits(line))

    def test_posix_home_folders_are_flagged(self):
        self.assertEqual(["/home" + "/jsmith/"], personal_path_hits("cd /home" + "/jsmith/work"))
        self.assertEqual(["/Users" + "/jsmith/"], personal_path_hits('path: "/Users' + '/jsmith/work"'))

    def test_workspace_projects_folders_are_flagged(self):
        for line in (
            "D:" + "\\Workspace\\Projects\\Thing\\repo",
            "e:/workspace" + "/projects/thing",
            "C:" + "\\Tools\\Workspace\\Projects",
        ):
            with self.subTest(line=line):
                self.assertTrue(personal_path_hits(line), line)

    def test_neutral_placeholders_pass(self):
        for line in (
            self.DRIVE + "\\Users\\Example\\AppData\\Local\\Temp",
            self.DRIVE + "\\Users\\runneradmin\\work",
            self.DRIVE + "/users/EXAMPLE/work",
            self.DRIVE + "\\Users\\%USERPROFILE%\\work",
            self.DRIVE + "\\Users\\<name>\\work",
            "/home/runner/work/repo",
            "/home/<name>/work",
            "/Users/Example/work",
            "~/Users/example-dir/work",
        ):
            with self.subTest(line=line):
                self.assertEqual([], personal_path_hits(line))

    def test_ordinary_paths_and_urls_pass(self):
        for line in (
            "GET /api/v1/users/me",
            "https://web.example.test/users/me",
            "see src/users/profile.py",
            "C:" + "\\temp\\scratch",
            "D:" + "\\work\\Projects\\thing",
            "the Workspace and Projects folders",
            "Workspace\\Projects without a drive",
            "/usr/home/shared/docs",
        ):
            with self.subTest(line=line):
                self.assertEqual([], personal_path_hits(line))


class RepositoryHygieneTests(unittest.TestCase):
    def test_tracked_text_files_hold_no_personal_absolute_path(self):
        files = _tracked_files()
        if files is None:
            self.skipTest("git is unavailable or the repository has no git metadata")
        findings = []
        for name in files:
            path = REPO_ROOT / name
            try:
                data = path.read_bytes()
            except OSError:
                continue  # tracked but deleted or unreadable in this working tree
            if b"\0" in data:
                continue  # binary
            text = data.decode("utf-8", "replace")
            for number, line in enumerate(text.splitlines(), start=1):
                for hit in personal_path_hits(line):
                    findings.append(f"{name}:{number}: {hit}")
        self.assertEqual(
            [], findings,
            "Tracked files contain personal absolute paths. Replace each with a neutral placeholder "
            "such as C:\\Users\\Example, a relative path or an environment variable:\n" + "\n".join(findings),
        )


_PRIVATE_RECORD_PATTERNS = (
    # Maintainer-only records live in the private plans repository, never here.
    re.compile(r"^docs/reviews/"),
    re.compile(r"^docs/[^/]*-acceptance\.md$"),
    re.compile(r"^\.claude/agents/"),
    re.compile(r"(?i)(?:^|/)[^/]*(?:fable|opus|sonnet|haiku|astra|luna|gpt-?\d)[^/]*review[^/]*$"),
)


def private_record_paths(names):
    return [name for name in names if any(pattern.search(name) for pattern in _PRIVATE_RECORD_PATTERNS)]


class PrivateRecordTests(unittest.TestCase):
    def test_the_matcher_flags_review_and_acceptance_records(self):
        flagged = private_record_paths([
            "docs/reviews/2026-09-22-plan-review.md",
            "docs/connected-core-acceptance.md",
            ".claude/agents/prism-implementer.md",
            "notes/2026-09-24-fable5-implementation-review.json",
            "notes/opus-review.md",
        ])
        self.assertEqual(5, len(flagged))
        self.assertEqual([], private_record_paths([
            "docs/shared-board.md",
            "docs/agent-hosts.md",
            "scripts/e2e/journey.py",
            "tests/test_board_review_fixes.py",
            "template/.claude/agents/README.md.jinja",
        ]))

    def test_no_maintainer_review_or_acceptance_record_is_tracked(self):
        files = _tracked_files()
        if files is None:
            self.skipTest("git is unavailable or the repository has no git metadata")
        found = private_record_paths(files)
        self.assertEqual(
            [], found,
            "Maintainer review, acceptance and agent-definition records belong in the private plans "
            "repository, not in this public repository:\n" + "\n".join(found),
        )


if __name__ == "__main__":
    unittest.main()
