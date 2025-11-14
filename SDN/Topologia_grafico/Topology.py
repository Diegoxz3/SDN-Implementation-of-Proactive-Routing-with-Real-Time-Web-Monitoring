#!/usr/bin/env python3
"""
Visualizador de Topología NSFNET - Versión Completa con Puertos e IPs
Topología con 14 switches, 14 hosts y 20 enlaces backbone

Requisitos:
    pip install networkx matplotlib

Uso:
    python visualizar_topologia.py
"""

import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

def crear_topologia_completa():
    """
    Crea la topología NSFNET completa con switches, hosts y enlaces.
    Incluye información de puertos e IPs basada en la salida de Mininet.
    """
    # Crear grafo no dirigido
    G = nx.Graph()
    
    # ========================================
    # AGREGAR SWITCHES (nodos 1-14)
    # ========================================
    for i in range(1, 15):
        G.add_node(f's{i}', tipo='switch', dpid=i)
    
    # ========================================
    # AGREGAR HOSTS CON IPs (h1-h14)
    # ========================================
    host_info = {
        'h1': '10.0.0.1',   'h2': '10.0.0.2',   'h3': '10.0.0.3',   'h4': '10.0.0.4',
        'h5': '10.0.0.5',   'h6': '10.0.0.6',   'h7': '10.0.0.7',   'h8': '10.0.0.8',
        'h9': '10.0.0.9',   'h10': '10.0.0.10', 'h11': '10.0.0.11', 'h12': '10.0.0.12',
        'h13': '10.0.0.13', 'h14': '10.0.0.14'
    }
    
    for i in range(1, 15):
        host = f'h{i}'
        G.add_node(host, tipo='host', ip=host_info[host])
        # Enlace host-switch (puerto 1 en switch para hosts)
        G.add_edge(host, f's{i}', tipo='access', 
                   puerto_host=f'{host}-eth0', 
                   puerto_switch=f's{i}-eth1')
    
    # ========================================
    # ENLACES BACKBONE CON PUERTOS
    # ========================================
    # Basado en la salida de "mininet> links"
    # Formato: (switch_a, switch_b, bw, delay, puerto_a, puerto_b)
    
    backbone_links = [
        # Zona Izquierda
        (1,  3,  45, '8ms', 's1-eth2', 's3-eth2'),    # s1-eth2<->s3-eth2
        (1,  2,  50, '7ms', 's1-eth3', 's2-eth2'),    # s1-eth3<->s2-eth2
        (1,  6,  10, '10ms', 's1-eth4', 's6-eth2'),   # s1-eth4<->s6-eth2
        (3,  2,  35, '6ms', 's3-eth3', 's2-eth3'),    # s3-eth3<->s2-eth3
        
        # Zona Centro-Izquierda
        (6,  7,  5, '9ms', 's6-eth3', 's7-eth2'),    # s6-eth3<->s7-eth2
        (2,  4,  25, '11ms', 's2-eth4', 's4-eth2'),   # s2-eth4<->s4-eth2
        
        # Zona Centro-Superior
        (3,  9,  50, '12ms', 's3-eth4', 's9-eth2'),   # s3-eth4<->s9-eth2
        
        # Zona Centro
        (6, 11,  35, '8ms', 's6-eth4', 's11-eth2'),   # s6-eth4<->s11-eth2
        (7,  8,  30, '10ms', 's7-eth3', 's8-eth2'),   # s7-eth3<->s8-eth2
        (7,  4,  40, '7ms', 's7-eth4', 's4-eth3'),    # s7-eth4<->s4-eth3
        
        # Zona Este-Centro
        (8,  9,  25, '9ms', 's8-eth3', 's9-eth3'),    # s8-eth3<->s9-eth3
        
        # Zona Sur
        (4,  5,  45, '6ms', 's4-eth4', 's5-eth2'),    # s4-eth4<->s5-eth2
        (4, 14,  30, '8ms', 's4-eth5', 's14-eth2'),   # s4-eth5<->s14-eth2
        
        # Zona Este
        (9, 10,  35, '10ms', 's9-eth4', 's10-eth2'),  # s9-eth4<->s10-eth2
        
        # Zona Derecha-Superior
        (11, 12, 50, '5ms', 's11-eth3', 's12-eth2'),  # s11-eth3<->s12-eth2
        (5, 10,  20, '11ms', 's5-eth3', 's10-eth3'),  # s5-eth3<->s10-eth3
        (10, 12, 30, '9ms', 's10-eth4', 's12-eth3'),  # s10-eth4<->s12-eth3
        (11, 13, 25, '8ms', 's11-eth4', 's13-eth2'),  # s11-eth4<->s13-eth2
        (10, 13, 40, '7ms', 's10-eth5', 's13-eth3'),  # s10-eth5<->s13-eth3
        
        # Zona Extremo Derecho
        (12, 14, 35, '10ms', 's12-eth4', 's14-eth3'), # s12-eth4<->s14-eth3
    ]
    
    # Agregar enlaces backbone con puertos
    for a, b, bw, delay, port_a, port_b in backbone_links:
        G.add_edge(
            f's{a}', f's{b}',
            tipo='backbone',
            bw=bw,
            delay=delay,
            weight=1/bw,
            puerto_a=port_a,
            puerto_b=port_b
        )
    
    return G

