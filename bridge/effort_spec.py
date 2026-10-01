"""Laya's second question: how much thinking a task needs (quick = thinking off, deep = thinking on)."""
EFFORTS = {
    "quick": "One simple action or lookup with an obvious tool: check something on the computer (disk, memory, files), read or search email, "
             "see the calendar, add a single event, turn a device on or off, play music, send one short message the user dictated, "
             "look up one fact, today's weather or a price, open a website, or a follow-up like 'yes do it'.",
    "deep": "Needs planning or judgment across several steps or sources: research and compare options, find the best or cheapest something, "
            "plan a trip or a project, write or rewrite a document or email from scratch, analyze or summarize files or data, "
            "organize or clean up many files, debug or build something, or anything with several parts.",
}
EFFORT_Q = {"type": "choice", "instructions": "How much thinking does this task need?", "criteria": EFFORTS}
