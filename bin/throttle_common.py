"""Shared collection logic for TA-throttle scripted inputs (cpufreq + thermal throttle)."""
import json
import os
import re
import sys
import time

CPU_DIR = "/sys/devices/system/cpu"
STATE_FILE = "/var/tmp/ta_throttle_state.json"
SAME_CYCLE_SECS = 60

CPU_RE = re.compile(r"^cpu(\d+)$")


def read_file(path):
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return None


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _cpu_index(name):
    m = CPU_RE.match(name)
    return int(m.group(1)) if m else 0


def _read_cpu(name):
    base = os.path.join(CPU_DIR, name)
    rec = {"pkg": read_file(os.path.join(base, "topology", "physical_package_id")) or "0"}
    freq = {}
    for key in ("cur", "min", "max"):
        v = _num(read_file(os.path.join(base, "cpufreq", "scaling_%s_freq" % key)))
        if v is not None:
            freq[key] = v
    if freq:
        rec["freq_khz"] = freq
    gov = read_file(os.path.join(base, "cpufreq", "scaling_governor"))
    if gov:
        rec["governor"] = gov
    t = _num(read_file(os.path.join(base, "thermal_throttle", "package_throttle_count")))
    if t is not None:
        rec["throttle_count"] = int(t)
    return rec


def _load_state():
    try:
        with open(STATE_FILE) as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def _save_state(state):
    try:
        os.makedirs("/var/tmp", exist_ok=True)
        with open(STATE_FILE, "w") as fh:
            json.dump(state, fh)
    except (OSError, TypeError, ValueError):
        pass


def _pkg_key(pkg):
    try:
        return (0, int(pkg))
    except (TypeError, ValueError):
        return (1, 0)


def discover():
    try:
        names = [n for n in os.listdir(CPU_DIR) if CPU_RE.match(n)]
        names.sort(key=_cpu_index)
    except OSError:
        return {"status": "absent", "cpu_count": 0, "governors": {}, "packages": {}}
    if not names:
        return {"status": "absent", "cpu_count": 0, "governors": {}, "packages": {}}
    cpus = {}
    for name in names:
        try:
            cpus[name] = _read_cpu(name)
        except (OSError, ValueError):
            continue
    gov_counts = {}
    cur_freqs = []
    packages = {}
    for name in names:
        rec = cpus.get(name)
        if not rec:
            continue
        gov = rec.get("governor")
        if gov:
            gov_counts[gov] = gov_counts.get(gov, 0) + 1
        cur = (rec.get("freq_khz") or {}).get("cur")
        if cur is not None:
            cur_freqs.append(cur)
        pkg = str(rec.get("pkg") or "0")
        if rec.get("throttle_count") is not None:
            if pkg not in packages or rec["throttle_count"] > packages[pkg]:
                packages[pkg] = rec["throttle_count"]
    state = _load_state()
    last_counts = state.get("pkg")
    if not isinstance(last_counts, dict):
        last_counts = {}
    last_deltas = state.get("deltas")
    last_ts = _num(state.get("ts"))
    same_cycle = isinstance(last_deltas, dict) and last_ts is not None and (time.time() - last_ts) < SAME_CYCLE_SECS
    alarm = False
    deltas = {}
    packages_out = {}
    for pkg in sorted(packages, key=lambda p: _pkg_key(str(p))):
        if same_cycle:
            d = _num(last_deltas.get(pkg))
            delta = max(0, int(d)) if d is not None else 0
        else:
            last = _num(last_counts.get(pkg))
            delta = max(0, int(packages[pkg]) - int(last)) if last is not None else 0
        deltas[pkg] = delta
        if delta > 0:
            alarm = True
        packages_out[pkg] = {"throttle_count": packages[pkg], "new": delta}
    if not same_cycle:
        _save_state({"pkg": {str(k): v for k, v in packages.items()}, "deltas": deltas, "ts": time.time()})
    data = {
        "status": "alarm" if alarm else "ok",
        "cpu_count": len(cpus),
        "governors": gov_counts,
    }
    if cur_freqs:
        data["freq_min_mhz"] = round(min(cur_freqs) / 1000.0, 1)
        data["freq_max_mhz"] = round(max(cur_freqs) / 1000.0, 1)
        data["freq_avg_mhz"] = round(sum(cur_freqs) / float(len(cur_freqs)) / 1000.0, 1)
    data["packages"] = packages_out
    return data


def metrics_payload(data):
    if not isinstance(data, dict):
        data = {}
    payload = {}
    n = _num(data.get("cpu_count"))
    if n is not None:
        payload["cpu_count"] = int(n)
    for key in ("freq_avg_mhz", "freq_max_mhz", "freq_min_mhz"):
        v = _num(data.get(key))
        if v is not None:
            payload[key] = v
    gov = data.get("governors")
    if not isinstance(gov, dict):
        gov = {}
    payload["governor_fixed"] = 1 if len(gov) <= 1 else 0
    pkgs = data.get("packages")
    if not isinstance(pkgs, dict):
        pkgs = {}
    payload["pkg_count"] = len(pkgs)
    for pkg, rec in pkgs.items():
        rec = rec if isinstance(rec, dict) else {}
        key = re.sub(r"[^a-z0-9_]", "_", str(pkg).lower()).strip("_")
        for src, dst in (("throttle_count", "throttle_count"), ("new", "throttle_new")):
            v = _num(rec.get(src))
            if v is not None:
                payload["pkg_%s_%s" % (key, dst)] = int(v)
    return payload


def emit(payload):
    sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
    sys.stdout.flush()


def fail(message):
    sys.stderr.write("TA-throttle collection error: %s\n" % message)
    return 1
