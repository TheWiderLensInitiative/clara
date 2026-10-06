"""Clara's front door: decide where a phone message goes.

Cascade: fine-tuned Laya (CPU, ~0.35 s) -> if unsure, Bonsai with a tiny no-thinking prompt (~0.5 s)
-> if the two still disagree, Hermes (the full agent can chat, act, and schedule, so it is the safe default).
"""
import hashlib, json, os, time, urllib.request
from dataclasses import dataclass

from router_spec import QUESTION, ROUTES, state
from effort_spec import EFFORT_Q
from need_spec import NEED_Q
from followup_spec import FOLLOWUP_Q, followup_state
from risk_spec import RISK_Q, risk_state
from laya_unified import load_agent
from legacy_laya_spec import LEGACY_QUESTIONS

from paths import ROUTER_MODEL
LAYA_MODEL = str(ROUTER_MODEL)   # primary checkpoint; unified builds answer all four questions
LLM_URL = os.environ.get("CLARA_LLM_URL", "http://127.0.0.1:8080/v1/chat/completions")
CONFIDENT = float(os.environ.get("CLARA_ROUTER_THRESHOLD", "0.7"))
_SYS = ("Classify the user's message to a personal assistant into exactly one route. Reply with only the route name.\n"
        + "\n".join(f"- {k}: {v}" for k, v in ROUTES.items()))


@dataclass
class Route:
    route: str          # chat | task | schedule
    source: str         # laya | bonsai | fallback
    confidence: float   # legacy: entropy; unified: selected-answer probability
    ms: float
    effort: str = "deep"          # tasks only: quick (thinking off) | deep (thinking on)
    effort_conf: float = 0.0
    need: str = ""                # what kind of help (need_spec), "" when the model wasn't trained for it
    need_conf: float = 0.0        # Laya's probability for that answer


