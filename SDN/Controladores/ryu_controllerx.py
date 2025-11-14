#!/usr/bin/env python3
# =============================================================================================================================================
# CONTROLADOR RYU PARA ENRUTAMIENTO PROACTIVO
# =============================================================================================================================================

#===================================== LIBRERIAS ===============================================================================================
"""
#from ryu.base import app_manager  #Contiene la clase base y utilidades para crear aplicaciones Ryu.

app_manager.RyuApp : Da hooks y el contexto para manejar eventos OpenFlow y registrar extensiones (WSGI, etc.).

#from ryu.controller import ofp_event #Define eventos asociados a OpenFlow que Ryu publica cuando ocurren mensajes del switch (Se usa decoradores para escuchar eventos)

#from ryu.controller.handler import MAIN_DISPATCHER, CONFIG_DISPATCHER, DEAD_DISPATCHER, set_ev_cls 
MAIN_DISPATCHER: canal OpenFlow activo; se pueden instalar flujos y manejar tráfico
CONFIG_DISPATCHER: fase temprana (intercambio de características).
DEAD_DISPATCHER: datapath desconectado; útil para limpiar estructuras y eliminar datapaths.
set_ev_cls es el decorador que se aplica a métodos para indicar “este método maneja tal evento cuando el datapath está en tal estado(s)”

#from ryu.ofproto import ofproto_v1_3 #Obtener constantes y estructuras para la versión OpenFlow 1.3 (OFP_MATCH_*, OFP_FLOW_MOD)

ofproto_v1_3 también da ofp.OFPP_CONTROLLER, OFPCML_NO_BUFFER, y constantes usadas en acciones y flow-mods.

#from ryu.topology import event, api as topo_api 

ryu.topology.event contiene eventos de descubrimiento de topología 
(p. ej. EventSwitchEnter, EventSwitchLeave, EventLinkAdd, EventLinkDelete). 
Los usas para reaccionar cuando aparecen switches o enlaces (tu controlador escucha EventSwitchEnter y EventLinkAdd).

topo_api (alias para ryu.topology.api) es la API programática que te permite consultar la información de topología que Ryu ha descubierto: 
get_all_switch(self), get_all_link(self) (los invocas en _build_graph() 
para obtener switches y enlaces detectados por LLDP/Topology discovery).

#from ryu.app.wsgi import WSGIApplication, ControllerBase, route, Response

WSGIApplication es el módulo que agrega una API REST a la aplicación Ryu mediante WSGI. 
Al registrar WSGIApplication en _CONTEXTS, Ryu instancia un servidor HTTP que sirve rutas REST definidas por tu app.
ControllerBase es la clase base para definir controladores REST que reciben peticiones;
RestAPI(ControllerBase) extiende esto para definir endpoints (/set_mode, /reinstall, /topology)
route es un decorador para registrar rutas REST con verbos HTTP (methods=['POST'] / GET) y path
Response encapsula respuestas HTTP (status, body, content_type) que devuelves desde los handlers REST.
Permitiendo cambiar el modo del controlador (hops/distrak) por HTTP y obtener la topología vía JSON sin tocar el código Ryu directamente.

#import json

Se usa para serializar/deserializar JSON en la API REST (leer req.body con json.loads, devolver json.dumps).
En tu REST API conviertes cuerpos HTTP a estructuras Python y devuelves JSON con payloads (topología, estado, etc.)

#import networkx as nx

Es la biblioteca Python para manipular grafos.
construir self.G = nx.Graph(),
añadir nodos y aristas (con atributos bw, weight),
calcular rutas más cortas con nx.shortest_path(..., weight='weight').
lógica de enrutamiento/proactividad: permite cambiar la métrica (peso inverso a ancho de banda o simple número de saltos) 
recalcular árboles de rutas con sus utilidades.

#from collections import defaultdict

defaultdict es una variante de dict que crea valores por defecto al acceder claves inexistentes 
(ej. defaultdict(set) crea automáticamente un set() la primera vez que se usa una clave).


"""

from ryu.base import app_manager  
from ryu.controller import ofp_event 
from ryu.controller.handler import MAIN_DISPATCHER, CONFIG_DISPATCHER, DEAD_DISPATCHER, set_ev_cls 
from ryu.ofproto import ofproto_v1_3 
from ryu.topology import event, api as topo_api 
from ryu.app.wsgi import WSGIApplication, ControllerBase, route, Response

import json
import networkx as nx
from collections import defaultdict

# ========================= CONSTANTES GLOBALES ==========================

"""
API_INSTANCE Es un nombre de clave (string) usado cuando se registra la aplicación Ryu en el WSGIApplication y cuando instancias el RestAPI.
API_INSTANCE es un identificador consistente y único para recuperar el objeto principal del controlador desde los handlers REST

NUM_HOST Valor entero (14) que representa el número total de hosts en la topología Mininet
Usado  en _install_all_destinations() para iterar los destinos h1..h14.

"""
API_INSTANCE = 'PR_APP_INSTANCE'
NUM_HOSTS = 14

# ========================= FUNCIONES AUXILIARES ==========================

"""
ip_of(i: int) Dada una entrada i (entero), devuelve la cadena con la IP de host correspondiente: 10.0.0.<i>.

undirected_key(a, b) Dada una pareja de nodos (a, b), devuelve una tupla ordenada cuyo primer elemento es el menor entre a y b.
representa una arista no dirigida de forma única independientemente del orden en que se pase.

En self.link_bw se guarda bws para enlaces que son no dirigidos (el enlace s1-s3 es el mismo que s3-s1).
Si usas (a, b) o (b, a) arbitrariamente como clave en un dict, terminarás con duplicados o lookup fallidos. 
undirected_key garantiza una clave canónica para el par.

"""

def ip_of(i: int) -> str:
    return f"10.0.0.{i}"

def undirected_key(a, b):
    return (a, b) if a < b else (b, a)

# ==============================================================================
#                     CLASE PRINCIPAL DEL CONTROLADOR 
"""
ProactiveRouting es la clase principal del controlador Ryu.

Esta clase se ejecuta dentro del controlador SDN Ryu y es la responsable de:

Detectar switches y enlaces en la red (topología).
Mantener una representación del grafo de la red usando NetworkX.
Calcular rutas (según el modo elegido: hops o ancho de banda).
Instalar flujos proactivos (de ahí el nombre) en los switches.
Exponer una API REST para monitoreo o control externo.

"""
# ==============================================================================

