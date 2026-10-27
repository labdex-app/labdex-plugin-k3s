# k3s / Kubernetes

A [labdex](https://github.com/reykimedev/labdex) plugin. Read-only. A cluster's nodes matched to inventory hosts, with their roles and versions, node readiness as host status, and drift against the cluster's feature (hosts that have the feature but aren't nodes, and the other way round).

**Version** 1.0 · **Works with** labdex >=1.3,<2 · **Plugin id** `k3s`

> [!WARNING]
> Built with AI, for home labs only: labdex and its plugins were written largely with an AI
> coding assistant (Claude), directed and reviewed by a human. They haven't had an independent
> security audit and may contain security problems. Run them on a trusted home network.

## Install

It ships with labdex: **Plugins › Marketplace**, then *Install* (nothing is downloaded). Updates arrive through the official Marketplace (signed with the labdex project key).

## Settings

| Setting | Notes |
| --- | --- |
| API server |  |
| Bearer token | A service account token with get/list on nodes and pods (read-only) |
| Cluster CA (PEM) | certificate-authority-data from the kubeconfig, decoded; empty = the system CAs |
| Check the TLS certificate |  |
| The cluster's feature | Feature path every node should have, e.g. kube.cluster.oak |

## Actions

- **Check connection** (run)
- **Read nodes** (run): Node readiness as host status, roles and versions, drift against the feature

## Releasing

Bump `version` in `plugin.yaml`, add a `## <version>` section to `CHANGELOG.md`, commit, then
publish a GitHub release tagged `v<version>` (web UI, or `gh release create v<version> --target main --notes ""`).
The release workflow signs the plugin with the `LABDEX_SIGNING_KEY` secret, attaches the zip and
`CHANGELOG.md` to the release and puts that version's CHANGELOG section into its description.
Files listed in `.releaseignore` stay out of the zip.
