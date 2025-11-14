from mininet.topo import Topo

class MiTopologia(Topo):
    def __init__(self):
        # Llamar al constructor de la clase padre
        super(MiTopologia, self).__init__()

        # Añadir hosts y conmutador
        host1 = self.addHost('h1')
        host2 = self.addHost('h2')
        switch1 = self.addSwitch('s1')

        # Añadir enlaces entre ellos
        self.addLink(host1, switch1)
        self.addLink(host2, switch1)

# El script se ejecuta en la línea de comandos de Mininet con la opción --custom
# sudo mn --custom /ruta/al/archivo.py --topo MiTopologia
