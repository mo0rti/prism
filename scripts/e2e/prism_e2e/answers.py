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

FALLBACK = "Out of scope for this release: the feature does not include it."
ROLE_FALLBACKS = {
    "po": FALLBACK,
    "designer": FALLBACK,
    "dev": "The technical design page settles this; build it as that page says.",
}

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
            "no comments",
            r"\b(?:no|without|zero)\s+comments?\b|\bcomments?\b.*\b(?:empty|none)\b",
            'Export is still available for a finished review with no comments. Keep the header and show "No comments." in the comments section.',
        ),
        _topic(
            "comment order",
            r"(?=.*\bcomments?\b).*\b(?:order\w*|sort\w*|chronolog\w*|sequence)\b",
            "Show comments in the order they were left, oldest first. For equal timestamps, use the stored comment ID in ascending order.",
        ),
        _topic(
            "export access and comment ownership",
            r"\b(?:who|whose)\b.*\b(?:export\w*|summary|comments?)\b|\b(?:other reviewers?|permissions?|authori[sz]\w*|access)\b.*\b(?:export\w*|summary|comments?)\b",
            "Only the signed-in reviewer who recorded the decision may export their review. The summary holds only that reviewer's comments, never another reviewer's comments.",
        ),
        _topic(
            "language",
            r"\blanguages?\b|\blocali[sz]\w*|\btranslat\w*",
            "No. English only; no other language is needed for this feature.",
        ),
        _topic(
            "header",
            r"\bheader\b|\bdocument title\b|\b(?:date|version)\b.*\b(?:summary|review|document)\b|\b(?:summary|review|document)\b.*\b(?:date|version)\b",
            "The header shows the date the review was finished, in YYYY-MM-DD format, along with the document title, reviewer name and recorded decision. It does not show a document version.",
        ),
        _topic(
            "finished review and export eligibility",
            r"(?=.*\b(?:review\w*|export\w*)\b).*\b(?:eligib\w*|permit\w*|in progress|unfinished|counts? as|consider\w*|determin\w*|complet\w*)\b|\bwhen\b.*\b(?:finished|export\w*)\b|\bwhich\b.*\b(?:review states?|decisions?)\b",
            "A review is finished once its reviewer records a decision: approved, changes requested or rejected. Each of those decisions permits export. Export is never offered while the review is in progress.",
        ),
        _topic(
            "format and channel",
            r"(?=.*\b(?:summary|reviewer|file|export\w*|output|deliver\w*|pdf)\b).*\b(?:format|channel)\b",
            "A downloaded PDF file. The system only produces it; the reviewer sends it on themselves.",
        ),
        _topic(
            "overflow",
            r"(?=.*\b(?:comments?|summary)\b).*\b(?:fit|overflow|spill\w*|too (?:many|long|much)|more than one page|one[ -]page|truncat\w*|page limit|exceed\w*)\b",
            "One page stays the limit. Show as many whole comments as fit and end with a line saying how many more comments are not shown.",
        ),
    ),
    "designer": (
        _topic(
            "export control and summary layout",
            r"\bexport (?:control|button)\b|\b(?:where|which screen)\b.*\bexport\b|(?=.*\b(?:summary|document title)\b).*\b(?:layout|arrang\w*|look\w*|appear\w*|structure|order)\b",
            'One "Export summary" button on the finished review page. The summary is one A4 page: a header with the document title, the reviewer, the decision and the review date, then the comments in the order they were left.',
        ),
    ),
    "dev": (
        _topic(
            "generation failure",
            r"(?=.*\b(?:generat\w*|export\w*|pdf|download)\b).*\b(?:fail\w*|error\w*|times? out|retry|partial)\b|(?=.*\b(?:generat\w*|export\w*|pdf)\b).*\b(?:handle|happens?)\b.*\btimeout\b",
            "If PDF generation fails or exceeds its time or size limit, return an error with no PDF or partial download and store nothing. The reviewer can retry the export; the stored review and comments stay unchanged.",
        ),
        _topic(
            "app that presents the export control",
            r"\bwhich app\b|\bapps?\b.*\b(?:present\w*|export control)\b",
            'The backend serves the export through a service operation. The "Export summary" button lives in the client that calls the backend, and that client is outside this feature. Only the backend app is in scope.',
        ),
        _topic(
            "review data and eligibility",
            r"\b(?:records?|stores?|data|fields?)\b.*\b(?:decision|reviewer|comments?)\b|(?=.*\b(?:review\w*|export\w*|pdf)\b).*\b(?:eligib\w*|in progress|authori[sz]\w*|permissions?|whose|other reviewers?|requesting|requester|comments?)\b|(?=.*\b(?:review\w*|export\w*|pdf)\b)(?=.*\b(?:identif\w*|determin\w*)\b).*\b(?:finished|complet\w*)\b",
            "Use the stored review's document title, reviewer, recorded decision, completion date and comments. Require the requesting reviewer to own that review and have recorded approved, changes requested or rejected; reject in-progress reviews and other reviewers' requests. Read only that reviewer's comments in the order they were left, oldest first, with stored comment ID ascending for equal timestamps.",
        ),
        _topic(
            "delivery and generation",
            r"(?=.*\b(?:export\w*|summary|pdf)\b)(?:.*\bbackend\b.*\b(?:deliver\w*|generat\w*|return\w*)\b|.*\b(?:how|where)\b.*\b(?:deliver\w*|generat\w*|download\w*|stor\w*|persist\w*|cach\w*)\b|.*\b(?:on request|response|download|stor\w*|persist\w*|cach\w*|stack|service|librar\w*|synchronous|asynchronous|background)\b)",
            "The backend generates the PDF on request from the stored review and returns it in the same response as a file download; no generated file is stored or cached. It reads only the requesting reviewer's comments of a finished review, using the backend's existing stack with no new service. Generation is limited to 5 seconds and a PDF of at most 1 MiB; exceeding either limit returns an error with no partial download.",
        ),
        _topic(
            "generation constraints",
            r"(?=.*\b(?:generat\w*|export\w*|summary|pdf)\b).*\b(?:constraints?|limits?|time|size|latency|performance|memory|timeout)\b",
            "Generate one A4 page with the header, whole comments that fit and the hidden-comment count. Generation is limited to 5 seconds and a PDF of at most 1 MiB; exceeding either limit returns an error with no partial download and stores nothing.",
        ),
    ),
}


def answer_for(role: str, question: str) -> str:
    """The owner's answer to one question: the first scripted topic that matches, else the fallback decision."""

    for topic in TOPICS.get(role, ()):
        if topic.matches(question):
            return topic.answer
    return fallback_for(role)


def fallback_for(role: str) -> str:
    """The fixed fallback decision for an owner role, or the general fallback for an unknown role."""

    return ROLE_FALLBACKS.get(role, FALLBACK)


def render_answers(role: str, open_questions: Iterable[tuple[str, str]]) -> str:
    """The answer list for ``(number, text)`` pairs of the open questions the role owns, in table order."""

    lines = [f'- Question {number} ("{text}"): {answer_for(role, text)}' for number, text in open_questions]
    return "\n".join(lines) if lines else f"- {NO_QUESTIONS}"


def fill(template: str, role: str, open_questions: Iterable[tuple[str, str]]) -> str:
    """``template`` with its ``{answers}`` placeholder replaced by the rendered answer list."""

    return template.replace(PLACEHOLDER, render_answers(role, open_questions))
