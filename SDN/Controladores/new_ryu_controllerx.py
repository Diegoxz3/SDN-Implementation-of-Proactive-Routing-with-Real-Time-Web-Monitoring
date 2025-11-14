#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ==============================================================================
# CONTROLADOR RYU PARA ENRUTAMIENTO PROACTIVO + PUSH DE EVENTOS A BACKEND
# ==============================================================================
#
# Mantiene la lógica original (topología, rutas proactivas, REST /set_mode|/reinstall|/topology)
# y agrega:
#   - Envío de eventos incrementales al backend Flask (POST /ryu/events) con token.
#   - Eventos: switch_enter/leave, link_add/delete, host_add, port_up/down.
#   - Versiones "hops" (saltos) y "distrak" (1/bw) intactas.
#   - Logs más claros y robustez en detección de puertos/hosts.
#
# VARIABLES DE ENTORNO (opcional):
#   NETWEB_BACKEND   (URL del backend Flask; p.ej. http://192.168.0.119:5000)
#   NETWEB_TOKEN     (token Bearer para POST /ryu/events en Flask)
#   PUSH_TIMEOUT     (segundos; por defecto 2.5)
#
# Requiere que ryu-manager cargue también el módulo REST de topología:
#   ryu-manager --ofp-tcp-listen-port 6653 --observe-links ryu.app.rest_topology ~/ryu_apps/ryu_controllerx_push.py
#
# Nota: Para enviar eventos se usa 'requests'. Instalar si hace falta:
#   pip install requests
# ==============================================================================

import os
import json
import threading
from collections import defaultdict

import requests
import networkx as nx

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, CONFIG_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.topology import event, api as topo_api
from ryu.app.wsgi import WSGIApplication, ControllerBase, route, Response


# ========================= CONFIG PUSH BACKEND ==========================

BACKEND = os.getenv("NETWEB_BACKEND", "http://127.0.0.1:5000")
PUSH_TOKEN = os.getenv("NETWEB_TOKEN", "changeme-token")
PUSH_TIMEOUT = float(os.getenv("PUSH_TIMEOUT", "2.5"))


def undirected_key(a, b):
    return (a, b) if a < b else (b, a)


def ip_of(i: int) -> str:
    return f"10.0.0.{i}"


class _BackendPusher:
    """Pequeña cola asincrónica para no bloquear el hilo de eventos de Ryu."""
    def __init__(self, url: str, token: str, timeout: float = 2.5, maxsize: int = 512):
        self.url = url.rstrip("/") + "/ryu/events"
        self.token = token
        self.timeout = timeout
        self.q = []
        self.lock = threading.Lock()
        self.sem = threading.Semaphore(0)
        self.worker = threading.Thread(target=self._loop, daemon=True)
        self.worker.start()

    def push(self, etype: str, data: dict) -> None:
        payload = {"type": etype, "data": data}
        with self.lock:
            if len(self.q) >= 512:
                # drop más viejo (backpressure)
                self.q.pop(0)
            self.q.append(payload)
        self.sem.release()

    def _loop(self):
        s = requests.Session()
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        while True:
            self.sem.acquire()
            with self.lock:
                if not self.q:
                    continue
                item = self.q.pop(0)
            try:
                s.post(self.url, headers=headers, data=json.dumps(item), timeout=self.timeout)
            except Exception:
                # swallow y continuar; es un canal de "mejora", no crítico
                pass


# ==============================================================================
# CLASE PRINCIPAL DEL CONTROLADOR
# ==============================================================================

API_INSTANCE = 'PR_APP_INSTANCE'
NUM_HOSTS = 14


