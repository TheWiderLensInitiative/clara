"""Whether a new message needs the context of Clara's recent task reply.
Keep Bridge and training identical, including the 600-character context window.
"""
FOLLOWUPS = {
    "continue": "Uses Clara's last result or answers her question: approve, reject, correct, refine, ask for details, or continue the same task.",
    "new": "An independent request or question, even on a related topic; or just greeting, thanks, praise, or reaction without requesting more work.",
}
FOLLOWUP_Q = {"type": "choice", "instructions": "Does the user's message continue what Clara just did?", "criteria": FOLLOWUPS}


def followup_state(text, last_reply):
    return {"message": text, "clara_just_said": (last_reply or "")[-600:]}
