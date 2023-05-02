import random
import socket
from socket import *
import threading # multi threading: sending and receiving at the same time
from threading import Condition
import sys # for CLI
import os # os.exit()
import time
import json
import copy
import signal
from gbn_for_cn import gbnNode

# p = packetFormat(type="DV", sender_listening_port=6666, DV=DV, pktNum="", char="")
# p = packetFormat(type="ack", pktNum=1, char="", sender_listening_port=6666, DV=None)
# p = packetFormat(type="probe", pktNum=1, char="a", sender_listening_port=6666, DV=None)

def packetFormat(type, pktNum, char, sender_listening_port, DV):
    """
    type:
        probe/ack/DV
    pktNum:
        1,...,N, ... when type==probe/ack, "" when type==DV
    char:
        for probe packet, "" when type==DV/ack
    sender_listening_port:
        sender's listening port
    timestamp:
        for DV update
    DV:
        for DV update
    """
    DV_str = {str(TO): {k: str(v) for k, v in INFO.items()} for TO, INFO in DV.items()} if DV is not None else {}

    out_packet = "\n".join(["type", type, "pktNum", str(pktNum), "char", char,
                            "sender_listening_port", str(sender_listening_port),
                            "timestamp", str(time.time()),
                             "DV", json.dumps(DV_str)])
    return out_packet

def TDV(recv_DV):
    trans_DV = {}
    for TO, INFO in recv_DV.items():
        trans_DV[int(TO)] = {"distance": float(INFO['distance']),
                             "next_hop": int(INFO['next_hop']) if INFO['next_hop'] != "None" else None}
    return trans_DV

def packetResolve(in_packet):
    in_packet = in_packet.decode()
    lines = in_packet.splitlines()
    type = lines[1]
    pktNum = int(lines[3]) if lines[3] != "" else None
    char = lines[5] if lines[5] != "" else None
    sender_listening_port = int(lines[7])
    timestamp = float(lines[9])
    recv_DV = json.loads(lines[11])
    trans_DV = TDV(recv_DV)
    return type, pktNum, char, sender_listening_port, timestamp, trans_DV

