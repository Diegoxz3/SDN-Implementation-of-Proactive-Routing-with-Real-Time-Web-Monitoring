#!/usr/bin/env python3
# Nueva Topología Personalizada (14 nodos, 20 enlaces) para Mininet + OVS
# Proactivo con RYU remoto (en otra VM).

import argparse #Definir y parsear argumentos de la linea de comandos ej: --controller_ip 192.168.18.40
from mininet.topo import Topo #Definir topologia de forma declarativa 
from mininet.link import TCLink #Clase de enlace que permite parámetros reales (bw, delay, loss, cola) usa las utilidades de tráfico del kernel (tc)
from mininet.net import Mininet #Crea y gestiona la red real basada en la topología. crea switches (OVS), hosts (namespaces), enlaces (veth pairs), configura IP, arranca controladores
from mininet.node import RemoteController # Indica que el controlador OpenFlow está en otra máquina; los switches se conectan a él.
from mininet.cli import CLI # Entrega la consola interactiva de Mininet (el prompt mininet>).


#se hereda de la clase Topo
"""
   Se define una nueva clase llamada CustomTopo, que hereda de la clase Topo

"""
class CustomTopo(Topo):

    """
    Se define build(self) para añadir hosts/switches/enlaces.
    Es un método sobrescrito (override) de la clase base Topo.
    Cuando Mininet crea tu topología, automáticamente llama a este método para “construir” los elementos que formarán la red virtual.

    """
    def build(self):
        # ==============================================================
        # 1) CREACIÓN DE SWITCHES 
        # ==============================================================

        """
        Forma compacta de crear un diccionario.

        switches = {}
        for i in range(1, 15):
           switch_name = 's%d' % i   # genera 's1', 's2', ..., 's14'
           switches[i] = self.addSwitch(switch_name)

        addSwitch: registra un switch virtual en la topologia 

        's%d' % i : si i=1 la salida sera 's1'

        estructura final del diccionario:

        {
            1: 's1',
            2: 's2',
            3: 's3',
            ...
            14: 's14'
        }

        """
        switches = {i: self.addSwitch('s%d' % i) for i in range(1, 15)}
        
        # ==============================================================
        # 2) CREACIÓN DE HOSTS Y ENLACES HOST-SWITCH 
        # ==============================================================
        for i in switches:
            # El for toma las llaves del diccionario switches
            h = self.addHost('h%d' % i, ip='10.0.0.%d/24' % i)

            #self.addHost          : Declarar un nuevo host dentro de la topologia
            #'h%d' % i             : nombre del host concuerda con el del switch asociado
            #ip='10.0.0.%d/24' % i : Asignacion de IP estatica todos los host en la misma red
            #self.addHost() devuelve un identificador interno del host (por ejemplo 'h1'), que aquí se guarda en la variable h.

            # Enlace host-switch     
            self.addLink(h, switches[i], cls=TCLink)

            # addLink() : Crea un enlace virtual entre dos nodos de la topología (en este caso, un host y su switch).
            # Un enlace en Mininet se implementa como un par de interfaces virtuales (veth pair).
            # Una interfaz se conecta al host.
            # La otra se conecta al switch.

            """
            Parámetros:

            h: es el host creado en la línea anterior ('h1', 'h2', ...).
            switches[i]: el switch correspondiente ('s1', 's2', ...).
            cls=TCLink: le dice a Mininet que el enlace se base en la clase TCLink (Traffic Control Link).
            ancho de banda ilimitado (o máximo disponible),
            sin retardo, sin pérdida, y con comportamiento estándar

            """
        
        # ==============================================================
        # 3) DEFINICIÓN DE ENLACES BACKBONE CON UNA LISTA DE TUPLAS
        # ==============================================================
        backbone_links = [
            # Zona Izquierda (switches 1, 2, 3)
            (1,  3,  45, '8ms'),    # s1-s3: enlace de alta capacidad
            (1,  2,  50, '7ms'),    # s1-s2: enlace principal (máximo BW)
            (1,  6,  30, '10ms'),   # s1-s6: conexión hacia centro
            (3,  2,  35, '6ms'),    # s3-s2: enlace local rápido
            
            # Zona Centro-Izquierda (switches 6, 7)
            (6,  7,  40, '9ms'),    # s6-s7: enlace centro importante
            (2,  4,  25, '11ms'),   # s2-s4: hacia zona sur
            
            # Zona Centro-Superior (switch 3, 9)
            (3,  9,  20, '12ms'),   # s3-s9: enlace de menor capacidad
            
            # Zona Centro (switches 6, 7, 11)
            (6, 11,  35, '8ms'),    # s6-s11: enlace centro-derecha
            (7,  8,  30, '10ms'),   # s7-s8: conexión este
            (7,  4,  40, '7ms'),    # s7-s4: enlace importante
            
            # Zona Este-Centro (switches 8, 9)
            (8,  9,  25, '9ms'),    # s8-s9: conexión norte-sur
            
            # Zona Sur (switches 4, 5, 14)
            (4,  5,  45, '6ms'),    # s4-s5: enlace sur de alta capacidad
            (4, 14,  30, '8ms'),    # s4-s14: hacia extremo derecho
            
            # Zona Este (switches 9, 10)
            (9, 10,  35, '10ms'),   # s9-s10: enlace este importante
            
            # Zona Derecha-Superior (switches 11, 12, 13)
            (11, 12, 50, '5ms'),    # s11-s12: enlace de máxima capacidad (backbone principal)
            (5, 10,  20, '11ms'),   # s5-s10: enlace de baja capacidad
            (10, 12, 30, '9ms'),    # s10-s12: conexión cruzada
            (11, 13, 25, '8ms'),    # s11-s13: hacia nodo extremo
            (10, 13, 40, '7ms'),    # s10-s13: enlace importante
            
            # Zona Extremo Derecho (switches 12, 14)
            (12, 14, 35, '10ms'),   # s12-s14: cierre del backbone
        ]

        """
        (nodo_a, nodo_b, bw, delay). 
        
        los nodos son las claves del diccionario switches
        bw: ancho de banda expresado en Mbps 
        delay: retraso expresado en ms

        """
        
        # ==============================================================
        # 4) CREACIÓN DE ENLACES BACKBONE 
        # ==============================================================

        """

        Con el for toma cada tupla y asigna sus valores a las variables a, b, bw, delay.

        self.addLink(switches[a], switches[b], cls=TCLink, ...) :  Aquí creas un enlace entre dos switches.

        Con switches[a] y switches[b] recuperas las referencias internas de los switches s1 y s2 creados antes.

        bw=bw : Establece el ancho de banda, TCLink aplica control de tráfico (HTB/TBF) para limitar el egress (salida) de paquetes y así forzar ese tope.

        delay=delay Añade retardo (latencia) con netem en ambas direcciones

        loss=0 : Configura porcentaje de pérdida de paquetes en ese enlace (0% aquí).

        max_queue_size=1000 : Define el tamaño máximo de cola en número de paquetes (valor en paquetes)

        use_htb=True : 
        Indica que se utilice HTB (Hierarchical Token Bucket) para shaping.
        HTB es un scheduler que permite garantizar tasas mínimas/máximas y agrupar clases. 
        TCLink usa HTB para aplicar las limitaciones de bw de forma estable y predecible, 
        en lugar de mecanismos más simples como tbf únicamente.
        HTB permite políticas más “suaves” y funciona bien para modelar enlaces con garantías de BW.

        """

        for a, b, bw, delay in backbone_links:
            self.addLink(
                switches[a], switches[b],
                cls=TCLink,
                bw=bw,
                delay=delay,
                loss=0,
                max_queue_size=1000,
                use_htb=True
            )

