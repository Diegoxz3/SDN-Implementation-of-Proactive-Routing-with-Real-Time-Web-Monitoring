#!/usr/bin/env python3
# -- coding: utf-8 --
"""
NetWeb backend (Flask + SSE) — versión con mejoras de "casi tiempo real"
-----------------------------------------------------------------------
Mejoras incluidas:
- Variables de entorno para configuración (IP/puerto del controlador, intervalos, token).
- Versionado y timestamp del snapshot; healthcheck en /healthz.
- SSE con keep-alives y cola de eventos (topology + incrementales).
- "What-if" de enlaces: excluir/rehabilitar enlaces para cálculo de rutas.
- Ingesta de eventos push desde Ryu en /ryu/events (port/link/switch/host) con token.
- Poller con intervalo configurable (queda como respaldo si no hay push).
- Caminos que evitan enlaces excluidos; opcional k-shortest (parámetro k).
- Difusión de diffs de enlaces (added/removed) cuando cambia la topología.
- **NUEVO (Fase 1 métricas pasivas)**: cálculo de *throughput* y *loss* por enlace (a partir de
  /stats/port/<dpid> de ryu.app.ofctl_rest), agregados de red, y métricas de camino.
  Expuestos en /metrics, /metrics/link y /metrics/path; además, evento SSE "metrics".

Requiere que ryu-manager incluya:
    ryu-manager --ofp-tcp-listen-port 6653 --observe-links \
      ryu.app.ofctl_rest ryu.app.rest_topology ~/ryu_apps/ryu_controllerx.py
"""

from typing import Dict, Any, Tuple, Set, List
import json
import threading
import time
import queue
import os
import math

import requests
import networkx as nx
from flask import Flask, Response, jsonify, request, send_from_directory

# =================== Config ===================
CONTROLLER = os.getenv("CONTROLLER", "http://127.0.0.1:8080")
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "1.0"))  # s (fallback si no hay push)
SSE_KEEPALIVE_SEC = int(os.getenv("SSE_KEEPALIVE_SEC", "10"))
RYU_PUSH_TOKEN = os.getenv("RYU_PUSH_TOKEN", "changeme-token")
ENABLE_POLLING = os.getenv("ENABLE_POLLING", "1") not in ("0", "false", "False")

# Tiempo de espera para peticiones al ofctl_rest (stats de puertos)
OFCTL_TIMEOUT = float(os.getenv("OFCTL_TIMEOUT", "4.0"))

# Flask
app = Flask(__name__, static_folder="static", static_url_path="/static")

# =================== Estado compartido ===================
_snapshot: Dict[str, Any] = {
    "version": 0,
    "ts": time.time(),
    "mode": "hops",
    "nodes": [],
    "links": [],     # cada e: {u,v,bw,weight,p_u?,p_v?}
    "hosts": []      # cada h: {id,ip,sw,port}
}
_excluded_links: Set[Tuple[str, str]] = set()  # what-if
_last_controller_ok = False
_last_controller_ts = 0.0

# Métricas (último cómputo)
_last_metrics: Dict[str, Any] = {
    "ts": 0.0,
    "window_sec": 0.0,
    "link_metrics": [],
    "net": {"t_bps_total": 0.0, "avg_loss_pct": None}
}

# Historias por puerto para deltas (dpid,port) -> counters
_port_prev: Dict[Tuple[str, int], Dict[str, float]] = {}

_lock = threading.Lock()
_updates: "queue.Queue[str]" = queue.Queue(maxsize=256)


# =================== Helpers HTTP ===================
def _safe_get(path: str, timeout: float = 4.0) -> Any:
    r = requests.get(f"{CONTROLLER}{path}", timeout=timeout)
    r.raise_for_status()
    ct = r.headers.get("content-type", "")
    if "application/json" in ct or r.text.strip().startswith("{") or r.text.strip().startswith("["):
        return r.json()
    return r.text


# =================== Normalización / utilidades ===================
def _normalize(snap: Dict[str, Any]) -> Dict[str, Any]:
    s = {
        "mode": snap.get("mode", "hops"),
        "nodes": [str(n) for n in snap.get("nodes", [])],
        "links": [],
        "hosts": snap.get("hosts", []),
    }
    for e in snap.get("links", []):
        s["links"].append(
            {
                "u": str(e.get("u")),
                "v": str(e.get("v")),
                "bw": int(e.get("bw", 0)),
                "weight": float(e.get("weight", 1.0)),
                **({"p_u": e["p_u"], "p_v": e["p_v"]} if "p_u" in e and "p_v" in e else {})
            }
        )
    return s


