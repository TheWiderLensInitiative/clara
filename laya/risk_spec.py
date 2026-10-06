"""Laya's fifth question: would clicking this control commit something the user should approve first?
A second opinion next to the browser's word list (clara-browse/actions.py COMMIT): it can only ADD an approval,
never remove one. Training and runtime must use this exact spec and state (laya/ keeps an identical copy)."""
RISKS = {   # compact: Laya cuts each option's description at its per-option token budget
    "commits": "Needs the user's OK: buys, pays, sends, posts, deletes, cancels, submits, books, signs up, accepts terms, "
               "saves account changes, or gives final confirmation.",
    "safe": "Just looks or prepares: opens a page, menu or details, steps forward or back before anything is final, "
            "searches, filters, closes, or picks a changeable option.",
}
RISK_Q = {"type": "choice", "instructions": "Should Clara ask the user before clicking this?", "criteria": RISKS}


def risk_state(control, site="", page="", dialog=""):
    """control like 'button "Done"'; page = the page title; dialog = an open dialog's text, if any."""
    return {"control": str(control)[:160], "site": str(site)[:80], "page": str(page)[:160], "dialog": str(dialog)[:240]}
