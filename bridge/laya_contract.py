"""Versioned question contract shared by unified training and Bridge inference."""
import hashlib
import json

from router_spec import QUESTION, state
from effort_spec import EFFORT_Q
from need_spec import NEED_Q
from followup_spec import FOLLOWUP_Q, followup_state

QUESTIONS = {"route": QUESTION, "effort": EFFORT_Q, "need": NEED_Q, "followup": FOLLOWUP_Q}


def schema_hash(name):
    return hashlib.sha256(json.dumps(QUESTIONS[name], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def ordered_schema_hash(name):
    payload = {"question":QUESTIONS[name],"criteria_order":list(QUESTIONS[name]["criteria"])}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def example_state(example):
    return (followup_state(example["text"], example.get("last"))
            if example.get("question", "route") == "followup" else state(example["text"]))
