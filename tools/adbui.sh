# helpers for driving the emulator UI: source this file
A=~/Android/Sdk/platform-tools/adb; E=${E:-emulator-5554}
dump(){ $A -s $E exec-out uiautomator dump /dev/tty 2>/dev/null; }
center(){ set -- $(echo "$1" | grep -oE '[0-9]+' | tail -4 | tr '\n' ' '); [ -n "$1" ] && echo "$(( ($1+$3)/2 )) $(( ($2+$4)/2 ))"; }
tapt(){ local c; c=$(center "$(dump | grep -oE "(text|content-desc)=\"$1\"[^>]*bounds=\"[^\"]*\"" | head -1)"); [ -n "$c" ] && $A -s $E shell input tap $c && return 0; echo "not found: $1"; return 1; }
field(){ local c; c=$(center "$(dump | grep -oE 'class="android.widget.EditText"[^>]*bounds="[^"]*"' | sed -n "${1}p")"); [ -n "$c" ] && $A -s $E shell input tap $c; }
shot(){ $A -s $E exec-out screencap -p > ${SHOTS:-/tmp}/$1.png; }
# unlock the test emulator (PIN 1234): retries until the keyguard is gone
unlock(){ for i in 1 2 3 4 5; do $A -s $E shell input keyevent KEYCODE_WAKEUP; $A -s $E shell input keyevent 82; sleep 1; $A -s $E shell input swipe 540 1900 540 400 200; sleep 1.5; $A -s $E shell input text 1234; $A -s $E shell input keyevent KEYCODE_ENTER; sleep 2; $A -s $E shell dumpsys window 2>/dev/null | grep -q "mDreamingLockscreen=false" && ! $A -s $E shell dumpsys window 2>/dev/null | grep -q "isKeyguardShowing=true\|mShowingLockscreen=true" && return 0; done; return 1; }
