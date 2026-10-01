"""The one question Clara's front door asks. Training and runtime must use this exact spec."""
ROUTES = {
    "chat": "Casual conversation, greetings, thanks, feelings, jokes, opinions, advice, explanations, math, definitions, or writing help. Answerable from general knowledge with no tools, files, internet, live data, or actions.",
    "task": "Do something now using the computer, files, apps, terminal, web browser, web search, live or current information (weather, news, prices, scores), email or messages, shopping, booking, or installing or running software.",
    "schedule": "Create, change, cancel, or list a reminder, alarm, timer, or a recurring or future scheduled job.",
}
QUESTION = {"type": "choice", "instructions": "Which route should handle this message to a personal assistant?", "criteria": ROUTES}
def state(text):
    return {"message": text}
