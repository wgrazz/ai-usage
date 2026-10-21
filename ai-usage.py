#!/usr/bin/env python3
"""AI usage dashboard: mines local Claude Code + Codex logs into a daily burn report.

Usage: python3 ai-usage.py [days] [repo ...]   (default: 14 days, the current directory)

Read-only. Data sources:
  ~/.claude/projects/*/*.jsonl   (Claude Code transcripts, incl. claude-mem observer)
  ~/.codex/sessions/**/*.jsonl   (Codex CLI rollouts)
  git log of each repo           (commits and lines added, attributed by Co-Authored-By)
"""
import json, glob, os, sys, collections, datetime, subprocess

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 14
CUTOFF = (datetime.date.today() - datetime.timedelta(days=DAYS)).isoformat()

REPOS = sys.argv[2:] or ["."]

# $/Mtok input, output — editable estimates, checked against Anthropic pricing Aug 2026.
# Cache read billed at 10% of input, cache write at 125% (Anthropic convention).
PRICES = {
    "claude-fable-5": (10, 50),
    "claude-opus": (5, 25),
    "claude-sonnet-5": (3, 15),
    "claude-sonnet": (3, 15),
    "claude-haiku": (1, 5),
}

def price_for(model):
    for prefix, p in PRICES.items():
        if model.startswith(prefix):
            return p
    return (5, 25)

def day_of(ts):
    return ts[:10]

# ---- Claude ----
claude = collections.defaultdict(lambda: collections.defaultdict(float))  # day -> metrics
model_toks = collections.Counter()
limit_hits = []          # (datetime, lane)
bins = collections.defaultdict(set)  # day -> {(bin, file)} for session-weighted hours

