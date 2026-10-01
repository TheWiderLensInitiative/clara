"""Rewrite SVG path data so Android's VectorDrawable parser reads it exactly: every number separated,
and arc flags (which SVG lets you glue together, e.g. 'a1 1 0 00-4 2') split into separate tokens."""
import re
NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
ARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}

def normalize(d: str) -> str:
    out, i, cmd = [], 0, None
    while i < len(d):
        c = d[i]
        if c.isalpha():
            cmd = c; out.append(c); i += 1
            if cmd.upper() == "Z":
                continue
            n, k = ARGS[cmd.upper()], 0
            while True:   # read argument groups for this command (implicit repeats allowed)
                j = i
                while j < len(d) and d[j] in " ,\t\n": j += 1
                if j >= len(d) or d[j].isalpha(): i = j; break
                for a in range(n):
                    while i < len(d) and d[i] in " ,\t\n": i += 1
                    if cmd.upper() == "A" and a in (3, 4):   # flags: exactly one char, 0 or 1
                        out.append(d[i]); i += 1
                    else:
                        m = NUM.match(d, i); out.append(m.group(0)); i = m.end()
                k += 1
        else:
            i += 1
    s = " ".join(out)
    return re.sub(r" (?=[A-Za-z])|(?<=[A-Za-z]) ", lambda m: " ", s)

if __name__ == "__main__":
    print(normalize("M20.317 4.37a19.791 19.791 0 00-4.885-1.515.074.074 0 00-.079.037z"))
