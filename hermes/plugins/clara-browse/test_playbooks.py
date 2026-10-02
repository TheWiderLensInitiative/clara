"""Checks for browser playbooks. Run: python test_playbooks.py"""
import importlib.util
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
pkg = types.ModuleType("clara_browse_test")
pkg.__path__ = [HERE]
sys.modules["clara_browse_test"] = pkg
for name in ("actions", "playbooks"):
    spec = importlib.util.spec_from_file_location(f"clara_browse_test.{name}", os.path.join(HERE, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    setattr(pkg, name, module)
pb = pkg.playbooks

CASES = []


def check(name, got, want):
    CASES.append((name, got, want))


PATH = os.path.join(tempfile.mkdtemp(), "browser-playbooks.json")
snap = ('- button "Create group" [ref=e28]\n- textbox "Group name" [ref=e40]\n- slider "Who can post, " [ref=e92]: 3\n'
        '- combobox "Language" [ref=e5]: English\n- button "Next" [ref=e36]')
goal = 'Create a Google Group named "Clara Support" with the email clara-support'
steps = [
    pb.step({"action": "open", "url": "https://groups.google.com/my-groups?authuser=0&token=secret"}, ""),
    pb.step({"action": "click", "ref": "@e28"}, snap),
    pb.step({"action": "fill", "ref": "@e40", "text": "Clara Support"}, snap),
    pb.step({"action": "set", "ref": "@e92", "value": "Anyone on the web"}, snap, result={"success": True, "value": "Anyone on the web"}),
    pb.step({"action": "select", "ref": "@e5", "value": "Spanish"}, snap, result={"success": True}),
    pb.step({"action": "click", "ref": "@e36"}, snap, result={"success": False, "error": "covered"}),   # failed: not saved
    pb.step({"action": "wait"}, snap),                                                                   # not worth saving
]
check("query stripped from urls", steps[0], {"do": "open", "url": "https://groups.google.com/my-groups"})
check("typed text never saved", "Clara Support" in str(steps[2]), False)
check("slider setting saved", steps[3]["value"], "Anyone on the web")
check("failed and wait steps skipped", steps[5:], [None, None])
check("describe fill", pb.describe(steps[2]), 'fill textbox "Group name" (with what this task needs)')
check("describe set", pb.describe(steps[3]), 'set slider "Who can post" to Anyone on the web')

saved = pb.save(goal, steps, path=PATH)
check("saved under the site", saved["host"], "groups.google.com")
check("too short not saved", pb.save("look at a page", [steps[0]], path=PATH), None)
# Different names and wording still match; an unrelated goal doesn't.
check("similar goal matches", (pb.find('create a google group named "Beta Testers" with email beta', path=PATH) or {}).get("host"), "groups.google.com")
check("other site skipped", pb.find("create a google group", start_url="https://example.com", path=PATH), None)
check("unrelated goal skipped", pb.find("check the weather in Boston tomorrow", path=PATH), None)

book = pb.find(goal, path=PATH)
h = pb.hint(book, 1, snap)
check("hint marks next step", "→ next 2. click button \"Create group\"" in h, True)
check("hint marks done steps", "✓ 1. open https://groups.google.com/my-groups" in h, True)
changed = pb.hint(book, 1, '- button "New group" [ref=e2]')
check("site change noticed", "isn't on this page right now" in changed, True)
check("same step", pb.same(pb.step({"action": "click", "ref": "@e28"}, snap), book["steps"][1]), True)

# A newer success replaces the old path; two failures in a row drop it.
newer = pb.save(goal, steps[:2] + [steps[3]], path=PATH, replaces=book)
check("replaced, not duplicated", len(pb.load(PATH)), 1)
check("uses counted", newer["uses"], 2)
pb.failed(newer, path=PATH)
check("one failure keeps it", len(pb.load(PATH)), 1)
pb.failed(newer, path=PATH)
check("two failures drop it", pb.load(PATH), [])
check("missing file is empty", pb.load(PATH + ".none"), [])

# The live run's wandering (2026-10-02): open, select, then click "help" -> back to tab t1, four times, then select again.
o = {"do": "open", "url": "https://shop.example/checkout"}; sel = {"do": "select", "role": "combobox", "name": "Country", "value": "Canada"}
helpc = {"do": "click", "role": "link", "name": "Open help in new tab"}; back = {"do": "tab"}
check("tidy drops detours and repeats", pb.tidy([o, sel] + [helpc, back] * 4 + [sel]), [o, sel])
check("tidy keeps a real path", pb.tidy([o, helpc, sel]), [o, helpc, sel])

cv = pb.step({"action": "click_at", "x": 83.4, "y": 478.0, "_target": {"role": "", "name": "", "tag": "canvas"}}, "")
check("unnamed spot kept as a rough hint", pb.describe(cv), "click the canvas at about x=83, y=478 on the grid")
check("nothing under the spot not saved", pb.step({"action": "click_at", "x": 1, "y": 1, "_target": {}}, ""), None)

fails = 0
for name, got, want in CASES:
    if got != want:
        fails += 1
        print(f"FAIL {name}: got {got!r}, want {want!r}")
print(f"{len(CASES) - fails}/{len(CASES)} passed")
sys.exit(1 if fails else 0)
