"""One full scan with callbacks - shows the multi-market task mix."""
import time
import scanner as scanner_mod

logs = []
watches = []
signals = []


def on_log(t):
    logs.append(str(t))


def on_watch(row):
    watches.append(row)


def on_signal(sig, tg):
    signals.append(sig)


s = scanner_mod.Scanner(on_log=on_log, on_watch=on_watch,
                        on_signal=on_signal)
s.refresh_context(force=True)
s.run_scan()

print("\n--- session / class lines ---")
for line in logs:
    if any(k in line for k in ("[forex]", "[metal]", "[stock]", "scanning",
                               "scan done", "benchmark")):
        print(" ", line)

by_mkt = {}
for w in watches:
    by_mkt.setdefault(w.get("mkt", "crypto"), []).append(w)
print("--- watch rows by market ---")
for m, rows in sorted(by_mkt.items()):
    top = sorted(rows, key=lambda r: -r["score"])[:4]
    print(f"  {m}: {len(rows)} rows | " +
          ", ".join(f"{r['sym']} {r['side']} {r['score']} "
                    f"({r['status'][:26]})" for r in top))

print(f"--- signals: {len(signals)} ---")
print(f"--- stats: {s.stats}")
