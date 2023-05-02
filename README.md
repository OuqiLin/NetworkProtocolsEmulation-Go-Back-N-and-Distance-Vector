# NetworkProtocolsEmulation-Go-Back-N-and-Distance-Vector

- Name: Ouqi Lin
- UNI: ol2251

## Part 1: Go Back N
### How to Run
Type the following command in CLI, to start running the node. The node can behave like both sender and receiver.
```
python3 gbnnode.py <self-port> <peer-port> <window-size> [ -d <value-of-n> | -p <value-of-p>]
```

### Supported Function: Send Message
```
send <long message>
```

### Exit the Program
```
ctrl+C
```

### Program Structure
#### Features 
A node maintains: 
- a socket, keep listening for incoming char/ack
- a socket for sending char/ack, will be called when needed
- a buffer
  - implemented as a list, `len=10000`. Buffer length can be set to different values, as long as not shorter than the window size. 
  - a `buffer_idx` pointer go through the buffer. Chars will be put into the buffer whenever has empty space. `buffer_idx` will wrap around when reaches the buffer end. 
  - a `buffer_full` boolean flag & a `buffer_full_condition` threading condition, used together to control when to put chars into available places.
- a sliding window over buffer
  - a `send_base` pointer indicating the start of the window
  - a `to_send` pointer indicating the position idx of the next pkt going to be sent. `to_send` will only move within the range between `send_base` and `send_base + window_size`.
  - a `nothing_to_send` boolean flag & a `send_condition` threading condition, used together to control when to sent packets to peer, and start to send from which position
- a timer
  - implemented as a threading condition. used together with a `timer_running` boolean flag. 
  - timer will be activated when the first packet is sent out. 
  - timer will be stopped and reactivated when the desired ack is received
  - if reach 500msec, will ask the `SendToPeer` thread to send everything from the the start of window all over again.
- a `pkt_num` counter
  - uniquely indentify every char that has been put into the buffer. 
  - keep increasing. The pkt_num of first char of the second input is that of the last char of the first input plus 1.
  - is used to determine whether a desired ack is correctly received. 
- a `correctly_received` indicator
  - start from -1. record the pkt_num that has been correctly received. used to move the window and print messages.
  - only be used when the node is acts as a receiver.
- a `last_ack_received` boolean flag and `last_ack_condition` threading condition, used together to decide when to print out summary. It's the ack of the last char of the current string.
- a `recv_pkt_cnt` counter and a `drop_pkt_cnt` counter, used together to calculate the actual drop rate of the node.

#### Threads and Notifications between threads
##### 1. Listening thread `NodeListen`
Keep listening for incoming char or ack. Determine whether to drop the packet or not. If not dropped: 
- if `ack`: 
  - if the ack pkt_num is larger than or equal to the window start, means the pkt up tp here are correctly received. therefore:
    - move the window
    - notify the current timer to stop and restart for the oldest in-flight packet
    - notify the `SendToPeer` thread to send new chars exposed in the window
    - clear the buffer up to here, notify the `TakeInput` thread to put more chars in the available space.
  - if this is the last ack, print out summary
- if `data`: 
  - if the pkt_num is equal to `correctly_received + 1`, means that the pkt is desired. therefore:
    - send back ack
    - if this is the last pkt, print out summary

##### 2. Input thread `TakeInput`
- supports take in a second input, after the first transmission is completed. (Actually, can support take in second input when the first is still transmitting, but the prompt `>node` will look ugly, because everything is done in one terminal, so I just let the `TakeInput` theard to wait until the first transmission is finished, then take another input) 
- split into chars and pack them into pkts.
- put pkts into buffer when has empty space. If buffer full, wait until being notified by `NodeListen` thread. 
- if buffer is full, or buffer not full yet but the entire string is in buffer, notify the send thread to start sending to peer. 

##### 3. SendToPeer thread
- wait until there's something need to be sent. 
  - will be notified by `TakeInput`, when buffer is full, or the entire string is in buffer
  - will be notified by `NodeListen`, when window moved
  - will be notified by `Timer` threads, when timeout
- when notified, send everything from `to_send` to window end.
- when `to_send` pointer is out of window, set `nothing_to_send` flag as True, therefore let the thread to waits until there's new things to send

##### 4. Timer thread
- wait for 500msec or be interrupted by `NodeListen` thread.
  - if the desired ack is receievd: check if the first char of the window is sent, if sent, restart the timer right away; if not sent, wait until it's sent.
  - if timeout: move the `to_send` back to the start of window, notify the `SendToPeer` thread to start sending.


## Part 2: Distance Vector
### How to Run
Type the following command in CLI, to start running the node.
```
python3 dvnode.py <local-port> <neighbor1-port> <loss-rate-1> <neighbor2-port> <loss-rate-2> ... [last]
```

### Exit the Program
```
ctrl+C
```

### Program Structure
#### Features 
- a socket keep listening for incoming DV 
- a socket for sending out DV
- routing table, includes:
  - the node's DV
  - the node's neighbor's DV
