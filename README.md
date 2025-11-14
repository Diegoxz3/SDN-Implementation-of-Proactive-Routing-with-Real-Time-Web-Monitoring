# SDN-Implementation-of-Proactive-Routing-with-Real-Time-Web-Monitoring


---

# NetWeb — NSFNET SDN (Mininet + Ryu + Flask + D3.js)

Proyecto que combina Mininet (topología NSFNET), un controlador Ryu proactivo y un backend Flask que publica métricas y eventos para una UI D3.js en tiempo real.

---

## 🧾 Resumen rápido

* Topología: **NSFNET personalizada** (14 switches, 14 hosts) con `nsfnet_topologyx.py` (Mininet).
* Controlador: **Ryu** con aplicación `new_ryu_controllerx.py` — rutas proactivas, descubrimiento LLDP, push de eventos a backend.
* Backend / UI: `newapp.py` (Flask) que sirve la UI (D3.js), expone API `/topology`, `/metrics`, `/ryu/events`, SSE `/events`.
* Objetivo: pruebas de conectividad, medición de throughput/loss por enlace y visualización en tiempo real.

---

## 🧩 Versiones (entorno de referencia)

* Python (Mininet VM): **3.5.2**
* Python (Ryu VM / entorno): **3.9.23**
* Ryu framework: **4.34**
* Mininet: **2.3.0**
* OVS: revisar `ovs-vsctl --version`
* Flask: **3.1.2**
* networkx: **3.2.1**
* Imagen Mininet usada: `mininet-2.3.0-210211-ubuntu-16.04.6-server-i386-ovf`

---

## 📁 Estructura (ejemplo)

```
/ryu-app/
  ├─ new_ryu_controllerx.py   # controlador Ryu (en la VM del controlador)
  ├─ newapp.py                # Flask backend + web (en la VM del controlador)
  └─ static/
      └─ index.html           # UI D3.js
/mininet-vm/
  └─ nsfnet_topologyx.py      # script de topología (en la VM mininet)
```

---

## ▶️ Comandos EXACTOS para ejecutar (orden recomendado)

> **Suposición**:
>
> * IP del controlador = `192.168.18.40`
> * Puerto OpenFlow = `6653`
> * Flask sirve en `:5000` (por defecto)

### 1) En la VM del controlador — iniciar Ryu (primero)

```bash
# En la VM del controlador (ej. ubuntu@ubuntu-svr)
ryu-manager --ofp-tcp-listen-port 6653 --observe-links \
    ryu.app.rest_topology ryu.app.ofctl_rest \
    /usr/lib/python3/dist-packages/ryu/app/new_ryu_controllerx.py
```

**Qué hace**:

* Levanta el framework Ryu, carga `rest_topology` y `ofctl_rest` (necesarios para /v1.0/topology y /stats),
* Instancia tu app `new_ryu_controllerx.py`,
* Habilita descubrimiento por LLDP (`--observe-links`) y escucha OpenFlow en `6653`.

---

### 2) En otra terminal de la misma VM del controlador — iniciar el backend / UI

```bash
# En la misma VM del controlador
python3 newapp.py
```

**Qué hace**:

* Levanta Flask (por defecto `0.0.0.0:5000`) y sirve `index.html` en `/`.
* Expone SSE `/events` y endpoints `/mode`, `/reinstall`, `/topology`, `/metrics`, `/ryu/events` (para recibir pushes).

**URL de la UI** (si el servidor tiene IP `192.168.18.40`):

```
http://192.168.18.40:5000
```

---

### 3) En la VM Mininet — iniciar la topología apuntando al controlador remoto

```bash
# En la VM mininet
sudo python3 nsfnet_topologyx.py --controller_ip 192.168.18.40 --controller_port 6653
```

**Qué hace**:

* Crea switches y hosts,
* Conecta los switches al controlador remoto en `192.168.18.40:6653`,
* Instala enlaces (TCLink con bw/delay definidos).

---

## ✅ Orden correcto de inicio (resumen)

1. `ryu-manager ... new_ryu_controllerx.py`  (Controlador Ryu)
2. `python3 newapp.py`                       (Flask backend + UI)
3. `sudo python3 nsfnet_topologyx.py --controller_ip 192.168.18.40 --controller_port 6653` (Mininet)

> **Nota**: si empiezas Mininet antes de que Ryu esté listo, los switches intentarán reconectarse; mejor arrancar Ryu primero.

---

## 🧪 Pruebas y comandos útiles (Mininet)

Desde el prompt de Mininet (`mininet>`):

* Probar conectividad (ping all):

  ```bash
  mininet> pingall
  ```

* Ejecutar iperf TCP (servidor en h14, cliente en h1):

  ```bash
  mininet> h14 iperf -s -p 5001 &
  mininet> h1 iperf -c 10.0.0.14 -p 5001 -t 10
  ```

* Traza (si falta traceroute instala paquete en imagen/VM):

  ```bash
  mininet> h1 traceroute h8
  # si "traceroute: command not found" -> instalar iputils-tracepath o traceroute en la VM Mininet
  ```

