"""Laya's third question: what kind of help a task needs. Asked together with the route, so it costs no extra call.
The Bridge uses it next to its keyword rules (either one can send a task down a lane), e.g. "browser" -> the fast
website lane and the browser card. Training and runtime must use this exact spec."""
NEEDS = {
    "browser": "Operate a particular website or web app the way a person would: open a site, sign in, click through pages, fill in "
               "a form, book a table or a ticket, order or buy something on a site, post or change settings on a site.",
    "search": "Find information or live facts on the web without operating a site: news, weather, prices, scores, reviews, "
              "comparisons, research, looking something up.",
    "email_calendar": "The user's own email or calendar: read, search, sort, draft or send email, see the schedule, add or move "
                      "a meeting, find free time.",
    "apps": "One of the user's connected apps or devices: music or Spotify, smart lights or thermostat, Notion, Todoist, GitHub, "
            "Slack, Discord, Telegram, Dropbox, Microsoft, posting to social media, uploading to YouTube.",
    "computer": "The user's own computer: files and folders, disk space, installing, running or updating programs, the terminal, "
                "system information.",
    "create": "Make something new: a picture, logo or video, or write code, a script, an app or a website, or fix a bug.",
    "memory": "Remember, forget or recall a fact or preference about the user ('remember that I...', 'don't forget my...').",
    "other": "Anything else a task needs.",
}
NEED_Q = {"type": "choice", "instructions": "What kind of help does this task need?", "criteria": NEEDS}
