from machine import UART
from machine import Pin
from machine import Timer

# append so we can also access root directory modules
import sys
import gc
sys.path.append("..")

import umsgpack

#import lora_comm as comm  #selfmade

import uasyncio
import time
# init lora
lora = UART(0, baudrate=9600, tx=Pin(12), rx=Pin(13), txbuf=128, rxbuf=128)
tim_1s = Timer()


class MESSAGE_TYPE():
    REQUEST_UPDATE = 0
    UPDATE = 1
    STATUS = 2
    OK = 3
    SYNC = 4


ID = 0
# async def send_sync():
#     print("Sending sync..")
#     swriter = uasyncio.StreamWriter(lora, {})
#     s = SYNC
#     swriter.write(s)
#     print(s)
#     await swriter.drain()

async def broadcast_status(status):
    swriter = uasyncio.StreamWriter(lora, {})
    print("Sending", status)
    s = umsgpack.dumps(status)  # Synchronous serialisation
    swriter.write(package(s))
    await swriter.drain()  # Asynchonous transmission


# async def async_receiver():
#     sreader = uasyncio.StreamReader(lora)
#     while True:
#         res = await umsgpack.aload(sreader)
#         print('Recieved', res)

# """ receiver with packaging """
# async def receiver():
#     sreader = uasyncio.StreamReader(lora)
#     while True:
#         res = await sreader.read(1) # first read how many bytes should be read
#         real = await sreader.readexactly(int.from_bytes(res, 'big'))
#         try:
#             print("Recieved", umsgpack.loads(real))
#         except Exception as e:
#             print("Recieved weird", real)
        # res = umsgpack.load(sreader)
        # print("Recieved", res)
        # await uasyncio.sleep(1)

# def receiver_bad():
#     while True:
#         res = lora.read(1) # first read how many bytes should be read
#         if res:
#             print(res)
#             real = lora.read(int.from_bytes(res, 'big'))
#             try:
#                 print("Recieved", umsgpack.loads(real))
#             except Exception as e:
#                 print("Recieved weird", real.loads(real))
#         time.sleep(0.02)
#         #res = umsgpack.load(sreader)
#         #print("Recieved", res)
#         #await uasyncio.sleep(1)

# add leading byte to indicate size of package
def package(s):
    #print(s, "->", len(s).to_bytes(1, 'big') + s)
    return len(s).to_bytes(1, 'big') + s
    #return b"\x00" + bytes + b"\x00"

REQUEST_ID = 1
async def request_update(request_id=REQUEST_ID):
    print("Requesting update from COM"+str(3+request_id) + "...")
    swriter = uasyncio.StreamWriter(lora, {})
    msg = [ID, MESSAGE_TYPE.REQUEST_UPDATE, request_id]
    print("Sending", msg)
    time_ms = time.ticks_ms()
    swriter.write(package(umsgpack.dumps(msg))) # try package for now
    await swriter.drain()
    swriter.close()
    print("Time to write:", time.ticks_ms() - time_ms, "ms")
    # now listen to response
    
    print("Waiting for response...")
    sreader = uasyncio.StreamReader(lora)
    lead = await sreader.read(1)  # first read how many bytes should be read
    time_2 = time.ticks_ms()
    print("Time to receive first byte:", time_2 - time_ms, "ms")
    b = await sreader.readexactly(int.from_bytes(lead, 'big'))
    try: 
        res = umsgpack.loads(b)
    except:
        print("WARNING: Recieved not loadable:", b)
    print("Received from COM"+str(3+res[0]) + ":", res)
    # check if update is correct
    if type(res) == list:
        # UPDATE
        if res[0]==request_id and res[1]==MESSAGE_TYPE.UPDATE and res[2]==ID:
            print("Update received:", res[3])
            print("in", time.ticks_ms()-time_ms, "ms")
            return True
    else:
        print("Discarding...")
    return False

start_tickets = [100, 100]
d_tickets = [[0,0],[0,0],[0,0]]
flags_status = [0,0,0]
updates_received = [True, True]
def routine(x):
    global start_tickets, d_tickets, flags_status, updates_received
    
    import random
    for i in range(2):
        d_tickets[ID][i] += random.randint(0,1)
    
    
    print("")
    print("Routine ------------------------------------------------")
    # STATUS
    # send game state
    print("Delta tickets", d_tickets)
    displayed_tickets = start_tickets.copy()
    for i in range(2):
        for node in range(3):
            displayed_tickets[i] -= d_tickets[node][i]
    game = [ID, MESSAGE_TYPE.STATUS, [displayed_tickets, flags_status]]
    uasyncio.run(broadcast_status(game))
    # wait a bit TODO: wie lang? 
    time.sleep(2)
    
    # then read possibly arrived updates
    #sreader = uasyncio.StreamReader(lora)
    while True:
        lead = lora.read(1)  # first read how many bytes should be read
        if lead == None:
            break
        b = lora.read(int.from_bytes(lead, 'big'))
        print(b)
        try:
            res = umsgpack.loads(b)
        except:
            print("WARNING: Recieved not loadable:", b)
        print("Received from COM"+str(3+res[0]) + ":", res)
        # check if update is correct
        if type(res) == list:
            # UPDATE
            if res[1] == MESSAGE_TYPE.UPDATE and res[2] == ID:
                print("Update received:", res[3])
                update = res[3]
                d_tickets[res[0]] = update[0] # local d_tickets
                flags_status[res[0]] = update[1] # local flags_status
        else:
            print("Discarding...")
    

async def main():
    #uasyncio.create_task(sender())
    #await send_sync()
    tim_1s.init(period=5000, mode=Timer.PERIODIC, callback=routine)
    while True:
        gc.collect()
        print('mem free', gc.mem_free())
        await uasyncio.sleep(20)


def test():
    try:
        print("Hi, this is COM" + str(ID+3))
        uasyncio.run(main())
    except KeyboardInterrupt:
        print('Interrupted')
    finally:
        uasyncio.new_event_loop()

if "__main__" == __name__:
    test()
