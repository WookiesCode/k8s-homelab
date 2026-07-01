#!/usr/bin/env python3
"""
node_dashboard.py

A homelab Kubernetes cluster health dashboard. Fetches Nodes, Pods, and
Events via kubectl, and prints three tables:
  1. Node readiness
  2. Unhealthy pods (with restart info and the most recent related event)
  3. Recent Warning events (last RECENT_RESTART_HOURS hours)
"""

# modules
import subprocess
import json
from datetime import datetime, timezone
from tabulate import tabulate

# Color codes for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"

# Restart Threshold for considering a pod unhealthy
RESTART_THRESHOLD = 5
RECENT_RESTART_HOURS = 1  # Number of hours to consider for recent restarts/events

def run_kubectl(args):
    """
    Run a kubectl command and return the parsed JSON output.

    args: a list of arguments to pass after "kubectl", e.g.
        ["get", "nodes", "-o", "json"]
    
    Returns the parsed JSON as a dict on success, or None if kubectl
    isn't found, the command fails, or the output ins't vaild JSON.
    Callers must check for None before using the return values.
    """
    try:
        result = subprocess.run(
            ["kubectl"] + args,
            capture_output=True,
            text=True,
            check=True
        )
    except FileNotFoundError:
        print("Error: 'kubectl' command not found. Please ensure that kubectl is installed and in yyou PATH.")
        return None
    except subprocess.CalledProcessError as e:
        print(f"Error executing kubectl command: {e}")
        return None
    
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print("Error: could not parse kubectl output as JSON.")
        return None

def get_nodes():
    """
    Fetch all cluster nodes via `kubectl get nodes -o json`.

    Returns the parsed JSON as a dict on success, or None on failure.
    """
    return run_kubectl(["get", "nodes", "-o", "json"])


def get_node_status(node):
    """
    Given a single node dict (one item from get_nodes()'s "items" list),
    return (node_name, ready_status) where ready_status is "True",
    "False", or "Unknown" based on the node's "Ready" condition.
    """
    name = node["metadata"]["name"]
    conditions = node["status"]["conditions"]

    ready_status = "Unknown"
    for condition in conditions:
        if condition["type"] == "Ready":
            ready_status = condition["status"]

    return name, ready_status

def get_pods():
    """
    Fetch all pods across all namespaces via `kubectl get pods -A -o json`.

    Returns the parsed JSON as a dict on success, or None on failure
    (same failure modes/behavior as get_nodes()).
    """
    return run_kubectl(["get", "pods", "-A", "-o", "json"])

def get_pod_status(pod):
    """
    Given a single pod dict (one item from get_pods()'s "items" list),
    extract health info across all of its containers.

    Returns a tuple:
      (namespace/name, phase, restart_count, recent_restart, last_restart_age)

    - restart_count: total restarts summed across all containers (lifetime).
    - recent_restart: True if any container's last restart happened within
      RECENT_RESTART_HOURS.
    - last_restart_age: a timedelta representing how long ago the most
      recent restart (across all containers) happened, or None if the
      pod has no restart history at all.
    """
    name = pod["metadata"]["name"]
    namespace = pod["metadata"]["namespace"]
    phase = pod["status"].get("phase", "Unknown")

    containers = pod["status"].get("containerStatuses", [])
    restart_count = 0
    recent_restart = False
    last_restart_age = None

    now = datetime.now(timezone.utc)

    for container in containers:
        restart_count += container.get("restartCount", 0)

        # lastState/terminated only exists if this container has restarted
        # at least once, so we default-chain with .get() to avoid KeyErrors.
        last_state = container.get("lastState", {})
        terminated = last_state.get("terminated", {})
        finished_at_str = terminated.get("finishedAt")

        if finished_at_str:
            finished_at = datetime.fromisoformat(finished_at_str.replace("Z", "+00:00"))
            age = now - finished_at
            if last_restart_age is None or age < last_restart_age:
                last_restart_age = age
            if age.total_seconds() < RECENT_RESTART_HOURS * 3600:
                recent_restart = True

    return f"{namespace}/{name}", phase, restart_count, recent_restart, last_restart_age


def get_events():
    """
    Fetch all Kubernetes Events across all namespaces via
    `kubectl get events -A -o json`.

    Returns the parsed JSON as a dict on success, or None on failure
    (same failure modes/behavior as get_nodes()/get_pods()).
    """
    return run_kubectl(["get", "events", "-A", "-o", "json"])