"""
Al heredar de app_manager.RyuApp, la clase automáticamente puede recibir eventos, enviar mensajes OpenFlow, y usar el sistema de contexto de Ryu.

Ryu tiene un sistema de “contextos” que te permite compartir instancias entre aplicaciones 
habilita la interfaz web REST (a través de WSGI).

Indica que este controlador usa OpenFlow versión 1.3
Esto asegura que los mensajes flow_mod, packet_in, etc. usen los formatos de OpenFlow 1.3.
"""

class ProactiveRouting(app_manager.RyuApp):
    _CONTEXTS = { 'wsgi': WSGIApplication }
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]


    """
    Llama al constructor de la clase base RyuApp
    Esto inicializa las estructuras internas del framework (eventos, logs, canales OpenFlow, etc.).
    Los argumentos *args y **kwargs permiten que Ryu pase automáticamente parámetros como el contexto wsgi.
    """

    def __init__(self, *args, **kwargs):
        super(ProactiveRouting, self).__init__(*args, **kwargs)
        
        # ========== REGISTRO DE API REST ==========
        """
        Se recibe el objeto wsgi que Ryu inyectó gracias al _CONTEXTS anterior.
        Luego se registra una clase llamada RestAPI
        Le pasas un diccionario {API_INSTANCE: self} para que la clase REST tenga acceso a esta instancia del controlador.
        Esto crea una API web REST que te permitirá consultar y modificar parámetros del controlador
        (por ejemplo, cambiar el modo de enrutamiento o ver la topología) a través de peticiones HTTP.
        """
        wsgi = kwargs['wsgi']
        wsgi.register(RestAPI, {API_INSTANCE: self})

        # ========== VARIABLES DE ESTADO PRINCIPAL ==========

        """
        Alternar entre diferentes políticas de enrutamiento.
        'hops' : calcula la ruta más corta según número de saltos.
        'bw' o 'bandwidth' : podría calcular la ruta con mayor ancho de banda disponible.
        """
        self.mode = 'hops'  


        """
        Crea un grafo no dirigido usando NetworkX
        Nodos = switches (DPIDs)
        Aristas = enlaces entre switches, con atributos como bw o delay
        Luego se usa para calcular rutas (shortest_path, max_bandwidth_path, etc.).
        """
        self.G = nx.Graph()


        """
        Diccionario auxiliar que guardará la tabla de adyacencias: qué switches están conectados a cuáles.
        Es útil para acceder rápido a vecinos sin recorrer todo el grafo de NetworkX.
        """
        self.adj = {}


        """
        Guarda todos los switches registrados (su datapath), usando el DPID como clave:
        self.datapaths[dpid] = datapath_object
        El datapath es el objeto que representa una conexión entre el controlador y un switch OpenFlow.
        Este objeto se usa para enviar mensajes OpenFlow al switch (como flow_mod, packet_out, etc.).
        """
        self.datapaths = {}


        """
        Guarda todos los puertos conocidos de cada switch.
        self.sw_all_ports[1] = {1, 2, 3, 4}
        Se llena cuando el controlador recibe mensajes de descubrimiento (EventSwitchEnter, EventLinkAdd).
        """
        self.sw_all_ports  = defaultdict(set)

        
        """
        Guarda los puertos de cada switch que están conectados a otros switches (no a hosts)
        self.sw_link_ports[1] = {2,3,4} significa que los puertos 2,3 y 4    de s1 conectan con otros switches.
        Es clave para distinguir qué puertos son “enlaces internos del backbone” y cuáles son hacia hosts finales.
        """
        self.sw_link_ports = defaultdict(set)

        """
        Guarda en qué puerto está conectado cada host a su switch.
        self.host_port[1] = 1 → el host h1 está en el puerto 1 de su switch (s1).
        """
        self.host_port = {}

        # ========== TABLA DE ANCHO DE BANDA  ==========
        # ESTA ES LA ÚNICA PARTE QUE CAMBIA SUSTANCIALMENTE

        """
        tabla manual de capacidades de enlace (en Mbps) para cada enlace del backbone
        Cada clave es un par (a, b) de switches normalizado con undirected_key(a, b)
        Cada valor es el ancho de banda asignado a ese enlace, usado para calcular métricas de ruta o mostrar estadísticas.

        Ryu no obtiene automáticamente el “bw” de los enlaces de Mininet, así que se define aquí manualmente.
        """
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
        
        #Si el controlador descubre un enlace que no está en la tabla link_bw, le asigna 10 Mbps como valor por defecto.
        #También sirve como valor base para los enlaces “desconocidos”.
        self.default_bw = 10


    """
    _state_change: Monitorea los cambios de estado de los switches (conectados, configurando, desconectados).
    Esta función registra o elimina switches activos según el estado del canal OpenFlow entre el controlador y el switch.

    ev (evento): contiene información del evento generado por Ryu, en este caso, el cambio de estado del switch.
    dp (datapath): representa la conexión entre el controlador y el switch OpenFlow. Es el objeto que usamos para enviar mensajes
    (como FlowMod, StatsRequest, etc.).

    Estados:

    CONFIG_DISPATCHER: el switch está conectado y enviando sus capacidades iniciales (etapa de configuración).
    MAIN_DISPATCHER:   el switch ya está completamente conectado y operativo.
    DEAD_DISPATCHER:   el switch ha perdido conexión o se desconectó.

    Si el switch entra en CONFIG o MAIN
    → Se añade a la lista de datapaths activos:

    Si el switch pasa a DEAD_DISPATCHER
    → Se elimina de la lista de datapaths activos:

    Esto evita que el controlador intente comunicarse con switches desconectados.

    """


    @set_ev_cls(ofp_event.EventOFPStateChange,
                [MAIN_DISPATCHER, CONFIG_DISPATCHER, DEAD_DISPATCHER])
    def _state_change(self, ev):
        dp = ev.datapath
        if ev.state in (MAIN_DISPATCHER, CONFIG_DISPATCHER):
            self.datapaths[dp.id] = dp
        elif ev.state == DEAD_DISPATCHER:
            self.datapaths.pop(dp.id, None)



    """
    Esta función se ejecuta una sola vez por switch, justo después de que este se conecta y envía su mensaje FeaturesReply.
    Aquí el controlador instala las reglas base obligatorias en la tabla de flujos del switch.
    dp: objeto Datapath, que representa el switch.
    ofp: contiene las constantes OpenFlow (por ejemplo, OFPP_CONTROLLER, OFPCML_NO_BUFFER, etc.)
    parser: se usa para construir mensajes OpenFlow, como OFPMatch, OFPActionOutput, OFPFlowMo

    """

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def _switch_features(self, ev):
        dp = ev.msg.datapath
        ofp = dp.ofproto
        parser = dp.ofproto_parser

        # Regla LLDP -> CONTROLLER

        """
        eth_type=0x88cc: coincide con tramas LLDP (Link Layer Discovery Protocol). Ryu (y Mininet) las usa para descubrir la topología.
        Acción: enviar el paquete al controlador (OFPP_CONTROLLER).
        priority=500: le da alta prioridad para que estas tramas siempre se procesen primero.
        Propósito: Permite que Ryu detecte automáticamente los enlaces entre switches y hosts.
        """
        match_lldp = parser.OFPMatch(eth_type=0x88cc)
        actions_lldp = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        inst_lldp = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions_lldp)]
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=500,
                                      match=match_lldp, instructions=inst_lldp))

        # Regla TABLE-MISS -> DROP

        """
        OFPMatch() vacío: coincide con cualquier paquete que no cumpla con ninguna otra regla.
        Sin instrucciones: significa descartar el paquete (no se reenvía ni se envía al controlador).
        priority=0: prioridad más baja.
        Esta regla asegura que los paquetes desconocidos no saturen el controlador, mejorando rendimiento y seguridad.
        """
        match_any = parser.OFPMatch()
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=0,
                                      match=match_any, instructions=[]))

        # Solicitar descripción de puertos
        """
        Envía un mensaje al switch para obtener información de sus puertos físicos, como:
        Número de puerto
        Estado (UP/DOWN)
        Nombre del puerto
        Velocidad (ancho de banda)
        Esta información luego se usa para:
        Construir el grafo self.G
        Asociar enlaces con sus puertos reales (self.sw_link_ports)
        Calcular rutas o métricas de topología
        """
        req = parser.OFPPortDescStatsRequest(dp, 0)
        dp.send_msg(req)

    """
    Recibe la respuesta del switch con la descripción de sus puertos físicos, procesa esa información y la usa para reconstruir la topología

    ¿Qué evento maneja esto y cuándo se ejecuta?
    El decorador indica que este método se ejecuta cuando Ryu recibe la respuesta a una petición PortDescStatsRequest.
    El contexto MAIN_DISPATCHER significa que el datapath (switch) ya está totalmente operativo y listo para intercambiar estadísticas/flows.
    Cuando el switch responde con la lista de puertos, Ryu dispara este handler con el evento

    """

    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def _port_desc_reply(self, ev):

        """
        dp es el datapath (objeto que representa el switch conectado). Lo usarás como identificador y para enviar/recibir mensajes.
        ofp = dp.ofproto es una referencia a las constantes de OpenFlow
        ports = set() prepara un contenedor (set) para almacenar números de puerto físicos sin duplicados
        """
        dp = ev.msg.datapath
        ofp = dp.ofproto
        ports = set()

        """
        ev.msg.body Es una lista de objetos con información sobre cada puerto reportado por el switch 
        (cada p típicamente tiene atributos como port_no, name, hw_addr, config, state, curr, advertised, supported, etc.).
        Es la descripción completa de cada puerto físico o lógico que el switch conoce.

        En OpenFlow existen puertos “especiales/reservados”, con números altos que no representan interfaces físicas
        FPP_MAX es la constante que marca el límite superior de puertos físicos numerados; 
        los puertos con port_no >= OFPP_MAX son puertos especiales y normalmente no interesan al mapa físico de la red.
        Resultado: ports contendrá únicamente números de puerto físicos del switch (por ejemplo {1,2,3,4}), sin los especiales.
        """
        for p in ev.msg.body:
            if p.port_no < ofp.OFPP_MAX:
                ports.add(p.port_no)

        """
        self.sw_all_ports es un defaultdict(set) donde la clave es el dpid (por ejemplo 1 para s1) y el valor es el conjunto de puertos válidos.
        Guardar esta info es necesario para distinguir puertos que conectan a hosts y puertos que conectan a otros switches (separación host/link).

        logger.info registra la lista de puertos en el log (ordenada para legibilidad). Útil para depuración: verás en la consola algo como 
        s1: puertos válidos [1, 2, 3].

        Tras actualizar los puertos conocidos del switch, el controlador reconstruye el grafo de la topología y reinstala flujos proactivos.
        El conocimiento de puertos es necesario para asociar cada enlace descubierto
        (topo_api.get_all_link()) con los números de puerto correctos (p. ej. s1 tiene enlace con s2 por su port_no X).
        Si no tienes la lista de puertos, no puedes mapear correctamente enlaces a puertos ni deducir qué puerto es hacia el host.

        _rebuild_graph_and_push() a su vez llama a _build_graph(), _deduce_host_ports(),
        _clear_all_flows() y _install_all_destinations() — que usan self.sw_all_ports para deducir self.host_port y construir la topología.

        """
        self.sw_all_ports[dp.id] = ports
        self.logger.info("s%d: puertos válidos %s", dp.id, sorted(list(ports)))
        self._rebuild_graph_and_push()

    """
    event.EventSwitchEnter : Se emite cuando el topology discovery de Ryu detecta que un switch se ha unido al dominio gestionado por el controlador
    Un switch establece la conexión OpenFlow con Ryu (handshake y FeaturesReply), o
    El módulo de topología de Ryu recibe suficiente información para considerar presente al switch.

    cada vez que aparece un nuevo switch o un nuevo enlace, el controlador reconstruye su grafo de topología y 
    reinstala los flujos proactivos (operación central del controlador).
    """

    @set_ev_cls(event.EventSwitchEnter)
    def _on_switch_enter(self, ev):
        self.logger.info("Switch enter -> reconstruir grafo + flujos")
        self._rebuild_graph_and_push()

    """
    Se emite cuando Ryu detecta un nuevo enlace entre dos switches. La detección de enlaces en Ryu se basa mayoritariamente en LLDP
    los switches envían/reciben tramas LLDP y Ryu, al recibirlas/reportarlas, infiere que existe un enlace src -> dst
    El evento incluye información sobre el enlace (DPIDs de extremos y puertos).
    cada vez que aparece un nuevo switch o un nuevo enlace, el controlador reconstruye su grafo de topología y 
    reinstala los flujos proactivos (operación central del controlador).
    """

    @set_ev_cls(event.EventLinkAdd)
    def _on_link_add(self, ev):
        self.logger.info("Link add -> reconstruir grafo + flujos")
        self._rebuild_graph_and_push()


    """
    Consistency: Cuando cambia la topología (nuevo switch o enlace) la información que usa para calcular rutas puede estar obsoleta.

    Reconstruir el grafo asegura que:
    self.G contenga la lista actualizada de nodos y aristas.
    self.adj, self.sw_link_ports, self.host_port reflejen la realidad.
    Proactividad: Este controlador instala flujos proactivos para todos los destinos. 
    Si cambia la topología, las rutas optimas pueden cambiar y hay que recalcular y
    volver a instalar los flujos para mantener un encaminamiento correcto.
    Sencillez: Es una política simple: ante cualquier cambio de topología, 
    recalcula todo. Evita intentar parchar solo partes del grafo, lo que reduce errores lógicos.
    """

    # ==============================================================================
    # MÉTODOS DE LÓGICA PRINCIPAL
    # ==============================================================================

    """
    Esta función instala las reglas base o mínimas que todo switch controlado por Ryu debe tener antes de configurar el resto de los flujos.
    En esencia, realiza dos tareas fundamentales:
    
    Permitir que los paquetes LLDP lleguen al controlador (para descubrir la topología).
    Definir una regla por defecto de “table-miss” que descarta cualquier paquete no coincidente.
    """

    """
    dp (datapath) representa al switch OpenFlow conectado.
    ofp contiene las constantes del protocolo OpenFlow (como puertos especiales y tipos de mensajes)
    parser permite construir mensajes OpenFlow (por ejemplo, OFPFlowMod, OFPMatch, OFPActionOutput, etc.).
    """

    def _install_base_rules(self, dp):
        ofp = dp.ofproto
        parser = dp.ofproto_parser

        """
        Se crea una regla de coincidencia (match) que identifica paquetes con campo EtherType = 0x88cc, 
        que corresponde al protocolo LLDP (Link Layer Discovery Protocol).
        Este protocolo se usa para descubrir enlaces entre switches.
        """
        match_lldp = parser.OFPMatch(eth_type=0x88cc)

        """
        Se define la acción a ejecutar cuando un paquete coincide con la regla anterior:
        OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER) indica que el paquete se debe enviar al controlador.
        OFPCML_NO_BUFFER significa que se envía el paquete completo, no solo una parte.
        """
        actions_lldp = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]

        """
        Aquí se encapsulan las acciones dentro de una instrucción de tipo “apply-actions”, 
        que es el formato exigido por OpenFlow para indicar qué hacer con un paquete que coincide con un match.
        """
        inst_lldp = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions_lldp)]

        """
        Se construye un mensaje OFPFlowMod (modificación de flujo) y se envía al switch.
        priority=500: define que esta regla tiene prioridad media-alta 
        (por encima de la regla de “table-miss”, pero por debajo de otras reglas específicas).
        match=match_lldp: condición de coincidencia → LLDP.
        instructions=inst_lldp: acciones → enviar al controlador.
        """
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=500,
                                      match=match_lldp, instructions=inst_lldp))
        
        """
        Crea un match vacío, es decir, que coincide con cualquier paquete (sin condición específica).
        Esta es la típica forma de representar una regla “table-miss” en OpenFlow.
        """
        match_any = parser.OFPMatch()

        """
        Instala una regla de prioridad 0 (la más baja posible).
        Tiene un match que captura todos los paquetes no coincidentes con reglas anteriores.
        instructions=[] indica que no se realiza ninguna acción → el paquete se descarta.
        """
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=0,
                                      match=match_any, instructions=[]))
        

    """


    Esta función _rebuild_graph_and_push() se ejecuta cada vez que cambia la topología de la red por ejemplo : 
    Cuando entra un nuevo switch (EventSwitchEnter),
    Cuando se agrega un nuevo enlace (EventLinkAdd),
    O cuando se actualizan los puertos (EventOFPPortDescStatsReply).

    En esencia, su propósito es reconstruir la visión global de la red (grafo de topología) y 
    reinstalar las reglas de reenvío (flows) en todos los switches de manera proactiva.

    """    
    def _rebuild_graph_and_push(self):

        """
        Esta llamada genera (o actualiza) el grafo de topología de red self.G
        usando la información que el controlador Ryu ha recopilado mediante LLDP

        self.G es un objeto de tipo networkx.Graph(), donde:
        Cada nodo representa un switch OpenFlow o un host,
        Cada arista (enlace) representa una conexión física entre puertos (switch-switch o host-switch).

        Qué hace internamente:
        Toma los enlaces detectados por los mensajes LLDP recibidos.
        Asocia los IDs de los switches con sus puertos.
        Añade al grafo los pesos de los enlaces, que pueden basarse en la latencia (delay) o ancho de banda (bw).
        """
        self._build_graph()
        
        """
        Esta verificación comprueba si el grafo quedó vacío, es decir, sin nodos detectados.
        Puede darse si Ryu no recibió aún ningún paquete LLDP → por tanto, no conoce ningún enlace.
        El usuario no ejecutó Mininet con la opción --controller=remote o sin --observe-links, lo que impide el intercambio de LLDP.
        """
        if self.G.number_of_nodes() == 0:
            self.logger.warning("Grafo vacío (¿arrancaste con --observe-links y LLDP punt?)")
            return
        

        """
        Esta llamada analiza los datos de la topología (self.adj) y de los switches (self.sw_all_ports)
        para deducir qué puertos de cada switch están conectados directamente a hosts (no a otros switches).
        Esto es clave, porque el controlador necesita saber por qué puerto debe enviar paquetes hacia un host final.
        Si el host h1 está conectado al switch s1 por el puerto 1,
        entonces la función guardará algo como:

        self.host_port[1] = { '10.0.0.1': 1 }
        Significa: “en el switch 1, el host con IP 10.0.0.1 está en el puerto 1”.
        """
        self._deduce_host_ports()
        
        """
        Esta función elimina todas las reglas de flujo existentes en los switches registrados.
        Cuando la topología cambia (nuevo enlace, switch caído, etc.), las reglas antiguas pueden volverse inválidas o ineficientes.
        Por eso, antes de instalar nuevas rutas, se limpia la tabla de flujos.
        """
        self._clear_all_flows()
        
        """
        Finalmente, esta llamada instala todas las rutas proactivas en los switches, basándose en el grafo actualizado (self.G).
        El controlador calcula el camino óptimo entre cada par de switches/hosts (por número de saltos o por ancho de banda, según el modo).
        Luego instala flujos OFPFlowMod en cada switch intermedio para que los paquetes viajen automáticamente por ese camino.
        el tráfico fluirá automáticamente sin intervención reactiva (de ahí el nombre ProactiveRouting).
        """
        self._install_all_destinations()


    """
    _build_graph, Construye o recontruye la topología lógica de la red dentro del controlador SDN
    es decir, una representación abstracta de los switches y enlaces que existen actualmente en la red.

    Este grafo servirá luego para calcular rutas, instalar flujos, detectar fallos, etc.
    Internamente, la topología se modela usando una estructura de grafo (normalmente con la librería networkx).

    """

    def _build_graph(self):

        """
        self.G → Es el grafo de la red ( networkx.Graph()).
        self.adj → Es un diccionario que guarda los puertos de salida de cada enlace, es decir, qué puerto conecta un switch con otro.
        self.sw_link_ports → Es un diccionario que asocia a cada switch con el conjunto de puertos utilizados en enlaces (no los de hosts).

        Antes de reconstruir la topología, limpia todos los datos previos para evitar que queden restos de configuraciones antiguas o enlaces caídos.
        Esto es clave en entornos SDN donde los enlaces pueden cambiar dinámicamente.
        """
        self.G.clear()
        self.adj.clear()
        self.sw_link_ports.clear()


        """
        topo_api.get_all_switch(self) → Devuelve una lista de todos los switches detectados por el controlador 
        (gracias a los mensajes LLDP y eventos del Ryu Topology API).

        topo_api.get_all_link(self) → Devuelve una lista de todos los enlaces detectados entre switches
        (también gracias al descubrimiento LLDP).

        """
        switches = topo_api.get_all_switch(self)
        links = topo_api.get_all_link(self)

        """
        Cada switch se agrega como un nodo del grafo, identificado por su dp.id (Datapath ID).
        """
        for sw in switches:
            self.G.add_node(sw.dp.id)

        """
        Agregar enlaces (edges) y asociar puertos
        Cada Link tiene dos extremos: un origen (lk.src) y un destino (lk.dst), ambos con:
        
        dpid → ID del switch
        port_no → número de puerto de conexión

        Por ejemplo, si s1 se conecta a s2 por el puerto 3 en s1 y el puerto 1 en s2, entonces

        u = 1  # s1
        v = 2  # s2
        lk.src.port_no = 3
        lk.dst.port_no = 1

        """
        for lk in links:
            u, v = lk.src.dpid, lk.dst.dpid

            """
            self.adj[(1,2)] = 3 → el puerto 3 de s1 lleva hacia s2
            self.adj[(2,1)] = 1 → el puerto 1 de s2 lleva hacia s1
            """
            self.adj[(u, v)] = lk.src.port_no
            self.adj[(v, u)] = lk.dst.port_no


            """
            Tambien se agrega
            self.sw_link_ports[1].add(3)
            self.sw_link_ports[2].add(1)
            Así, el controlador sabe qué puertos están ocupados por enlaces inter-switch.
            """
            self.sw_link_ports[u].add(lk.src.port_no)
            self.sw_link_ports[v].add(lk.dst.port_no)


            """
            Cálculo del ancho de banda y peso del enlace
            self.link_bw → Diccionario que guarda el ancho de banda (en Mbps, por ejemplo) de cada enlace.
            undirected_key(u, v) → Devuelve una clave única (sin dirección) para identificar un enlace 
            por ejemplo (1,2) y (2,1) se consideran iguales).
            Si no existe ese enlace en self.link_bw, usa un valor por defecto: self.default_bw
            """
            bw = self.link_bw.get(undirected_key(u, v), self.default_bw)

            """
            Luego define el peso del enlace, que se usa para calcular rutas más cortas en el grafo.

            Si self.mode == 'distrak' (modo “distribución adaptativa” o “dijkstra con tráfico”):
            se usa weight = 1 / bw, es decir, cuanto mayor ancho de banda, menor peso → rutas preferidas por enlaces más rápidos.

            En otro caso, todos los enlaces tienen el mismo peso (=1), como en un Dijkstra clásico por número de saltos.
            """
            if self.mode == 'distrak':
                weight = 1.0 / bw
            else:
                weight = 1.0

            """
            Aquí se agrega el enlace bidireccional al grafo, con atributos:
            bw → ancho de banda
            weight → peso para cálculos de ruta
            """
            self.G.add_edge(u, v, bw=bw, weight=weight)

        """
        Finalmente, el controlador imprime un log informativo indicando:
        cuántos nodos (switches) detectó,
        cuántos enlaces encontró, y en qué modo está operando (distrak o normal).
        """

        self.logger.info("Grafo listo: %d nodos, %d enlaces (modo=%s)",
                         self.G.number_of_nodes(), 
                         self.G.number_of_edges(), 
                         self.mode)
        

    """
    Esta función _deduce_host_ports() es clave para que el controlador sepa en qué puerto de cada switch está conectado el host dentro de la red.

    El controlador Ryu descubre los puertos conectados entre switches usando LLDP, pero no sabe directamente cuál puerto va al host.
    Esta función deduce ese puerto de forma lógica, analizando los datos que ya tiene
    """
    def _deduce_host_ports(self):
        """
        Se limpia el diccionario self.host_port, que almacena el número de puerto del switch donde está conectado el host correspondiente.
        """
        self.host_port.clear()


        """
        Se recorre cada nodo del grafo (cada switch detectado en la red).
        El identificador dpid (Datapath ID) representa el switch.
        """
        for dpid in self.G.nodes:

            """
            Obtener los conjuntos de puertos:

            self.sw_all_ports[dpid] → conjunto con todos los puertos válidos del switch. 
            Estos puertos fueron detectados en el evento EventOFPPortDescStatsReply.
            self.sw_all_ports[1] = {1, 2, 3, 4}

            self.sw_link_ports[dpid] → conjunto de puertos usados para enlaces entre switches (detectados en _build_graph()).
            self.sw_link_ports[1] = {2, 3, 4}
            Por tanto, los puertos que no están en sw_link_ports son candidatos a estar conectados con hosts.
            """
            allp  = self.sw_all_ports.get(dpid, set())
            linkp = self.sw_link_ports.get(dpid, set())

            """
            Cálculo de los posibles puertos hacia hosts
            Se hace una resta de conjuntos:
            todos los puertos del switch (allp) menos los usados para enlaces (linkp).
            """
            cand = allp - linkp

            """
            Análisis de los casos posibles 
            La función maneja tres casos:
        
            Si solo hay un puerto posible, entonces ese es el puerto del host (hp).

            Si hay más de un puerto posible, el controlador elige el menor número de puerto por defecto (min(cand)),
            pero muestra una advertencia en el log para que el administrador lo sepa.

            Si no hay ningún puerto candidato (posiblemente un error de detección LLDP o topología incompleta),
            se asume por defecto que el puerto 1 es el puerto del host.

            """
            if len(cand) == 1:
                hp = next(iter(cand))
            elif len(cand) > 1:
                hp = min(cand)
                self.logger.warning("s%d: múltiples candidatos host-port %s -> uso %d", 
                                    dpid, sorted(list(cand)), hp)
            else:
                hp = 1
                self.logger.warning("s%d: sin candidato claro a host-port -> asumo 1", dpid)

            """
            Finalmente, se guarda en el diccionario host_port el resultado para ese switch,
            y se imprime un mensaje informativo indicando qué puerto fue identificado como host-port.
            """    
            
            self.host_port[dpid] = hp
            self.logger.info("s%d: host-port = %d", dpid, hp)

    """
    La función _clear_all_flows() tiene como misión borrar todas las reglas de flujo existentes en los switches y 
    luego restaurar las reglas base mínimas (LLDP y table-miss).

    Esto asegura que el controlador no acumule reglas viejas o inconsistentes cada vez que se reconstruye la red
    (por ejemplo, cuando cambia la topología).
    “Deja todos los switches en estado limpio y listo para volver a programarse correctamente”.
    """        

    def _clear_all_flows(self):

        """
        Recorriendo los switches activos
        self.datapaths es un diccionario donde:
        La clave dpid es el identificador único del switch.
        El valor dp es el objeto Datapath, que representa la conexión activa entre el controlador y el switch.

        self.datapaths = {
            1: <ryu.controller.controller.Datapath objeto s1>,
            2: <ryu.controller.controller.Datapath objeto s2>,
            3: <ryu.controller.controller.Datapath objeto s3>
        }

        Por tanto, el bucle itera sobre cada switch conectado al controlador.

        ofp → contiene constantes del protocolo (por ejemplo OFPFC_DELETE, OFPP_ANY, etc.)
        parser → tiene los constructores de mensajes (por ejemplo OFPFlowMod, OFPMatch, etc.
        """
        for dpid, dp in self.datapaths.items():
            ofp = dp.ofproto
            parser = dp.ofproto_parser

            """
            Creación del mensaje OFPFlowMod para borrar flujos
            datapath=dp: Indica el switch al que se enviará el mensaje
            command=ofp.OFPFC_DELETE: Le dice al switch: “Borra todas las reglas de flujo que coincidan con los criterios siguientes”.
            out_port=ofp.OFPP_ANY y out_group=ofp.OFPG_ANY: Usando ANY, significa que no se filtra ningún flujo: se borran todas las reglas instaladas, 
            sin importar el puerto o el grupo de salida.
            Este mensaje elimina todos los flujos instalados en la tabla de ese switch.
            """
            mod = parser.OFPFlowMod(
                datapath=dp,
                command=ofp.OFPFC_DELETE,
                out_port=ofp.OFPP_ANY,
                out_group=ofp.OFPG_ANY
            )

            """
            El controlador envía el mensaje OFPFlowMod al switch correspondiente.
            El switch, al recibirlo, limpia toda su tabla de flujo.
            table=0: (vacía)
            """
            dp.send_msg(mod)

            """
            Una vez que el switch quedó vacío, se llama a _install_base_rules(dp) para volver a instalar las reglas mínimas necesarias
            """
            self._install_base_rules(dp)

    """
    Esta función se encarga de instalar flujos proactivos hacia todos los hosts destino de la red, es decir, 
    preconfigura las rutas desde todos los switches hacia cada host, sin esperar a que el tráfico comience a circular.

    Construye y aplica las reglas de encaminamiento (flow entries) para que todos los paquetes IP destinados a cualquier host de la red 
    ya tengan su camino predefinido desde el inicio.
    """        
    def _install_all_destinations(self):

        """
        Se recorre una lista de todos los hosts conectados a la red, desde h1 hasta hNUM_HOSTS.
        Esto implica que se configurará una ruta hacia cada host destino.

        dst_ip = ip_of(j) obtiene la dirección IP del host hj
        Por ejemplo, si ip_of(3) retorna "10.0.0.3", significa que ese es el IP del host destino h3

        dst_sw = j asume que el host hj está conectado al switch sj
        Esto es cierto en topologías simples donde cada host está directamente asociado a un switch
        """
        for j in range(1, NUM_HOSTS + 1):
            dst_ip = ip_of(j)
            dst_sw = j

            """
            Aquí se verifica si el switch destino (sX) está presente en el grafo self.G
            Se emite una advertencia (logger.warning) en la consola de Ryu indicando que ese destino no se puede procesar.
            Se usa continue para saltar al siguiente host sin intentar instalar flujos para este.
            """
            if dst_sw not in self.G:
                self.logger.warning("s%d (destino de %s) no está en el grafo", dst_sw, dst_ip)
                continue

            """
            Llama a otra función del controlador que instala todos los flujos hacia ese destino (dst_ip) en la red.
            Esta función es clave: probablemente usa algoritmos de árbol de caminos más cortos (shortest path tree) 
            para determinar por qué puerto debe salir un paquete en cada switch para llegar al host destino
            De esta manera, construye un árbol de encaminamiento proactivo para el tráfico con destino a dst_ip

            Ej: Para llegar a 10.0.0.3, instala en cada switch una regla que indique por cuál puerto reenviar los paquetes 
            que tengan ese destino IP.
            """
            self._install_tree_to_destination(dst_sw, dst_ip)

        """
        Una vez completado el ciclo, el controlador imprime un mensaje informando que todas las reglas proactivas se instalaron correctamente.
        """    
        self.logger.info("Flujos proactivos instalados para todos los destinos.")


    """
    _install_tree_to_destination : instala flujos proactivos en cada switch u del grafo para que todo tráfico con destino dst_ip 
    sea reenviado correctamente hacia dst_sw (el switch al que está conectado ese host). Instala reglas tanto para IPv4 como para ARP.

    self.G: grafo NetworkX con nodos = dpids (switch ids) y aristas entre switches.

    self.adj[(u,v)]: puerto de salida en u hacia su vecino v.

    self.host_port[dpid]: puerto del switch dpid donde está conectado su host.

    self.datapaths[dpid]: objeto Datapath (conexión OpenFlow) para el switch dpid.

    """

    def _install_tree_to_destination(self, dst_sw: int, dst_ip: str):

        """
        Recorre cada switch u en el grafo.
        """
        for u in self.G.nodes:

            """
            Caso: u == dst_sw (switch destino)
            Si u es el switch donde está el host destino, el puerto de salida (out_port) será el host-port de ese switch (desde self.host_port).
            get(dst_sw, 1) usa 1 como fallback si no hay entrada (por seguridad).

            Efecto práctico: en el switch destino la regla enviará los paquetes hacia el puerto que conecta con el host final.
            """
            if u == dst_sw:
                out_port = self.host_port.get(dst_sw, 1)
            else:
                """
                Caso: u != dst_sw (switch intermedio)
                Calcula path = camino más corto desde u hasta dst_sw usando el atributo weight de las aristas (nx.shortest_path(..., weight='weight')).
                Si path existe y tiene al menos 2 nodos, v = path[1] es el siguiente salto desde u hacia dst_sw.
                out_port = self.adj.get((u, v)) obtiene el número de puerto local en u que conecta con v.

                """
                try:
                    path = nx.shortest_path(self.G, source=u, target=dst_sw, weight='weight')
                    if len(path) < 2:
                        continue
                    v = path[1]
                    out_port = self.adj.get((u, v))

                    """
                    Si no hay camino (NetworkXNoPath) o no hay puerto (out_port is None), no instala flujo en u y continúa.
                    """
                    if out_port is None:
                        continue
                except nx.NetworkXNoPath:
                    continue

                #Ejemplo: si path = [1, 2, 5, 8] (de u=1 a dst_sw=8) entonces v = 2 y out_port será el puerto en s1 que apunta a s2.

            """
            Obtener datapath y validar
            Recupera el objeto Datapath asociado a u. Si no está conectado al controlador (no hay dp), salta ese u.
            """
            dp = self.datapaths.get(u)
            if not dp:
                continue

            """
            Construir acción e instrucción OpenFlow:

            Crea la acción: OFPActionOutput(out_port) → enviar paquetes por out_port.
            Encapsula la acción en una instrucción apply-actions, lista para OFPFlowMod.
            """
            parser = dp.ofproto_parser
            ofp = dp.ofproto
            actions = [parser.OFPActionOutput(out_port)]
            inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]


            # Regla IPv4
            """
            Crea un match que selecciona paquetes IPv4 cuyo ipv4_dst == dst_ip.
            Construye un FlowMod con priority=100 (nota: prioridad intermedia).
            Envía el FlowMod al switch dp. Resultado: paquetes IPv4 dirigidos a dst_ip serán reenviados por out_port.
            """
            match_ip = parser.OFPMatch(eth_type=0x0800, ipv4_dst=dst_ip)
            mod_ip = parser.OFPFlowMod(datapath=dp, priority=100, match=match_ip, instructions=inst)
            dp.send_msg(mod_ip)

            """
            Ejemplo concreto: para dst_ip = "10.0.0.4" y u=1 con out_port=3, en s1 se instalaria:
            Si recibe paquete IPv4 con dst 10.0.0.4 → output:3.
            """


            # Regla ARP
            """
            Crea match que selecciona paquetes ARP cuyo arp_tpa (target protocol address) es dst_ip.
            Instala flujo idéntico (misma instrucción output), con la misma prioridad 100.
            """
            match_arp = parser.OFPMatch(eth_type=0x0806, arp_tpa=dst_ip)
            mod_arp = parser.OFPFlowMod(datapath=dp, priority=100, match=match_arp, instructions=inst)
            dp.send_msg(mod_arp)

            """
            Efecto: consultas ARP dirigidas a la IP destino también serán encaminadas por el mismo puerto que el tráfico IPv4, 
            evitando la necesidad de enviar las ARP al controlador o flood.
            """

    # ==============================================================================
    # MÉTODOS DE API PÚBLICA
    # ==============================================================================

    """
    diseñados para ser llamados desde fuera del flujo interno de eventos de Ryu.
    Pueden ser invocados, por ejemplo:

    Desde una interfaz de administración del controlador,
    O mediante una API REST si este controlador se integra con un servicio web,
    O incluso desde otro módulo Python (otra aplicación Ryu) para modificar el comportamiento del controlador en tiempo real.

    En concreto, permiten:

    Cambiar el modo de cálculo de rutas (set_mode()).
    Reinstalar todas las reglas de flujo desde cero (reinstall()).
    """

    """
    Permitir cambiar la estrategia de cálculo de rutas que usa el controlador entre dos modos posibles:

    'hops' → rutas con peso uniforme (minimiza el número de saltos).

    'distrak' → rutas con peso inverso al ancho de banda (1/bw), es decir, prefiere enlaces de mayor capacidad.
    """
    def set_mode(self, new_mode: str):
        """
        Usa una aserción para asegurarse de que el valor recibido sea uno de los dos válidos.
        Si alguien llama set_mode("otro"), el controlador lanzará un error AssertionError.
        """
        assert new_mode in ('hops', 'distrak'), "Modo debe ser 'hops' o 'distrak'"

        """
        Si el modo es diferente al actual (self.mode), lo actualiza.
        Registra en el log del controlador un mensaje de confirmación.
        Finalmente llama a _rebuild_graph_and_push(), lo que:
        Reconstruye el grafo con los nuevos pesos (_build_graph()).
        Limpia todas las tablas de flujo en los switches (_clear_all_flows()).
        Vuelve a instalar todas las reglas de encaminamiento para todos los destinos (_install_all_destinations()).
        """
        if new_mode != self.mode:
            self.mode = new_mode
            self.logger.info("Modo cambiado a %s", self.mode)
            self._rebuild_graph_and_push()


    """
    Permite reinstalar todos los flujos proactivos sin cambiar el modo actual.
    Este método es útil si, por ejemplo:

    Se reconectan switches,Se actualizan los enlaces, O se modifican manualmente las tablas de flujo (y quieres restaurar el estado inicial).

    Reconstruir el grafo (_build_graph()),
    Deducir los puertos de host (_deduce_host_ports()),
    Borrar todos los flujos (_clear_all_flows()),
    Volver a instalar las reglas para todos los destinos (_install_all_destinations()).
    """        
    def reinstall(self):
        self._rebuild_graph_and_push()