class ProactiveRouting(app_manager.RyuApp):
    _CONTEXTS = {'wsgi': WSGIApplication}
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(ProactiveRouting, self).__init__(*args, **kwargs)

        # ========== REGISTRO DE API REST ==========
        wsgi = kwargs['wsgi']
        wsgi.register(RestAPI, {API_INSTANCE: self})

        # ========== PUSHER BACKEND ==========
        self.pusher = _BackendPusher(BACKEND, PUSH_TOKEN, PUSH_TIMEOUT)

        # ========== VARIABLES DE ESTADO PRINCIPAL ==========
        self.mode = 'hops'  # 'hops' o 'distrak'

        self.G = nx.Graph()
        self.adj = {}
        self.datapaths = {}
        self.sw_all_ports = defaultdict(set)
        self.sw_link_ports = defaultdict(set)
        self.host_port = {}

        # ========== TABLA DE ANCHO DE BANDA - NUEVA TOPOLOGÍA ==========
        self.link_bw = {
            # Zona Izquierda (switches 1, 2, 3)
            undirected_key(1, 3): 45,
            undirected_key(1, 2): 50,
            undirected_key(1, 6): 30,
            undirected_key(3, 2): 35,

            # Zona Centro-Izquierda (switches 6, 7)
            undirected_key(6, 7): 40,
            undirected_key(2, 4): 25,

            # Zona Centro-Superior (switch 3, 9)
            undirected_key(3, 9): 20,

            # Zona Centro (switches 6, 7, 11)
            undirected_key(6, 11): 35,
            undirected_key(7, 8): 30,
            undirected_key(7, 4): 40,

            # Zona Este-Centro (switches 8, 9)
            undirected_key(8, 9): 25,

            # Zona Sur (switches 4, 5, 14)
            undirected_key(4, 5): 45,
            undirected_key(4, 14): 30,

            # Zona Este (switches 9, 10)
            undirected_key(9, 10): 35,

            # Zona Derecha-Superior (switches 11, 12, 13)
            undirected_key(11, 12): 50,
            undirected_key(5, 10): 20,
            undirected_key(10, 12): 30,
            undirected_key(11, 13): 25,
            undirected_key(10, 13): 40,

            # Zona Extremo Derecho (switches 12, 14)
            undirected_key(12, 14): 35,
        }
        self.default_bw = 10

    # ==================================================================
    # EVENTOS DEL CANAL DE CONTROL / TOPOLOGÍA
    # ==================================================================
    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, CONFIG_DISPATCHER, DEAD_DISPATCHER])
    def _state_change(self, ev):
        dp = ev.datapath
        if ev.state in (MAIN_DISPATCHER, CONFIG_DISPATCHER):
            self.datapaths[dp.id] = dp
        elif ev.state == DEAD_DISPATCHER:
            self.datapaths.pop(dp.id, None)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def _switch_features(self, ev):
        dp = ev.msg.datapath
        ofp = dp.ofproto
        parser = dp.ofproto_parser

        # Regla LLDP -> CONTROLLER
        match_lldp = parser.OFPMatch(eth_type=0x88cc)
        actions_lldp = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        inst_lldp = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions_lldp)]
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=500, match=match_lldp, instructions=inst_lldp))

        # Regla TABLE-MISS -> DROP
        match_any = parser.OFPMatch()
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=0, match=match_any, instructions=[]))

        # Pedir descripción de puertos
        req = parser.OFPPortDescStatsRequest(dp, 0)
        dp.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def _port_desc_reply(self, ev):
        dp = ev.msg.datapath
        ofp = dp.ofproto
        ports = set()
        for p in ev.msg.body:
            if p.port_no < ofp.OFPP_MAX:
                ports.add(p.port_no)
        self.sw_all_ports[dp.id] = ports
        self.logger.info("s%d: puertos válidos %s", dp.id, sorted(list(ports)))
        self._rebuild_graph_and_push()

    @set_ev_cls(event.EventSwitchEnter)
    def _on_switch_enter(self, ev):
        sw = getattr(ev, "switch", None)
        swid = getattr(getattr(sw, "dp", None), "id", None)
        if swid:
            self.pusher.push("switch_enter", {"sw": str(swid)})
        self.logger.info("Switch enter -> reconstruir grafo + flujos")
        self._rebuild_graph_and_push()

    @set_ev_cls(event.EventSwitchLeave)
    def _on_switch_leave(self, ev):
        sw = getattr(ev, "switch", None)
        swid = getattr(getattr(sw, "dp", None), "id", None)
        if swid:
            self.pusher.push("switch_leave", {"sw": str(swid)})
        self.logger.info("Switch leave -> reconstruir grafo + flujos")
        self._rebuild_graph_and_push()

    @set_ev_cls(event.EventLinkAdd)
    def _on_link_add(self, ev):
        lk = getattr(ev, "link", None)
        if lk and lk.src and lk.dst:
            u, v = lk.src.dpid, lk.dst.dpid
            data = {
                "u": str(u),
                "v": str(v),
                "p_u": int(lk.src.port_no),
                "p_v": int(lk.dst.port_no),
                "bw": int(self.link_bw.get(undirected_key(u, v), self.default_bw)),
                "weight": float(1.0 / self.link_bw.get(undirected_key(u, v), self.default_bw) if self.mode == "distrak" else 1.0),
            }
            self.pusher.push("link_add", data)
        self.logger.info("Link add -> reconstruir grafo + flujos")
        self._rebuild_graph_and_push()

    @set_ev_cls(event.EventLinkDelete)
    def _on_link_delete(self, ev):
        lk = getattr(ev, "link", None)
        if lk and lk.src and lk.dst:
            u, v = lk.src.dpid, lk.dst.dpid
            data = {"u": str(u), "v": str(v)}
            self.pusher.push("link_delete", data)
        self.logger.info("Link delete -> reconstruir grafo + flujos")
        self._rebuild_graph_and_push()

    @set_ev_cls(event.EventHostAdd)
    def _on_host_add(self, ev):
        try:
            host = getattr(ev, "host", None)
            ip = ""
            if host is not None:
                if getattr(host, "ipv4", None):
                    # host.ipv4 suele ser lista
                    ip = host.ipv4[0] if host.ipv4 else ""
                sw = host.port.dpid
                port = host.port.port_no
                hid = f"h{ip.split('.')[-1]}" if ip else f"h{sw}_{port}"
                self.pusher.push("host_add", {"id": hid, "ip": ip, "sw": str(sw), "port": int(port)})
        except Exception as e:
            self.logger.warning("HostAdd parse error: %s", e)

    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
    def _on_port_status(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp = dp.ofproto
        desc = msg.desc  # OFPPort
        port_no = int(desc.port_no)

        # Determinar up/down
        # Si el bit OFPPS_LIVE no está, consideramos "down"
        state = getattr(desc, "state", 0)
        OFPPS_LIVE = getattr(ofp, "OFPPS_LIVE", 0)
        is_up = bool(state & OFPPS_LIVE)
        etype = "port_up" if is_up else "port_down"
        self.pusher.push(etype, {"sw": str(dp.id), "port": port_no})

        # Re-construcción no siempre es necesaria, pero ayuda a reflejar rápido
        self._rebuild_graph_and_push()

    # ==================================================================
    # LÓGICA DE PROVISIONAMIENTO DE FLUJOS (igual al original)
    # ==================================================================
    def _install_base_rules(self, dp):
        ofp = dp.ofproto
        parser = dp.ofproto_parser

        match_lldp = parser.OFPMatch(eth_type=0x88cc)
        actions_lldp = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        inst_lldp = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions_lldp)]
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=500, match=match_lldp, instructions=inst_lldp))

        match_any = parser.OFPMatch()
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=0, match=match_any, instructions=[]))

    def _rebuild_graph_and_push(self):
        self._build_graph()

        if self.G.number_of_nodes() == 0:
            self.logger.warning("Grafo vacío (¿iniciaste con --observe-links y ryu.app.rest_topology?)")
            return

        self._deduce_host_ports()
        self._clear_all_flows()
        self._install_all_destinations()

    def _build_graph(self):
        self.G.clear()
        self.adj.clear()
        self.sw_link_ports.clear()

        switches = topo_api.get_all_switch(self)
        links = topo_api.get_all_link(self)

        for sw in switches:
            self.G.add_node(sw.dp.id)

        for lk in links:
            u, v = lk.src.dpid, lk.dst.dpid

            self.adj[(u, v)] = lk.src.port_no
            self.adj[(v, u)] = lk.dst.port_no

            self.sw_link_ports[u].add(lk.src.port_no)
            self.sw_link_ports[v].add(lk.dst.port_no)

            bw = self.link_bw.get(undirected_key(u, v), self.default_bw)
            weight = (1.0 / bw) if self.mode == 'distrak' else 1.0

            self.G.add_edge(u, v, bw=bw, weight=weight)

        self.logger.info("Grafo listo: %d nodos, %d enlaces (modo=%s)",
                         self.G.number_of_nodes(),
                         self.G.number_of_edges(),
                         self.mode)

    def _deduce_host_ports(self):
        self.host_port.clear()

        for dpid in self.G.nodes:
            allp = self.sw_all_ports.get(dpid, set())
            linkp = self.sw_link_ports.get(dpid, set())
            cand = allp - linkp

            if len(cand) == 1:
                hp = next(iter(cand))
            elif len(cand) > 1:
                hp = min(cand)
                self.logger.warning("s%d: múltiples candidatos host-port %s -> uso %d", dpid, sorted(list(cand)), hp)
            else:
                hp = 1
                self.logger.warning("s%d: sin candidato claro a host-port -> asumo 1", dpid)

            self.host_port[dpid] = hp
            self.logger.info("s%d: host-port = %d", dpid, hp)

    def _clear_all_flows(self):
        for dpid, dp in self.datapaths.items():
            ofp = dp.ofproto
            parser = dp.ofproto_parser

            mod = parser.OFPFlowMod(
                datapath=dp,
                command=ofp.OFPFC_DELETE,
                out_port=ofp.OFPP_ANY,
                out_group=ofp.OFPG_ANY
            )
            dp.send_msg(mod)
            self._install_base_rules(dp)

    def _install_all_destinations(self):
        for j in range(1, NUM_HOSTS + 1):
            dst_ip = ip_of(j)
            dst_sw = j

            if dst_sw not in self.G:
                self.logger.warning("s%d (destino de %s) no está en el grafo", dst_sw, dst_ip)
                continue

            self._install_tree_to_destination(dst_sw, dst_ip)

        self.logger.info("Flujos proactivos instalados para todos los destinos.")

    def _install_tree_to_destination(self, dst_sw: int, dst_ip: str):
        for u in self.G.nodes:
            if u == dst_sw:
                out_port = self.host_port.get(dst_sw, 1)
            else:
                try:
                    path = nx.shortest_path(self.G, source=u, target=dst_sw, weight='weight')
                    if len(path) < 2:
                        continue
                    v = path[1]
                    out_port = self.adj.get((u, v))
                    if out_port is None:
                        continue
                except nx.NetworkXNoPath:
                    continue

            dp = self.datapaths.get(u)
            if not dp:
                continue

            parser = dp.ofproto_parser
            ofp = dp.ofproto

            actions = [parser.OFPActionOutput(out_port)]
            inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]

            # Regla IPv4
            match_ip = parser.OFPMatch(eth_type=0x0800, ipv4_dst=dst_ip)
            mod_ip = parser.OFPFlowMod(datapath=dp, priority=100, match=match_ip, instructions=inst)
            dp.send_msg(mod_ip)

            # Regla ARP
            match_arp = parser.OFPMatch(eth_type=0x0806, arp_tpa=dst_ip)
            mod_arp = parser.OFPFlowMod(datapath=dp, priority=100, match=match_arp, instructions=inst)
            dp.send_msg(mod_arp)

    # ==================================================================
    # API PÚBLICA (igual que original)
    # ==================================================================
    def set_mode(self, new_mode: str):
        assert new_mode in ('hops', 'distrak'), "Modo debe ser 'hops' o 'distrak'"
        if new_mode != self.mode:
            self.mode = new_mode
            self.logger.info("Modo cambiado a %s", self.mode)
            self._rebuild_graph_and_push()

    def reinstall(self):
        self._rebuild_graph_and_push()


