# Kubernetes Home Lab

A production-grade Kubernetes cluster running on Proxmox VMs, built to learn and demonstrate cloud-native technologies.

## Cluster Architecture

| Node | Role | CPU | RAM | Disk |
|---|---|---|---|---|
| k8s-controller | Control Plane | 4 vCPU | 4GB | 50GB |
| k8s-worker1 | Worker | 4 vCPU | 8GB | 150GB |
| k8s-worker2 | Worker | 4 vCPU | 8GB | 150GB |
| k8s-worker3 | Worker | 4 vCPU | 8GB | 150GB |

## Stack

| Component | Purpose |
|---|---|
| Kubernetes v1.32 | Container orchestration |
| Flannel | Pod networking (CNI) |
| MetalLB | Bare-metal load balancer |
| ingress-nginx | Ingress controller / reverse proxy |
| cert-manager | Automatic TLS certificate management |
| local-path-provisioner | Persistent storage |
| Sealed Secrets | GitOps-safe secrets management |
| Helm | Package management |

## Deployed Applications

| Application | Description |
|---|---|
| Prometheus + Grafana | Cluster monitoring and observability |
| Uptime Kuma | Service uptime monitoring |
| Homepage | Self-hosted dashboard |
| Vaultwarden | Self-hosted password manager (Bitwarden compatible) |
| Nextcloud | Self-hosted cloud storage with PostgreSQL backend |

## Repository Structure
apps/
├── homepage/
├── monitoring/
├── nextcloud/
├── uptime-kuma/
└── vaultwarden/

## Secrets Management

Sensitive data is managed using Sealed Secrets. Plain text secrets are never committed to this repository. All secrets are encrypted with the cluster public key before being stored in Git.

## Key Concepts Demonstrated

- Multi-node Kubernetes cluster setup with kubeadm
- Persistent storage with PersistentVolumeClaims
- Ingress routing with TLS termination
- Helm chart deployment and customization
- GitOps-safe secrets management
- Rolling updates with zero downtime
- Resource monitoring and observability
