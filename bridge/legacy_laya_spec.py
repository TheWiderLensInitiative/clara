"""Original pre-unified input definitions for existing checkpoints.

Preserve these verbatim: legacy weights were trained with these descriptions.
This selects input definitions for one primary model; it never loads a second model.
"""

LEGACY_QUESTIONS = {
    "effort": {
        "type": "choice",
        "instructions": "How much thinking does this task need?",
        "criteria": {
            "quick": "One simple action or lookup with an obvious tool: check something on the computer (disk, memory, files), read or search email, see the calendar, add a single event, turn a device on or off, play music, send one short message the user dictated, look up one fact, today's weather or a price, open a website, or a follow-up like 'yes do it'.",
            "deep": "Needs planning or judgment across several steps or sources: research and compare options, find the best or cheapest something, plan a trip or a project, write or rewrite a document or email from scratch, analyze or summarize files or data, organize or clean up many files, debug or build something, or anything with several parts."
        }
    },
    "need": {
        "type": "choice",
        "instructions": "What kind of help does this task need?",
        "criteria": {
            "browser": "Operate a particular website or web app the way a person would: open a site, sign in, click through pages, fill in a form, book a table or a ticket, order or buy something on a site, post or change settings on a site.",
            "search": "Find information or live facts on the web without operating a site: news, weather, prices, scores, reviews, comparisons, research, looking something up.",
            "email_calendar": "The user's own email or calendar: read, search, sort, draft or send email, see the schedule, add or move a meeting, find free time.",
            "apps": "One of the user's connected apps or devices: music or Spotify, smart lights or thermostat, Notion, Todoist, GitHub, Slack, Discord, Telegram, Dropbox, Microsoft, posting to social media, uploading to YouTube.",
            "computer": "The user's own computer: files and folders, disk space, installing, running or updating programs, the terminal, system information.",
            "create": "Make something new: a picture, logo or video, or write code, a script, an app or a website, or fix a bug.",
            "memory": "Remember, forget or recall a fact or preference about the user ('remember that I...', 'don't forget my...').",
            "other": "Anything else a task needs."
        }
    },
    "followup": {
        "type": "choice",
        "instructions": "Does the user's message continue what Clara just did?",
        "criteria": {
            "continue": "The message continues or answers what Clara just did or said: yes or no to her offer or question, more details, a correction, a change ('make it 7pm instead'), more of the same ('also add...', 'what about tomorrow'), or it refers to her result ('that one', 'send it', 'why did it fail').",
            "new": "A new request on a different subject, or small talk that doesn't need what she just did: thanks, a greeting, a feeling, a joke, an unrelated question."
        }
    }
}