def _links_set(snap: Dict[str, Any]) -> Set[Tuple[str, str]]:
    def key(e):
        u, v = str(e["u"]), str(e["v"])
        return tuple(sorted((u, v)))
    return {key(e) for e in snap.get("links", [])}


def _dpid_to_dec(s: str) -> str:
    if s is None:
        return ""
    s2 = s.replace(":", "")
    try:
        return str(int(s2, 16))
    except Exception:
        return s  # fallback


def _set_ports_on_link(new_links: List[Dict[str, Any]], u: str, v: str, pu: int, pv: int) -> None:
    for e in new_links:
        if {e["u"], e["v"]} == {u, v}:
            if e["u"] == u:
                e["p_u"], e["p_v"] = pu, pv
            else:
                e["p_u"], e["p_v"] = pv, pu
            break


def _bump_version_locked() -> None:
    _snapshot["version"] = int(_snapshot.get("version", 0)) + 1
    _snapshot["ts"] = time.time()


def _emit(event: Dict[str, Any]) -> None:
    """Encola un evento SSE con protección ante cola llena."""
    try:
        _updates.put_nowait(json.dumps(event))
    except queue.Full:
        # Último recurso: descartar el evento más antiguo y meter el nuevo
        try:
            _updates.get_nowait()
            _updates.put_nowait(json.dumps(event))
        except Exception:
            pass


