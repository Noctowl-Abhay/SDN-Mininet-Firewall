from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel

class PracticalFirewallTopo(Topo):
    def build(self):
        # Adding two switches to make it a multi-hop network
        s1 = self.addSwitch('s1', cls=OVSKernelSwitch, protocols='OpenFlow13')
        s2 = self.addSwitch('s2', cls=OVSKernelSwitch, protocols='OpenFlow13')

        # Connect the switches together
        self.addLink(s1, s2)

        # Adding 6 hosts (3 on each switch)
        # Switch 1 Hosts
        h1 = self.addHost('h1', ip='19.0.0.1', mac='00:00:00:00:00:10')
        h2 = self.addHost('h2', ip='19.0.0.2', mac='00:00:00:00:00:20')
        h3 = self.addHost('h3', ip='19.0.0.3', mac='00:00:00:00:00:30')
        
        # Switch 2 Hosts
        h4 = self.addHost('h4', ip='19.0.0.4', mac='00:00:00:00:00:40')
        h5 = self.addHost('h5', ip='19.0.0.5', mac='00:00:00:00:00:50')
        h6 = self.addHost('h6', ip='19.0.0.6', mac='00:00:00:00:00:60')

        # Establishing links
        self.addLink(h1, s1)
        self.addLink(h2, s1)
        self.addLink(h3, s1)
        
        self.addLink(h4, s2)
        self.addLink(h5, s2)
        self.addLink(h6, s2)

def run():
    topo = PracticalFirewallTopo()
    # Ensure the controller is pointing to your Ryu instance
    net = Mininet(topo=topo, controller=lambda name: RemoteController(name, ip='127.0.0.1', port=6653))
    net.start()
    CLI(net)
    net.stop()

if __name__ == '__main__':
    setLogLevel('info')
    run()
