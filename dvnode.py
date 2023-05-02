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

"""
format of X's routing table, only store its neighbors' DV, not storing non-neighbor's DV
{
X:{ X: {"distance": , "next_hop": },
    Y: {"distance": , "next_hop": },
    Z: {"distance": , "next_hop": },
    A: {"distance": , "next_hop": }, -- A is not X's neighbor
    },
Y:{ Y: {"distance": , "next_hop": },
    X: {"distance": , "next_hop": },
    Z: {"distance": , "next_hop": },
    A: {"distance": , "next_hop": }
    },
Z:{ Z: {"distance": , "next_hop": },
    X: {"distance": , "next_hop": },
    Y: {"distance": , "next_hop": },
    A: {"distance": , "next_hop": }, 
    },...
}
"""



def packetFormat(sender_listening_port, DV):
    """
    timestamp:
    time.time()
    sender_listening_port:
    port number
    DV:
    its own distance vector, a dict
    """
    DV_str = {str(TO): {k: str(v) for k, v in INFO.items()} for TO, INFO in DV.items()} # avoid precision error...
    out_packet = "\n".join(["timestamp", str(time.time()),"sender_listening_port", str(sender_listening_port), "DV", json.dumps(DV_str)])
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
    timestamp = float(lines[1])
    sender_listening_port = int(lines[3])
    recv_DV = json.loads(lines[5])
    trans_DV = TDV(recv_DV)
    # trans_DV = {int(TO): {k: float(v) if k == "distance" else int(v) for k, v in INFO.items()} for TO, INFO in recv_DV.items()} # avoid precision error...
    return timestamp, sender_listening_port, trans_DV


class DvNode():
    def __init__(self, self_port, initial_routing_table, last_node):
        self.self_listen_port = self_port  # self listening port
        self.listen_socket = socket(AF_INET, SOCK_DGRAM)
        self.listen_socket.bind(("", self.self_listen_port))

        self.send_socket = socket(AF_INET, SOCK_DGRAM)  # send ack don't bind port number
        self.send_socket_lock = threading.Lock()

        self.routing_table = initial_routing_table
        self.neighbors = list(self.routing_table.keys()) #BIG ASSUMPTION: nodes will know ALL its neighbors when initiate (confirmed in Ed)
        self.neighbors.remove(self.self_listen_port)
        self.last_node = last_node  # True / False

        self.recv_time = {}
        """
        sender1: lastest-processed-pkt-timestamp, 
        sender2: lastest-processed-pkt-timestamp, 
        ...
        """

        self.sent_once = False



    def NodeListen(self):
        """
        keep listening
        """

        while True:
            # receive neighbor's new DV
            data, addr = self.listen_socket.recvfrom(4096)
            timestamp, sender_listening_port, DV = packetResolve(data)
            # print("-------------------------------------------------------")
            # print(f"RECEIVED PKT FROM {sender_listening_port}, CONTENT IS:")
            # print(DV)
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
                        if candidate_distance < new_DV[target_dest]['distance']:
                            # NOTE: sometimes, the precision error of json will make the program thinks the distance is shorter in this round
                            # e.g. 0.799999999999 < 0.8
                            # but the routing table will eventually converge!
                            # print(f"NEW DISTANCE IS {candidate_distance}")
                            new_DV[target_dest]['distance'] = candidate_distance
                            new_DV[target_dest]['next_hop'] = old_DV[neighbor]['next_hop']

                if old_DV != new_DV:
                    # store the new DV
                    # print("DV CHANGED, STORED INTO TABLE")
                    # print("NEW DV IS ")
                    # print(new_DV)
                    self.routing_table[self.self_listen_port] = new_DV

                if old_DV != new_DV or (not self.sent_once):
                    out_pkt = packetFormat(self.self_listen_port, self.routing_table[self.self_listen_port])

                    for neighbor_port in self.neighbors:
                        threading.Thread(target=self.SendDV, args=(out_pkt, neighbor_port)).start()

                    self.sent_once = True

                # if not sent before, even if no update, should send DV to neighbors at least once
                # print out updated routing table, everytime a msg is received
                # print("-----------------CURRENT ROUTING TABLE BECAUSE RECEIVED A USEFUL MSG---------------")
                # for key, val in self.routing_table.items():
                #     print(f"FROM {key}------")
                #     print(val)
            # else:
                # print("NOT CONSIDER TO DO CALCULATION BECAUSE")

                # if not self.recv_time.get(sender_listening_port):
                #     print("NOT GET RECV TIME")
                # else:
                #     print("GET RECV TIME")

                # if timestamp > self.recv_time[sender_listening_port]:
                # print(f"RECEIVED TIMESTAMP IS {timestamp}")
                # print(f"STORED TIMESTAMP IS {self.recv_time[sender_listening_port]}")

                # PROBLEM: everything goes too fast... two msg received in one same timestamp

            # NOTE: might print some "sent" prompt before this table, but acceptable and not hurting the overall result
            print(f"[{time.time()}] Node {self.self_listen_port} Routing Table")
            self_DV = self.routing_table[self.self_listen_port]
            for TO, INFO in self_DV.items():
                if TO != self.self_listen_port:
                    if INFO['next_hop'] == TO:
                        print(f"- ({round(INFO['distance'], 3)}) -> Node {TO}")
                    else:
                        print(f"- ({round(INFO['distance'], 3)}) -> Node {TO}; Next hop -> Node {INFO['next_hop']}")


    def SendDV(self, out_pkt, neighbor_port):
        time.sleep(random.uniform(0.001, 0.01)) # to avoid too synchronised receiving activities... otherwise some msg may be deemed useless
        with self.send_socket_lock:
            self.send_socket.sendto(out_pkt.encode(), ("127.0.0.1", neighbor_port))
            print(f"[{time.time()}] Message sent from Node {self.self_listen_port} to Node {neighbor_port}")


    def NodeMode(self):
        self.thread_listen = threading.Thread(target=self.NodeListen)
        self.thread_listen.start()
        # print("NODE START LISTENING")

        if self.last_node:
            # send Node's own DV to all its neighbors
            DV = self.routing_table[self.self_listen_port]
            out_pkt = packetFormat(self.self_listen_port, DV)

            # print("THIS IS LAST NODE, START BROADCASTING")
            with self.send_socket_lock:
                for neighbor_port in self.neighbors:
                    self.send_socket.sendto(out_pkt.encode(), ("127.0.0.1", neighbor_port))
                    print(f"[{time.time()}] Message sent from Node {self.self_listen_port} to Node {neighbor_port}")
            # print("BROADCAST FINISHED")

            self.sent_once = True




