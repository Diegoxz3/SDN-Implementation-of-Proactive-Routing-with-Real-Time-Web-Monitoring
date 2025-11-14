#!/usr/bin/env python3
"""
Visualizador de Topología NSFNET - Versión Definitiva
Topología con 14 switches y 20 enlaces backbone

Requisitos:
    pip install networkx matplotlib

Uso:
    python visualizar_topologia.py
"""

import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

def crear_topologia_definitiva():
    """
    Crea la topología NSFNET con las conexiones definitivas especificadas.
    14 switches, 20 enlaces con BW y delay asignados estratégicamente.
    """
    # Crear grafo no dirigido
    G = nx.Graph()
    
    # ========================================
    # AGREGAR SWITCHES (nodos 1-14)
    # ========================================
    for i in range(1, 15):
        G.add_node(i)
    
    # ========================================
    # ENLACES BACKBONE - TOPOLOGÍA DEFINITIVA
    # ========================================
    # Formato: (switch_a, switch_b, ancho_banda_Mbps, delay)
    # BW asignados de forma variada (15-50 Mbps) para experimentos Dijkstra
    # Delays entre 5-12ms simulando diferentes distancias geográficas
    
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
    
    # Agregar enlaces con atributos
    for a, b, bw, delay in backbone_links:
        G.add_edge(
            a, b,
            bw=bw,              # Ancho de banda en Mbps
            delay=delay,        # Latencia
            weight=1/bw         # Peso para algoritmo Dijkstra (1/BW)
        )
    
    return G

def posiciones_topologia_definitiva():
    """
    Define posiciones manuales optimizadas para la topología definitiva.
    Distribución que facilita visualización de las conexiones.
    """
    pos = {
        # Columna izquierda
        1: (0, 3),      # Superior izquierda
        2: (0, 1.5),    # Centro izquierda
        3: (1, 4),      # Superior centro-izquierda
        
        # Columna centro-izquierda
        6: (2, 3),      # Centro-superior
        7: (2.5, 1.5),  # Centro
        4: (2, 0),      # Centro-inferior
        
        # Columna centro
        9: (4, 4),      # Superior centro
        8: (4, 2),      # Centro
        5: (4, -0.5),   # Inferior centro
        
        # Columna centro-derecha
        10: (6, 2.5),   # Centro-derecha
        
        # Columna derecha
        11: (7, 4),     # Superior derecha
        12: (8, 3),     # Centro-superior derecha
        13: (8, 1.5),   # Centro derecha
        14: (7, 0),     # Inferior derecha
    }
    return pos

