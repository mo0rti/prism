"""The notice every response carries, and the one place to adapt it.

The wording is generic. A product adapts it to its domain (a finance, health or legal product names its own
boundary), and the system prompt in `app/agent/prompts.py` states the same boundary to the model.
"""

NOTICE = (
    "This assistant helps you understand your own data. It does not give financial or other professional "
    "advice or personal recommendations. Check important decisions with a qualified person."
)