def posiciones_topologia_completa():
    """
    Define posiciones para switches y hosts con mayor separación.
    """
    # Posiciones de switches (con mayor escala para evitar solapamiento)
    pos_switches = {
        's1': (0, 3.5),      
        's2': (0, 1.5),    
        's3': (1.8, 4.5),
        's6': (2.5, 3.2),      
        's7': (3.2, 1.5),  
        's4': (2.5, -0.3),
        's9': (5, 4.5),      
        's8': (5, 2),      
        's5': (5, -1),
        's10': (7.5, 2.5),
        's11': (8.5, 4.5),     
        's12': (10, 3.2),     
        's13': (10, 1.3),   
        's14': (9, -0.3),
    }
    
    # Posiciones de hosts (desplazados de forma estratégica)
    # Ajustados para no solaparse con enlaces
    offsets = {
        'h1': (-0.7, -0.5),   'h2': (-0.7, -0.5),   'h3': (-0.5, 0.6),
        'h4': (-0.5, -0.7),   'h5': (0.5, -0.7),    'h6': (-0.5, 0.6),
        'h7': (0.5, -0.6),    'h8': (0.5, 0.6),     'h9': (-0.5, 0.6),
        'h10': (0.5, -0.6),   'h11': (-0.5, 0.6),   'h12': (0.7, 0.5),
        'h13': (0.7, -0.5),   'h14': (0.5, -0.7)
    }
    
    pos_hosts = {}
    for i in range(1, 15):
        sw_pos = pos_switches[f's{i}']
        offset = offsets[f'h{i}']
        pos_hosts[f'h{i}'] = (sw_pos[0] + offset[0], sw_pos[1] + offset[1])
    
    # Combinar posiciones
    pos = {**pos_switches, **pos_hosts}
    return pos

def calcular_posicion_etiqueta_inteligente(pos, u, v, tipo='puerto', enlaces_cercanos=None):
    """
    Calcula posición óptima para etiquetas evitando solapamiento.
    
    Args:
        pos: diccionario de posiciones de nodos
        u, v: nodos del enlace
        tipo: 'puerto' o 'bw' (determina el offset)
        enlaces_cercanos: lista de otros enlaces para evitar
    """
    # Posición base (punto medio)
    x_mid = (pos[u][0] + pos[v][0]) / 2
    y_mid = (pos[u][1] + pos[v][1]) / 2
    
    # Vector del enlace
    dx = pos[v][0] - pos[u][0]
    dy = pos[v][1] - pos[u][1]
    length = (dx**2 + dy**2)**0.5
    
    if length == 0:
        return x_mid, y_mid
    
    # Vector perpendicular normalizado
    perp_x = -dy / length
    perp_y = dx / length
    
    # Offset según tipo
    if tipo == 'puerto':
        offset_dist = 0.25  # Más cerca del enlace
    else:  # bw/delay
        offset_dist = 0.4   # Más lejos del enlace
    
    # Aplicar offset perpendicular
    x_label = x_mid + perp_x * offset_dist
    y_label = y_mid + perp_y * offset_dist
    
    return x_label, y_label