# Funcion: parse_args() : Define qué argumentos de línea de comandos acepta el script y parsea esos argumentos cuando se llama.

def parse_args():

    #Crea un parser que maneja los argumentos CLI. El argumento description se muestra cuando el usuario pide --help (es la descripción del programa).
    p = argparse.ArgumentParser(description="Topología Personalizada con RemoteController (RYU)")


    #Define un argumento opcional con nombre --controller_ip
    #required=True obliga a que el usuario debe proporcionar ese argumento
    p.add_argument("--controller_ip", type=str, required=True, 
                   help="IP del controlador RYU (VM remota)")
    
    #Define --controller_port que se convertirá a int
    #default=6653 significa que si no lo pasas, args.controller_port valdrá 6653
    p.add_argument("--controller_port", type=int, default=6653, 
                   help="Puerto OpenFlow del RYU (default 6653)")
    
    #p.parse_args() lee sys.argv (los argumentos que se pasaron al script), valida y convierte según lo definido, y devuelve un Namespace
    return p.parse_args()


"""
if __name__ == '__main__':

Es una guardia estándar en Python que asegura que el bloque que sigue sólo se ejecute si el archivo se corre directamente 
(python3 nsfnet_topologyx.py) y no si el archivo se importa como módulo desde otro script.

"""

