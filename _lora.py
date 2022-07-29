import time
import uasyncio
import umsgpack
from machine import UART
from machine import Pin
from machine import Timer

# append so we can also access root directory modules
import sys
import gc
sys.path.append("..")


#import lora_comm as comm  #selfmade


class MESSAGE_TYPE():
    REQUEST_UPDATE = 0
    UPDATE = 1
    STATUS = 2
    OK = 3
    SYNC = 4

# get current time
def get_time(self):
    t = time.localtime()
    return str(t[4]) + ":" + str(t[5])

class Client():
    
    def __init__(self, id, lora):
        self.id = id
        self.lora = lora
        try:
            uasyncio.run(self.initialize_connection())
        except KeyboardInterrupt:
            self.log('Interrupted')
        finally:
            uasyncio.new_event_loop()
    
    
    def log(self, message):
        # log handling
        # at the moment just prints to the console TODO: add to log file
        self.log("COM" + str(self.id+3) +" (client) @ " + self.get_time() + " > " + str(message))
    
    
    async def initialize_connection(self):
        self.log("Hi, this is COM" + str(self.id+3))
        uasyncio.create_task(self.wait_for_status())
        while True:
            gc.collect()
            self.log('mem free', gc.mem_free())
            await uasyncio.sleep(20)
    
    def package(self,s):
        return len(s).to_bytes(1, 'big') + s
    
    """_summary_: Sends an update to given ID
    """
    async def send_update(self, send_to, update):
        swriter = uasyncio.StreamWriter(self.lora, {})
        msg = [self.id, MESSAGE_TYPE.UPDATE, send_to, update]
        self.log("Sending update:", msg)
        s = umsgpack.dumps(msg)
        #self.log(msg, "->")
        swriter.write(self.package(s))
        await swriter.drain()
        self.log("")
        swriter.close()

    """_summary_: Receives status
       _returns_: status of server([display_tickets, flag_status])
    """
    async def wait_for_status(self) -> list:
        sreader = uasyncio.StreamReader(self.lora)

        while True:
            self.log("Listening for status(aka. update request)...")

            # first read how many bytes should be read
            lead = await sreader.read(1)
            self.log("Received leading byte:", lead)
            if lead == b"\x00":  # EOF
                self.log("EOF")
                continue  # try again

            b = await sreader.read(int.from_bytes(lead, 'big'))
            try:
                res = umsgpack.loads(b)
            except:
                self.log("WARNING: Recieved not loadable:", b)

            if type(res) == list:
                self.log("Received from COM" + str(res[0]+3) + ":", res)
                if res[1] == MESSAGE_TYPE.STATUS:
                    self.log("It's a status.")
                    sreader.close()
                    if self.id > 1:
                        self.log("Waiting for", 0.3*(self.id-1), "s")
                        await uasyncio.sleep(0.3*(self.id-1))
                    await self.send_update(res[0])
                    return res[2]
            else:  # not a useful object
                self.log('Recieved', res)
                self.log('Discarding...')


class Server():
    def __init__(self, id, lora):
        self.id = id
        self.lora = lora
        try:
            uasyncio.run(self.initialize_connection())
        except KeyboardInterrupt:
            self.log('Interrupted')
        finally:
            uasyncio.new_event_loop()

    async def broadcast_status(self, status):
        swriter = uasyncio.StreamWriter(self.lora, {})
        print("Sending", status)
        s = umsgpack.dumps(status)  # Synchronous serialisation
        swriter.write(self.package(s))
        await swriter.drain()  # Asynchonous transmissi

    def package(self,s):
        return len(s).to_bytes(1, 'big') + s

    def log(self, message):
        # log handling
        # at the moment just prints to the console TODO: add to log file
        print("COM" + str(self.id+3) + " (client) @ " + self.get_time() + " > " + str(message))

    def routine(self, start_tickets, d_tickets, flags_status):

        self.log("")
        self.log("Routine ------------------------------------------------")
        # STATUS
        # send game state
        self.log("Delta tickets", d_tickets)
        displayed_tickets = start_tickets.copy()
        for i in range(2):
            for node in range(3):
                displayed_tickets[i] -= d_tickets[node][i]
        game = [self.id, MESSAGE_TYPE.STATUS, [displayed_tickets, flags_status]]
        uasyncio.run(self.broadcast_status(game))
        # wait a bit TODO: wie lang?
        time.sleep(2)

        # then read possibly arrived updates
        #sreader = uasyncio.StreamReader(lora)
        while True:
            lead = self.lora.read(1)  # first read how many bytes should be read
            if lead == None:
                break
            b = self.lora.read(int.from_bytes(lead, 'big'))
            self.log(b)
            try:
                res = umsgpack.loads(b)
            except:
                self.log("WARNING: Recieved not loadable:", b)
            self.log("Received from COM"+str(3+res[0]) + ":", res)
            # check if update is correct
            if type(res) == list:
                # UPDATE
                if res[1] == MESSAGE_TYPE.UPDATE and res[2] == ID:
                    self.log("Update received:", res[3])
                    update = res[3]
                    d_tickets[res[0]] = update[0]  # local d_tickets
                    
                    flags_status[res[0]] = update[1]  # local flags_status
                    
            else:
                self.log("Discarding...")
        # return at the end
        return start_tickets, d_tickets, flags_status