def get_event_status(event):
    """
    Given a single event dict (one item from get_events()'s "items" list),
    pull out the fields we care about.

    Returns a tuple:
      (event_type, reason, count, last_timestamp_str, pod_name, namespace)

    - event_type: "Normal" or "Warning" (defaults to "Normal" if missing).
    - count: how many times Kubernetes has aggregated this exact event
      (defaults to 1, since a missing count means it's only happened once).
    - last_timestamp_str: raw ISO 8601 string, or None if not present.
      Left as None (no default) so callers can tell "no timestamp" apart
      from a real value.
    """
    event_type = event.get("type", "Normal")
    reason = event.get("reason", "Unknown")
    count = event.get("count", 1)
    last_timestamp_str = event.get("lastTimestamp")

    involved_object = event.get("involvedObject", {})
    pod_name = involved_object.get("name", "unknown")
    namespace = involved_object.get("namespace", "unknown")

    return event_type, reason, count, last_timestamp_str, pod_name, namespace


def build_event_reason_lookup(events):
    """
    Build a dict mapping "namespace/podname" -> {"reason": ..., "timestamp": ...}
    using only Warning-type events that have a valid timestamp.

    This lets the Pods table show "what's the most recent thing that went
    wrong with this pod" without re-scanning the full events list per pod.
    If a pod has multiple Warning events, only the most recent one is kept.
    """
    lookup = {}

    for event in events:
        event_type, reason, count, last_timestamp_str, pod_name, namespace = get_event_status(event)

        if event_type != "Warning":
            continue
        if last_timestamp_str is None:
            continue

        key = f"{namespace}/{pod_name}"
        last_timestamp = datetime.fromisoformat(last_timestamp_str.replace("Z", "+00:00"))

        if key not in lookup or last_timestamp > lookup[key]["timestamp"]:
            lookup[key] = {"reason": reason, "timestamp": last_timestamp}

    return lookup


def format_age(age):
    """
    Convert a timedelta into a short human-readable string like
    "2h 15m 3s ago", "15m 3s ago", or "3s ago" (dropping leading
    zero-value units).
    """
    total_seconds = int(age.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s ago"
    elif minutes > 0:
        return f"{minutes}m {seconds}s ago"
    else:
        return f"{seconds}s ago"


if __name__ == "__main__":
    # --- Nodes ---
    data = get_nodes()
    if data is None:
        exit(1)
    nodes = data["items"]

    node_rows = []
    for node in nodes:
        name, ready_status = get_node_status(node)
        node_rows.append([name, ready_status])

    print(tabulate(node_rows, headers=["NODE", "STATUS"], tablefmt="grid"))

    print()  # blank line between sections

    # --- Events (fetched early so Pods can reference them) ---
    events_data = get_events()
    if events_data is None:
        exit(1)
    events = events_data["items"]
    event_reason_lookup = build_event_reason_lookup(events)

    # --- Pods ---
    pods_data = get_pods()
    if pods_data is None:
        exit(1)
    pods = pods_data["items"]

    running_count = 0
    pending_count = 0
    succeeded_count = 0
    other_count = 0
    pod_rows = []

    for pod in pods:
        pod_name, phase, restart_count, recent_restart, last_restart_age = get_pod_status(pod)
        last_event_reason = event_reason_lookup.get(pod_name, {}).get("reason", "-")
        has_recent_event = last_event_reason != "-"

        if phase == "Running" and not has_recent_event:
            running_count += 1
        elif phase == "Running":            
            running_count += 1
            if last_restart_age is not None:
                last_restart_text = format_age(last_restart_age)
            else:
                last_restart_text = "-"
            pod_rows.append([pod_name, phase, restart_count, last_restart_text, last_event_reason])
        elif phase in ("Pending", "Unknown"):
            pending_count += 1
            pod_rows.append([pod_name, phase, "-", "-", last_event_reason])
        elif phase == "Succeeded":
            succeeded_count += 1
        else:
            other_count += 1
            pod_rows.append([pod_name, phase, "-", "-", last_event_reason])

    print(f"Pods: {running_count} running, {pending_count} pending, {other_count} other")
    print()

    if pod_rows:
        print(tabulate(
            pod_rows,
            headers=["POD", "STATUS", "RESTARTS", "LAST RESTART", "LAST EVENT"],
            tablefmt="grid"
        ))
    else:
        print("All pods are healthy.")

    print()  # blank line between sections

    # --- Recent Warning Events (last hour) ---
    event_rows = []

    for event in events:
        event_type, reason, count, last_timestamp_str, pod_name, namespace = get_event_status(event)

        if event_type != "Warning":
            continue
        if last_timestamp_str is None:
            continue

        last_timestamp = datetime.fromisoformat(last_timestamp_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        age = now - last_timestamp

        if age.total_seconds() < RECENT_RESTART_HOURS * 3600:
            event_rows.append([f"{namespace}/{pod_name}", reason, count, format_age(age)])

    if event_rows:
        print("Recent Warning Events (last hour):")
        print(tabulate(event_rows, headers=["POD", "REASON", "COUNT", "LAST SEEN"], tablefmt="grid"))
    else:
        print("No recent warning events.")