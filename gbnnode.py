import random
import socket
from socket import *
import threading # multi threading: sending and receiving at the same time
from threading import Condition
import sys # for CLI
import os # os.exit()
import time
import signal




def packetFormat(type, pktNum="", char="", last_pkt=False):
    """
    type:
    data/ack
    pktNum:
    1,..., keep increasing continuously for all input strings
    char:
    each char a pkt when type==data, None when type==ack
    last_pkt: -- used to print out loss rate calculation
    Yes/No
    """
    out_packet = "\n".join(["type", type, "pktNum", str(pktNum), "char", str(char), "last_pkt", str(last_pkt)])
    return out_packet

def packetResolve(in_packet):
    in_packet = in_packet.decode()
    lines = in_packet.splitlines()
    type = lines[1]
    if type == "ack":
        return type, int(lines[3]), None, eval(lines[7])
        # eval convert string-type 'True' 'False' to boolean type
    elif type == "data":
        return type, int(lines[3]), lines[5], eval(lines[7])


class gbnNode():
    def __init__(self, self_port, peer_port, window_size, drop_pkt, drop_param):

        self.self_listen_port = self_port # self listening port
        self.listen_socket = socket(AF_INET, SOCK_DGRAM)
        self.listen_socket.bind(("", self.self_listen_port))

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

        self.recv_pkt_cnt = 0
        self.drop_pkt_cnt = 0


    def TakeInput(self):
        """
        terminal won't read any chars by send command until the previous one is fully put into the buffer
        """
        while True:
            # prompt
            print("\nnode> ", end="")

            # take user "send" command
            try:
                temp = input()
            except KeyboardInterrupt:
                # user close program by ctrl+C (recognized as KeyboardInterrupt in Python)
                os._exit(1)

            input_list = temp.split()

            # reorganize the command, if is valid command "send"
            try:
                command = input_list[0]
                msg = input_list[1:]
            except:
                print("\nInvalid command. Only support send <message>.", end="")
                continue
            if command != "send":
                print("\nInvalid command. Only support send <message>.", end="")
                continue

            self.last_ack_received = False

            # reconstruct the message
            msg = ""
            for i in range(1, len(input_list)-1):
                msg = msg + input_list[i] + " "
            msg = msg + input_list[len(input_list)-1] # concat the last char without extra space at the end

            # break the string into a list of chars
            chars = [*msg]

            # iterate through chars
            for n in range(len(chars)):
                # format the packet
                if n == (len(chars)-1):
                    # last packet
                    pkt = packetFormat(type="data", pktNum=self.pkt_num, char=chars[n], last_pkt=True)
                else:
                    pkt = packetFormat(type="data", pktNum=self.pkt_num, char=chars[n], last_pkt=False)

                # wait until the buffer has empty space
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

                if self.buffer[self.buffer_idx] is not None:
                    self.buffer_full = True

                if (self.buffer[self.buffer_idx] is not None) or (n == len(chars)-1):
                    # 1st condition: buffer alreay full (although msg not fully put into buffer)
                    # 2nd condition: deal with short string but long buffer & only one message buffer never full

                    self.nothing_to_send = False
                    with self.send_condition:
                        self.send_condition.notify() # after fill out the buffer for the first time, ask the send thread begin sending
                        # print("\nINPUT THREAD NOTIFIED SEND THREAD", end="")



            # TA adviser on ed:
            # only after the string has been fully put into the buffer,
            # will take the next input msg
            # HOWEVER, this look ugly because the ">node " prompt will be print out when the curr string msg printing out
            # so modify as only after the last char's ack is received, will the thread take in a new input
            while not self.last_ack_received:
                with self.last_ack_condition:
                    self.last_ack_condition.wait()



    def SendToPeer(self):
        """
        read chars from buffer, send to peer
        window slides across the buffer, and wrap around when reach the end
        """

        while True:
            # wait until has something to send
            # will be notified by:
            # 1) buffer full for the first time 2) window slide 3) timeout, send again from the window begin
            while self.nothing_to_send:
                # print("\nSEND THREAD WAITING...", end="")
                with self.send_condition:
                    self.send_condition.wait()
            # print("\nSEND THREAD BE NOTIFIED, NOW START TO SEND", end="")

            # because need to deal with window wrap around case
            window_contains = list(range(self.send_base, self.send_base + self.window_size))
            window_contains = [idx % self.buffer_len for idx in window_contains]

            # iterate through chars in window
            while self.to_send in window_contains and self.buffer[self.to_send] is not None:
                # the 2nd cond: deal with short string but long buffer
                out_pktNum = self.buffer[self.to_send][0]
                out_pkt = self.buffer[self.to_send][1]
                out_char = out_pkt.splitlines()[5]

                with self.send_socket_lock:
                    self.send_socket.sendto(out_pkt.encode(), ("127.0.0.1", self.peer_listen_port))
                    print(f"\n[{time.time()}] packet{out_pktNum} {out_char} sent", end="")

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
                    print(f"\n[{time.time()}] packet{self.send_base} timeout", end="")
                    self.to_send = self.send_base
                    self.nothing_to_send = False
                    with self.send_condition:
                        # print("\nTIMER THREAD NOTIFY SEND THREAD", end="")
                        self.send_condition.notify()



    def NodeListen(self):
        """
        listen for ack
        side thread starts before type in msg and send pkts
        """
        while True:
            data, addr = self.listen_socket.recvfrom(4096)
            type, pktNum, char, last_pkt = packetResolve(data)
            self.recv_pkt_cnt += 1
            # print("MSG RECEIVED:")
            # print(type)
            # print(pktNum)
            # print(char)

            if type == "ack":
                # Node acts as a sender
                # emulate ack drop
                lost = False
                if self.drop_pkt == "d":
                    if self.recv_pkt_cnt % self.drop_param == 0:
                        # print(f"CURRENT PKT NUM IS {self.recv_pkt_cnt}, CAN BE FULLY DIVIDED, DROPPED")
                        lost = True
                        self.drop_pkt_cnt += 1
                elif self.drop_pkt == "p":
                    if random.random() < self.drop_param:
                        lost = True
                        self.drop_pkt_cnt += 1

                waiting_ack_pktNum = self.buffer[self.send_base][0]
                distance = pktNum - waiting_ack_pktNum # due to GBN property, may lost send_base ack but received following ack
                # correctly received
                if pktNum >= waiting_ack_pktNum and not lost:

                    # erase buffer up til correctly received
                    erase_idx = list(range(self.send_base, self.send_base+distance+1))
                    erase_idx = [idx % self.buffer_len for idx in erase_idx]
                    for e_idx in erase_idx:
                        self.buffer[e_idx] = None

                    # move forward the window
                    self.send_base = (self.send_base + distance + 1) % self.buffer_len
                    print(f"\n[{time.time()}] ACK{pktNum} received, window moves to {self.send_base}", end="")

                    # notify the timer to stop timing and restart for the oldest in-flight packet
                    with self.timer_condition:
                        # print("\nLISTEN THREAD NOTIFY TIMER", end="")
                        self.timer_condition.notify()
                        # print("\nCurrent Timer stop", end="")

                    # notify the send thread to send new chars exposed in the window
                    self.nothing_to_send = False
                    with self.send_condition:
                        # print("\nLISTEN THREAD NOTIFY SEND THREAD", end="")
                        self.send_condition.notify()

                    # notify the input thread to put remaining chars into buffer
                    self.buffer_full = False
                    with self.buffer_full_condition:
                        # print("\nLISTEN THREAD NOTIFY BUFFER", end="")
                        self.buffer_full_condition.notify()

                    if last_pkt == True:
                        self.last_ack_received = True
                        with self.last_ack_condition:
                            self.last_ack_condition.notify()

                        print(f"\n[Summary] {self.drop_pkt_cnt}/{self.recv_pkt_cnt} packets dropped, loss rate = {round(self.drop_pkt_cnt / self.recv_pkt_cnt, 2)}")



                # elif pktNum < send_base and not lost:  # actually don't care this ack
                elif lost:
                    # useless ack, discard
                    # either deliberately or because of useless Q: is that true?
                    print(f"\n[{time.time()}] ACK{pktNum} discarded", end="")

            elif type == "data":
                # Node acts as a receiver

                # emulate data drop
                lost = False
                if self.drop_pkt == "d":
                    if self.recv_pkt_cnt % self.drop_param == 0:
                        # print(f"\nCURRENT PKT COUNT IS {self.recv_pkt_cnt}, CAN BE FULLY DIVIDED, DROPPED", end="")
                        lost = True
                        self.drop_pkt_cnt += 1
                elif self.drop_pkt == "p":
                    if random.random() < self.drop_param:
                        lost = True
                        self.drop_pkt_cnt += 1

                if lost:
                    print(f"\n[{time.time()}] packet{pktNum} {char} discarded", end="")
                else:
                    print(f"\n[{time.time()}] packet{pktNum} {char} received", end="")

                    # if received desired pkt, add correct_received 1, get new correct_received
                    if pktNum == (self.correct_received + 1):
                        # print(f"\nPREVIOUS ACK TIL {self.correct_received}, now add to:", end="")
                        self.correct_received += 1
                        # print(f" CURRENT ACT TIL {self.correct_received}", end="")

                    # send ack in a sub thread
                    # always reply the most up-to-date correct_received
                    ack_packet = packetFormat(type="ack", pktNum=self.correct_received, char="", last_pkt=last_pkt)
                    """
                    threading.Thread(target=self.replyAck,
                                     args=(self.correct_received, ack_packet, self.peer_listen_port)).start()
                    """

                    with self.send_socket_lock:
                        self.send_socket.sendto(ack_packet.encode(), ("127.0.0.1", self.peer_listen_port))
                        print(f"\n[{time.time()}] ACK{self.correct_received} sent, expecting packet{self.correct_received + 1}", end="")

                    if last_pkt and self.correct_received+1 > pktNum:
                        # if last pkt, and expecting # is larger than this last pkt (so that the last pkt's previous is also received)
                        print(f"\n[Summary] {self.drop_pkt_cnt}/{self.recv_pkt_cnt} packets dropped, loss rate = {round(self.drop_pkt_cnt/self.recv_pkt_cnt, 2)}")


                # if last_char:
                #     # ADD: field in header indicate last char of this msg, so that know reset curr_ack
                #     self.current_ack = -1
    """
    def replyAck(self, current_ack, ack_packet, target_port):
        with self.send_socket_lock:
            self.send_socket.sendto(ack_packet.encode(), ("127.0.0.1", target_port))
            print(f"\n[{time.time()}] ACK{current_ack} sent, expecting packet{current_ack+1}", end="")
    """

    def NodeMode(self):

        self.thread_listen = threading.Thread(target=self.NodeListen)
        self.thread_listen.start()
        # print("\n>>> Node start listening", end="")

        self.thread_send = threading.Thread(target=self.SendToPeer)
        self.thread_send.start()
        # print("\n>>> Node start waiting to send chars in buffer, when buffer is filled", end="")

        self.thread_input = threading.Thread(target=self.TakeInput)
        self.thread_input.start()
        # print("\n>>> Node start to take user input, whenever buffer has space", end="")

