# node_dashboard.py

An interactive, menu-driven health dashboard for a homelab Kubernetes
cluster. Pulls live data via `kubectl` (and optionally a local Ollama
model) and presents it as clean terminal tables.

## What it checks

From the menu:

1. **Nodes** — whether each node's `Ready` condition is `True`.
2. **Pods** — flags any `Running` pod that has a recent Warning event
   tied to it (see "How pod health is determined" below), plus any pod
   that's `Pending`, `Unknown`, or otherwise not `Running`/`Succeeded`.
3. **Recent Warning Events** — every Warning-type event from the last
   `RECENT_RESTART_HOURS`, with occurrence count and last-seen time.
4. **Node Resource Usage** — CPU/memory per node, via `kubectl top nodes`.
5. **Top Pods by CPU/Memory** — the busiest pods, sorted and limited to
   `TOP_N_PODS`.
6. **PVCs** — any PersistentVolumeClaim that isn't `Bound`.
7. **Deployments** — any deployment with fewer ready replicas than
   desired (ignoring ones intentionally scaled to 0).
8. **All sections** — runs 1–7 in sequence.
9. **AI Summary** — sends a plain-text digest of cluster state to a
   local Ollama model and prints its summary.
10. **Run Tests** — runs the project's unit test suite inline.

Healthy, uneventful items are not printed in most sections — the goal
is to only show what's actually worth looking at.

Any menu choice (1–10) can be run in **live mode**: choose it, then
answer "y" when asked, and the screen will clear and re-run that
section every `REFRESH_INTERVAL_SECONDS` until you press Ctrl+C.

## How pod health is determined

Kubernetes pod restart counts are lifetime totals with no time context,
so a pod that restarted once during a reboot months ago looks identical
to one that's actively crash-looping right now. To get a more accurate
picture, this script cross-references each pod against cluster Events:
a `Running` pod is only flagged if it has a Warning event (e.g.
`BackOff`, `FailedScheduling`, `FailedMount`) within the last
`RECENT_RESTART_HOURS`.

This also catches problems that don't show up in a pod's own container
status at all — for example, a crash-looping **init container** won't
affect the pod's regular `restartCount`, but it will generate BackOff
events, so it still gets surfaced.

## Requirements

- Python 3
- `kubectl`, configured with access to your cluster
- `metrics-server` running in the cluster (required for the Node/Pod
  usage sections — without it, those sections report usage data as
  unavailable, but the rest of the dashboard still works)
- A reachable Ollama server (required only for the AI Summary option)
- Packages in `requirements.txt` (`tabulate`, `ollama`)

## Setup

```bash
cd tools/node-dashboard
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Usage

Interactive menu:

```bash
source venv/bin/activate
./node_dashboard.py
```

(Make sure the file is executable: `chmod +x node_dashboard.py`, or run
it with `python3 node_dashboard.py` instead.)

Headless / cron-friendly mode — runs the core health checks (Nodes,
Pods, PVCs, Deployments) once, prints only problems found, and exits
with a status code (`0` = healthy, `1` = problems found):

```bash
./node_dashboard.py --check
```

## Command-line options

| Flag           | Default | Meaning                                                                 |
|-----------------|---------|--------------------------------------------------------------------------|
| `--hours`       | `1`     | How far back to look for Warning events / recent restarts.              |
| `--top`         | `10`    | How many pods to show in the Top CPU/Memory tables.                     |
| `--namespace`   | (all)   | Limit every section to a single namespace instead of the whole cluster. |
| `--check`       | off     | Skip the menu; run core health checks once and exit with a status code. |

## Configuration constants

A few settings live as constants near the top of the file rather than
command-line flags, since they change rarely:

| Constant                  | Default                     | Meaning                                    |
|----------------------------|------------------------------|----------------------------------------------|
| `REFRESH_INTERVAL_SECONDS` | `30`                         | How often live mode refreshes.               |
| `OLLAMA_HOST`               | `http://10.10.10.8:11434`   | Address of the Ollama server for AI Summary. |
| `OLLAMA_MODEL`              | `ornith:35b`                 | Which Ollama model to use for AI Summary.    |

## Testing

Unit tests cover the pure logic functions (unit conversion, age
formatting, event-reason lookup building) using known inputs/outputs —
no live cluster required:

```bash
python3 -m unittest test_node_dashboard.py -v
```

The same suite is also runnable from inside the dashboard itself via
menu option 10.

## Known limitations

- Restart counts shown in the Pods table are still lifetime totals, not
  scoped to the recent window — only the *filtering* decision uses
  recency, the displayed number is historical context.
- Events are matched to pods by name/namespace, so if a pod is recreated
  with a new name (e.g. after a reschedule), its event history under the
  old name won't carry over.
- `kubectl top` doesn't support JSON output, so Node/Pod usage sections
  parse plain text column output instead — this is more brittle than the
  JSON-based sections if kubectl's output format ever changes.
- The AI Summary option requires network access to the configured
  `OLLAMA_HOST` and fails gracefully (with a clear message) if it's
  unreachable.
- `--check` mode covers Nodes, Pods, PVCs, and Deployments only — it
  does not check Node/Pod resource usage or Recent Warning Events
  directly (those aren't simple pass/fail signals).

## Possible future additions

- Job/CronJob health checks
- Alerting (webhook/ntfy) when `--check` finds problems
- A config file for settings currently hardcoded as constants
- Mocking `subprocess.run` to unit test the `kubectl`-calling functions
- A refactor of tuples-as-return-values into small classes (`Pod`,
  `Node`, etc.), once classes are covered in coursework