# ==============================================================================
# REST API
# ==============================================================================

class RestAPI(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(RestAPI, self).__init__(req, link, data, **config)
        self.app = data[API_INSTANCE]

    @route('pr', '/set_mode', methods=['POST'])
    def set_mode(self, req, **kwargs):
        try:
            body = json.loads(req.body.decode('utf-8'))
            mode = body.get('mode')

            if mode not in ('hops', 'distrak'):
                return Response(status=400,
                                body=b'{"error":"mode must be hops|distrak"}',
                                content_type='application/json')

            self.app.set_mode(mode)

            return Response(status=200,
                            body=json.dumps({"mode": self.app.mode}).encode('utf-8'),
                            content_type='application/json')

        except Exception as e:
            return Response(status=500,
                            body=json.dumps({"error": str(e)}).encode('utf-8'),
                            content_type='application/json')

    @route('pr', '/reinstall', methods=['POST'])
    def reinstall(self, req, **kwargs):
        self.app.reinstall()
        return Response(status=200,
                        body=b'{"status":"reinstalled"}',
                        content_type='application/json')

    @route('pr', '/topology', methods=['GET'])
    def topology(self, req, **kwargs):
        nodes = list(self.app.G.nodes)
        links = []
        for (u, v, data) in self.app.G.edges(data=True):
            links.append({
                "u": u,
                "v": v,
                "bw": data.get("bw"),
                "weight": data.get("weight")
            })
        payload = {
            "mode": self.app.mode,
            "nodes": nodes,
            "links": links
        }
        return Response(status=200,
                        body=json.dumps(payload).encode('utf-8'),
                        content_type='application/json')
