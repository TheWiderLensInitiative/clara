"""Scheduling rules for Clara's check-ins and daily note: python test_proactive.py"""
import datetime as dt
import proactive as p

tz = dt.datetime.now().astimezone().tzinfo
D = lambda d, h, m=0: dt.datetime(2026, 9, d, h, m, tzinfo=tz)   # Sep 2026: the 28th is a Monday
ok = fails = 0
def check(name, got, want):
    global ok, fails
    if got == want: ok += 1
    else: fails += 1; print("FAIL", name, "got", got, "want", want)

# quiet hours across midnight and same-day
check("quiet late", p.in_quiet_hours(D(30, 23), "22:00", "07:30"), True)
check("quiet early", p.in_quiet_hours(D(30, 6, 59), "22:00", "07:30"), True)
check("not quiet", p.in_quiet_hours(D(30, 8), "22:00", "07:30"), False)
check("quiet daytime window", p.in_quiet_hours(D(30, 13), "12:00", "14:00"), True)

# daily slot
check("before slot", p.is_due(D(30, 8, 29), "08:30", None), False)
check("at slot", p.is_due(D(30, 8, 30), "08:30", None), True)
check("late but in window", p.is_due(D(30, 11, 0), "08:30", None), True)
check("too late", p.is_due(D(30, 11, 31), "08:30", None), False)
check("already sent today", p.is_due(D(30, 9), "08:30", D(30, 8, 31)), False)
check("sent yesterday", p.is_due(D(30, 9), "08:30", D(29, 8, 31)), True)

# goals
g = {"title": "Run", "checkin": "daily", "checkin_time": "19:00", "done": False, "last_checkin": None}
check("goal daily due", p.goal_due(g, D(30, 19, 5)), True)
check("goal off", p.goal_due(dict(g, checkin="off"), D(30, 19, 5)), False)
check("goal done", p.goal_due(dict(g, done=True), D(30, 19, 5)), False)
check("goal checked in", p.goal_due(dict(g, last_checkin=D(30, 19, 1).timestamp()), D(30, 19, 5)), False)
w = dict(g, checkin="weekly", checkin_day=6)   # Sundays
check("weekly wrong day", p.goal_due(w, D(30, 19, 5)), False)           # Wednesday
check("weekly right day", p.goal_due(w, D(27, 19, 5)), True)            # Sunday the 27th

# Bonsai's JSON
check("parse", p.parse_suggestions('```json\n{"message": "Morning!", "suggestions": ["Remind me at 3", "Plan dinner", "x", "y"]}\n```'),
      ("Morning!", ["Remind me at 3", "Plan dinner", "x"]))
check("parse junk", p.parse_suggestions("sorry"), (None, []))
print(f"{ok} passed, {fails} failed")
check("fresh", p.fresh(["What's using the most memory on my PC?", "Plan dinner"], ["what's using the most memory on my PC"]), ["Plan dinner"])
print("fresh ok" if fails == 0 else "fresh FAILED")

raise SystemExit(1 if fails else 0)
