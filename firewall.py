import logging
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4, tcp, ether_types

# --- FILE LOGGING SETUP ---
# Initialize a custom logger to save firewall events to a persistent text file.
# This ensures that blocking history is preserved even if the terminal is cleared.
file_logger = logging.getLogger('FirewallFile')
file_logger.setLevel(logging.INFO)

# Define the log file location and ensure it appends ('a') rather than overwriting.
fh = logging.FileHandler('firewall_log.txt', mode='a')
formatter = logging.Formatter('%(asctime)s - %(message)s')
fh.setFormatter(formatter)
file_logger.addHandler(fh)

class UltimateSdnFirewall(app_manager.RyuApp):
    """
    SDN Firewall implementation for the Orange Problem assignment.
    This application acts as both a Layer 2 Learning Switch and a 
    multi-layer Firewall (MAC, IP, and Port filtering).
    """
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(UltimateSdnFirewall, self).__init__(*args, **kwargs)
        # MAC Table to store host locations: {datapath_id: {mac_address: port}}
        self.mac_to_port = {}
        
        # --- FIREWALL POLICIES (Configurable Lists) ---
        # Any traffic matching these identifiers will be intercepted/blocked.
        self.BLOCK_MAC_LIST = ['00:00:00:00:00:30']  # Blocks specific hardware (Host 3)
        self.BLOCK_IP_LIST  = ['19.0.0.4']           # Blocks specific Network ID (Host 4)
        self.BLOCK_PORT_LIST = [80]                  # Blocks HTTP traffic specifically

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """
        Triggered when a switch first connects to the controller.
        Installs the 'Table-Miss' flow entry to handle unknown traffic.
        """
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        # Wipe existing flows to ensure a clean state for the simulation.
        self.del_flows(datapath)

        # Priority 0 Rule: If no other rule matches, send the packet to the controller.
        # This is essential for the Learning Switch and Firewall logic to function.
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

    def add_flow(self, datapath, priority, match, actions, idle=0):
        """
        Helper method to push flow rules (FlowMod) to the switch's hardware table.
        """
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        # Apply the list of actions provided (Forwarding, Dropping, or sending to Controller).
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        
        mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                idle_timeout=idle, match=match, instructions=inst)
        datapath.send_msg(mod)

    def del_flows(self, datapath):
        """
        Helper method to clear all flow entries from a specific switch.
        """
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        mod = parser.OFPFlowMod(datapath=datapath, command=ofproto.OFPFC_DELETE,
                                out_port=ofproto.OFPP_ANY, out_group=ofproto.OFPG_ANY)
        datapath.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        """
        The core logic engine. Handles packets that the switch doesn't recognize.
        Flow: 1. Parse Packet -> 2. Apply Firewall Filters -> 3. Learning/Forwarding.
        """
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        # The physical port where the packet entered the switch.
        in_port = msg.match['in_port']

        # Extract protocol information (Ethernet, IPv4, TCP).
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if not eth: 
            return # Ignore non-Ethernet traffic

        dst, src = eth.dst, eth.src
        
        # LEARNING PHASE: Map the source MAC to the port it arrived on.
        self.mac_to_port.setdefault(datapath.id, {})
        self.mac_to_port[datapath.id][src] = in_port

        def log_event(text):
            """Internal utility to update terminal and log file simultaneously."""
            self.logger.info(text)
            file_logger.info(text)

        # --- FIREWALL SECTION 1: LAYER 2 (MAC) BLOCKING ---
        if src in self.BLOCK_MAC_LIST or dst in self.BLOCK_MAC_LIST:
            # Avoid logging background multicast/IPv6 neighbor discovery noise.
            if not dst.startswith('ff:ff:ff') and not dst.startswith('33:33'):
                log_event(f"!! [MAC BLOCK] Detected: {src} -> {dst}")
                
                # Install a rule at the switch to intercept this specific hardware pair.
                match = parser.OFPMatch(eth_src=src, eth_dst=dst)
                actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER)]
                self.add_flow(datapath, 100, match, actions)
                return 
            else:
                return 

        # --- FIREWALL SECTION 2: LAYER 3 & 4 (IP & PORT) BLOCKING ---
        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        if ip_pkt:
            src_ip, dst_ip = ip_pkt.src, ip_pkt.dst

            # LAYER 4: Block specific TCP ports (e.g., HTTP Port 80).
            tcp_pkt = pkt.get_protocol(tcp.tcp)
            if tcp_pkt and (tcp_pkt.dst_port in self.BLOCK_PORT_LIST or tcp_pkt.src_port in self.BLOCK_PORT_LIST):
                log_event(f"!! [PORT BLOCK] Detected: {src_ip} -> {dst_ip} on Port {tcp_pkt.dst_port}")
                
                # Install L4-specific rule in the switch.
                match = parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IP, ip_proto=6, tcp_dst=tcp_pkt.dst_port)
                actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER)]
                self.add_flow(datapath, 110, match, actions)
                return

            # LAYER 3: Block specific IP addresses.
            if src_ip in self.BLOCK_IP_LIST or dst_ip in self.BLOCK_IP_LIST:
                log_event(f"!! [IP BLOCK] Detected: {src_ip} -> {dst_ip}")
                
                # Install L3-specific rule in the switch.
                match = parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IP, ipv4_src=src_ip, ipv4_dst=dst_ip)
                actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER)]
                self.add_flow(datapath, 105, match, actions)
                return

        # --- FORWARDING SECTION 3: NORMAL TRAFFIC (LEARNING SWITCH) ---
        # If the destination MAC is already in our table, send to specific port.
        if dst in self.mac_to_port[datapath.id]:
            out_port = self.mac_to_port[datapath.id][dst]
        else:
            # If destination is unknown, flood the packet out of all ports (ARP-like behavior).
            out_port = ofproto.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        # If the destination is known, install a high-speed forwarding rule to avoid future PacketIns.
        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            self.add_flow(datapath, 10, match, actions)

        # Instruct the switch to send the packet.
        data = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id, 
                                  in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)
