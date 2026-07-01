#!/usr/bin/env python3
"""
node_dashboard.py

A homelab Kubernetes cluster health dashboard. Fetches Nodes, Pods,
Events, and resource usage via kubectl, and prints a series of tables:
  1. Node readiness
  2. Unhealthy pods (with restart info and the most recent related event)
  3. Recent Warning events (last RECENT_RESTART_HOURS hours)
  4. Node CPU/memory usage
  5. Top pods by CPU usage
  6. Top pods by memory usage
"""

# modules
import subprocess
import json
import argparse
from datetime import datetime, timezone
from tabulate import tabulate

# Color codes for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"

# Restart Threshold for considering a pod unhealthy
RECENT_RESTART_HOURS = 1  # Number of hours to consider for recent restarts/events
TOP_N_PODS = 10  # How many pods to show in the Top CPU / Top Memory usage tables


def run_kubectl(args):
    """
    Run a kubectl command and return the parsed JSON output.

    args: a list of arguments to pass after "kubectl", e.g.
        ["get", "nodes", "-o", "json"]

    Returns the parsed JSON as a dict on success, or None if kubectl
    isn't found, the command fails, or the output isn't valid JSON.
    Callers must check for None before using the return value.
    """
    try:
        result = subprocess.run(
            ["kubectl"] + args,
            capture_output=True,
            text=True,
            check=True
        )
    except FileNotFoundError:
        print("Error: 'kubectl' command not found. Please ensure that kubectl is installed and in your PATH.")
        return None
    except subprocess.CalledProcessError as e:
        print(f"Error executing kubectl command: {e}")
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print("Error: could not parse kubectl output as JSON.")
        return None

def parse_args():
    """
    Define and parse command-line arguments.

    Returns an argparse.Namespace with .hours and .top attributes.
    """
    parser = argparse.ArgumentParser(
        description="Homelab Kubernetes cluster health dashboard."
    ) 
    parser.add_argument(
        "--hours",
        type=float,
        default=1,
        help="How many hours back to look for recent restarts/events (default: 1)" 
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="How man pods to show in the Top CPU/Memory tables (default: 10)"
    )
    return parser.parse_args()

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


def run_kubectl_text(args):
    """
    Run a kubectl command and return its raw stdout as plain text
    (for commands like `kubectl top` that don't support -o json).

    args: a list of arguments to pass after "kubectl", e.g.
        ["top", "nodes"]

    Returns the raw stdout string on success, or None on failure.
    """
    try:
        result = subprocess.run(
            ["kubectl"] + args,
            capture_output=True,
            text=True,
            check=True
        )
    except FileNotFoundError:
        print("Error: 'kubectl' command not found. Please ensure that kubectl is installed and in your PATH.")
        return None
    except subprocess.CalledProcessError as e:
        print(f"Error executing kubectl command: {e}")
        return None

    return result.stdout


def get_node_usage():
    """
    Fetch and parse `kubectl top nodes` output.

    Returns a list of rows, each row a list:
        [node_name, cpu_cores, cpu_percent, memory_bytes, memory_percent]

    Returns an empty list if the command fails or produces no data.
    """
    output = run_kubectl_text(["top", "nodes"])
    if output is None:
        return []

    lines = output.strip().split("\n")
    data_lines = lines[1:]  # skip header row

    rows = []
    for line in data_lines:
        columns = line.split()
        rows.append(columns)

    return rows


def get_pod_usage():
    """
    Fetch and parse `kubectl top pods -A` output.

    Returns a list of rows, each row a list:
        [namespace, pod_name, cpu_cores, memory_bytes]

    Returns an empty list if the command fails or produces no data.
    """
    output = run_kubectl_text(["top", "pods", "-A"])
    if output is None:
        return []

    lines = output.strip().split("\n")
    data_lines = lines[1:]  # skip header row

    rows = []
    for line in data_lines:
        columns = line.split()
        rows.append(columns)

    return rows

def get_pvcs():
    """
    Fetch all PersistentVolumeClaims across all namepaces via
    `kubectl get pvc -A -o json`.

    Returns the parsed JSON as a dict on success, or None on failure.
    """
    return run_kubectl(["get", "pvc", "-A", "-o", "json"])

