"""Run-time answers for the clarify steps.

An agent writes its own question set, so a prompt that answers fixed questions breaks
when the questions differ. The clarify prompts therefore carry an ``{answers}``
placeholder. At run time it is filled from the open questions the role owns on the
feature page: each question is listed with its number and text, followed by the
owner's answer. A question whose topic is scripted here gets that scripted answer;
any other question gets the role's fixed fallback decision. The answer is the human
owner's reply, pasted verbatim, never content the agent has to invent.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

PLACEHOLDER = "{answers}"

# Clarify step to the owner role whose open questions it answers.
CLARIFY_ROLES = {"po-clarify": "po", "design-clarify": "designer", "dev-clarify": "dev"}

FALLBACK = "Not needed for this release; decide later."

NO_QUESTIONS = "I have no open question on this feature, so there is nothing to answer. Tell me that and make no change."


@dataclass(frozen=True)
class Topic:
    name: str
    pattern: re.Pattern[str]
    answer: str

    def matches(self, question: str) -> bool:
        return bool(self.pattern.search(question))


def _topic(name: str, pattern: str, answer: str) -> Topic:
    return Topic(name, re.compile(pattern, re.IGNORECASE), answer)


# Scripted answers by owner role. A pattern is matched against the question text; the first
# matching topic of the role answers it.
TOPICS: dict[str, tuple[Topic, ...]] = {
    "po": (
        _topic(
            "format and channel",
            r"\bchannel\b|\b(?:in|what|which|file|export|output|delivery)\s+format\b",
            "A downloaded PDF file. The system only produces it; the reviewer sends it on themselves.",
        ),
        _topic(
            "overflow",
            r"\b(?:fit|overflow|spill\w*|too (?:many|long|much)|more than one page|one page|truncat\w*|page limit)\b",
            "One page stays the limit. Show as many whole comments as fit and end with a line saying how many more comments are not shown.",
        ),
        _topic(
            "date or version",
            r"\bdate\b.*\bversion\b|\bversion\b.*\bdate\b",
            "The header shows the date the review was finished. It does not show a document version.",
        ),
        _topic(
            "language",
            r"\blanguages?\b|\blocali[sz]\w*|\btranslat\w*",
            "No. English only; no other language is needed for this feature.",
        ),
    ),
    "designer": (
        _topic(
            "export control and summary layout",
            r"\bexport control\b|\b(?:where|which screen)\b.*\bexport\b|\bwhat does the summary look like\b",
            'One "Export summary" button on the finished review page. The summary is one A4 page: a header with the document title, the reviewer, the decision and the review date, then the comments in the order they were left.',
        ),
    ),
    "dev": (
        _topic(
            "app that presents the export control",
            r"\bwhich app\b|\bapps?\b.*\b(?:present\w*|export control)\b",
            'The backend serves the export through a service operation. The "Export summary" button lives in the client that calls the backend, and that client is outside this feature. Only the backend app is in scope.',
        ),
    ),
}


def answer_for(role: str, question: str) -> str:
    """The owner's answer to one question: the first scripted topic that matches, else the fallback decision."""

    for topic in TOPICS.get(role, ()):
        if topic.matches(question):
            return topic.answer
    return FALLBACK


def render_answers(role: str, open_questions: Iterable[tuple[str, str]]) -> str:
    """The answer list for ``(number, text)`` pairs of the open questions the role owns, in table order."""

    lines = [f'- Question {number} ("{text}"): {answer_for(role, text)}' for number, text in open_questions]
    return "\n".join(lines) if lines else f"- {NO_QUESTIONS}"


def fill(template: str, role: str, open_questions: Iterable[tuple[str, str]]) -> str:
    """``template`` with its ``{answers}`` placeholder replaced by the rendered answer list."""

    return template.replace(PLACEHOLDER, render_answers(role, open_questions))
