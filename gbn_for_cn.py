import random
import socket
from socket import *
import threading # multi threading: sending and receiving at the same time
from threading import Condition
import sys # for CLI
import os # os.exit()
import time
import signal
import json



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




class gbnNode():
    def __init__(self, self_port, peer_port, window_size, drop_pkt, drop_param):

        self.self_listen_port = self_port # self listening port
        # MODIFIED: no need listen port

        self.send_socket = socket(AF_INET, SOCK_DGRAM) # send ack don't bind port number
        self.send_socket_lock = threading.Lock()

        self.peer_listen_port = peer_port # node already know who is the peer, peer listening port

        self.drop_pkt = drop_pkt # d or p
        self.drop_param = drop_param

        self.buffer_len = 10000
        # Any reasonable buffer size satisfy!!! can wrap around by my design (not shorter than window though)
        # you can try some buffer size like 10, 20 with a long string len >> 10
        self.buffer = [None] * self.buffer_len # can be assessed by both send and listen thread
        """
        [(pktNum, pkt), (pktNum, pkt), ...]
        """
        self.buffer_idx = 0 # add the pkt to which place of the buffer
        self.buffer_lock = threading.Lock()
        self.buffer_full = False # if full, wait until buffer has empty space, then add remaining chars into the buffer
        self.buffer_full_condition = threading.Condition()

        self.send_base = 0 # the begin of the window
        self.window_size = window_size # window sliding across the buffer, wrap around when reach the buffer end
        self.to_send = 0 # move within the window. If out, wait until notified
        self.nothing_to_send = True # wait until window contains sth needed to be sent
        self.send_condition = threading.Condition()

        self.timer_running = False
        self.timer_condition = threading.Condition() # wait until timeout, or be notified because expected ack received

        self.pkt_num = 0
        self.correct_received = -1 # only used when acts as a receiver

        self.last_ack_received = False
        # only after the last ack of current string is received, will the input thread take a new input
        # otherwise, the ">node " prompt will look ugly, because all prints are one the same terminal in this assignment
        self.last_ack_condition = threading.Condition()

        # MODIFIED: ack won't loss so don't need this counter
        # self.recv_pkt_cnt = 0
        # self.drop_pkt_cnt = 0

        self.sent_loss_counter = {"send_cnt": 0, "ack_cnt": 0}


    def TakeInput(self):
        """
        terminal won't read any chars by send command until the previous one is fully put into the buffer
        """
        probe_char = "a"
        while True:
            pkt = packetFormat(type="probe", pktNum=self.pkt_num, char=probe_char, sender_listening_port=self.self_listen_port, DV=None)

            # wait until the buffer has empty space, then put in the next probe packet
            while self.buffer_full:
                with self.buffer_full_condition:
                    self.buffer_full_condition.wait()

            # put (pktNum, pkt) into buffer
            self.buffer[self.buffer_idx] = (self.pkt_num, pkt)
            # print(f"\nPUT {self.pkt_num} INTO BUFFER", end="")
            self.buffer_idx = (self.buffer_idx + 1) % self.buffer_len # where to insert a new pkt into buffer in the next round , wrap around
            self.pkt_num += 1 # uniquely identify each char

            # print("\n BUFFER LOOKS LIKE:")
            # print(self.buffer)

            # MODIFIED: start to send probe packet only when buffer full for the first time, then never stop
            if self.buffer[self.buffer_idx] is not None:
                self.buffer_full = True
                self.nothing_to_send = False
                with self.send_condition:
                    self.send_condition.notify() # after fill out the buffer for the first time, ask the send thread begin sending
                    # print("\nINPUT THREAD NOTIFIED SEND THREAD", end="")



    def SendToPeer(self):
        """
        read chars from buffer, send to peer
        window slides across the buffer, and wrap around when reach the end
        """
        # ADD: should move the send_loss_counter here, and be accessed by cnnode to print

        while True:
            # wait until has something to send
            # will be notified by:
            # 1) buffer full for the first time 2) window slide 3) timeout, send again from the window begin
            while self.nothing_to_send:
                # print("\nSEND THREAD WAITING...", end="")
                with self.send_condition:
                    self.send_condition.wait()
            # print("\nSEND THREAD BE NOTIFIED, NOW START TO SEND", end="")

            # MODIFIED: make the probe sent slow, otherwise flood the network... make the listener hard to manage other messgae
            time.sleep(0.05)

            # because need to deal with window wrap around case
            window_contains = list(range(self.send_base, self.send_base + self.window_size))
            window_contains = [idx % self.buffer_len for idx in window_contains]

            # iterate through chars in window
            while self.to_send in window_contains and self.buffer[self.to_send] is not None:
                # the 2nd cond: deal with short string but long buffer
                # out_pktNum = self.buffer[self.to_send][0]
                out_pkt = self.buffer[self.to_send][1]
                # out_char = out_pkt.splitlines()[5]

                with self.send_socket_lock:
                    self.send_socket.sendto(out_pkt.encode(), ("127.0.0.1", self.peer_listen_port))
                    # print(f"\n[{time.time()}] packet probe sent", end="")
                    self.sent_loss_counter['send_cnt'] += 1

                self.to_send = (self.to_send + 1) % self.buffer_len

                # start the timer when first char is sent out. This piece only run once
                if not self.timer_running:
                    threading.Thread(target=self.Timer).start()
                    self.timer_running = True
                    # print("\nTimer starts working", end="")

            # loop break if to_send pointer out of window
            # from here, start waiting until other threads notify it to send
            self.nothing_to_send = True


    def Timer(self):
        """
        return True: if notified by other thread
        return False: if timeout happens
        """
        # wait() method is used to block the thread and wait until some other thread notifies it by calling the notify() or notify_all() method
        # or if the timeout occurs.
        while True:
            if not self.last_ack_received:
                with self.timer_condition:
                    good_ack = self.timer_condition.wait(0.5)
                if good_ack:
                    # if timer_condition be notified by listening thread, means that ack is received
                    # start new timer for the oldest in-flight pkt

                    # if the first char of window has not been sent, wait until it be sent, then start the timer
                    while True:
                        if self.to_send != self.send_base:
                            break
                else:
                    # if timeout happens, let the send thread send from window beginning
                    # print(f"\n[{time.time()}] packet{self.send_base} timeout", end="")
                    self.to_send = self.send_base
                    self.nothing_to_send = False
                    with self.send_condition:
                        # print("\nTIMER THREAD NOTIFY SEND THREAD", end="")
                        self.send_condition.notify()

    def NodeMode(self):

        # self.thread_listen = threading.Thread(target=self.NodeListen)
        # self.thread_listen.start()
        # print("\n>>> Node start listening", end="")

        self.thread_send = threading.Thread(target=self.SendToPeer)
        self.thread_send.start()
        # print("\n>>> Node start waiting to send chars in buffer, when buffer is filled", end="")

        self.thread_input = threading.Thread(target=self.TakeInput)
        self.thread_input.start()
        # print("\n>>> Node start to take user input, whenever buffer has space", end="")


# if __name__ == "__main__":
#     # create Node instance, start the NodeMode
#     node = gbnNode(6666, 7777, 5, 'p', 0)
#     node.NodeMode()

