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
check("find send", actions.commit_label({"action": "find", "text": "Send message"}, ""), 'click "Send message"')
check("find plain", actions.commit_label({"action": "find", "text": "Pricing"}, ""), None)
# Real Google Groups rows (2026-10-02): wizard steps and settings don't ask; risky buttons do.
gsnap = ('- button "Main menu" [ref=e10]\n- button "Next" [ref=e36]\n- button "Back" [ref=e86]\n'
         '- slider "Who can post, " [ref=e92]: 3\n- option "Anyone on the web" [ref=e100]\n'
         '- button "Send invites" [ref=e7]\n- button "Submit" [ref=e8]\n- link "Post a reply" [ref=e9]\n'
         '- button "Continue" [ref=e11]\n- button "Delete group" [ref=e12]\n- button "Buy now" [ref=e13]\n'
         '- button "Create group" [ref=e28]')
for name, ref in [("next", "@e36"), ("back", "@e86"), ("menu", "@e10"), ("slider", "@e92"), ("option", "@e100")]:
    check(f"{name} free", actions.commit_label({"action": "click", "ref": ref}, gsnap), None)
for label, ref in [("Send invites", "@e7"), ("Submit", "@e8"), ("Post a reply", "@e9"), ("Continue", "@e11"),
                   ("Delete group", "@e12"), ("Buy now", "@e13"), ("Create group", "@e28")]:
    check(f"{label} asks", actions.commit_label({"action": "click", "ref": ref}, gsnap), f'click "{label}"')
check("unknown asks", actions.commit_label({"action": "click", "ref": "@e55"}, gsnap), "click a control I can't identify")
check("enter in search free", actions.commit_label({"action": "press", "key": "Enter"}, '- searchbox "Search" [ref=e1]'), None)
check("enter in form asks", actions.commit_label({"action": "press", "key": "Enter"}, gsnap) is not None, True)
check("tab free", actions.commit_label({"action": "press", "key": "Tab"}, gsnap), None)


class FakeSlider:
    """Google Groups' 'Who can post' slider: four stops, arrow keys move one stop, ends don't wrap."""
    def __init__(self, stops, now, name="Who can post,"):
        self.stops, self.now, self.name, self.keys = stops, now, name, []

    def read(self):
        return {"role": "slider", "name": self.name, "now": str(self.now + 1), "text": self.stops[self.now]}

    def press(self, key):
        self.keys.append(key)
        self.now = max(0, self.now - 1) if key == "ArrowLeft" else min(len(self.stops) - 1, self.now + 1)


STOPS = ["Group owners", "Group managers", "Group members", "Anyone on the web"]
sl = FakeSlider(STOPS, 2)
check("slider by label", actions.set_slider(sl.read, sl.press, "Anyone on the web", "Who can post, "), {"success": True, "value": "Anyone on the web"})
check("slider sweeps left first", sl.keys, ["ArrowLeft", "ArrowLeft", "ArrowLeft", "ArrowRight", "ArrowRight", "ArrowRight"])
sl = FakeSlider(STOPS, 2)
check("slider already there", actions.set_slider(sl.read, sl.press, "group members")["value"], "Group members")
check("slider no keys needed", sl.keys, [])
sl = FakeSlider(STOPS, 3)
check("slider by number", actions.set_slider(sl.read, sl.press, "2")["value"], "Group managers")
sl = FakeSlider(STOPS, 0)
missing = actions.set_slider(sl.read, sl.press, "Friends")
check("slider lists its settings", missing["error"], 'This slider has no setting "Friends". Its settings are: Group owners, Group managers, Group members, Anyone on the web.')
sl = FakeSlider(STOPS, 0, name="Who can view members,")
check("slider focus mismatch", actions.set_slider(sl.read, sl.press, "Group members", "Who can post, ")["success"], False)
check("not a slider", actions.set_slider(lambda: {"role": "button", "name": "Next"}, lambda k: None, "x")["success"], False)
check("parse set", actions.parse_action('{"action":"set","ref":"e92","value":"Anyone on the web"}'), {"action": "set", "ref": "@e92", "value": "Anyone on the web"})
check("set on slider allowed", actions.veto({"action": "set", "ref": "@e92", "value": "x"}, gsnap), None)
check("set on button vetoed", actions.veto({"action": "set", "ref": "@e36", "value": "x"}, gsnap) is not None, True)
check("set needs no approval", actions.commit_label({"action": "set", "ref": "@e92", "value": "x"}, gsnap), None)
# New actions (Antigravity-style): dropdowns, panel scroll, pixel click/drag, tabs.
csnap = gsnap + '\n- combobox "Country" [expanded=false, ref=e3]: United States\n- generic "Results" [ref=e40]'
check("parse select", actions.parse_action('{"action":"select","ref":"e3","value":"Canada"}'), {"action": "select", "ref": "@e3", "value": "Canada"})
check("select on dropdown ok", actions.veto({"action": "select", "ref": "@e3", "value": "Canada"}, csnap), None)
check("select on button vetoed", actions.veto({"action": "select", "ref": "@e36", "value": "x"}, csnap) is not None, True)
check("select needs no approval", actions.commit_label({"action": "select", "ref": "@e3", "value": "Canada"}, csnap), None)
check("parse panel scroll", actions.parse_action('{"action":"scroll","direction":"down","ref":"e40"}'), {"action": "scroll", "direction": "down", "ref": "@e40"})
check("panel scroll missing ref vetoed", actions.veto({"action": "scroll", "direction": "down", "ref": "@e99"}, csnap) is not None, True)
check("parse click_at", actions.parse_action('{"action":"click_at","x":"640","y":300}'), {"action": "click_at", "x": 640.0, "y": 300.0})
for bad in ('{"action":"click_at","x":1200,"y":3}', '{"action":"scroll","direction":"down","x":5,"y":1001}'):
    try:
        actions.parse_action(bad); check("off the 0-1000 grid rejected " + bad, False, True)
    except ValueError:
        check("off the 0-1000 grid rejected " + bad, True, True)
