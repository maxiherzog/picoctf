import random
from machine import UART
from machine import Pin
import uasyncio
import gc

import umsgpack

d_tickets_local = [0,0]
flag_status = 0

lora = UART(0, baudrate=9600, tx=Pin(12), rx=Pin(13), txbuf=128, rxbuf=128)

class MESSAGE_TYPE():
    REQUEST_UPDATE = 0
    UPDATE = 1
    STATUS = 2
    OK = 3
    SYNC = 4

ID = 1
    
"""_summary_: Adds leading byte to indicate size of package
"""
def package(s):
    return len(s).to_bytes(1, 'big') + s

"""_summary_: Sends an update to given ID
"""
async def send_update(send_to, update):
    global d_tickets_local, flag_status

    print("BASDKMA")
    for i in range(2):
        d_tickets_local[i] +=random.randint(0,1) # TODO: Entfernen

    
    swriter = uasyncio.StreamWriter(lora, {})
    msg = [ID, MESSAGE_TYPE.UPDATE, send_to, [d_tickets_local, flag_status]]
    print("Sending update:", msg)
    s = umsgpack.dumps(msg)
    #print(msg, "->")
    swriter.write(package(s))
    await swriter.drain()
    print("")
    swriter.close()

"""_summary_: Receives status
   _returns_: status of server([display_tickets, flag_status])
"""
async def wait_for_status() -> list:
    sreader = uasyncio.StreamReader(lora)

    while True:
        print("Listening for status(aka. update request)...")

        # first read how many bytes should be read
        lead = await sreader.read(1)
        print("Received leading byte:", lead)
        if lead == b"\x00":  # EOF
            print("EOF")
            continue  # try again

        b = await sreader.read(int.from_bytes(lead, 'big'))
        try:
            res = umsgpack.loads(b)
        except:
            print("WARNING: Recieved not loadable:", b)

        if type(res) == list:
            print("Received from COM" + str(res[0]+3) + ":", res)
            #TODO: mehr requestspezifisches zeugs
            if res[1] == MESSAGE_TYPE.STATUS:
                print("It's a status.")
                sreader.close()
                if ID > 1:
                    print("Waiting for",0.3*(ID-1),"s")
                    await uasyncio.sleep(0.3*(ID-1))
                await send_update(res[0])
                return res[2]
        else:  # not a useful object
            print('Recieved', res)
            print('Discarding...')

async def main():
    print("Hi, this is COM" + str(ID+3))
    uasyncio.create_task(wait_for_status())
    #uasyncio.create_task(receiver())
    while True:
        gc.collect()
        print('mem free', gc.mem_free())
        await uasyncio.sleep(20)


def test():
    try:
        uasyncio.run(main())
    except KeyboardInterrupt:
        print('Interrupted')
    finally:
        uasyncio.new_event_loop()

if "__main__" == __name__:
    test()