def visualizar_topologia_definitiva(G, mostrar_etiquetas_enlaces=True):
    """
    Visualiza la topología definitiva con estilo profesional.
    """
    # Crear figura grande
    plt.figure(figsize=(18, 12))
    
    # Usar posiciones optimizadas
    pos = posiciones_topologia_definitiva()
    
    # ========================================
    # DIBUJAR ENLACES CON COLORES POR BW
    # ========================================
    edge_colors = []
    edge_widths = []
    
    for u, v, data in G.edges(data=True):
        bw = data['bw']
        edge_colors.append(bw)
        # Grosor proporcional al ancho de banda
        edge_widths.append(2.5 + bw/12)
    
    # Dibujar enlaces con degradado de color
    edges = nx.draw_networkx_edges(
        G, pos,
        width=edge_widths,
        alpha=0.7,
        edge_color=edge_colors,
        edge_cmap=plt.cm.viridis,  # Degradado verde-azul-morado
        edge_vmin=20,
        edge_vmax=50
    )
    
    # ========================================
    # DIBUJAR NODOS (SWITCHES)
    # ========================================
    nx.draw_networkx_nodes(
        G, pos,
        node_color='lightcoral',
        node_size=2500,
        node_shape='o',
        edgecolors='darkred',
        linewidths=3.5,
        alpha=0.9
    )
    
    # ========================================
    # ETIQUETAS DE NODOS
    # ========================================
    nx.draw_networkx_labels(
        G, pos,
        labels={n: f's{n}' for n in G.nodes()},
        font_size=13,
        font_weight='bold',
        font_color='white'
    )
    
    # ========================================
    # ETIQUETAS DE ENLACES
    # ========================================
    if mostrar_etiquetas_enlaces:
        edge_labels = {}
        for u, v, data in G.edges(data=True):
            # Formato: BW (en Mbps) / Delay
            edge_labels[(u, v)] = f"{data['bw']}M\n{data['delay']}"
        
        nx.draw_networkx_edge_labels(
            G, pos,
            edge_labels=edge_labels,
            font_size=8,
            font_color='darkblue',
            font_weight='bold',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='white', 
                     edgecolor='gray', alpha=0.85)
        )
    
    # ========================================
    # TÍTULO Y DECORACIÓN
    # ========================================
    plt.title('Topología NSFNET Definitiva - Red SDN con Controlador Ryu', 
              fontsize=20, fontweight='bold', pad=25, color='darkblue')
    
    # Barra de colores para ancho de banda
    sm = plt.cm.ScalarMappable(cmap=plt.cm.viridis, 
                                norm=plt.Normalize(vmin=20, vmax=50))
    sm.set_array([])
    cbar = plt.colorbar(sm, ax=plt.gca(), orientation='vertical', 
                        fraction=0.025, pad=0.02)
    cbar.set_label('Ancho de Banda (Mbps)', rotation=270, labelpad=25, 
                   fontsize=12, fontweight='bold')
    
    # Calcular estadísticas
    bandwidths = [data['bw'] for u, v, data in G.edges(data=True)]
    delays = [int(data['delay'].replace('ms', '')) for u, v, data in G.edges(data=True)]
    
    # Panel de información
    info_text = (
        f"🔷 Switches (OVS): {G.number_of_nodes()}\n"
        f"🔗 Enlaces Backbone: {G.number_of_edges()}\n"
        f"📊 BW min/max: {min(bandwidths)}/{max(bandwidths)} Mbps\n"
        f"📊 BW promedio: {sum(bandwidths)/len(bandwidths):.1f} Mbps\n"
        f"⏱️  Delay min/max: {min(delays)}/{max(delays)} ms\n"
        f"⏱️  Delay promedio: {sum(delays)/len(delays):.1f} ms"
    )
    plt.text(0.015, 0.98, info_text, transform=plt.gcf().transFigure, 
             fontsize=11, verticalalignment='top', family='monospace',
             bbox=dict(boxstyle='round,pad=0.8', facecolor='lightyellow', 
                      edgecolor='orange', linewidth=2, alpha=0.95))
    
    # Nota sobre algoritmos
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