check("scroll at a spot", actions.parse_action('{"action":"scroll","direction":"down","x":120,"y":300}'), {"action": "scroll", "direction": "down", "x": 120.0, "y": 300.0})
check("parse drag", actions.parse_action('{"action":"drag","x":1,"y":2,"to_x":3,"to_y":4}')["to_x"], 3.0)
for bad in ('{"action":"click_at","x":"left","y":1}', '{"action":"drag","x":1,"y":2}', '{"action":"tab","to":"javascript:x"}'):
    try:
        actions.parse_action(bad); check("rejects " + bad, False, True)
    except ValueError:
        check("rejects " + bad, True, True)
check("parse tab", actions.parse_action('{"action":"tab","to":"t2"}'), {"action": "tab", "to": "t2"})
at = lambda target, kind="click_at": {"action": kind, "x": 10.0, "y": 20.0, "to_x": 50.0, "to_y": 20.0, "_target": target}
check("pixel on plain button free", actions.commit_label(at({"role": "button", "name": "Next", "tag": "button"}), ""), None)
check("pixel on buy asks", actions.commit_label(at({"role": "button", "name": "Buy now", "tag": "button"}), ""), 'click "Buy now"')
check("pixel on canvas asks", actions.commit_label(at({"role": "", "name": "", "tag": "canvas"}), "").startswith("click a spot"), True)
check("drag slide-to-pay asks", actions.commit_label(at({"role": "", "name": "Slide to pay", "tag": "div"}, "drag"), ""), 'drag "Slide to pay"')
check("drag captcha vetoed", actions.veto(at({"role": "", "name": "Slide to verify", "tag": "div"}, "drag"), "") is not None, True)
check("drag slider vetoed (use set)", actions.veto(at({"role": "slider", "name": "Volume", "tag": "div"}, "drag"), "") is not None, True)
ev = actions.drag_events(0, 0, 120, 0, steps=4)
check("drag presses, moves, releases", [e["eventType"] for e in ev], ["mouseMoved", "mousePressed"] + ["mouseMoved"] * 4 + ["mouseReleased"])
check("drag ends at target", (ev[-1]["x"], ev[-1]["y"]), (120, 0))
view = actions.page_view('- button "Next" [ref=e1]', "Total: $42.50", [{"tabId": "t1", "title": "Shop", "active": True}, {"tabId": "t2", "title": "Help"}])
check("page view has tabs, controls and text", ("Open tabs: t1" in view, "Controls on the page" in view, "Text on screen:\nTotal: $42.50" in view), (True, True, True))
check("page view hides tabs when one", "Open tabs" in actions.page_view("x", "", [{"tabId": "t1"}]), False)
osnap = ('- combobox "Country" [expanded=false, ref=e3]: United States\n  - option "United States" [selected, ref=e4]\n'
         '  - option "Canada" [ref=e5]\n- link "Help" [ref=e2]')