class CnNode():
    def __init__(self, self_port, drop_rate_table, send_probe_to, all_neighbors, init_routing_table):
        self.self_listen_port = self_port  # self listening port
        self.listen_socket = socket(AF_INET, SOCK_DGRAM)
        self.listen_socket.bind(("", self.self_listen_port))

        self.send_socket = socket(AF_INET, SOCK_DGRAM)  # send DV
        self.send_socket_lock = threading.Lock()

        # DV update related
        self.routing_table = init_routing_table
        self.neighbors = all_neighbors # send DV to all neighbors
        self.last_node = last_node  # True / False
        self.recv_time = {} # used to discard the out-of-date DV received
        """
        sender1: lastest-processed-pkt-timestamp, 
        sender2: lastest-processed-pkt-timestamp, 
        ...
        """
        self.sent_DV_once = False

        # send_probe_to related
        self.sent_probe_once = False
        self.send_probe_to = send_probe_to # send probe pkt to them
        """this two need to move to gbn inside"""
        # self.send_loss_counter = {port:{"send_cnt": 0, "ack_cnt": 0} for port in self.send_probe_to} # used to print status msg
        # self.send_loss_counter_lock = threading.Lock() # fast write and read...
        self.GBN_NODES = {}

        # recv_probe_from related
        self.recv_probe_from = list(set(all_neighbors) - set(send_probe_to))
        self.drop_rate_table = drop_rate_table # determine the drop rate when receiving probe pkts
        self.recv_loss_counter = {port:{"recv_cnt": 0, "drop_cnt": 0} for port in self.recv_probe_from} # used to calc current link loss rate
        self.recv_loss_counter_lock = threading.Lock() # fast write and read...
        # self.reply_ack_sockest = {port: socket(AF_INET, SOCK_DGRAM) for port in self.recv_probe_from} # each port a socket to reply continuous ack
        self.correct_received = {port: -1 for port in self.recv_probe_from}

    def NodeListen(self):
        while True:
            data, addr = self.listen_socket.recvfrom(4096)
            type, pktNum, char, sender_listening_port, timestamp, DV = packetResolve(data)

            if type == "DV":
                print(f"[{time.time()}] Message received at Node {self.self_listen_port} from Node {sender_listening_port}")

                # determine the effectiveness of this packet:
                # if from the same sender_listening_port, this timestamp is smaller than the previous one from the same sender, then drop
                if (not self.recv_time.get(sender_listening_port)) or timestamp >= self.recv_time[sender_listening_port]:
                    # print("IT'S A USEFUL PKT, NEED TO DO CALCULATION......")
                    # update recv_time record
                    self.recv_time[sender_listening_port] = timestamp

                    # see if destinations added (may not know this destination before)
                    curr_dests = set(self.routing_table[self.self_listen_port].keys())
                    new_dests = set(DV.keys())
                    added_dests = list(new_dests - curr_dests)
                    if added_dests:
                        # print("NEED TO ADD DESTINATIONS INTO ROUTING TABLE")
                        # if new destination node known from the received DV,
                        # add this info to routing table, distance set as Inf initially
                        for added_dest in added_dests:
                            for FROM, TO in self.routing_table.items():
                                self.routing_table[FROM][added_dest] = {"distance": float("Inf"), "next_hop": None}

                    # store neighbor's DV into routing table,
                    # NOTE: should not directly replace the old DV, because the recipient node might already store some dest unknown for the sender before...
                    # self.routing_table[sender_listening_port] = DV
                    for TO, TO_INFO in DV.items():
                        self.routing_table[sender_listening_port][TO] = TO_INFO
                    # MODIFIED: need to update cnnode's own dv as well
                    self.routing_table[self.self_listen_port][sender_listening_port]['distance'] = DV[self.self_listen_port]['distance']

                    # calc its own DV
                    # 1. iterate all destinations
                    old_DV = copy.deepcopy(self.routing_table[self.self_listen_port])
                    new_DV = copy.deepcopy(self.routing_table[self.self_listen_port])
                    # DON'T WANT TO CHANGE THE REFERENCED SOURCE!!!, deepcopy because want deeper layer use diff addr as well...

                    target_dests = list(set(self.routing_table[self.self_listen_port].keys()) - {self.self_listen_port})
                    for target_dest in target_dests:
                        for neighbor in self.neighbors:
                            neighbor_DV = self.routing_table[neighbor]
                            candidate_distance = old_DV[neighbor]['distance'] + neighbor_DV[target_dest]['distance']
                            if round(candidate_distance, 2) < round(new_DV[target_dest]['distance'], 2):
                                # NOTE: sometimes, the precision error of json will make the program thinks the distance is shorter in this round
                                # e.g. 0.799999999999 < 0.8
                                # but the routing table will eventually converge!
                                # print(f"NEW DISTANCE IS {round(candidate_distance,2)}")
                                new_DV[target_dest]['distance'] = round(candidate_distance, 2) # compare at 2 decimal level
                                new_DV[target_dest]['next_hop'] = old_DV[neighbor]['next_hop']

                    if old_DV != new_DV:
                        self.routing_table[self.self_listen_port] = new_DV

                    if old_DV != new_DV or (not self.sent_DV_once):
                        threading.Thread(target=self.SendDV).start()
                        self.sent_DV_once = True

                    if not self.sent_probe_once:
                        # start to send probe
                        self.thread_probe_monitor = threading.Thread(target=self.ProbeController)
                        self.thread_probe_monitor.start()
                        self.sent_probe_once = True

                    print(f"[{time.time()}] Node {self.self_listen_port} Routing Table")
                    self_DV = self.routing_table[self.self_listen_port]
                    for TO, INFO in self_DV.items():
                        if TO != self.self_listen_port:
                            if INFO['next_hop'] == TO:
                                print(f"- ({round(INFO['distance'], 3)}) -> Node {TO}")
                            else:
                                print(f"- ({round(INFO['distance'], 3)}) -> Node {TO}; Next hop -> Node {INFO['next_hop']}")


            elif type == "probe":
                """node as a probe receiver"""
                self.recv_loss_counter[sender_listening_port]['recv_cnt'] += 1

                # determine whether to drop this probe packet or not
                ideal_drop_rate = self.drop_rate_table[sender_listening_port]
                lost = False
                if random.random() < ideal_drop_rate:
                    lost = True

                if lost:
                    self.recv_loss_counter[sender_listening_port]['drop_cnt'] += 1
                else:
                    # reply ack, maybe (???) set up a separate send socket for each probe sender
                    if pktNum == (self.correct_received[sender_listening_port] + 1):
                        # print(f"\nPREVIOUS ACK TIL {self.correct_received}, now add to:", end="")
                        self.correct_received[sender_listening_port] += 1
                        # print(f" CURRENT ACT TIL {self.correct_received}", end="")

                    ack_pkt = packetFormat(type="ack", pktNum=self.correct_received[sender_listening_port], char="", sender_listening_port=self.self_listen_port, DV=None)
                    with self.send_socket_lock:
                        self.send_socket.sendto(ack_pkt.encode(), ("127.0.0.1", sender_listening_port))


            elif type == "ack":
                """node as a probe sender"""
                # ACK of probe, never drop
                curr_gbn_node = self.GBN_NODES[sender_listening_port] # manipulate with this specific gbn_node

                # cooperate with gbnnode, let the window move, from 'pktNum'
                waiting_ack_pktNum = curr_gbn_node.buffer[curr_gbn_node.send_base][0]
                distance = pktNum - waiting_ack_pktNum  # due to GBN property, may lost send_base ack but received following ack

                # correctly received
                if pktNum >= waiting_ack_pktNum:

                    # erase buffer up til correctly received
                    erase_idx = list(range(curr_gbn_node.send_base, curr_gbn_node.send_base + distance + 1))
                    erase_idx = [idx % curr_gbn_node.buffer_len for idx in erase_idx]
                    for e_idx in erase_idx:
                        curr_gbn_node.buffer[e_idx] = None

                    # move forward the window
                    curr_gbn_node.send_base = (curr_gbn_node.send_base + distance + 1) % curr_gbn_node.buffer_len
                    # print(f"\n[{time.time()}] ACK{pktNum} received, window moves to {curr_gbn_node.send_base}", end="")

                    # notify the timer to stop timing and restart for the oldest in-flight packet
                    with curr_gbn_node.timer_condition:
                        # print("\nLISTEN THREAD NOTIFY TIMER", end="")
                        curr_gbn_node.timer_condition.notify()
                        # print("\nCurrent Timer stop", end="")

                    # notify the send thread to send new chars exposed in the window
                    curr_gbn_node.nothing_to_send = False
                    with curr_gbn_node.send_condition:
                        # print("\nLISTEN THREAD NOTIFY SEND THREAD", end="")
                        curr_gbn_node.send_condition.notify()

                    # notify the input thread to put remaining chars into buffer
                    curr_gbn_node.buffer_full = False
                    with curr_gbn_node.buffer_full_condition:
                        # print("\nLISTEN THREAD NOTIFY BUFFER", end="")
                        curr_gbn_node.buffer_full_condition.notify()

                # count num of ack received, so that print status message
                # don't care about whether is good ack
                curr_gbn_node.sent_loss_counter['ack_cnt'] += 1




    def ProbeController(self):
        """node as a probe sender"""
        for probe_receiver in self.send_probe_to:
            # create a gbnnode instance for each probe receiver of the cnnode
            gbnnode = gbnNode(self.self_listen_port, probe_receiver, window_size=5, drop_pkt='p', drop_param=0) # drop pkt&param is when node as receiver, not used here
            self.GBN_NODES[probe_receiver] = gbnnode # store the node in dict, for reference in other places...
            gbnnode.NodeMode() # start the node, ~ start to send probes...



    def SendDV(self):
        """
        send DV to all neighbors
        will be called when: (1) DV updated (2) first time send DV (3) last node automatically (4) every 5 seconds
        """
        # send Node's own DV to all its neighbors
        DV = self.routing_table[self.self_listen_port]
        out_pkt = packetFormat(type='DV', pktNum="", char="", sender_listening_port=self.self_listen_port, DV=DV)

        # print("START SENDING DV TO NEIGHBORS")
        with self.send_socket_lock:
            for neighbor_port in self.neighbors:
                self.send_socket.sendto(out_pkt.encode(), ("127.0.0.1", neighbor_port))
                print(f"[{time.time()}] Message sent from Node {self.self_listen_port} to Node {neighbor_port}")
        # print("BROADCAST DV FINISHED")

        self.sent_DV_once = True

        print(f"[{time.time()}] Node {self.self_listen_port} Routing Table")
        self_DV = self.routing_table[self.self_listen_port]
        for TO, INFO in self_DV.items():
            if TO != self.self_listen_port:
                if INFO['next_hop'] == TO:
                    print(f"- ({round(INFO['distance'], 3)}) -> Node {TO}")
                else:
                    print(f"- ({round(INFO['distance'], 3)}) -> Node {TO}; Next hop -> Node {INFO['next_hop']}")


    def KeepSendingDV(self):
        """
        send DV to neighbors for every 5 seconds
        (required by Ed https://edstem.org/us/courses/35445/discussion/3039529, https://edstem.org/us/courses/35445/discussion/3034975)
        """
        while True:
            # will begin sending every 5 seconds when sent DV at least once (because of DV change or last node)
            if self.sent_DV_once:
                # print("NODE SENT DV AT LEAST ONCE, START KEEP SENDING EVERY 5 SECONDS")
                time.sleep(5)

                # calculate the most up-to-date link loss rate from self.recv_loss_counter,
                for dest_port in self.recv_loss_counter.keys():
                    curr_loss_rate = round(self.recv_loss_counter[dest_port]['drop_cnt'] / self.recv_loss_counter[dest_port]['recv_cnt'], 2)
                    self.routing_table[self.self_listen_port][dest_port]['distance'] = curr_loss_rate

                # deicde whether to send DV
                threading.Thread(target=self.SendDV).start()




    def KeepPrintingStatus(self):
        while True:
            # will begin if sent out the first probe packet
            if self.sent_probe_once:
                # print("NODE SENT PROBE AT LEAST ONCE, START PRINT STATUS MSG")
                time.sleep(1)
                for probe_receiver, gbn_instance in self.GBN_NODES.items():
                    send_cnt = gbn_instance.sent_loss_counter['send_cnt']
                    ack_cnt = gbn_instance.sent_loss_counter['ack_cnt']
                    print(f"[{time.time()}] Link to {probe_receiver}: {send_cnt} packets sent, {send_cnt - ack_cnt} packets lost, lost rate {round((send_cnt - ack_cnt)/ send_cnt, 2)}")



    def NodeMode(self):
        self.thread_listen = threading.Thread(target=self.NodeListen)
        self.thread_listen.start()
        # print("NODE START LISTENING")

        self.thread_dv_monitor = threading.Thread(target=self.KeepSendingDV)
        self.thread_dv_monitor.start()
        # print("NODE START MONITER ON WHETHER TO KEEP SENDING DV EVERY SECONDS")

        self.thread_status_monitor = threading.Thread(target=self.KeepPrintingStatus)
        self.thread_status_monitor.start()
        # print("NODE START MONITOR ON WHETHER TO PRINT STATUS")

        if self.last_node:
            # send DV for the first time, activate the whole network
            threading.Thread(target=self.SendDV).start()

            # if last node is also probe sender, it starts to send probe when it is set up
            self.thread_probe_monitor = threading.Thread(target=self.ProbeController)
            self.thread_probe_monitor.start()
            self.sent_probe_once = True





