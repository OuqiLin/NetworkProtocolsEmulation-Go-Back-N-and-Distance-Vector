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

### Program Structure
#### Threads and Notifications between them
##### 1. Listening thread
##### 2. Input thread
##### 3. SendToPeer thread
##### 4. Timer thread
##### structure diagram
##### UDP Packet Format

### Test Case
#### 1. Sender p=0.3 drop ACK, Receiver p=0 drop data, window size=5, string abcdefghijk
#### 2. Sender p=0 drop ACK, Receiver p=0.3 drop data, window size=5, string abcdefghijk
#### 3. Sender p=0.3 drop ACK, Receiver p=0.1 drop ACK, window size=5, string abcdefghijk
#### 4. Sender p=0 drop ACK, Receiver p=0.3 drop data, window size=5, long string 1000chars


### Potential Problems
1. If buffer size shorter than one message, 
2. Relationship between Deterministic drop interval and window size, may cause endless loop in some special case
