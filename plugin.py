"""k3s / Kubernetes, read-only: nodes, versions, readiness and drift against the cluster's feature."""
from __future__ import annotations

import os
import tempfile

from labdex.plugins.base import Plugin as Base
from labdex.plugins.base import PluginError


class Plugin(Base):
    def _api(self):
        s = self.settings
        if not s.get("url"):
            raise PluginError("set the API server first")
        verify = bool(s.get("verify_tls", True))
        if verify and (s.get("ca_pem") or "").strip():
            fd, path = tempfile.mkstemp(prefix="labdex-k8s-ca-", suffix=".pem")
            with os.fdopen(fd, "w") as f:
                f.write(s["ca_pem"].strip() + "\n")
            self._ca_file = path
            verify = path
        return self.ctx.http(s["url"].rstrip("/") + "/", verify=verify, timeout=10, headers={"Authorization": f"Bearer {s.get('token', '')}"})

    def _done(self):
        p = getattr(self, "_ca_file", None)
        if p:
            os.unlink(p)
            self._ca_file = None

    def _read(self):
        http = self._api()
        try:
            version = (http.get("version").json() or {}).get("gitVersion", "")
            items = (http.get("api/v1/nodes").json() or {}).get("items") or []
            pods = (http.get("api/v1/pods", params={"fieldSelector": "status.phase=Running"}).json() or {}).get("items") or []
        finally:
            self._done()
        per_node: dict[str, int] = {}
        for p in pods:
            n = (p.get("spec") or {}).get("nodeName")
            if n:
                per_node[n] = per_node.get(n, 0) + 1
        match = self.ctx.match_host()
        nodes = []
        for it in items:
            md, st = it.get("metadata") or {}, it.get("status") or {}
            labels = md.get("labels") or {}
            roles = sorted(k.split("/", 1)[1] for k in labels if k.startswith("node-role.kubernetes.io/") and "/" in k) or ["worker"]
            addrs = {a.get("type"): a.get("address") for a in st.get("addresses") or []}
            ready = next((c.get("status") for c in st.get("conditions") or [] if c.get("type") == "Ready"), "Unknown")
            info = st.get("nodeInfo") or {}
            name = md.get("name", "")
            host = match(addrs.get("InternalIP", "")) or match(name) or match(addrs.get("Hostname", ""))
            nodes.append({"node": name, "host": host, "roles": roles, "ready": ready, "version": info.get("kubeletVersion", ""),
                          "os": info.get("osImage", ""), "address": addrs.get("InternalIP", ""), "pods": per_node.get(name, 0),
                          "unschedulable": bool((it.get("spec") or {}).get("unschedulable"))})
        return version, sorted(nodes, key=lambda n: n["node"])

    def test(self):
        version, nodes = self._read()
        return f"{version}: {len(nodes)} node(s)"

    def run_poll(self, params):
        from labdex import features
        from labdex.models import Host, db
        version, nodes = self._read()
        report = {}
        for n in nodes:
            if n["host"]:
                state = "up" if n["ready"] == "True" else "down" if n["ready"] == "False" else "unknown"
                report[n["host"]] = {"state": state, "detail": f"node {n['node']} {'Ready' if state == 'up' else 'NotReady' if state == 'down' else 'unknown'}"
                                     + (", cordoned" if n["unschedulable"] else "") + f" · {n['version']}",
                                     "data": {"roles": n["roles"], "pods": n["pods"]}}
        self.ctx.report_status(report)
        drift = []
        feat = (self.settings.get("feature") or "").strip()
        if feat:
            node_hosts = {n["host"] for n in nodes if n["host"]}
            with_feature = {h.name for h in db.session.scalars(db.select(Host)) if feat in features.expanded(h.features or [])}
            drift += [{"host": h, "issue": f"has {feat} but isn't a node"} for h in sorted(with_feature - node_hosts)]
            drift += [{"host": h, "issue": f"is a node but lacks {feat}"} for h in sorted(node_hosts - with_feature)]
        drift += [{"host": "", "issue": f"node {n['node']} ({n['address'] or 'no address'}) matches no host"} for n in nodes if not n["host"]]
        versions = sorted({n["version"] for n in nodes})
        if len(versions) > 1:
            drift.append({"host": "", "issue": "nodes run different versions: " + ", ".join(versions)})
        for d in drift:
            self.log(("" if not d["host"] else d["host"] + ": ") + d["issue"])
        self.ctx.set_state("cluster", {"version": version, "nodes": nodes, "drift": drift})
        return {"nodes": len(nodes), "ready": sum(1 for n in nodes if n["ready"] == "True"), "drift": len(drift)}

    # ---------------------------------------------------------------- views
    def page_cluster(self, args):
        st = self.ctx.state.get("cluster") or {}
        nodes = st.get("nodes", [])
        return {"summary": [{"label": "version", "value": st.get("version", "?")},
                            {"label": "nodes", "value": len(nodes)},
                            {"label": "ready", "value": sum(1 for n in nodes if n["ready"] == "True"), "tone": "ok"},
                            {"label": "drift", "value": len(st.get("drift", [])), "tone": "warn" if st.get("drift") else "ok"}],
                "sections": [
                    {"title": "Nodes", "type": "table",
                     "columns": [{"key": "node", "label": "Node"}, {"key": "host", "label": "Host"}, {"key": "roles", "label": "Roles"},
                                 {"key": "ready", "label": "Ready"}, {"key": "version", "label": "Version"}, {"key": "pods", "label": "Pods"},
                                 {"key": "os", "label": "OS"}],
                     "rows": [n | {"roles": ", ".join(n["roles"]), "host": n["host"] or "—",
                                   "_tone": "" if n["ready"] == "True" else "err"} for n in nodes],
                     "empty": "Not read yet: run “Read nodes”."},
                    {"title": "Drift", "type": "table", "columns": [{"key": "host", "label": "Host"}, {"key": "issue", "label": "Differs"}],
                     "rows": [d | {"_tone": "warn"} for d in st.get("drift", [])], "empty": "Nodes and the feature match."}],
                "note": "Read-only: labdex never changes the cluster."}

    def widget_cluster(self, host):
        st = self.ctx.state.get("cluster")
        if not st:
            return {"kind": "list", "items": [], "sub": "run “Read nodes”"}
        items = [{"label": n["node"], "state": "up" if n["ready"] == "True" else "down", "detail": ", ".join(n["roles"]) + f" · {n['pods']} pods",
                  "link": f"/hosts/{n['host']}" if n["host"] else ""} for n in st["nodes"]]
        return {"kind": "status", "items": items, "link": f"/integrations/{self.ctx.name}?tab=cluster",
                "sub": f"{st.get('version', '')} · {len(st.get('drift', []))} drift" if st.get("drift") else st.get("version", "")}

    def widget_node(self, host):
        st = self.ctx.state.get("cluster") or {}
        n = next((x for x in st.get("nodes", []) if x["host"] == host["name"]), None)
        if n is None:
            return {"kind": "list", "items": [], "sub": "not a node of this cluster"}
        return {"kind": "list", "items": [
            {"label": "node", "value": n["node"]}, {"label": "roles", "value": ", ".join(n["roles"])},
            {"label": "ready", "value": n["ready"], "tone": "ok" if n["ready"] == "True" else "err"},
            {"label": "version", "value": n["version"]}, {"label": "pods", "value": str(n["pods"])},
        ] + [{"label": "drift", "value": d["issue"], "tone": "warn"} for d in st.get("drift", []) if d["host"] == host["name"]],
            "sub": n["os"]}
