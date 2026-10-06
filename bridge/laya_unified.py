"""One resident Laya with independently calibrated Clara questions.

The decode adapter is tested against the pinned laya==0.3.21 API. It rescales
raw logits before upstream decoding, without changing shared agent state.
Legacy checkpoints keep their original decoding and calibration.
"""
import math

from laya_contract import QUESTIONS, schema_hash, ordered_schema_hash


def agent_class(base_class):
    class ClaraAgent(base_class):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.question_temperatures = self.cfg.get("clara_temperature_by_question", {})
            if not self.question_temperatures:
                return
            trained = set(self.cfg.get("questions") or [])
            if set(self.question_temperatures) != trained or not trained <= set(QUESTIONS):
                raise ValueError("Unified Laya calibration must match the declared trained questions")
            hashes = self.cfg.get("clara_question_hashes", {})
            ordered = self.cfg.get("clara_ordered_question_hashes")
            if ordered is not None and set(ordered) != trained:
                raise ValueError("Ordered question hashes must match the trained questions")
            for name, temp in self.question_temperatures.items():
                if isinstance(temp, bool) or not isinstance(temp, (int, float)) or not math.isfinite(temp) or not .5 <= temp <= 5:
                    raise ValueError(f"Invalid calibration temperature for {name}")
                if hashes.get(name) != schema_hash(name):
                    raise ValueError(f"Unified Laya question changed since training: {name}")
                if ordered is not None and ordered[name] != ordered_schema_hash(name):
                    raise ValueError(f"Unified Laya question or answer order changed: {name}")

        def _decode_answers(self, logits, act, items, ids, internal, offset, lang=None):
            if not self.question_temperatures:
                return super()._decode_answers(logits, act, items, ids, internal, offset, lang)
            from laya.common import QTYPES, temp_bucket
            adjusted = logits.copy()
            for j, name in enumerate(ids):
                if name not in self.question_temperatures:
                    raise ValueError(f"Question {name!r} was not calibrated for this checkpoint")
                k = len(items[j]["markers"])
                qt = QTYPES[internal[name]["t"]]
                current = self.temperature_by_options.get(temp_bucket(qt, k), self.temperature[qt])
                if lang and lang.split("-")[0].lower() in self.lang_temperatures:
                    cfg = self.lang_temperatures[lang.split("-")[0].lower()]
                    current = cfg["temperature_by_options"].get(temp_bucket(qt, k), cfg["temperature"][qt])
                adjusted[offset + j, :k] *= current / self.question_temperatures[name]
            return super()._decode_answers(adjusted, act, items, ids, internal, offset, lang)

    return ClaraAgent


def load_agent(path, device="cpu"):
    import laya
    return agent_class(laya.Agent)(str(path), device=device)
