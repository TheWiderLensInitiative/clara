"""Checks for Clara's browser decisions. Run: python test_actions.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import actions

CASES = []


def check(name, got, want):
    CASES.append((name, got, want))


check("public", actions.blocked_url_reason("https://example.com/search?q=1"), None)
check("adds https", actions.blocked_url_reason("example.com"), None)
check("localhost", actions.blocked_url_reason("http://localhost:8700") is not None, True)
check("loopback", actions.blocked_url_reason("http://127.0.0.1/") is not None, True)
check("lan", actions.blocked_url_reason("http://192.168.1.20/") is not None, True)
check("metadata", actions.blocked_url_reason("http://169.254.169.254/") is not None, True)
check("file", actions.blocked_url_reason("file:///etc/passwd") is not None, True)
check("userinfo", actions.blocked_url_reason("https://user:pw@example.com") is not None, True)

click = actions.parse_action('Sure.\n```json\n{"action":"click","ref":"e12"}\n```')
check("click ref", click, {"action": "click", "ref": "@e12"})
check("done", actions.parse_action('{"action":"done","summary":"Found the price: $12"}')["summary"], "Found the price: $12")
try:
    actions.parse_action("I don't know")
    check("rejects prose", False, True)
except ValueError:
    check("rejects prose", True, True)

snap = '@e2 [input type="password"] "Password"\n@e3 [button] "Buy now"'
check("password veto", actions.veto({"action": "fill", "ref": "@e2", "text": "hunter2"}, snap) is not None, True)
check("card veto", actions.veto({"action": "fill", "ref": "@e9", "text": "4111 1111 1111 1111"}, snap) is not None, True)
check("search ok", actions.veto({"action": "fill", "ref": "@e1", "text": "cheap flights"}, '@e1 [input] "Search"'), None)
check("buy needs ok", actions.commit_label({"action": "click", "ref": "@e3"}, snap) is not None, True)
check("find send", actions.commit_label({"action": "find", "text": "Send message"}, "") , "activate control: Send message")
check("plain click", actions.commit_label({"action": "click", "ref": "@e1"}, '@e1 [link] "Pricing"'), None)
check("captcha", actions.looks_like_human_check("please verify you are human"), True)
check("google block", actions.signin_blocked("Couldn't sign you in. Try using a different browser"), True)
check("same", actions.same_step({"action": "click", "ref": "@e1"}, {"action": "click", "ref": "@e1"}), True)
check("not same", actions.same_step({"action": "click", "ref": "@e1"}, {"action": "click", "ref": "@e2"}), False)

real = '- button "Buy now" [ref=e3]\n- slider "Volume" [ref=e12]: 10'
check("ref= line", "Buy now" in actions._line(real, "@e3"), True)
check("ref= not a prefix", actions._line(real, "@e1"), "")
check("slider center", actions.box_center({"x": 10, "y": 20, "width": 100, "height": 8}), (60.0, 24.0))
check("empty box", actions.box_center({"x": 0, "y": 0, "width": 0, "height": 4}), None)
tap = actions.tap_events(60, 24)
check("tap ends up", [e["eventType"] for e in tap], ["mouseMoved", "mouseReleased", "mousePressed", "mouseReleased"])
check("tap point", (tap[-1]["x"], tap[-1]["y"], tap[-1]["button"]), (60, 24, "left"))

fails = [c for c in CASES if c[1] != c[2]]
for name, got, want in fails:
    print(f"FAIL {name}: got {got!r}, expected {want!r}")
print(f"{len(CASES) - len(fails)}/{len(CASES)} passed")
sys.exit(1 if fails else 0)