check("option maps to its dropdown", actions.option_owner(osnap, "@e5"), "@e3")
check("non-option has no owner", actions.option_owner(osnap, "@e2"), "")
check("verdict yes", actions.parse_verdict('```json\n{"verified": true, "reason": "page says PLAY clicked"}\n```')["verified"], True)
check("verdict no", actions.parse_verdict('{"verified": false, "reason": "canvas not clicked"}'), {"verified": False, "reason": "canvas not clicked"})
check("verdict garbage is not verified", actions.parse_verdict("I think so")["verified"], False)
ssnap = '- textbox "Password" [ref=e1]\n- slider "Who can post, " [ref=e2]: 3\n- button "Save changes" [ref=e3]'
check("step: typed text never shown", actions.step_text({"action": "fill", "ref": "@e1", "text": "hunter2"}, ssnap), 'Typed into "Password"')
check("step: slider", actions.step_text({"action": "set", "ref": "@e2", "value": "Anyone on the web"}, ssnap, {"success": True, "value": "Anyone on the web"}), 'Set "Who can post" to Anyone on the web')
check("step: click", actions.step_text({"action": "click", "ref": "@e3"}, ssnap), 'Clicked "Save changes"')
check("step: open", actions.step_text({"action": "open", "url": "https://groups.google.com/my-groups?x=1"}), "Opened groups.google.com")
check("step: failure noted", actions.step_text({"action": "click", "ref": "@e3"}, ssnap, {"success": False, "error": "covered"}), 'Clicked "Save changes" (didn\'t work: covered)')
check("step: pixel", actions.step_text({"action": "click_at", "x": 1, "y": 2, "_target": {"tag": "canvas"}}), 'Clicked "canvas" (by position)')
rsnap = ('- dialog "Delete 3 files?"\n  - button "OK" [ref=e1]\n  - button "Cancel" [ref=e2]\n- button "Done" [ref=e3]\n'
         '- button "Submit" [ref=e4]\n- slider "Volume" [ref=e5]: 3\n- link "Help" [ref=e6]')
check("2nd opinion: plain button", actions.second_opinion_control({"action": "click", "ref": "@e3"}, rsnap), 'button "Done"')
check("2nd opinion: word list already asks", actions.second_opinion_control({"action": "click", "ref": "@e4"}, rsnap), None)
check("2nd opinion: settings never", actions.second_opinion_control({"action": "click", "ref": "@e5"}, rsnap), None)
check("2nd opinion: not a click", actions.second_opinion_control({"action": "scroll", "direction": "down"}, rsnap), None)
check("2nd opinion: find", actions.second_opinion_control({"action": "find", "text": "Looks good"}, ""), 'control "Looks good"')
check("2nd opinion: pixel spot with a name", actions.second_opinion_control({"action": "click_at", "x": 1, "y": 1, "_target": {"role": "button", "name": "Go"}}, ""), 'button "Go"')
check("dialog text", actions.dialog_text(rsnap), "Delete 3 files?")
check("no dialog", actions.dialog_text('- button "Next" [ref=e1]'), "")
check("control old format", actions.control('@e3 [button] "Buy now"'), ("button", "Buy now"))
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
card = "Scoped access New Select the level of access your app needs to Dropbox data. Learn more Image alt"
check("card: page text vs accessible name", actions.same_control("Scoped access\nNew\nSelect the level of access your app needs to Dropbox data. Learn more", card), True)
check("card: a link inside is not the card", actions.same_control("Learn more", card), False)
check("short names must match exactly", actions.same_control("Delete", "Delete account"), False)
check("exact name", actions.same_control(" Next ", "Next"), True)
check("card spots: center first", actions.box_points({"x": 0, "y": 0, "width": 200, "height": 100})[:2], [(100.0, 50.0), (100.0, 25.0)])
check("small control: center only", len(actions.box_points({"x": 0, "y": 0, "width": 20, "height": 20})), 1)
tap = actions.tap_events(60, 24)
check("tap ends up", [e["eventType"] for e in tap], ["mouseMoved", "mouseReleased", "mousePressed", "mouseReleased"])
check("tap point", (tap[-1]["x"], tap[-1]["y"], tap[-1]["button"]), (60, 24, "left"))

fails = [c for c in CASES if c[1] != c[2]]
for name, got, want in fails:
    print(f"FAIL {name}: got {got!r}, expected {want!r}")
print(f"{len(CASES) - len(fails)}/{len(CASES)} passed")
sys.exit(1 if fails else 0)