# =================== Ofctl helpers (port stats) ===================
def _get_ports_stats(dpid: str, timeout: float = OFCTL_TIMEOUT) -> Dict[int, Dict[str, int]]:
    """
    Devuelve un dict {port_no -> counters} usando /stats/port/<dpid> de ofctl_rest.
    Estructura típica: {"<dpid>": [{"port_no":1,"rx_packets":...,"tx_packets":...,"rx_bytes":...,"tx_bytes":...}, ...]}
    Filtra puertos >= OFPP_MAX.
    """
    try:
        r = requests.get(f"{CONTROLLER}/stats/port/{dpid}", timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return {}

    # data puede ser {"<dpid>":[...]} o lista directa
    if isinstance(data, dict):
        if str(dpid) in data:
            lst = data[str(dpid)]
        elif data:
            lst = next(iter(data.values()))
        else:
            lst = []
    elif isinstance(data, list):
        lst = data
    else:
        lst = []

    out = {}
    for it in lst:
        try:
            p = int(it.get("port_no"))
            if p >= 0xFFFFFF00:  # OFPP_MAX y especiales
                continue
            out[p] = {
                "rx_packets": int(it.get("rx_packets", 0)),
                "tx_packets": int(it.get("tx_packets", 0)),
                "rx_bytes": int(it.get("rx_bytes", 0)),
                "tx_bytes": int(it.get("tx_bytes", 0)),
            }
        except Exception:
            continue
    return out


def _compute_link_metrics(snap: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calcula métricas por enlace a partir de counters de puertos en Δt.
    - Throughput por dirección = Δtx_bytes/Δt * 8 [bps]
    - Throughput de enlace (t_bps) = suma bidireccional (u->v + v->u)
    - Loss por dirección ≈ max(0, 1 - Δrx_pkts_opuesto / Δtx_pkts_local) [%]
    - Loss de enlace = promedio de ambas direcciones
    Devuelve payload con arreglo link_metrics y agregados de red.
    """
    now = time.time()
    dpids = list({str(n) for n in snap.get("nodes", [])})
    sw_stats: Dict[str, Dict[int, Dict[str, int]]] = {}
    for dpid in dpids:
        sw_stats[dpid] = _get_ports_stats(dpid)

    link_metrics = []
    losses = []
    t_bps_total = 0.0

    for e in snap.get("links", []):
        u, v = str(e["u"]), str(e["v"])
        pu = int(e.get("p_u") or 0)
        pv = int(e.get("p_v") or 0)
        if not pu or not pv:
            continue

        su = sw_stats.get(u, {}).get(pu)
        sv = sw_stats.get(v, {}).get(pv)
        if su is None or sv is None:
            continue

        key_u = (u, pu)
        key_v = (v, pv)
        prev_u = _port_prev.get(key_u)
        prev_v = _port_prev.get(key_v)

        _port_prev[key_u] = {"tx_bytes": su["tx_bytes"], "rx_packets": su["rx_packets"],
                             "tx_packets": su["tx_packets"], "t": now}
        _port_prev[key_v] = {"tx_bytes": sv["tx_bytes"], "rx_packets": sv["rx_packets"],
                             "tx_packets": sv["tx_packets"], "t": now}

        if not prev_u or not prev_v:
            continue

        dt = max(1e-6, min(now - float(prev_u["t"]), now - float(prev_v["t"])))

        # u -> v
        d_tx_bytes_u = max(0, su["tx_bytes"] - int(prev_u["tx_bytes"]))
        t_uv_bps = (d_tx_bytes_u * 8.0) / dt

        d_tx_pkts_u = max(0, su["tx_packets"] - int(prev_u["tx_packets"]))
        d_rx_pkts_v = max(0, sv["rx_packets"] - int(prev_v["rx_packets"]))
        loss_uv = 0.0 if d_tx_pkts_u == 0 else max(0.0, 1.0 - (d_rx_pkts_v / float(d_tx_pkts_u))) * 100.0

        # v -> u
        d_tx_bytes_v = max(0, sv["tx_bytes"] - int(prev_v["tx_bytes"]))
        t_vu_bps = (d_tx_bytes_v * 8.0) / dt

        d_tx_pkts_v = max(0, sv["tx_packets"] - int(prev_v["tx_packets"]))
        d_rx_pkts_u = max(0, su["rx_packets"] - int(prev_u["rx_packets"]))
        loss_vu = 0.0 if d_tx_pkts_v == 0 else max(0.0, 1.0 - (d_rx_pkts_u / float(d_tx_pkts_v))) * 100.0

        t_bps = t_uv_bps + t_vu_bps
        loss_pct = (loss_uv + loss_vu) / 2.0

        link_metrics.append({
            "u": u, "v": v, "p_u": pu, "p_v": pv,
            "t_bps": t_bps,
            "dir": {
                f"{u}->{v}": {"tx_bps": t_uv_bps, "loss_pct": loss_uv},
                f"{v}->{u}": {"tx_bps": t_vu_bps, "loss_pct": loss_vu},
            },
            "loss_pct": loss_pct,
            "window_sec": dt
        })

        t_bps_total += t_bps
        losses.append(loss_pct)

    avg_loss = None
    if losses:
        avg_loss = sum(losses) / len(losses)

    return {
        "ts": now,
        "link_metrics": link_metrics,
        "net": {
            "t_bps_total": t_bps_total,
            "avg_loss_pct": avg_loss
        },
        "window_sec": link_metrics[0]["window_sec"] if link_metrics else 0.0
    }


def _lookup_link_metric(u: str, v: str, metrics: Dict[str, Any]) -> Dict[str, Any]:
    uu, vv = str(u), str(v)
    for m in metrics.get("link_metrics", []):
        if {m["u"], m["v"]} == {uu, vv}:
            return m
    return {}


def _path_metrics(paths: List[List[str]], metrics: Dict[str, Any]) -> Dict[str, Any]:
    """
    Para cada camino, calcula:
    - bottleneck throughput = min(t_bps por enlace del camino)
    - loss total ≈ suma(loss_pct por enlace) acotada a 100
    Devuelve mejor camino (por mayor bottleneck) y métricas de todos.
    """
    out = {"per_path": []}
    best_idx = None
    best_bottleneck = -1.0
    for i, p in enumerate(paths):
        if len(p) < 2:
            out["per_path"].append({"path": p, "bottleneck_bps": 0.0, "loss_pct": None})
            continue
        t_list = []
        l_list = []
        ok = True
        for j in range(len(p)-1):
            u, v = p[j], p[j+1]
            m = _lookup_link_metric(u, v, metrics)
            if not m:
                ok = False
                break
            t_list.append(m.get("t_bps", 0.0))
            lp = m.get("loss_pct")
            if lp is not None:
                l_list.append(max(0.0, float(lp)))
        if not ok or not t_list:
            out["per_path"].append({"path": p, "bottleneck_bps": None, "loss_pct": None})
            continue
        bottleneck = min(t_list)
        loss_sum = min(100.0, sum(l_list)) if l_list else None
        out["per_path"].append({"path": p, "bottleneck_bps": bottleneck, "loss_pct": loss_sum})
        if bottleneck > best_bottleneck:
            best_bottleneck, best_idx = bottleneck, i
    if best_idx is not None:
        out["best_index"] = best_idx
        out["best"] = out["per_path"][best_idx]
    return out


# =================== Poller (fallback) ===================
def poller():
    global _snapshot, _last_controller_ok, _last_controller_ts, _last_metrics
    prev_links_set: Set[Tuple[str, str]] = set()
    backoff = POLL_INTERVAL

    while True:
        if not ENABLE_POLLING:
            time.sleep(0.25)
            continue

        try:
            topo = _safe_get("/topology")
            new_norm = _normalize(topo)

            # Enriquecer con puertos (links)
            try:
                rt_links = _safe_get("/v1.0/topology/links")
                for rt in rt_links:
                    u = _dpid_to_dec(rt["src"]["dpid"])
                    v = _dpid_to_dec(rt["dst"]["dpid"])
                    pu = int(rt["src"]["port_no"])
                    pv = int(rt["dst"]["port_no"])
                    _set_ports_on_link(new_norm["links"], u, v, pu, pv)
            except Exception:
                pass

            # Enriquecer con hosts
            try:
                rt_hosts = _safe_get("/v1.0/topology/hosts")
                hosts = []
                for h in rt_hosts:
                    ip = ""
                    if isinstance(h.get("ipv4"), list) and h["ipv4"]:
                        ip = h["ipv4"][0]
                    sw = _dpid_to_dec(h["port"]["dpid"])
                    port = int(h["port"]["port_no"])
                    hid = f"h{ip.split('.')[-1]}" if ip else f"h{sw}_{port}"
                    hosts.append({"id": hid, "ip": ip, "sw": sw, "port": port})
                new_norm["hosts"] = hosts
            except Exception:
                new_norm.setdefault("hosts", [])

            # Publicar cambios
            topology_changed = False
            with _lock:
                old_norm = {k: _snapshot.get(k) for k in ("mode", "nodes", "links", "hosts")}
                changed = json.dumps(new_norm, sort_keys=True) != json.dumps(old_norm, sort_keys=True)
                if changed:
                    _snapshot["mode"] = new_norm["mode"]
                    _snapshot["nodes"] = new_norm["nodes"]
                    _snapshot["links"] = new_norm["links"]
                    _snapshot["hosts"] = new_norm["hosts"]
                    _bump_version_locked()
                    _emit({"type": "topology", "data": _snapshot})
                    topology_changed = True

                    new_set = _links_set(_snapshot)
                    added = list(new_set - prev_links_set)
                    removed = list(prev_links_set - new_set)
                    if added or removed:
                        _emit({"type": "diff", "added": added, "removed": removed})
                    prev_links_set = new_set

            # === MÉTRICAS pasivas basadas en ofctl_rest ===
            try:
                with _lock:
                    snap_copy = {
                        "nodes": list(_snapshot.get("nodes", [])),
                        "links": [dict(e) for e in _snapshot.get("links", [])]
                    }
                metrics = _compute_link_metrics(snap_copy)
                with _lock:
                    _last_metrics = metrics
                if metrics.get("link_metrics"):
                    _emit({"type": "metrics", "data": metrics})
            except Exception as me:
                _emit({"type": "error", "message": f"metrics: {me}"})

            _last_controller_ok = True
            _last_controller_ts = time.time()
            backoff = POLL_INTERVAL  # reset en éxito

        except Exception as e:
            _last_controller_ok = False
            _emit({"type": "error", "message": str(e)})
            backoff = min(8.0, max(POLL_INTERVAL, backoff * 1.5))

        time.sleep(backoff)


# =================== Rutas HTTP ===================
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/events")
def events():
    """Server-Sent Events para actualizaciones en vivo + keepalives."""
    def gen():
        with _lock:
            init = json.dumps({"type": "topology", "data": _snapshot})
        yield f"data: {init}\n\n"

        last_ping = time.time()
        while True:
            try:
                now = time.time()
                if now - last_ping >= SSE_KEEPALIVE_SEC:
                    yield ":ping\n\n"
                    last_ping = now
                data = _updates.get(timeout=1.0)
                yield f"data: {data}\n\n"
            except queue.Empty:
                continue

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    }
    return Response(gen(), headers=headers)


@app.get("/graph")
def graph():
    with _lock:
        out = dict(_snapshot)
        out["excluded_links"] = sorted([list(t) for t in _excluded_links])
    return jsonify(out)


@app.get("/path")
def path():
    """Camino más corto switch->switch usando 'weight'; evita enlaces excluidos. Admite ?k=1..N."""
    src, dst = request.args.get("src"), request.args.get("dst")
    k = int(request.args.get("k", "1"))
    if not src or not dst:
        return jsonify(error="query params: src, dst"), 400
    if k < 1 or k > 10:
        return jsonify(error="k debe estar entre 1 y 10"), 400

    with _lock:
        snap = _snapshot.copy()
        excluded = set(_excluded_links)

    G = nx.Graph()
    for n in snap.get("nodes", []):
        G.add_node(str(n))

    for e in snap.get("links", []):
        u, v = str(e["u"]), str(e["v"])
        if tuple(sorted((u, v))) in excluded:
            continue
        G.add_edge(u, v, weight=float(e.get("weight", 1.0)))

    if not G.has_node(src) or not G.has_node(dst):
        return jsonify(error="Nodo inexistente"), 404

    try:
        if k == 1:
            p = nx.shortest_path(G, src, dst, weight="weight")
            cost = sum(G[p[i]][p[i+1]]["weight"] for i in range(len(p)-1))
            return jsonify(paths=[p], costs=[cost])
        else:
            paths = []
            costs = []
            gen = nx.shortest_simple_paths(G, src, dst, weight="weight")
            for _ in range(k):
                p = next(gen)
                c = sum(G[p[i]][p[i+1]]["weight"] for i in range(len(p)-1))
                paths.append(p)
                costs.append(c)
            return jsonify(paths=paths, costs=costs)
    except StopIteration:
        if paths := locals().get("paths", []):
            return jsonify(paths=paths, costs=locals().get("costs", []))
        return jsonify(error="No hay camino"), 404
    except nx.NetworkXNoPath:
        return jsonify(error="No hay camino"), 404


# ---- Proxies a tu controlador ----------------------------------------------
@app.post("/mode")
def set_mode():
    """Proxy a /set_mode y /reinstall de tu controlador."""
    j = request.get_json(force=True, silent=True) or {}
    mode = j.get("mode")
    if mode not in ("hops", "distrak"):
        return jsonify(error="mode debe ser 'hops' o 'distrak'"), 400
    r = requests.post(f"{CONTROLLER}/set_mode", json={"mode": mode}, timeout=5)
    r.raise_for_status()
    try:
        requests.post(f"{CONTROLLER}/reinstall", timeout=5)
    except Exception:
        pass
    return jsonify(status="ok", mode=mode)


@app.post("/reinstall")
def reinstall():
    r = requests.post(f"{CONTROLLER}/reinstall", timeout=10)
    r.raise_for_status()
    return jsonify(status="ok")


# ---- What-if de enlaces -----------------------------------------------------
def _norm_uv(u: str, v: str) -> Tuple[str, str]:
    return tuple(sorted((str(u), str(v))))  # clave canónica


@app.post("/whatif/disable_link")
def whatif_disable_link():
    j = request.get_json(force=True, silent=True) or {}
    u, v = j.get("u"), j.get("v")
    if not u or not v:
        return jsonify(error="Faltan u,v"), 400
    key = _norm_uv(u, v)
    with _lock:
        _excluded_links.add(key)
        _bump_version_locked()
        _emit({"type": "whatif_excluded", "link": list(key)})
    return jsonify(status="ok", excluded=list(map(list, _excluded_links)))


@app.post("/whatif/enable_link")
def whatif_enable_link():
    j = request.get_json(force=True, silent=True) or {}
    u, v = j.get("u"), j.get("v")
    if not u or not v:
        return jsonify(error="Faltan u,v"), 400
    key = _norm_uv(u, v)
    with _lock:
        _excluded_links.discard(key)
        _bump_version_locked()
        _emit({"type": "whatif_included", "link": list(key)})
    return jsonify(status="ok", excluded=list(map(list, _excluded_links)))


@app.get("/whatif/excluded")
def whatif_list():
    with _lock:
        excl = sorted([list(t) for t in _excluded_links])
    return jsonify(excluded=excl)


# ---- Ingesta de eventos push desde Ryu -------------------------------------
"""
Esperado (JSON) en POST /ryu/events  (encabezado Authorization: Bearer <token>):
{
  "type": "port_down|port_up|link_add|link_delete|switch_enter|switch_leave|host_add|host_del",
  "ts": 1699999999.123,           # opcional
  "data": {... campos del evento ...}
}
Campos sugeridos:
- link_* : {"u": "1", "v": "2", "p_u": 1, "p_v": 3, "bw": 10, "weight": 1.0}
- port_* : {"sw": "1", "port": 1}
- switch_* : {"sw": "1"}
- host_add : {"id":"h10","ip":"10.0.0.10","sw":"3","port":1}
- host_del : {"id":"h10"}  (o {"ip":"10.0.0.10"})
"""
def _auth_ok(req) -> bool:
    auth = req.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth.split(" ", 1)[1].strip()
    else:
        token = req.args.get("token", "")
    return token == RYU_PUSH_TOKEN


@app.post("/ryu/events")
def ryu_events():
    if not _auth_ok(request):
        return jsonify(error="unauthorized"), 401

    j = request.get_json(force=True, silent=True) or {}
    etype = j.get("type")
    data = j.get("data", {}) or {}
    if not etype:
        return jsonify(error="missing type"), 400

    with _lock:
        changed = False
        def add_link(d):
            nonlocal changed
            u, v = str(d["u"]), str(d["v"])
            bw = int(d.get("bw", 0))
            wt = float(d.get("weight", 1.0))
            pu = d.get("p_u"); pv = d.get("p_v")
            for e in _snapshot["links"]:
                if {e["u"], e["v"]} == {u, v}:
                    e["bw"], e["weight"] = bw, wt
                    if pu is not None and pv is not None:
                        if e["u"] == u: e["p_u"], e["p_v"] = int(pu), int(pv)
                        else:           e["p_u"], e["p_v"] = int(pv), int(pu)
                    changed = True; return
            newe = {"u": u, "v": v, "bw": bw, "weight": wt}
            if pu is not None and pv is not None:
                newe["p_u"], newe["p_v"] = int(pu), int(pv)
            _snapshot["links"].append(newe)
            for n in (u, v):
                if n not in _snapshot["nodes"]:
                    _snapshot["nodes"].append(n)
            changed = True

        def del_link(d):
            nonlocal changed
            u, v = str(d["u"]), str(d["v"])
            before = len(_snapshot["links"])
            _snapshot["links"] = [e for e in _snapshot["links"] if {e["u"], e["v"]} != {u, v}]
            changed |= (len(_snapshot["links"]) != before)

        def add_node(sw):
            nonlocal changed
            if sw not in _snapshot["nodes"]:
                _snapshot["nodes"].append(sw); changed = True

        def del_node(sw):
            nonlocal changed
            if sw in _snapshot["nodes"]:
                _snapshot["nodes"].remove(sw)
                _snapshot["links"] = [e for e in _snapshot["links"] if sw not in (e["u"], e["v"])]
                changed = True

        def add_host(d):
            nonlocal changed
            hid = d.get("id") or (f"h{d['ip'].split('.')[-1]}" if d.get("ip") else None)
            if not hid: return
            for h in _snapshot["hosts"]:
                if h["id"] == hid:
                    h.update({k: d[k] for k in ("ip", "sw", "port") if k in d})
                    changed = True; return
            rec = {"id": hid, "ip": d.get("ip", ""), "sw": str(d.get("sw", "")), "port": int(d.get("port", 0))}
            _snapshot["hosts"].append(rec); changed = True

        def del_host(d):
            nonlocal changed
            hid = d.get("id"); ip = d.get("ip")
            if hid:
                before = len(_snapshot["hosts"])
                _snapshot["hosts"] = [h for h in _snapshot["hosts"] if h["id"] != hid]
                changed |= (len(_snapshot["hosts"]) != before)
            elif ip:
                before = len(_snapshot["hosts"])
                _snapshot["hosts"] = [h for h in _snapshot["hosts"] if h.get("ip") != ip]
                changed |= (len(_snapshot["hosts"]) != before)

        if etype == "link_add": add_link(data)
        elif etype == "link_delete": del_link(data)
        elif etype == "switch_enter": add_node(str(data.get("sw")))
        elif etype == "switch_leave": del_node(str(data.get("sw")))
        elif etype == "host_add": add_host(data)
        elif etype == "host_del": del_host(data)
        elif etype in ("port_down", "port_up"):
            pass
        else:
            return jsonify(error=f"unknown type {etype}"), 400

        if changed:
            _bump_version_locked()
            _emit({"type": "topology", "data": _snapshot})

    _emit({"type": etype, "data": data, "at": time.time()})
    return jsonify(status="ok")


# ---- Endpoints de MÉTRICAS --------------------------------------------------
@app.get("/metrics")
def get_metrics():
    """Devuelve las métricas más recientes (enlace y red)."""
    with _lock:
        m = dict(_last_metrics)
    return jsonify(m)


@app.get("/metrics/link")
def get_link_metric():
    """Métrica puntual de un enlace (?u= & v=)."""
    u = request.args.get("u"); v = request.args.get("v")
    if not u or not v:
        return jsonify(error="Faltan u y v"), 400
    with _lock:
        m = _lookup_link_metric(u, v, _last_metrics)
    if not m:
        return jsonify(error="sin datos para ese enlace (¿aún sin deltas o sin puertos p_u/p_v?)"), 404
    return jsonify(m)


@app.get("/metrics/path")
def get_path_metrics():
    """Métricas de camino para 1..k rutas candidatas (usa métricas actuales)."""
    src, dst = request.args.get("src"), request.args.get("dst")
    k = int(request.args.get("k", "1"))
    if not src or not dst:
        return jsonify(error="query params: src, dst"), 400
    if k < 1 or k > 10:
        return jsonify(error="k debe estar entre 1 y 10"), 400

    with _lock:
        snap = _snapshot.copy()
        excluded = set(_excluded_links)
        metrics = dict(_last_metrics)

    G = nx.Graph()
    for n in snap.get("nodes", []):
        G.add_node(str(n))
    for e in snap.get("links", []):
        u, v = str(e["u"]), str(e["v"])
        if tuple(sorted((u, v))) in excluded:
            continue
        G.add_edge(u, v, weight=float(e.get("weight", 1.0)))

    if not G.has_node(src) or not G.has_node(dst):
        return jsonify(error="Nodo inexistente"), 404

    try:
        paths = []
        gen = nx.shortest_simple_paths(G, src, dst, weight="weight")
        for _ in range(k):
            paths.append(next(gen))
    except StopIteration:
        if not locals().get("paths"):
            return jsonify(error="No hay camino"), 404

    out = _path_metrics(paths, metrics)
    return jsonify(out)


# ---- Healthcheck ------------------------------------------------------------
@app.get("/healthz")
def healthz():
    with _lock:
        age = max(0.0, time.time() - float(_snapshot.get("ts", 0.0)))
        ver = int(_snapshot.get("version", 0))
        nodes = len(_snapshot.get("nodes", []))
        links = len(_snapshot.get("links", []))
        hosts = len(_snapshot.get("hosts", []))
        metrics_age = max(0.0, time.time() - float(_last_metrics.get("ts", 0.0)))
    out = {
        "controller_url": CONTROLLER,
        "controller_ok": _last_controller_ok,
        "last_controller_contact": _last_controller_ts,
        "snapshot_age_sec": round(age, 3),
        "version": ver,
        "counts": {"nodes": nodes, "links": links, "hosts": hosts},
        "excluded_links": sorted([list(t) for t in _excluded_links]),
        "polling_enabled": ENABLE_POLLING,
        "poll_interval": POLL_INTERVAL,
        "metrics_age_sec": round(metrics_age, 3),
        "metrics_links": len(_last_metrics.get("link_metrics", []))
    }
    return jsonify(out)


# ----------------------------------------------------------------------------
if __name__ == "__main__":
    threading.Thread(target=poller, daemon=True).start()
    print("NetWeb backend en http://0.0.0.0:5000  (frontend en /)")
    app.run(host="0.0.0.0", port=5000, threaded=True)