# ==============================================================================
# CLASES REST API (Controlador Programable desde fuera de Ryu)
# ==============================================================================

"""
Define una clase llamada RestAPI que extiende ControllerBase, una clase base proporcionada por Ryu WSGI (Web Server Gateway Interface).
Esto convierte el controlador en un servidor HTTP interno, capaz de exponer endpoints REST (como /set_mode, /reinstall, /topology).
"""
#Hereda de ControllerBase, la clase que Ryu usa para manejar rutas REST.
#Su constructor (__init__) recibe varios parámetros del entorno WSGI (como la solicitud HTTP req, la conexión link, y los datos compartidos data).
#Guarda una referencia a la aplicación principal (self.app), es decir, a tu clase ProactiveRouting, que fue registrada en el controlador con:
#wsgi.register(RestAPI, {API_INSTANCE: self})
#De este modo, self.app te da acceso completo al controlador desde las rutas REST.
class RestAPI(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(RestAPI, self).__init__(req, link, data, **config)
        self.app = data[API_INSTANCE]

    """
    Define un endpoint REST:
    URL → /set_mode
    Método HTTP → POST
    Prefijo de aplicación ('pr') → sirve para agrupar rutas relacionadas
    Permite cambiar el modo de operación del controlador ('hops' o 'distrak') desde una petición web.
    """    
    @route('pr', '/set_mode', methods=['POST'])
    def set_mode(self, req, **kwargs):
        try:

            """
            Lee el cuerpo de la petición HTTP (req.body).
            Lo decodifica desde bytes a texto y lo convierte a un diccionario JSON.
            Extrae el campo "mode" (por ejemplo "hops" o "distrak").

            Ejemplo de la peticion : 

            curl -X POST http://127.0.0.1:8080/set_mode -d '{"mode":"distrak"}' \
            -H "Content-Type: application/json"

            """
            body = json.loads(req.body.decode('utf-8'))
            mode = body.get('mode')

            """
            Si el valor no es válido, devuelve un HTTP 400 (Bad Request) con un mensaje de error JSON.
            """
            if mode not in ('hops', 'distrak'):
                return Response(status=400, 
                                body=b'{"error":"mode must be hops|distrak"}',
                                content_type='application/json')
            
            """
            Llama al método set_mode() de ProactiveRouting.
            Esto reconstruye el grafo, reinstala los flujos, y actualiza el modo de cálculo de rutas en tiempo real.
            """
            self.app.set_mode(mode)
            
            """
            Si todo va bien, devuelve un HTTP 200 OK con el nuevo modo activo en formato JSON.

            Ej:

            {
                "mode": "distrak"
            }

            """
            return Response(status=200, 
                            body=json.dumps({"mode": self.app.mode}).encode('utf-8'),
                            content_type='application/json')
        
        except Exception as e:
            return Response(status=500, 
                            body=json.dumps({"error": str(e)}).encode('utf-8'),
                            content_type='application/json')
        


    """
    Reinstalar flujos (/reinstall)
    Permite reinicializar completamente los flujos en todos los switches sin cambiar el modo actual.
    Es una especie de “botón de reinicio” para la red SDN.

    Llama al método self.app.reinstall() que hace:
    Reconstruir el grafo (_build_graph)
    Limpiar todos los flujos (_clear_all_flows)
    Volver a instalarlos (_install_all_destinations)

    Ejemplo: curl -X POST http://127.0.0.1:8080/reinstall

    {
    "status": "reinstalled"
    }

    """
    @route('pr', '/reinstall', methods=['POST'])
    def reinstall(self, req, **kwargs):
        self.app.reinstall()
        return Response(status=200, 
                        body=b'{"status":"reinstalled"}',
                        content_type='application/json')
    


    """
    Consultar topología (/topology)
    Expone un endpoint para ver la topología actual detectada por el controlador:
    Los nodos (switches),Los enlaces entre ellos, El ancho de banda (bw) y el peso (weight) de cada enlace, Y el modo de operación actua

    Ejemplo curl http://127.0.0.1:8080/topology

    {
        "mode": "distrak",
        "nodes": [1, 2, 3, 4, 5, 6],
        "links": [
          {"u": 1, "v": 2, "bw": 50, "weight": 0.02},
          {"u": 2, "v": 3, "bw": 35, "weight": 0.0285},
          {"u": 3, "v": 4, "bw": 25, "weight": 0.04}
        ]
    }

    """
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