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
#### Threads and Notifications between threads
##### 1. Listening thread
##### 2. Input thread
##### 3. SendToPeer thread
##### 4. Timer thread


### Potential Problems
1. If buffer size shorter than one message, 
2. Deterministic drop interval ~ window size -> endless loop