def signal_handler(signal, frame):
    print("\nProgram interrupted. Exiting...")
    global sigint_received
    sigint_received = True
    os._exit(1)


if __name__ == "__main__":
    """
    python3 cnnode.py <local-port> receive <neighbor1-port> <loss-rate-1> <neighbor2-port> <loss-rate-2> ... <neighborM-port>
<loss-rate-M> send <neighbor(M+1)-port> <neighbor(M+2)-port> ... <neighborN-port> [last]
    """
    command = sys.argv

    # Set up the signal handler to catch SIGINT
    signal.signal(signal.SIGINT, signal_handler)

    try:
        self_port = int(command[1])
        recv_idx = command.index("receive") # 2
        send_idx = command.index("send") # 9
        last_node = True if command[-1] == 'last' else False

        # store neighbor ports and loss rates
        drop_rate_table = {}
        for i in range(recv_idx+1, send_idx, 2):
            drop_rate_table[int(command[i])] = float(command[i+1])

        # store send probe to who
        send_probe_to = command[(send_idx+1):-1] if last_node else command[(send_idx+1):]
        send_probe_to = [int(port) for port in send_probe_to]

    except:
        print("\nPlease type in valid command like:", end="")
        print("python3 cnnode.py <local-port> receive <neighbor1-port> <loss-rate-1> <neighbor2-port> <loss-rate-2> ... <neighborM-port> <loss-rate-M> send <neighbor(M+1)-port> <neighbor(M+2)-port> ... <neighborN-port> [last]")
        sys.exit(1)

    # build up initial routing table with initial distance=0
    all_neighbors = list(drop_rate_table.keys()) + send_probe_to

    # initiate routing table, only contain Node's own DV, to all its neighbor
    init_routing_table = {
        self_port: {
            self_port: {"distance": 0, "next_hop": self_port}
        }
    }
    for neighbor in all_neighbors:
        # self -> neighbor
        init_routing_table[self_port][neighbor] = {"distance": float("inf"), "next_hop": neighbor}

    for neighbor in all_neighbors:
        # neighbor -> self
        init_routing_table[neighbor] = {} # create neighbor's DV
        init_routing_table[neighbor][self_port] = {"distance": float("inf"), "next_hop": self_port}
        # neighbor -> neighbor itself
        init_routing_table[neighbor][neighbor] = {"distance": 0, "next_hop": neighbor}
        # neighbor -> other known destination
        for another_neighbor in all_neighbors:
            if another_neighbor != neighbor:
                init_routing_table[neighbor][another_neighbor] = {"distance": float("inf"), "next_hop": None}

    # print initial routing table
    print(f"[{time.time()}] Node {self_port} Routing Table")
    self_DV = init_routing_table[self_port]
    for TO, INFO in self_DV.items():
        if TO != self_port:
            if INFO['next_hop'] == TO:
                print(f"- ({round(INFO['distance'],3)}) -> Node {TO}")
            else:
                print(f"- ({round(INFO['distance'], 3)}) -> Node {TO}; Next hop -> Node {INFO['next_hop']}")

    cnnode = CnNode(self_port, drop_rate_table, send_probe_to, all_neighbors, init_routing_table)
    cnnode.NodeMode() # start the node

    # Wait for SIGINT to be received, let the main thread not terminate
    sigint_received = False
    while not sigint_received:
        time.sleep(1)
