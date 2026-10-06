"""Laya's thinking budget: one specified action versus work requiring judgment.
Criteria stay within Laya's 48-token per-option limit. Keep Bridge and training identical.
"""
EFFORTS = {
    "quick": "Direct lookups or specified actions: read values, list matches, open things, copy named files, or send given text.",
    "deep": "Judgment or synthesis: plan, compare, write, debug, organize, review contents, select important items, or decide what needs attention.",
}
EFFORT_Q = {"type": "choice", "instructions": "How much thinking does this task need?", "criteria": EFFORTS}