for f in glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")):
    lane = "observer" if "observ" in f else "main"
    try:
        fh = open(f, errors="replace")
    except OSError:
        continue
    for line in fh:
        if '"timestamp"' not in line:
            continue
        try:
            r = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        ts = r.get("timestamp", "")
        if not ts or day_of(ts) < CUTOFF:
            continue
        d = day_of(ts)
        m = r.get("message") or {}
        if isinstance(m, dict):
            u = m.get("usage")
            if u:
                inp, out = u.get("input_tokens", 0), u.get("output_tokens", 0)
                cr, cw = u.get("cache_read_input_tokens", 0), u.get("cache_creation_input_tokens", 0)
                claude[d][lane + "_in"] += inp
                claude[d][lane + "_out"] += out
                claude[d][lane + "_cr"] += cr
                claude[d][lane + "_cw"] += cw
                model = m.get("model", "?")
                model_toks[model] += out
                pi, po = price_for(model)
                claude[d]["cost"] += (inp * pi + out * po + cr * pi * 0.1 + cw * pi * 1.25) / 1e6
            if lane == "main":
                hh, mm = ts[11:13], ts[14:16]
                bins[d].add((int(hh) * 12 + int(mm) // 5, f))
        content = str(m.get("content", ""))[:300]
        if "hit your session limit" in content:
            limit_hits.append((ts[:16], lane))

# cluster limit hits into episodes (>90 min apart), main lane only
episodes = collections.Counter()
last = None
for ts, lane in sorted(set(h for h in limit_hits if h[1] == "main")):
    t = datetime.datetime.fromisoformat(ts)
    if last is None or (t - last).total_seconds() > 5400:
        episodes[ts[:10]] += 1
    last = t

# ---- Codex ----
codex = collections.defaultdict(lambda: [0, 0, 0, 0])  # day -> [in, cached, out, sessions]
for f in glob.glob(os.path.expanduser("~/.codex/sessions/*/*/*/*.jsonl")):
    day, final = None, None
    try:
        fh = open(f, errors="replace")
    except OSError:
        continue
    for line in fh:
        if '"total_token_usage"' not in line:
            if day is None and '"timestamp"' in line:
                try:
                    day = day_of(json.loads(line).get("timestamp", ""))
                except (json.JSONDecodeError, ValueError):
                    pass
            continue
        try:
            tc = json.loads(line)["payload"]["info"]["total_token_usage"]
            final = tc
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    if day and day >= CUTOFF and final:
        c = codex[day]
        c[0] += final.get("input_tokens", 0)
        c[1] += final.get("cached_input_tokens", 0)
        c[2] += final.get("output_tokens", 0)
        c[3] += 1

# ---- Git output: commits + line deltas per day, attributed by Co-Authored-By ----
commits = collections.defaultdict(lambda: collections.Counter())  # day -> counters
agent_commits = collections.Counter()
for repo in REPOS:
    path = repo
    if not os.path.isdir(os.path.join(path, ".git")):
        print(f"skipping {repo}: not a git repo", file=sys.stderr)
        continue
    try:
        out = subprocess.run(
            ["git", "-C", path, "log", f"--since={DAYS} days ago", "--numstat",
             "--pretty=@@%ad|%(trailers:key=Co-Authored-By,valueonly,separator=;)", "--date=format:%Y-%m-%d"],
            capture_output=True, text=True, timeout=30).stdout
    except (subprocess.SubprocessError, OSError):
        continue
    day = agent = None
    for line in out.splitlines():
        if line.startswith("@@"):
            day, trailers = line[2:].split("|", 1)
            t = trailers.lower()
            agent = ("claude" if "claude" in t else "cursor" if "cursor" in t
                     else "codex" if "codex" in t or "openai" in t else "human")
            commits[day]["commits"] += 1
            agent_commits[agent] += 1
        elif day and line.strip() and line[0].isdigit():
            add = line.split("\t")[0]
            if add.isdigit():
                commits[day]["loc"] += int(add)

# ---- Report ----
alldays = sorted(set(claude) | set(codex) | set(commits))
W = "{:<11}{:>6}{:>9}{:>9}{:>9}{:>7}{:>6}{:>9}{:>10}{:>6}{:>6}{:>8}"
print(W.format("date", "hrs", "cl_out", "obs_out", "cl_cache", "$API", "caps", "cx_out", "cx_in", "cx_n", "cmts", "loc+"))
tot = collections.Counter()
for d in alldays:
    c, x, g = claude[d], codex[d], commits[d]
    hrs = len(bins[d]) * 5 / 60
    print(W.format(d, f"{hrs:.1f}", f"{c['main_out']/1e3:,.0f}k", f"{c['observer_out']/1e3:,.0f}k",
                   f"{(c['main_cr']+c['observer_cr'])/1e6:,.0f}M", f"{c['cost']:,.0f}",
                   episodes[d] or "", f"{x[2]/1e3:,.0f}k", f"{x[0]/1e3:,.0f}k", x[3] or "",
                   g["commits"] or "", f"{g['loc']:,}" if g["loc"] else ""))
    tot["hrs"] += hrs; tot["cost"] += c["cost"]; tot["caps"] += episodes[d]
    tot["cl_out"] += c["main_out"] + c["observer_out"]; tot["obs_out"] += c["observer_out"]
    tot["cx_out"] += x[2]; tot["commits"] += g["commits"]; tot["loc"] += g["loc"]

n = max(len(alldays), 1)
print(f"\n{DAYS}-day totals: {tot['hrs']:.0f} session-hrs | claude out {tot['cl_out']/1e6:.1f}M "
      f"(observer {tot['obs_out']/1e6:.1f}M = {tot['obs_out']/max(tot['cl_out'],1)*100:.0f}%) | "
      f"codex out {tot['cx_out']/1e6:.1f}M | window caps hit {tot['caps']}")
print(f"API-equivalent: ${tot['cost']:,.0f} over {n} active days -> ~${tot['cost']/n*30:,.0f}/month pace")
if tot["commits"]:
    print(f"shipped: {tot['commits']} commits, {tot['loc']:,} lines added -> "
          f"${tot['cost']/tot['commits']:,.2f}/commit, "
          f"{(tot['cl_out']+tot['cx_out'])/tot['commits']/1e3:,.0f}k out-tokens/commit")
    print("commits by agent: " + ", ".join(f"{a} {c}" for a, c in agent_commits.most_common()))
print("\nclaude output tokens by model:")
for m, t in model_toks.most_common(6):
    print(f"  {m:<28}{t/1e3:>10,.0f}k")