def signal_handler(signal, frame):
    print("\nProgram interrupted. Exiting...")
    global sigint_received
    sigint_received = True
    os._exit(1)


if __name__ == "__main__":
    # take in user CLI input
    if len(sys.argv) != 6:
        print("\nPlease use valid input command like:", end="")
        print("\npython3 gbnnode.py <self-port> <peer-port> <window-size> [ -d <value-of-n> | -p <value-of-p>]", end="")
        sys.exit(1)

    # Set up the signal handler to catch SIGINT
    signal.signal(signal.SIGINT, signal_handler)

    # split the command
    drop_pkt = sys.argv[4]
    drop_param = sys.argv[5]

    # valid self_port
    try:
        self_port = int(sys.argv[1])
    except:
        print("\nInvalid self port number. Try again.", end="")
        sys.exit(1)
    if not (self_port >= 1024 and self_port <= 65535):
        print("\nInvalid server port number", end="")
        sys.exit(1)

    # valid peer_port
    try:
        peer_port = int(sys.argv[2])
    except:
        print("\nInvalid peer port number. Try again.", end="")
        sys.exit(1)
    if not (peer_port >= 1024 and peer_port <= 65535):
        print("\nInvalid server port number", end="")
        sys.exit(1)

    # valid window_size
    try:
        window_size = int(sys.argv[3])
    except:
        print("\nInvalid winow size number. Try again.", end="")
        sys.exit(1)


    # valid drop_pkt command, and valid value after that
    try:
        drop_pkt = sys.argv[4][1]
    except:
        print("\nInvalid drop packet method. Should be -d or -p. Try again", end="")
        sys.exit(1)
    if drop_pkt == "d":
        try:
            drop_param = int(sys.argv[5])
        except:
            print("\nInvalid drop pakcet argument.", end="")
            sys.exit(1)
        if drop_param < 0:
            print("\nInvalid drop pakcet argument.", end="")
            sys.exit(1)

        """
        NOTE: window size + 1 can't be fully devide by drop_param, otherwise, will endless
        """

    elif drop_pkt == "p":
        try:
            drop_param = float(sys.argv[5])
        except:
            print("\nInvalid drop pakcet argument.", end="")
            sys.exit(1)
        if drop_param > 1 or drop_param < 0:
            print("\nInvalid drop pakcet argument.", end="")
            sys.exit(1)

    else:
        print("\nInvalid drop packet method. Should be -d or -p. Try again", end="")
        sys.exit(1)

    # create Node instance, start the NodeMode
    node = gbnNode(self_port, peer_port, window_size, drop_pkt, drop_param)
    node.NodeMode()


    # Wait for SIGINT to be received, let the main thread not terminate
    sigint_received = False
    while not sigint_received:
        time.sleep(1)
