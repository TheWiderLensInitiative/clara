"""Laya's fourth question: does the new message continue what Clara just did? Asked only when her last reply was a
task (the agent), so the message goes back to that task with its context instead of starting fresh or going to chat.
Training and runtime must use this exact spec and state."""
FOLLOWUPS = {
    "continue": "The message continues or answers what Clara just did or said: yes or no to her offer or question, more details, "
                "a correction, a change ('make it 7pm instead'), more of the same ('also add...', 'what about tomorrow'), "
                "or it refers to her result ('that one', 'send it', 'why did it fail').",
    "new": "A new request on a different subject, or small talk that doesn't need what she just did: thanks, a greeting, "
           "a feeling, a joke, an unrelated question.",
}
FOLLOWUP_Q = {"type": "choice", "instructions": "Does the user's message continue what Clara just did?", "criteria": FOLLOWUPS}


def followup_state(text, last_reply):
    return {"message": text, "clara_just_said": (last_reply or "")[-600:]}
