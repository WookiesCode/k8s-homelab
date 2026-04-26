#!/bin/bash
echo "=========================================="
echo "CLUSTER HEALTH CHECK - $(date)"
echo "=========================================="

echo ""
echo "--- NODES ---"
kubectl get nodes -o wide

echo ""
echo "--- PODS (non-running) ---"
kubectl get pods -A --field-selector='status.phase!=Running,status.phase!=Succeeded' 2>/dev/null | grep -v "^NAMESPACE"

echo ""
echo "--- ALL PODS STATUS SUMMARY ---"
kubectl get pods -A --no-headers | awk '{print $4}' | sort | uniq -c | sort -rn

echo ""
echo "--- RESTARTS (>5) ---"
kubectl get pods -A --no-headers | awk '$5 > 5 {print}' 

echo ""
echo "--- PVC STATUS ---"
kubectl get pvc -A

echo ""
echo "--- INGRESS ---"
kubectl get ingress -A

echo ""
echo "--- CERTIFICATES ---"
kubectl get certificate -A

echo ""
echo "--- VELERO BACKUPS (last 3) ---"
velero backup get 2>/dev/null | head -4

echo ""
echo "--- LONGHORN VOLUMES ---"
kubectl get volumes -n longhorn-system 2>/dev/null | head -20

echo ""
echo "--- SEALED SECRETS ---"
kubectl get sealedsecrets -A

echo ""
echo "--- NODE RESOURCE USAGE ---"
kubectl top nodes 2>/dev/null || echo "metrics-server not available"

echo ""
echo "--- POD RESOURCE USAGE (top 10) ---"
kubectl top pods -A --sort-by=memory 2>/dev/null | head -11

echo ""
echo "=========================================="
echo "CHECK COMPLETE"
echo "=========================================="
