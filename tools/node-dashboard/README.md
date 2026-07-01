# node_dashboard.py

A quick-glance health dashboard for a homelab Kubernetes cluster. Pulls live
data via `kubectl` and prints three tables: node readiness, unhealthy pods,
and recent Warning events.

## What it checks

- **Nodes** — whether each node's `Ready` condition is `True`.
- **Pods** — flags any `Running` pod that has a recent Warning event tied
  to it (see "How pod health is determined" below), plus any pod that's
  `Pending`, `Unknown`, or otherwise not `Running`/`Succeeded`.
- **Events** — lists Warning-type events from the last hour (configurable),
  showing how many times each one has occurred and how long ago it last
  fired.

Healthy, uneventful pods and nodes are not printed — the goal is to only
show what's actually worth looking at.

## How pod health is determined

Kubernetes pod restart counts are lifetime totals with no time context, so
a pod that restarted once during a reboot months ago looks identical to one
that's actively crash-looping right now. To get a more accurate picture,
this script cross-references each pod against cluster Events: a `Running`
pod is only flagged if it has a Warning event (e.g. `BackOff`,
`FailedScheduling`, `FailedMount`) within the last `RECENT_RESTART_HOURS`.

This also catches problems that don't show up in a pod's own container
status at all — for example, a crash-looping **init container** won't
affect the pod's regular `restartCount`, but it will generate BackOff
events, so it still gets surfaced.

## Requirements

- Python 3
- `kubectl`, configured with access to your cluster
- The `tabulate` package (see below)

## Setup

```bash
cd tools/node-dashboard
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
source venv/bin/activate
./node_dashboard.py
```

(Make sure the file is executable: `chmod +x node_dashboard.py`, or run it
with `python3 node_dashboard.py` instead.)

## Configuration

A couple of constants near the top of the file control behavior:

| Constant                | Default | Meaning                                                              |
|--------------------------|---------|------------------------------------------------------------------------|
| `RECENT_RESTART_HOURS`   | `1`     | How far back to look for Warning events / recent restarts.            |
| `RESTART_THRESHOLD`      | `5`     | Currently unused in filtering logic; kept for possible future use.    |

## Known limitations

- Restart counts shown in the Pods table are still lifetime totals, not
  scoped to the recent window — only the *filtering* decision uses
  recency, the displayed number is historical context.
- Events are matched to pods by name/namespace, so if a pod is recreated
  with a new name (e.g. after a reschedule), its event history under the
  old name won't carry over.

## Possible future additions

- Resource usage (`kubectl top`) as a fourth table
- PVC / storage health
- A shared `run_kubectl()` helper instead of repeating the subprocess/error
  handling in each `get_*()` function
- Live-refreshing mode instead of one-shot output