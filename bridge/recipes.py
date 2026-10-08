"""Recipes: multi-step jobs written down once, so Clara follows them instead of improvising.

A recipe is a list of steps, each finished by a tool (or by the user answering). When a request matches a recipe, the
Bridge tells Clara which steps are done and the one to do now, ticks steps off from the tools that actually ran (never
from what she says), and keeps the place between messages: a step that asks the user ("which one?") stops the run,
and their reply continues at the next step instead of starting over.

Built-in recipes live in bridge/recipes/*.json. Learned ones are saved from successful multi-step tasks (the order of
tools that ran) in DATA/recipes/learned/; once a learned recipe has worked twice, similar requests follow it.
"""
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import paths

BUILTIN = Path(__file__).resolve().parent / "recipes"
LEARNED = paths.DATA / "recipes" / "learned"
STALE = 3 * 3600            # a recipe in progress is forgotten after 3 hours without a step
TRUST_AFTER = 2             # a learned recipe is followed automatically after it worked this many times
MIN_TOOLS = 3               # tasks with fewer distinct tools aren't worth a recipe
IGNORED_TOOLS = {"", "memory", "session_search", "list_connections", "skills_list", "skill_view", "todo", "browser_snapshot",
                 "browser_vision", "vision_analyze"}   # bookkeeping and looking, not steps of a job
WORD = re.compile(r"[a-z0-9']+")
STOP = set("a an the to of for and or in on at my me i you it is be can please could would will with from this that "
           "get find buy some one".split())


@dataclass
class Step:
    id: str
    do: str                       # what Clara does in this step, in plain words
    tool: str = ""                # the tool whose use finishes it ("" with ask=True: the user's answer finishes it)
    ask: bool = False             # this step asks the user and waits

    @staticmethod
    def of(d):
        return Step(str(d["id"]), str(d["do"]), str(d.get("tool") or ""), bool(d.get("ask")))


@dataclass
class Recipe:
    name: str
    title: str
    steps: list
    triggers: list = field(default_factory=list)   # regexes on the user's message
    examples: list = field(default_factory=list)   # requests it worked for (learned recipes match on these)
    wins: int = 0
    learned: bool = False
    needs: list = field(default_factory=list)      # connectors that must be connected (e.g. "link")

    @staticmethod
    def load(path: Path, learned=False):
        d = json.loads(path.read_text())
        return Recipe(d["name"], d["title"], [Step.of(s) for s in d["steps"]], d.get("triggers", []), d.get("examples", []),
                      int(d.get("wins", 0)), learned, d.get("needs", []))

    def to_json(self):
        return {"name": self.name, "title": self.title, "triggers": self.triggers, "examples": self.examples[-8:],
                "wins": self.wins, "needs": self.needs,
                "steps": [{"id": s.id, "do": s.do, **({"tool": s.tool} if s.tool else {}), **({"ask": True} if s.ask else {})}
                          for s in self.steps]}


def all_recipes() -> list:
    out = [Recipe.load(p) for p in sorted(BUILTIN.glob("*.json"))]
    if LEARNED.exists():
        out += [Recipe.load(p, learned=True) for p in sorted(LEARNED.glob("*.json"))]
    return out


def get(name):
    return next((r for r in all_recipes() if r.name == name), None)


def _words(text):
    return {w for w in WORD.findall(text.lower()) if w not in STOP and len(w) > 2}


def _similar(a, b) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def match(text: str, connected=()) -> Recipe | None:
    """The recipe for this request: a built-in one whose trigger matches, or a trusted learned one that worked for a
    very similar request before."""
    for r in all_recipes():
        if r.learned or any(n not in connected for n in r.needs):
            continue
        if any(re.search(t, text, re.I) for t in r.triggers):
            return r
    best, score = None, 0.0
    for r in all_recipes():
        if not r.learned or r.wins < TRUST_AFTER or any(n not in connected for n in r.needs):
            continue
        s = max((_similar(text, e) for e in r.examples), default=0.0)
        if s > score:
            best, score = r, s
    return best if score >= 0.6 else None


# --- progress, kept per conversation ----------------------------------------------------------------------------
def start(recipe: Recipe, request: str) -> dict:
    return {"name": recipe.name, "done": [], "request": request[:500], "started": time.time(), "touched": time.time(),
            "waiting": False}


def fresh(state) -> bool:
    return bool(state) and time.time() - state.get("touched", 0) < STALE


def current(recipe: Recipe, state: dict):
    return next((s for s in recipe.steps if s.id not in state["done"]), None)


def instructions(recipe: Recipe, state: dict) -> str:
    """What Clara is told: the steps with ✓ for the finished ones, and the one to do now."""
    now = current(recipe, state)
    lines = [f"{'✓' if s.id in state['done'] else '→' if s is now else ' '} {i + 1}. {s.do}"
             for i, s in enumerate(recipe.steps)]
    rule = ("Do the step marked → now, then carry on in order. Never redo a ✓ step and never skip ahead. "
            "If a step says to ask the user, ask in one short message (numbered choices when there are options) and stop "
            "there: their reply continues the recipe.")
    return f" You're following the recipe “{recipe.title}” for this request: {state['request']!r}.\n" + "\n".join(lines) + "\n" + rule


def advance(recipe: Recipe, state: dict, tools_in_order: list, answered: bool, completed: bool = False) -> dict:
    """Tick steps off from what actually happened: the user's reply finishes a waiting ask step; each later step is
    finished when its tool ran (in order). An ask step that's reached ends the run and waits."""
    state = {**state, "done": list(state["done"]), "touched": time.time()}
    if answered and state.get("waiting"):
        step = current(recipe, state)
        if step and step.ask:
            state["done"].append(step.id)
        state["waiting"] = False
    tools = list(tools_in_order)
    while True:
        step = current(recipe, state)
        if step is None:
            break
        if step.ask:
            state["waiting"] = True     # she asked (or should have): the user's next message finishes it
            break
        if step.tool and step.tool in tools:
            tools = tools[tools.index(step.tool) + 1:]
            state["done"].append(step.id)
            continue
        if not step.tool and completed:   # a closing "tell the user" step: her reply in this run does it
            state["done"].append(step.id)
            continue
        break
    return state


def finished(recipe: Recipe, state: dict) -> bool:
    return current(recipe, state) is None


# --- learning ---------------------------------------------------------------------------------------------------
def learn(request: str, tools_in_order: list, final: str) -> Recipe | None:
    """After a successful task: save (or strengthen) a recipe from the tools that ran, if it was a real multi-step job."""
    seq = []
    for t in tools_in_order:
        if t not in IGNORED_TOOLS and (not seq or seq[-1] != t):
            seq.append(t)
    if len(set(seq)) < MIN_TOOLS:
        return None
    LEARNED.mkdir(parents=True, exist_ok=True)
    for r in all_recipes():
        if r.learned and [s.tool for s in r.steps] == seq:
            if not any(_similar(request, e) > 0.9 for e in r.examples):
                r.examples.append(request[:300])
            r.wins += 1
            (LEARNED / f"{r.name}.json").write_text(json.dumps(r.to_json(), indent=1))
            return r
    words = [w for w in WORD.findall(request.lower()) if w not in STOP][:5]
    name = "learned-" + ("-".join(words) or "task")[:40] + f"-{int(time.time()) % 100000}"
    r = Recipe(name, request[:80], [Step(f"s{i + 1}", f"Use {t} for this part of the job", t) for i, t in enumerate(seq)],
               examples=[request[:300]], wins=1, learned=True)
    (LEARNED / f"{name}.json").write_text(json.dumps(r.to_json(), indent=1))
    return r
