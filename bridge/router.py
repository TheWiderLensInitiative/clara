"""Clara's front door: decide where a phone message goes.

Cascade: fine-tuned Laya (CPU, ~0.35 s) -> if unsure, Bonsai with a tiny no-thinking prompt (~0.5 s)
-> if the two still disagree, Hermes (the full agent can chat, act, and schedule, so it is the safe default).
"""
import json, os, time, urllib.request
from dataclasses import dataclass

from router_spec import QUESTION, ROUTES, state
from effort_spec import EFFORT_Q

from paths import ROUTER_MODEL
LAYA_MODEL = str(ROUTER_MODEL)   # laya-for-clara: route (chat/task/schedule) + effort (quick/deep)
LLM_URL = os.environ.get("CLARA_LLM_URL", "http://127.0.0.1:8080/v1/chat/completions")
CONFIDENT = float(os.environ.get("CLARA_ROUTER_THRESHOLD", "0.7"))
_SYS = ("Classify the user's message to a personal assistant into exactly one route. Reply with only the route name.\n"
        + "\n".join(f"- {k}: {v}" for k, v in ROUTES.items()))


@dataclass
class Route:
    route: str          # chat | task | schedule
    source: str         # laya | bonsai | fallback
    confidence: float   # Laya's calibrated confidence
    ms: float
    effort: str = "deep"          # tasks only: quick (thinking off) | deep (thinking on)
    effort_conf: float = 0.0


class Router:
    def __init__(self, device="cpu"):
        import laya
        model = LAYA_MODEL
        if not (ROUTER_MODEL / "model.safetensors").exists():
            # laya-for-clara wasn't downloaded: the base model still routes well; quick/deep is less accurate
            print(f"router: {LAYA_MODEL} not found, using base Laya (convaiinnovations/laya)", flush=True)
            model = "convaiinnovations/laya"
        self.agent = laya.Agent(model, device=device)

    def _bonsai(self, text):
        body = {"messages": [{"role": "system", "content": _SYS}, {"role": "user", "content": text}],
                "max_tokens": 5, "temperature": 0, "chat_template_kwargs": {"enable_thinking": False}, "id_slot": 1}   # slot 1: keep the agent slot warm
        req = urllib.request.Request(LLM_URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
        out = json.load(urllib.request.urlopen(req, timeout=30))["choices"][0]["message"]["content"]
        word = out.strip().lower().strip(".")
        return word if word in ROUTES else None

    def effort(self, text):
        """quick vs deep for a task, with Laya's confidence."""
        a = self.agent.predict(state(text), {"effort": EFFORT_Q})["answers"]["effort"]
        # Laya's "confidence" is squeezed near 0.7; her probabilities separate cleanly (quick ≈0.95 vs deep ≤0.09 on the test set)
        return a["choice"], float((a.get("probabilities") or {}).get("quick", 0.0))

    def route(self, text) -> Route:
        t0 = time.perf_counter()
        ans = self.agent.predict(state(text), {"route": QUESTION})["answers"]["route"]
        laya_route, conf = ans["choice"], float(ans.get("confidence", 0.0))
        if conf >= CONFIDENT:
            return Route(laya_route, "laya", conf, (time.perf_counter() - t0) * 1000)
        try:
            second = self._bonsai(text)
        except Exception:
            second = None
        if second == laya_route or (second and second != "chat" and laya_route == "chat"):
            # agreement, or Bonsai says it needs tools where Laya said chat: take the non-chat answer
            chosen, source = second, "bonsai"
        else:
            chosen, source = "task", "fallback"   # disagreement or no answer: the full agent is the safe choice
        return Route(chosen, source, conf, (time.perf_counter() - t0) * 1000)