def signal_handler(signal, frame):
    print("\nProgram interrupted. Exiting...")
    global sigint_received
    sigint_received = True
    os._exit(1)


if __name__ == "__main__":
    """
    python3 dvnode.py <local-port> <neighbor1-port> <loss-rate-1> <neighbor2-port> <loss-rate-2> ... [last]
    """
    command = sys.argv

    # Set up the signal handler to catch SIGINT
    signal.signal(signal.SIGINT, signal_handler)

    try:
        self_port = int(command[1])
        neighbors_port = []
        neighbors_dist = []
        for i in range(2, len(command)-1, 2):
            neighbors_port.append(int(command[i]))
            neighbors_dist.append(float(command[i+1]))

        last_node = True if command[-1] == 'last' else False
    except:
        print("\nPlease type in valid command like:", end="")
        print("\npython3 dvnode.py <local-port> <neighbor1-port> <loss-rate-1> <neighbor2-port> <loss-rate-2> ... [last]", end="")
        sys.exit(1)

    # initiate routing table, only contain Node's own DV, to all its neighbor
    init_routing_table = {
        self_port: {
            self_port: {"distance": 0, "next_hop": self_port}
        }
    }
    for i in range(len(neighbors_port)):
        neighbor = neighbors_port[i]
        distance = neighbors_dist[i]
        # self -> neighbor
        init_routing_table[self_port][neighbor] = {"distance": distance, "next_hop": neighbor}

    for i in range(len(neighbors_port)):
        # neighbor -> self
        neighbor = neighbors_port[i]
        init_routing_table[neighbor] = {} # create neighbor's DV
        init_routing_table[neighbor][self_port] = {"distance": neighbors_dist[i], "next_hop": self_port}
        # neighbor -> neighbor itself
        init_routing_table[neighbor][neighbor] = {"distance": 0, "next_hop": neighbor}
        # neighbor -> other known destination
        for j in range(len(neighbors_port)):
            if j != i:
                dest = neighbors_port[j]
                init_routing_table[neighbor][dest] = {"distance": float("Inf"), "next_hop": None}

    # print("------------INITIAL ROUTING TABLE----------------")
    # for key, val in init_routing_table.items():
    #     print(key)
    #     print(val)

    print(f"[{time.time()}] Node {self_port} Routing Table")
    self_DV = init_routing_table[self_port]
    for TO, INFO in self_DV.items():
        if TO != self_port:
            if INFO['next_hop'] == TO:
                print(f"- ({round(INFO['distance'],3)}) -> Node {TO}")
            else:
                print(f"- ({round(INFO['distance'], 3)}) -> Node {TO}; Next hop -> Node {INFO['next_hop']}")

    dvnode = DvNode(self_port, init_routing_table, last_node)
    dvnode.NodeMode()

    # Wait for SIGINT to be received, let the main thread not terminate
    sigint_received = False
    while not sigint_received:
        time.sleep(1)