def imprimir_topologia_detallada(G):
    """
    Imprime información detallada de la topología en consola.
    """
    print("\n" + "="*80)
    print("TOPOLOGÍA NSFNET DEFINITIVA - ANÁLISIS COMPLETO")
    print("="*80)
    
    # Estadísticas generales
    print(f"\n📊 ESTADÍSTICAS GENERALES:")
    print(f"   • Total de Switches: {G.number_of_nodes()}")
    print(f"   • Total de Enlaces: {G.number_of_edges()}")
    print(f"   • Grado promedio: {sum(dict(G.degree()).values()) / G.number_of_nodes():.2f}")
    print(f"   • Densidad del grafo: {nx.density(G):.3f}")
    
    # Grado de cada nodo
    print(f"\n🔌 GRADO DE CONECTIVIDAD (# enlaces por switch):")
    grados = dict(G.degree())
    for nodo in sorted(grados.keys()):
        print(f"   s{nodo}: {grados[nodo]} enlaces")
    
    # Análisis de anchos de banda
    bandwidths = [data['bw'] for u, v, data in G.edges(data=True)]
    print(f"\n📶 ANÁLISIS DE ANCHOS DE BANDA:")
    print(f"   • Mínimo: {min(bandwidths)} Mbps")
    print(f"   • Máximo: {max(bandwidths)} Mbps")
    print(f"   • Promedio: {sum(bandwidths)/len(bandwidths):.1f} Mbps")
    print(f"   • Mediana: {sorted(bandwidths)[len(bandwidths)//2]} Mbps")
    
    # Análisis de delays
    delays = [int(data['delay'].replace('ms', '')) for u, v, data in G.edges(data=True)]
    print(f"\n⏱️  ANÁLISIS DE LATENCIAS:")
    print(f"   • Mínimo: {min(delays)} ms")
    print(f"   • Máximo: {max(delays)} ms")
    print(f"   • Promedio: {sum(delays)/len(delays):.1f} ms")
    
    # Tabla completa de enlaces
    print(f"\n📋 TABLA COMPLETA DE ENLACES (ordenados por BW descendente):")
    print(f"   {'Enlace':<12} {'BW (Mbps)':<12} {'Delay':<10} {'Peso (1/BW)':<12} {'Categoría':<12}")
    print(f"   {'-'*70}")
    
    enlaces_lista = [(u, v, d) for u, v, d in G.edges(data=True)]
    enlaces_lista.sort(key=lambda x: x[2]['bw'], reverse=True)
    
    for u, v, data in enlaces_lista:
        bw = data['bw']
        # Categorizar por BW
        if bw >= 45:
            categoria = "MUY ALTO"
        elif bw >= 35:
            categoria = "ALTO"
        elif bw >= 25:
            categoria = "MEDIO"
        else:
            categoria = "BAJO"
        
        print(f"   s{u}-s{v:<9} {bw:<12} {data['delay']:<10} {data['weight']:.4f}       {categoria}")
    
    # Enlaces críticos (mayor BW = mayor capacidad)
    print(f"\n⭐ TOP 5 ENLACES DE MAYOR CAPACIDAD:")
    top5 = sorted(enlaces_lista, key=lambda x: x[2]['bw'], reverse=True)[:5]
    for i, (u, v, data) in enumerate(top5, 1):
        print(f"   {i}. s{u}-s{v}: {data['bw']} Mbps, {data['delay']}")
    
    # Enlaces con menor latencia
    print(f"\n⚡ TOP 5 ENLACES DE MENOR LATENCIA:")
    enlaces_por_delay = sorted(enlaces_lista, 
                                key=lambda x: int(x[2]['delay'].replace('ms', '')))[:5]
    for i, (u, v, data) in enumerate(enlaces_por_delay, 1):
        print(f"   {i}. s{u}-s{v}: {data['delay']}, {data['bw']} Mbps")
    
    print("\n" + "="*80 + "\n")

def main():
    """
    Función principal.
    """
    print("🚀 Creando Topología NSFNET Definitiva...")
    print("   14 Switches | 20 Enlaces Backbone | BW: 20-50 Mbps | Delay: 5-12ms\n")
    
    # Crear grafo
    G = crear_topologia_definitiva()
    
    # Imprimir análisis detallado
    imprimir_topologia_detallada(G)
    
    # Opciones de visualización
    print("🎨 Opciones de Visualización:")
    print("   [1] Con etiquetas de BW/Delay en cada enlace (detallado)")
    print("   [2] Sin etiquetas (vista limpia)")
    print("   [3] Salir sin visualizar")
    
    opcion = input("\n   Selecciona opción [1-3, default=1]: ").strip()
    
    if opcion == '3':
        print("\n✅ Análisis completado. Saliendo...")
        return
    
    mostrar_etiquetas = (opcion != '2')
    
    print("\n📊 Generando visualización gráfica...")
    print("   (Cierra la ventana para terminar)\n")
    
    # Visualizar
    visualizar_topologia_definitiva(G, mostrar_etiquetas_enlaces=mostrar_etiquetas)
    
    print("✅ Visualización completada exitosamente.")

if __name__ == '__main__':
    main()