def visualizar_topologia_completa(G, modo='completo'):
    """
    Visualiza la topología completa con diferentes modos.
    
    Args:
        modo: 'completo', 'puertos_ips', 'bw_delay'
    """
    # Crear figura extra grande
    plt.figure(figsize=(22, 15))
    
    # Obtener posiciones
    pos = posiciones_topologia_completa()
    
    # Separar nodos por tipo
    switches = [n for n in G.nodes() if G.nodes[n]['tipo'] == 'switch']
    hosts = [n for n in G.nodes() if G.nodes[n]['tipo'] == 'host']
    
    # Separar enlaces por tipo
    enlaces_backbone = [(u, v) for u, v, d in G.edges(data=True) if d['tipo'] == 'backbone']
    enlaces_access = [(u, v) for u, v, d in G.edges(data=True) if d['tipo'] == 'access']
    
    # ========================================
    # DIBUJAR ENLACES ACCESS (HOST-SWITCH)
    # ========================================
    nx.draw_networkx_edges(
        G, pos,
        edgelist=enlaces_access,
        width=1.5,
        alpha=0.4,
        edge_color='gray',
        style='dashed'
    )
    
    # ========================================
    # DIBUJAR ENLACES BACKBONE CON COLORES
    # ========================================
    edge_colors = []
    edge_widths = []
    
    for u, v in enlaces_backbone:
        bw = G[u][v]['bw']
        edge_colors.append(bw)
        edge_widths.append(2.5 + bw/12)
    
    nx.draw_networkx_edges(
        G, pos,
        edgelist=enlaces_backbone,
        width=edge_widths,
        alpha=0.7,
        edge_color=edge_colors,
        edge_cmap=plt.cm.viridis,
        edge_vmin=20,
        edge_vmax=50
    )
    
    # ========================================
    # DIBUJAR NODOS - SWITCHES
    # ========================================
    nx.draw_networkx_nodes(
        G, pos,
        nodelist=switches,
        node_color='lightcoral',
        node_size=2800,
        node_shape='o',
        edgecolors='darkred',
        linewidths=3.5,
        alpha=0.9
    )
    
    # ========================================
    # DIBUJAR NODOS - HOSTS
    # ========================================
    nx.draw_networkx_nodes(
        G, pos,
        nodelist=hosts,
        node_color='lightyellow',
        node_size=1800,
        node_shape='s',
        edgecolors='orange',
        linewidths=2.5,
        alpha=0.95
    )
    
    # ========================================
    # ETIQUETAS DE SWITCHES
    # ========================================
    nx.draw_networkx_labels(
        G, pos,
        labels={n: n for n in switches},
        font_size=14,
        font_weight='bold',
        font_color='white'
    )
    
    # ========================================
    # ETIQUETAS DE HOSTS CON IPs
    # ========================================
    if modo in ['completo', 'puertos_ips']:
        host_labels = {}
        for host in hosts:
            ip = G.nodes[host]['ip']
            host_labels[host] = f"{host}\n{ip}"
        
        nx.draw_networkx_labels(
            G, pos,
            labels=host_labels,
            font_size=9,
            font_weight='bold',
            font_color='darkgreen'
        )
    else:
        nx.draw_networkx_labels(
            G, pos,
            labels={n: n for n in hosts},
            font_size=10,
            font_weight='bold',
            font_color='darkgreen'
        )
    
    # ========================================
    # ETIQUETAS DE ENLACES - BW/DELAY
    # ========================================
    if modo in ['completo', 'bw_delay']:
        for u, v, data in G.edges(data=True):
            if data['tipo'] == 'backbone':
                # Calcular posición inteligente para BW/Delay
                x_label, y_label = calcular_posicion_etiqueta_inteligente(
                    pos, u, v, tipo='bw'
                )
                
                label_text = f"{data['bw']}M\n{data['delay']}"
                
                plt.text(
                    x_label, y_label,
                    label_text,
                    fontsize=8,
                    ha='center',
                    va='center',
                    color='darkblue',
                    fontweight='bold',
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='white', 
                             edgecolor='darkblue', alpha=0.85, linewidth=1)
                )
    
    # ========================================
    # ETIQUETAS DE PUERTOS
    # ========================================
    if modo in ['completo', 'puertos_ips']:
        # Puertos de enlaces backbone
        for u, v, data in G.edges(data=True):
            if data['tipo'] == 'backbone':
                # Calcular posición inteligente para puertos (lado opuesto a BW)
                x_label, y_label = calcular_posicion_etiqueta_inteligente(
                    pos, u, v, tipo='puerto'
                )
                
                # Si modo completo, invertir el lado para evitar solapamiento
                if modo == 'completo':
                    # Vector del enlace
                    dx = pos[v][0] - pos[u][0]
                    dy = pos[v][1] - pos[u][1]
                    length = (dx**2 + dy**2)**0.5
                    if length > 0:
                        perp_x = -(-dy / length)  # Invertir
                        perp_y = -(dx / length)
                        x_mid = (pos[u][0] + pos[v][0]) / 2
                        y_mid = (pos[u][1] + pos[v][1]) / 2
                        x_label = x_mid + perp_x * 0.25
                        y_label = y_mid + perp_y * 0.25
                
                # Extraer números de puerto
                puerto_a = data['puerto_a'].split('-eth')[1]
                puerto_b = data['puerto_b'].split('-eth')[1]
                port_label = f"p{puerto_a}↔p{puerto_b}"
                
                plt.text(
                    x_label, y_label,
                    port_label,
                    fontsize=7,
                    ha='center',
                    va='center',
                    color='purple',
                    fontweight='bold',
                    bbox=dict(boxstyle='round,pad=0.25', facecolor='lavender', 
                             edgecolor='purple', alpha=0.75, linewidth=1)
                )
        
        # Puertos de enlaces access (host-switch)
        for u, v, data in G.edges(data=True):
            if data['tipo'] == 'access':
                # Posición cerca del switch
                p_sw = data['puerto_switch'].split('-eth')[1]
                
                # Encontrar cuál es el switch
                sw = u if u.startswith('s') else v
                host = u if u.startswith('h') else v
                
                # Posición entre host y switch, más cerca del switch
                x_label = pos[sw][0] * 0.7 + pos[host][0] * 0.3
                y_label = pos[sw][1] * 0.7 + pos[host][1] * 0.3
                
                plt.text(
                    x_label, y_label,
                    f"p{p_sw}",
                    fontsize=6,
                    ha='center',
                    va='center',
                    color='gray',
                    style='italic',
                    alpha=0.8
                )
    
    # ========================================
    # TÍTULO
    # ========================================
    titulos = {
        'completo': 'Topología NSFNET  - Switches, Hosts, Puertos, IPs, BW y Delay',
        'puertos_ips': 'Topología NSFNET - Puertos y Direcciones IP',
        'bw_delay': 'Topología NSFNET - Ancho de Banda y Latencia'
    }
    
    plt.title(titulos[modo], 
              fontsize=20, fontweight='bold', pad=25, color='darkblue')
    
    # ========================================
    # BARRA DE COLORES
    # ========================================
    sm = plt.cm.ScalarMappable(cmap=plt.cm.viridis, 
                                norm=plt.Normalize(vmin=20, vmax=50))
    sm.set_array([])
    cbar = plt.colorbar(sm, ax=plt.gca(), orientation='vertical', 
                        fraction=0.025, pad=0.02)
    cbar.set_label('Ancho de Banda (Mbps)', rotation=270, labelpad=25, 
                   fontsize=12, fontweight='bold')
    
    # ========================================
    # PANEL DE INFORMACIÓN
    # ========================================
    enlaces_bb = [(u, v, d) for u, v, d in G.edges(data=True) if d['tipo'] == 'backbone']
    bandwidths = [data['bw'] for u, v, data in enlaces_bb]
    delays = [int(data['delay'].replace('ms', '')) for u, v, data in enlaces_bb]
    
    info_text = (
        f"Switches (OVS): {len(switches)}\n"
        f"Hosts: {len(hosts)}\n"
        f"Enlaces Backbone: {len(enlaces_bb)}\n"
        f"BW: {min(bandwidths)}-{max(bandwidths)} Mbps (avg: {sum(bandwidths)/len(bandwidths):.1f})\n"
        f"Delay: {min(delays)}-{max(delays)} ms (avg: {sum(delays)/len(delays):.1f})\n"
        f"Red IP: 10.0.0.0/24"
    )
    plt.text(0.015, 0.98, info_text, transform=plt.gcf().transFigure, 
             fontsize=11, verticalalignment='top', family='monospace',
             bbox=dict(boxstyle='round,pad=0.8', facecolor='lightyellow', 
                      edgecolor='orange', linewidth=2, alpha=0.95))
    
    # ========================================
    # LEYENDA
    # ========================================
    legend_elements = [
        mpatches.Patch(facecolor='lightcoral', edgecolor='darkred', 
                      linewidth=2, label='Switch (OVS)'),
        mpatches.Patch(facecolor='lightyellow', edgecolor='orange', 
                      linewidth=2, label='Host'),
    ]
    
    if modo in ['completo', 'puertos_ips']:
        legend_elements.append(
            mpatches.Patch(facecolor='lavender', edgecolor='purple', 
                          linewidth=1, label='Puertos')
        )
    
    if modo in ['completo', 'bw_delay']:
        legend_elements.append(
            mpatches.Patch(facecolor='white', edgecolor='darkblue', 
                          linewidth=1, label='BW/Delay')
        )
    
    plt.legend(handles=legend_elements, loc='lower left', fontsize=11, framealpha=0.9)
    
    # ========================================
    # NOTA SOBRE ALGORITMOS
    # ========================================
    nota_text = (
        "Algoritmos de Enrutamiento:\n"
        "• Dijkstra (peso = 1/BW)\n"
        "• Shortest Path (# saltos)"
    )
    plt.text(0.015, 0.12, nota_text, transform=plt.gcf().transFigure, 
             fontsize=10, verticalalignment='bottom', style='italic',
             bbox=dict(boxstyle='round,pad=0.6', facecolor='lightblue', 
                      edgecolor='steelblue', linewidth=2, alpha=0.9))
    
    plt.axis('off')
    plt.tight_layout()
    plt.show()