def get_pvc_status(pvc):
    """
    Given a single PVC dict (one item from get_pvcs()'s "items" list),
    return (namespace/name, phase, storage_class, requested_storage).

    phase is typically "Bound" (healthy), "Pending" (note yet bound),
    or "Lost" (backing volume is gone).
    """
    name = pvc["metadata"]["name"]
    namespace = pvc["metadata"]["namespace"]
    phase = pvc["status"].get("phase", "Unknown")
    storage_class = pvc["spec"].get("storageClassName", "-")
    requested_storage = pvc["spec"].get("resources", {}).get("requests", {}).get("storage", "-")

    return f"{namespace}/{name}", phase, storage_class, requested_storage

def get_deployments():
    """
    Fetch all Deployments across all namespaces via
    `kubectl get deployments -A -o json`.

    Returns the parsed JSON as a dict on success, or None on failure.
    """
    return run_kubectl(["get", "deployments", "-A", "-o", "json"])

def get_deployment_status(deployment):
    """
    Given a single deployment dict (one item from get_deployments()'s
    "items" list), return (namespace/name, desired_replicas, ready_replicas).

    A deployment intentionally scaled to 0 replicas is not a problem -
    callers should only flag cases where desired > 0 but ready < desired.
    """
    name = deployment["metadata"]["name"]
    namespace = deployment["metadata"]["namespace"]
    desired_replicas = deployment["spec"].get("replicas", 0)
    ready_replicas = deployment["status"].get("readyReplicas", 0)

    return f"{namespace}/{name}", desired_replicas, ready_replicas    

def parse_cpu_millicores(cpu_str):
    """
    Convert a kubectl CPU string like "168m" or "1" into an integer
    number of millicores (1 core = 1000 millicores).
    """
    if cpu_str.endswith("m"):
        return int(cpu_str[:-1])
    else:
        return int(cpu_str) * 1000


