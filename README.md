# ai-usage

How much are your coding agents burning, and what did they ship? One read-only Python script,
no dependencies, that mines the logs Claude Code and Codex already keep on your machine and
lines them up against your git history.

```
$ python3 ai-usage.py 14 . ../other-repo
date         hrs   cl_out  obs_out cl_cache   $API  caps   cx_out     cx_in  cx_n  cmts    loc+
2026-10-08   4.2     312k      61k      41M    118     1     140k    2,310k     3    11   2,904
2026-10-09   6.1     540k      98k      77M    201     2       0k        0k          19   6,112
...

14-day totals: 37 session-hrs | claude out 7.3M (observer 2.4M = 33%) | codex out 4.5M | window caps hit 14
API-equivalent: $1,183 over 17 active days -> ~$2,088/month pace
shipped: 148 commits, 66,792 lines added -> $7.99/commit, 80k out-tokens/commit
commits by agent: claude 91, human 44, cursor 13

claude output tokens by model:
  claude-fable-5-1                 4,210k
  claude-haiku-4-5                 2,402k
```

## Why

Multiple AI coding subscriptions (Claude, Codex, Cursor, Copilot) and a decision about which
to keep paying for. Plans are priced in opaque "usage", so the only honest comparison is
API-equivalent dollars against output you can count: commits and lines. Every change to the
workflow (a cheaper memory model, a trimmed context injection, a consolidated instruction
file) can then be checked against the log instead of vibes.

## Columns

| Column | Meaning |
| --- | --- |
| `hrs` | Session-weighted active hours: 5-minute bins with any Claude activity, per transcript |
| `cl_out` / `obs_out` | Claude output tokens, main sessions / claude-mem observer sessions (transcript dirs containing `observ`) |
| `cl_cache` | Cache-read tokens, all lanes |
| `$API` | What the day would have cost at API prices (`PRICES` dict; cache read 10%, cache write 125% of input) |
| `caps` | Session-window-limit episodes (hits more than 90 min apart count separately) |
| `cx_out` / `cx_in` / `cx_n` | Codex output, input tokens and session count |
| `cmts` / `loc+` | Commits and lines added across the given repos |

Commit attribution reads `Co-Authored-By` trailers: Claude Code and Cursor add one, Codex
doesn't (its commits show as `human`), so per-agent commit credit is fuzzy while token burn is
complete. Cursor is the reverse: commits tracked, tokens not minable locally.

## Install

```
git clone https://github.com/wgrazz/ai-usage
python3 ai-usage/ai-usage.py            # last 14 days, current repo
python3 ai-usage/ai-usage.py 30 . a b   # last 30 days across three repos
```

Python 3.8+, nothing else. Edit `PRICES` when models or prices change.

## Keep a log

Claude Code prunes transcripts after roughly 30 days, so append a nightly report and keep the
numbers from before any experiment as a permanent baseline block:

```
50 23 * * * cd /path/to/repo && echo "===== run $(date) =====" >> ai-usage.log; /usr/bin/python3 /path/to/ai-usage.py 30 >> ai-usage.log 2>&1
```

Missed runs (laptop asleep) are harmless: the script recomputes from transcripts, nothing is
collected at runtime. Ratios (observer share, model mix, $/commit) survive volume swings;
absolutes don't, so compare light weeks by ratio only.

## License

MIT