* Simular enlace down/up:

  ```bash
  mininet> link s1 s2 down
  mininet> link s1 s2 up
  ```

* Mostrar nodos / enlaces en Mininet:

  ```bash
  mininet> nodes
  mininet> links
  ```

---

## 🔌 Endpoints útiles (curl / Postman)

### Cambiar modo (`hops` o `distrak`) — desde Postman o curl (llamar al backend Flask)

El frontend envía a Flask en `/mode` que hace proxy a tu controlador:

```bash
# cambiar a distrak
curl -X POST http://192.168.18.40:5000/mode -H "Content-Type: application/json" -d '{"mode":"distrak"}'

# cambiar a hops
curl -X POST http://192.168.18.40:5000/mode -H "Content-Type: application/json" -d '{"mode":"hops"}'
```

`/mode` hace a su vez `POST http://<CONTROLLER>/set_mode` y luego intenta `POST /reinstall`.

### Reinstalar flujos (reinstalación proactiva)

```bash
curl -X POST http://192.168.18.40:5000/reinstall
```

### Consultar topología desde Flask

```bash
curl http://192.168.18.40:5000/graph   # obtiene snapshot con nodes/links/hosts
```

### Consultar métricas

```bash
curl http://192.168.18.40:5000/metrics
curl "http://192.168.18.40:5000/metrics/link?u=1&v=2"
curl "http://192.168.18.40:5000/metrics/path?src=1&dst=12&k=1"
```

### Endpoint directo del controlador Ryu (si quieres evitar Flask proxy)

```bash
# ejemplo (si ryu expone su REST en 8080):
curl http://192.168.18.40:8080/topology
```

---

## 🔍 Cómo comprobar que el cambio de modo fue aplicado por el controlador

1. Hacer `POST /mode` (Flask) o `POST /set_mode` directamente al controlador Ryu.
2. En los logs del controlador Ryu verás:

   ```
   Modo cambiado a distrak
   Reconstruyendo grafo + reinstalando flujos...
   ```
3. En la UI ([http://192.168.18.40:5000](http://192.168.18.40:5000)) la etiqueta `mode` mostrará `distrak` o `hops`.
4. Opcional: comparar rutas usando `/path?src=X&dst=Y` (Flask) antes y después del cambio.

---

## 🛠️ Comprobaciones y troubleshooting rápido

* Si `index.html` devuelve **404 Not Found**:

  * Asegúrate de que `newapp.py` se está ejecutando en la máquina `192.168.18.40`.
  * Asegúrate de que `index.html` está en la carpeta `static/` o en la ruta que `newapp.py` utiliza.
  * Abrir `http://192.168.18.40:5000/` desde tu navegador.

* Si Mininet no se conecta al controlador:

  * Verifica que Ryu está arriba y escuchando `6653`:

    ```bash
    netstat -tulnp | grep 6653
    ```
  * Revisa logs del `ryu-manager` para errores de conexión.
  * Verifica que no haya firewall bloqueando 6653.

* Si no ves métricas en la UI:

  * Revisa que `newapp.py` haya arrancado sin errores.
  * Revisa que `ryu.app.ofctl_rest` esté cargado por ryu-manager (necesario para `/stats/port`).
  * Confirma que `--observe-links` está pasado a ryu-manager (para LLDP / topology).

---

## 💡 Notas técnicas y recomendaciones

* LLDP discovery requiere `--observe-links` y que `ryu.app.rest_topology` esté cargado (o el módulo de topología de Ryu).
* Flask (newapp.py) recibe eventos push desde `new_ryu_controllerx.py` en `/ryu/events` si está configurado el token correcto.
* Para métricas precisas por enlace el backend usa `/stats/port/<dpid>` (ofctl_rest) y calcula deltas de `tx_bytes`/`rx_packets` en ventanas temporales.
* Si tu Mininet VM no tiene `traceroute` o `iperf` instala el paquete correspondiente en la VM.

---

## 📌 Comandos adicionales útiles (en el controlador)

* Ver puertos y stats OF:

  ```bash
  # desde la VM Ryu si ofctl_rest está cargado:
  curl http://127.0.0.1:8080/stats/port/<dpid>
  ```

* Listar flujos en un switch (desde la VM Mininet o controlador, usando ovs-ofctl):

  ```bash
  sudo ovs-ofctl dump-flows s1  # en Mininet VM que controla s1
  ```

---

## 🔁 Recap — Comandos que estás usando (tal cual los pediste)

```bash
# En controlador (VM):
ryu-manager --ofp-tcp-listen-port 6653 --observe-links \
    ryu.app.rest_topology ryu.app.ofctl_rest \
    /usr/lib/python3/dist-packages/ryu/app/new_ryu_controllerx.py

# En controlador (otra terminal):
python3 newapp.py

# En Mininet VM:
sudo python3 nsfnet_topologyx.py --controller_ip 192.168.18.40 --controller_port 6653
```

---


* instrucciones para instalar `traceroute/iperf` en la VM Mininet,
* scripts `run_all.sh` que arranquen Ryu + Flask + Mininet (con pausa y checks),
* fragmentos de `systemd` para ejecutar el Flask app o ryu-manager en arranque.