if __name__ == '__main__':


    """
    args = parse_args()
    Llama a la función parse_args() ; obtiene args.controller_ip y args.controller_port.
    Esos valores serán usados para configurar el RemoteController.

    """
    args = parse_args()


    """
    topo = CustomTopo()

    Crea una instancia de tu topología.
    Al instanciar CustomTopo() Mininet no arranca nada todavía; simplemente construyes la descripción 
    (registro interno de hosts, switches y enlaces) porque tu CustomTopo.build() 
    ya añadió nodos y enlaces a la estructura de datos de la topología.
    Piensa en topo como el plano o “blueprint” de la red.

    """
    topo = CustomTopo()


    """

    topo = topo : Indica que la instancia net debe usar la topología que acabas de crear para materializar la red en el sistema cuando arranques.
    controller=None : Significa no crear automáticamente un controlador local por defecto, te deja añadir manualmente el controlador
    link=TCLink: Define la clase por defecto que se usará al crear enlaces si no se especifica otra

    autoStaticArp=True : 
    Muy útil para pruebas: hace que Mininet configure entradas ARP estáticas en los hosts, 
    basadas en las IPs que diste cuando creaste los hosts (10.0.0.X).

    Beneficio: evitas tráfico ARP (broadcasts) para resolución de direcciones durante las pruebas; 
    las respuestas ARP ya están en la tabla ARP de cada host. Esto acelera tests como pingall y evita resultados ruidosos por ARP.

    """
    
    net = Mininet(
        topo=topo,
        controller=None,
        link=TCLink,
        autoStaticArp=True
    )
    

    """

    creación del controlador remoto

    net.addController : registra un controlador en la red Mininet, configura el objeto controlador dentro de Mininet
    'c0' → nombre lógico del controlador en la topología.
    controller=RemoteController → tipo de controlador (indica conexión a controlador externo)
    ip=args.controller_ip, port=args.controller_port → dirección y puerto a los que los switches intentarán establecer la conexión OpenFlow.

    """
    c0 = net.addController(
        'c0',
        controller=RemoteController,
        ip=args.controller_ip,
        port=args.controller_port
    )
    

    """

    net.start() es la llamada que materializa toda la topología en el sistema. A grandes rasgos ocurren estos pasos

    Creación de switches (OVS bridges)
    Creación de hosts (namespaces) y sus interfaces
    Creación de enlaces (veth pairs)
    Configuración de tc en enlaces TCLink
    Conexión de switches al controlador
    Aplicación de flows iniciales (si hay)
    Activación de forwarding

    """
    net.start() #arranca la red (spawnea procesos y configura todo)
    
    print("\n=== Nueva Topología Personalizada iniciada ===")
    print("Controlador remoto: %s:%d" % (args.controller_ip, args.controller_port))
    print("Pruebas rápidas:")
    print("  mininet> pingall           # Prueba conectividad entre todos los hosts")
    print("  mininet> iperf h1 h14      # Mide ancho de banda entre h1 y h14")
    print("  mininet> nodes; links; net # Muestra información de la topología")
    print("  mininet> exit\n")


    """

    Abre el prompt de Mininet: mininet>.
    Desde ahí puedes ejecutar comandos de Mininet y comandos shell en hosts. Ejemplos prácticos:
    pingall — prueba conectividad ICMP entre todos los hosts. (Útil para verificar la topología completa).
    h1 ping -c3 10.0.0.14 — ejecuta ping desde h1 a h14.
    iperf h1 h14 o iperf3 — mide throughput entre hosts (si iperf está instalado).
    nodes — muestra hosts, switches y controladores creados.
    links — muestra enlaces y qué interfaces usan.
    net — muestra mapa de la topología.
    sh ovs-vsctl show — ejecuta comando de shell en el host (útil para inspeccionar OVS).
    h1 ifconfig — ver interfaces e IPs dentro de h1.
    exit — sale del CLI y sigue la ejecución (en tu script irá a net.stop()).
    Mientras estés en CLI, la red está activa; puedes hacer pruebas interactivas, capturas con tcpdump, o ejecutar scripts de prueba.

    """
    CLI(net) # Da una consola interactiva para probar


    """"
    net.stop() — limpieza y desmontaje
    Cuando terminas y el script llama a net.stop(), Mininet deshace todo lo creado:
    Mata procesos asociados (si los hubo).
    Quita qdiscs tc y clases asociadas a interfaces.
    Elimina veths y namespaces de hosts.
    Borra puentes OVS creados (bridges) y las interfaces virtuales.
    Libera recursos y devuelve el sistema a su estado previo (típicamente).
    Es importante usar net.stop() para evitar restos que afecten ejecuciones posteriores. Si abortas el script bruscamente (Ctrl+C) podrías necesitar limpiar manualmente (sudo mn -c o comandos ip link, ovs-vsctl).

    """
    net.stop() # Desmonta la red