class Router:
    def __init__(self, device="cpu"):
        self.cpu_threads = None
        if str(device) == "cpu":
            import torch
            self.cpu_threads = int(os.environ.get("CLARA_LAYA_THREADS", "8"))   # 8 of 16: ~350 ms vs ~550 ms at 4, identical answers
            if self.cpu_threads < 1:
                raise ValueError("CLARA_LAYA_THREADS must be positive")
            torch.set_num_threads(self.cpu_threads)
        model = LAYA_MODEL
        if not (ROUTER_MODEL / "model.safetensors").exists():
            # laya-for-clara wasn't downloaded: the base model still routes well; quick/deep is less accurate
            print(f"router: {LAYA_MODEL} not found, using base Laya (convaiinnovations/laya)", flush=True)
            model = "convaiinnovations/laya"
        self.agent = load_agent(model, device=device)
        def fingerprint(name):
            path = ROUTER_MODEL / name
            if not path.is_file():
                return None
            with path.open("rb") as handle:
                return hashlib.file_digest(handle,"sha256").hexdigest()
        self.weights_sha256 = fingerprint("model.safetensors")
        self.configuration_sha256 = fingerprint("rl_agent_config.json")
        self.unified = bool(self.agent.cfg.get("clara_temperature_by_question"))
        # Calibration and the exact question wording belong to the checkpoint.
        self.effort_question = EFFORT_Q if self.unified else LEGACY_QUESTIONS["effort"]
        self.need_question = NEED_Q if self.unified else LEGACY_QUESTIONS["need"]
        self.followup_question = FOLLOWUP_Q if self.unified else LEGACY_QUESTIONS["followup"]
        self.route_threshold = (float(os.environ.get("CLARA_ROUTER_THRESHOLD", self.agent.cfg.get("clara_route_threshold", .9)))
                                if self.unified else CONFIDENT)
        self.need_agent, self.knows_need = None, False
        self.knows_risk = self.unified and "risk" in set(self.agent.cfg.get("questions") or [])
        if {"route", "effort", "need", "followup"} <= set(self.agent.cfg.get("questions") or []):
            # A unified checkpoint supplies every decision from one resident model.
            self.need_agent, self.knows_need = self.agent, True
        # Older primary checkpoints use the app's existing fallback rules for
        # untrained questions. Never load a second model to add capabilities.

    def diagnostics(self):
        """Non-sensitive runtime identity for deployment checks and /v1/health."""
        return {"model": self.agent.cfg.get("model_name", "laya"),
                "weights_sha256": self.weights_sha256,
                "configuration_sha256": self.configuration_sha256,
                "resident_models": 1 + int(self.need_agent is not None and self.need_agent is not self.agent),
                "questions": sorted({"route", "effort"} | ({"need", "followup"} if self.knows_need else set())
                                    | ({"risk"} if self.knows_risk else set())),
                "unified_calibration": self.unified,
                "cpu_threads": self.cpu_threads,
                "route_confidence_metric": "selected_probability" if self.unified else "normalized_entropy",
                "route_threshold": self.route_threshold}

    def _bonsai(self, text):
        body = {"messages": [{"role": "system", "content": _SYS}, {"role": "user", "content": text}],
                "max_tokens": 5, "temperature": 0, "chat_template_kwargs": {"enable_thinking": False}, "id_slot": 1}   # slot 1: keep the agent slot warm
        req = urllib.request.Request(LLM_URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
        out = json.load(urllib.request.urlopen(req, timeout=30))["choices"][0]["message"]["content"]
        word = out.strip().lower().strip(".")
        return word if word in ROUTES else None

    def effort(self, text):
        """quick vs deep for a task, with Laya's confidence."""
        a = self.agent.predict(state(text), {"effort": self.effort_question})["answers"]["effort"]
        # Bridge applies its quick-mode threshold to P(quick), not normalized entropy.
        return a["choice"], float((a.get("probabilities") or {}).get("quick", 0.0))

    def risk(self, control, site="", page="", dialog=""):
        """Second opinion on a click: (choice, P(commits)), or (None, 0) when the model wasn't trained for it."""
        if not self.knows_risk:
            return None, 0.0
        a = self.agent.predict(risk_state(control, site, page, dialog), {"risk": RISK_Q})["answers"]["risk"]
        return a["choice"], float((a.get("probabilities") or {}).get("commits", 0.0))

    def followup(self, text, last_reply):
        """Does this continue Clara's last task? (choice, P(continue)); unknown on older checkpoints."""
        if not self.knows_need:
            return None, 0.0
        a = self.need_agent.predict(followup_state(text, last_reply), {"followup": self.followup_question})["answers"]["followup"]
        return a["choice"], float((a.get("probabilities") or {}).get("continue", 0.0))

    def route(self, text) -> Route:
        t0 = time.perf_counter()
        ans = self.agent.predict(state(text), {"route": QUESTION})["answers"]["route"]
        laya_route = ans["choice"]
        conf = (float((ans.get("probabilities") or {}).get(laya_route, 0.0))
                if self.unified else float(ans.get("confidence", 0.0)))
        if conf >= self.route_threshold:
            return self._with_need(Route(laya_route, "laya", conf, (time.perf_counter() - t0) * 1000), text, t0)
        try:
            second = self._bonsai(text)
        except Exception:
            second = None
        if second == laya_route or (second and second != "chat" and laya_route == "chat"):
            # agreement, or Bonsai says it needs tools where Laya said chat: take the non-chat answer
            chosen, source = second, "bonsai"
        else:
            chosen, source = "task", "fallback"   # disagreement or no answer: the full agent is the safe choice
        return self._with_need(Route(chosen, source, conf, (time.perf_counter() - t0) * 1000), text, t0)

    def _with_need(self, r, text, t0):
        """Tasks only: what kind of help (a second ~0.3 s pass; asking both at once isn't faster, and chat stays quick)."""
        if self.knows_need and r.route == "task":
            a = self.need_agent.predict(state(text), {"need": self.need_question})["answers"]["need"]
            r.need = a["choice"]
            r.need_conf = float((a.get("probabilities") or {}).get(r.need, 0.0))
            r.ms = (time.perf_counter() - t0) * 1000
        return r