def imprimir_info_detallada(G):
    """
    Imprime información detallada incluyendo puertos e IPs.
    """
    print("\n" + "="*80)
    print("TOPOLOGÍA NSFNET COMPLETA - INFORMACIÓN DETALLADA")
    print("="*80)
    
    # Hosts e IPs
    print(f"\n🖥️  HOSTS Y DIRECCIONES IP:")
    hosts = sorted([n for n in G.nodes() if G.nodes[n]['tipo'] == 'host'])
    for host in hosts:
        ip = G.nodes[host]['ip']
        # Obtener puerto del switch conectado
        for neighbor in G.neighbors(host):
            if G.nodes[neighbor]['tipo'] == 'switch':
                puerto_host = G[host][neighbor]['puerto_host']
                puerto_switch = G[host][neighbor]['puerto_switch']
                print(f"   {host:<5} IP: {ip:<12} Puerto: {puerto_host} <-> {puerto_switch}")
                break
    
    # Enlaces backbone con puertos
    print(f"\n🔗 ENLACES BACKBONE CON PUERTOS Y CARACTERÍSTICAS:")
    print(f"   {'Enlace':<12} {'Puertos':<25} {'BW':<8} {'Delay':<8} {'Peso':<10}")
    print(f"   {'-'*75}")
    
    enlaces_bb = [(u, v, d) for u, v, d in G.edges(data=True) if d['tipo'] == 'backbone']
    enlaces_bb.sort(key=lambda x: x[2]['bw'], reverse=True)
    
    for u, v, data in enlaces_bb:
        enlace = f"{u}-{v}"
        puertos = f"{data['puerto_a']} <-> {data['puerto_b']}"
        bw = data['bw']
        delay = data['delay']
        peso = data['weight']
        print(f"   {enlace:<12} {puertos:<25} {bw:<8} {delay:<8} {peso:.4f}")
    
    print("\n" + "="*80 + "\n")