def parse_memory_mi(mem_str):
    """
    Convert a kubectl memory string like "2745Mi", "512Ki", or "2Gi"
    into an integer number of Mi (mebibytes), for consistent sorting.
    """
    if mem_str.endswith("Gi"):
        return int(mem_str[:-2]) * 1024
    elif mem_str.endswith("Mi"):
        return int(mem_str[:-2])
    elif mem_str.endswith("Ki"):
        return int(mem_str[:-2]) // 1024
    else:
        return 0


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
    args = parse_args()
    RECENT_RESTART_HOURS = args.hours
    TOP_N_PODS = args.top

    # =========================================================
    # NODES
    # Fetch every node and print a simple Ready/Not Ready table.
    # =========================================================
    data = get_nodes()
    if data is None:
        exit(1)  # kubectl failed - get_nodes() already printed why
    nodes = data["items"]

    node_rows = []
    for node in nodes:
        name, ready_status = get_node_status(node)
        node_rows.append([name, ready_status])

    print(tabulate(node_rows, headers=["NODE", "STATUS"], tablefmt="grid"))

    print()  # blank line between sections

    # =========================================================
    # EVENTS (fetched early)
    # We need the event->reason lookup built BEFORE we process
    # pods, since the Pods table below cross-references it to
    # show "what's the most recent thing that went wrong" per pod.
    # =========================================================
    events_data = get_events()
    if events_data is None:
        exit(1)
    events = events_data["items"]  # raw list, reused again further down
    event_reason_lookup = build_event_reason_lookup(events)

    # =========================================================
    # PODS
    # A pod is only shown in this table if something is actually
    # wrong with it right now:
    #   - phase isn't Running/Succeeded, OR
    #   - it's Running but has a recent Warning event tied to it
    # Pods with no recent event are silently counted as healthy,
    # even if their lifetime restart count is high - see README
    # for why raw restart counts alone aren't a reliable signal.
    # =========================================================
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

        # Look up this pod's most recent Warning event, if any.
        # .get() twice: first find the pod's entry (default {} if
        # missing), then pull "reason" out of it (default "-").
        last_event_reason = event_reason_lookup.get(pod_name, {}).get("reason", "-")
        has_recent_event = last_event_reason != "-"

        if phase == "Running" and not has_recent_event:
            # Fully healthy - nothing to show, just count it.
            running_count += 1
        elif phase == "Running":
            # Running, but flagged because of a recent event.
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
            # One-shot Jobs/CronJobs finishing normally - not a problem.
            succeeded_count += 1
        else:
            # Anything else (e.g. Failed) - flag it.
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

    # =========================================================
    # RECENT WARNING EVENTS
    # Independent of the Pods table above - this lists every
    # Warning event (not just ones tied to a currently-Running
    # pod) seen within the last RECENT_RESTART_HOURS.
    # =========================================================
    event_rows = []

    for event in events:
        event_type, reason, count, last_timestamp_str, pod_name, namespace = get_event_status(event)

        if event_type != "Warning":
            continue  # skip Normal events entirely
        if last_timestamp_str is None:
            continue  # no timestamp to compare against, skip

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

    print()  # blank line between sections

    # =========================================================
    # NODE RESOURCE USAGE
    # Requires metrics-server to be running in the cluster.
    # Just displays raw kubectl top output as a table, no
    # filtering/sorting needed since there are only a few nodes.
    # =========================================================
    usage_rows = get_node_usage()
    if usage_rows:
        print("Node Resource Usage:")
        print(tabulate(usage_rows, headers=["NODE", "CPU", "CPU%", "MEMORY", "MEM%"], tablefmt="grid"))
    else:
        print("Node usage data unavailable (metrics-server may be down).")

    print()  # blank line between sections

    # =========================================================
    # TOP PODS BY CPU / MEMORY
    # With ~78 pods, showing all of them would be noise, so we
    # sort by usage (highest first) and only show the top N.
    # CPU/memory values come back as strings with units baked in
    # (e.g. "168m", "2745Mi"), so we convert them to plain integers
    # via parse_cpu_millicores()/parse_memory_mi() just for sorting -
    # the original formatted string is still what gets displayed.
    # =========================================================
    pod_usage_rows = get_pod_usage()

    if pod_usage_rows:
        # row[2] is the CPU column: [namespace, pod_name, cpu, memory]
        cpu_sorted = sorted(pod_usage_rows, key=lambda row: parse_cpu_millicores(row[2]), reverse=True)
        top_cpu = cpu_sorted[:TOP_N_PODS]

        print(f"Top {TOP_N_PODS} Pods by CPU:")
        print(tabulate(top_cpu, headers=["NAMESPACE", "POD", "CPU", "MEMORY"], tablefmt="grid"))

        print()

        # row[3] is the memory column
        mem_sorted = sorted(pod_usage_rows, key=lambda row: parse_memory_mi(row[3]), reverse=True)
        top_mem = mem_sorted[:TOP_N_PODS]

        print(f"Top {TOP_N_PODS} Pods by Memory:")
        print(tabulate(top_mem, headers=["NAMESPACE", "POD", "CPU", "MEMORY"], tablefmt="grid"))
    else:
        print("Pod usage data unavailable (metrics-server may be down).")
    
    print() # blank line between spaces

    # =========================================================
    # PERSISTENT VOLUME CLAIMS
    # Only shows PVCs that aren't Bound - a Bound PVC is healthy
    # and has nothing to report, so we skip it, same approach as
    # the Pods table.
    # =========================================================   

    pvc_data = get_pvcs()
    if pvc_data is None:
        exit(1)
    pvcs = pvc_data["items"]

    bound_count = 0 
    pvc_rows = []

    for pvc in pvcs:
        pvc_name, phase, storage_class, requested_storage = get_pvc_status(pvc)

        if phase == "Bound":
            bound_count += 1
        else:
            pvc_rows.append([pvc_name, phase, storage_class, requested_storage])
    
    print(f"PVCs: {bound_count} bound, {len(pvc_rows)} not bound")
    print()

    if pvc_rows:
        print("Unbound PVCs:")
        print(tabulate(pvc_rows, headers=["PVC", "PHASE", "STORAGE CLASS", "REQUESTED"], tablefmt="grid"))
    else:
        print("All PVCs are bound")

    print()  # blank line between sections

    # =========================================================
    # DEPLOYMENTS
    # Only flags deployments where desired replicas > 0 but
    # fewer are actually ready - a deployment intentionally
    # scaled to 0 (desired_replicas == 0) is not a problem.
    # =========================================================
    deployments_data = get_deployments()
    if deployments_data is None:
        exit(1)
    deployments = deployments_data["items"]

    healthy_deploy_count = 0
    deployment_rows = []

    for deployment in deployments:
        deploy_name, desired_replicas, ready_replicas = get_deployment_status(deployment)

        if desired_replicas == 0 or ready_replicas >= desired_replicas:
            healthy_deploy_count += 1
        else:
            deployment_rows.append([deploy_name, desired_replicas, ready_replicas])
    print(f"Deployments: {healthy_deploy_count} healthy, {len(deployment_rows)} degraded")
    print()

    if deployment_rows:
        print("Degraded Deployments:")
        print(tabulate(deployment_rows, headers=["DEPLOYMENT", "DESIRED", "READY"], tablefmt="grid"))
    else:
        print("All deployments are healthy.")