- a list of the node's neighbors. The program assumes that the node will know all its neighbors when setting up.
- `rece_time` table. Record the timestamp of the lastest msg received from each neighbor. It's used to determine whether a packet from the same sender need to be dropped. Due to the UDP property, a older pkt may be received later, but the info is already useless.

#### Threads and Notifications between threads
##### 1. `NodeListen` thread
when receiving DV, if not out-of-date:
- see if the DV contains some destinations that the node's current table don't know yet. If so, add these new destinations to routing table.
- calculate the new DV for the node, and determine the next_hop
- if DV updated, or the node has not sent once to neighbors yet, call the `SendDV` thread to broadcast the DV to neighbors.  
- print out the current routing table, whenever receive a DV, no matter DV is updated or not
##### 2. `SendDV` thread
a subthread for sending DV to neighbors
##### 3. `NodeMode`
- first start the `NodeListen` threads
- if this is the last node, then broadcast DV to its neighbors, to activate the network

## Part 4: GBN & DV Combination
### How to Run
**Please make sure the `gbn_for_cn.py` file is in the same folder as `cnnode.py`, before starting the `cnnode.py` program! This is served as a simplified GBN node script, which eliminates some specific requirements (e.g. CLI input) of Part 2, but keeps all the fundamental elements of GBN protocol.**

Then, type the following command in CLI, to start running the node.
```
python3 cnnode.py <local-port> receive <neighbor1-port> <loss-rate-1> <neighbor2-port> <loss-rate-2> ... <neighborM-port> <loss-rate-M> send <neighbor(M+1)-port> <neighbor(M+2)-port> ... <neighborN-port> [last]
```

### Exit the Program
```
ctrl+C
```

### Program Structure
#### Features
- CnNode
  - a socket keep listening for: 
    - (1) DV 
    - (2) probe packets, when performs as a probe receiver
    - (3) ack of probe packets, when performs as a probe sender
  - a socket for sending out: 
    - updated DV / keep sending DV for every 5 seconds (Note: this is different from the requirement from pdf, but conformed to https://edstem.org/us/courses/35445/discussion/3034975)
    - ack of probe packet, when performs as a probe receiver
  - Routing Table
  - `recv_time` table. Same function as part 3, used in DV algorithm.
  - lists containing who are the node's neighbors: `all_neighbor`, `send_probe_to`, `recv_prob_from`. 
  - `GBN_NODES` dictionary, used when performs as probe sender, key-value pair is `probe_receiver: corresponding_gbn_node_instance`.
  - `drop_rate_table`: record the ideal drop rate, for each probe sender sending probe to this cnnode.
  - `recv_loss_counter`: record the actual drop rate that this cnnode has achieved, for each probe sender sending probe to this cnnode.
  - `correctly_received`: similar to `correctly_received` counter in part 2, but now keep seperate `correctly_received` counter for each probe sender sending probe to this node.
  
- GbnNode
  - when CnNode is performing as a probe sender, for each probe receiver, create a seperate GbnNode instance to continuously send probe packet
  - maintains a `sent_loss_counter`, record the actual amount of packets sent out and actual amount of ack received. This is for print out the status message, when performs as a probe sender.

#### Threads and Notifications between threads
##### 1. NodeListen
if received:
- DV: do same calculation as part 3. Above that, this node will also use the distance from sender to itself in this DV to update its own DV. This is the major upgrade from part 3. 
  - if new DV is different from old DV, or the node has not sent DV once, call the `SendDV` thread to send the current DV.
  - when received a DV, if the node has not start to send probes yet, start the `ProbeController` thread, to manage the stuff of sending probes.
  - print out current routing table, whenever a DV is received.

- Probe pakcets, when performs as probe receiver
  - decide whether to drop the probe or not
  - update the `recv_loss_counter` for the probe's sender
  - if probe not lost, reply ack and update `correct_received` counter

- ack of probe, when performs as probe sender
  - retrieve the corresponding GbnNode for this probe's receiver
  - if ack pkt num is desired, move the window, clear the buffer, notify the timer to restart, notify the `SendToPeer` thread to send new chars exposed in the window, notify the `TakeInput` thread to put chars in newly available space.

##### 2. SendDv
A subthread, will be called when (1) DV updated (2) Every 5 seconds by `KeepSendingDV` thread.  
Routing Table will be printed everytime DV sent.

##### 3. KeepSendingDV
Sleep every 5 seconds, then wake up to send its current DV to neighbors. This thread sits aside and never stops.

##### 4. ProbeController
will be activated when called by (1) `NodeListen` thread, if is not the last node, or (2)`NodeMode` main thread, if is the last node.  
create a seperate GbnNode instance for each probe receiver, and start continuously send probes.  


##### 5. KeepPrintingStatus
Sleep every 1 second, wake up and read the `sent_loss_counter` to print for each probe receiver of the current node, what is the actual number of probes sent, and what is the actual number of packets lost (is lost if not receive ack, because ack never fails).



