"""What kind of help a task needs, asked after task routing.
Short criteria preserve every category within Laya's 192-token question budget.
Keep Bridge and training identical; changing these requires retraining unified checkpoints.
"""
NEEDS = {
    "browser": "Operate websites: click, sign in, fill forms, buy, book, or change settings.",
    "search": "Read web information: current facts, news, prices, reviews, comparisons, or research.",
    "email_calendar": "Use personal email or calendar: messages, meetings, availability, invitations.",
    "apps": "Apps: post existing media, tasks, notes, messages, music, smart devices, cloud files.",
    "computer": "Find or manage local files and folders; operate software, terminals, hardware, or system settings.",
    "create": "Make or edit media, code, apps, or websites. Excludes posting existing content.",
    "memory": "Remember personal facts and preferences, not documents stored on disk.",
    "other": "Planning, calculations, conversions, ideas, or unclear tasks outside the other categories.",
}
NEED_Q = {"type": "choice", "instructions": "What kind of help does this task need?", "criteria": NEEDS}
