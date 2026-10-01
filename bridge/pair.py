"""Print a one-time pairing code for a new phone, or manage paired devices.

  pair.py              new 6-digit code, valid 10 minutes, single use
  pair.py list         show paired devices
  pair.py revoke <id>  unpair a device
"""
import sys

from store import Store

s = Store()
if len(sys.argv) > 1 and sys.argv[1] == "list":
    for d in s.list_devices():
        print(d["id"], d["name"])
elif len(sys.argv) > 2 and sys.argv[1] == "revoke":
    s.revoke_device(sys.argv[2])
    print("revoked", sys.argv[2])
else:
    print(f"Pairing code: {s.new_pairing_code()}  (valid 10 minutes, single use)")