def main():
    """
    Función principal con opciones mejoradas de visualización.
    """
    print("🚀 Creando Topología NSFNET Completa...")
    print("   14 Switches | 14 Hosts | 20 Enlaces Backbone | IPs: 10.0.0.1-14\n")
    
    # Crear grafo
    G = crear_topologia_completa()
    
    # Imprimir información detallada
    imprimir_info_detallada(G)
    
    # Opciones de visualización mejoradas
    print("🎨 Opciones de Visualización:")
    print("   [1] Vista Completa: Puertos + IPs + BW/Delay (TODO)")
    print("   [2] Vista Puertos e IPs (solo identificación de enlaces y hosts)")
    print("   [3] Vista BW/Delay (solo métricas de rendimiento)")
    print("   [4] Salir sin visualizar")
    
    opcion = input("\n   Selecciona opción [1-4, default=1]: ").strip()
    
    if opcion == '4' or opcion == '':
        if opcion == '':
            opcion = '1'
        else:
            print("\n✅ Análisis completado. Saliendo...")
            return
    
    # Mapear opción a modo
    modos = {
        '1': 'completo',
        '2': 'puertos_ips',
        '3': 'bw_delay'
    }
    
    modo = modos.get(opcion, 'completo')
    
    print(f"\n📊 Generando visualización gráfica (modo: {modo})...")
    print("   (Cierra la ventana para terminar)\n")
    
    # Visualizar
    visualizar_topologia_completa(G, modo=modo)
    
    print("✅ Visualización completada exitosamente.")

if __name__ == '__main__':
    main()