import _thread
import ILI9341
import time
import uasyncio
import umsgpack
from machine import UART
from machine import Pin
from machine import Timer
import gc

## enums

class MESSAGE_TYPE():
    REQUEST_UPDATE = 0
    UPDATE = 1
    STATUS = 2
    OK = 3
    SYNC = 4
    READY = 5

class GAME_STATUS():
    PAIRING = 0
    RUNNING = 1
    ENDED = 2
    ERROR = 3

##################################

# SPIELEINSTELLUNG ####
# TODO: Sync
RESPAWN_TIME = 30
CONVERSION_TIME = 10000
RESPAWN_TICKET_COST = 5
INITIAL_TICKET_AMOUNT = 100
TICKET_DECAY_PERIOD = 5000
COUNTDOWN_GAME_START = 10

# TECHNICAL SETTINGS
DEBOUNCE_MS = 100
SEQUENTIAL_DIFFERENCE_UPDATE_CLIENTS_MS = 300 # CLIENT
WAIT_FOR_UPDATE_GATHERING_MS = 1000 # SERVER

####


#Pinbelegung
button_respawn = Pin(21, Pin.IN, Pin.PULL_UP)
button_flag_red = Pin(20, Pin.IN, Pin.PULL_UP)
button_flag_blue = Pin(19, Pin.IN, Pin.PULL_UP)
lora = UART(0, baudrate=9600, tx=Pin(12), rx=Pin(13))
LCD_RD = 15
LCD_WR = 9
LCD_RS = 26   # RS & CS pins must be ADC and OUTPUT
LCD_CS = 27   # for touch capability -> For Rpico only pins 26, 27 & 28 !
LCD_RST = 14

LCD_D0 = 0
LCD_D1 = 1
LCD_D2 = 2
LCD_D3 = 3
LCD_D4 = 10
LCD_D5 = 11
LCD_D6 = 6
LCD_D7 = 7

XP = LCD_D0
YM = LCD_D1
YP = LCD_CS
XM = LCD_RS

# Spielstatus
GAME_PAIRING = 0  # Wartet, bis beide Teams die Buttons drücken
GAME_COUNTDOWN = 1
GAME_RUNNING = 2

# Flaggennummer
ID = 1  # THIS FLAG

#Variablen
last_pressed = time.ticks_ms() # debounce

flag_status_local = [0, 0, 0]
respawn_timer = [] # list will be appended

d_tickets_local = [0,0]
displayed_tickets = [INITIAL_TICKET_AMOUNT, INITIAL_TICKET_AMOUNT]

game = GAME_PAIRING
countdown_timer = COUNTDOWN_GAME_START

# threading, async listening to lora
sLock = _thread.allocate_lock()


#Timer
tim = Timer()
tim_1s_server = Timer()
tim_flags = Timer()
tim_send = Timer()
tim_fast = Timer()
tim_logic = Timer()

# FLAG-STATUS mit Conversion process
NEUTRAL = 0
TEAM_RED = 1
TEAM_BLUE = 2
CONVERTING_BLUE_TO_RED = 3  # 3-6
CONVERIING_NEUTRAL_TO_RED = 4  # 7-10
CONVERTING_RED_TO_BLUE = 5  # 11-14
CONVERTING_NEUTRAL_TO_RED = 6  # 15-18

# HILFSFUNKTIONEN

def log(*args):
    # log handling
    # at the moment just prints to the console TODO: add to log file
    # get current time

    message = ""
    for arg in args:
        message += str(arg) + " "

    t = time.localtime()
    ts = str(t[4]) + ":" + str(t[5])
    print("COM" + str(ID+3) + " @ " + ts + " > " + str(message))

##### BUTTONS #####

# debounce, sodass immer nur ein button press registriert wird
def debounce():
    global last_pressed

    now = time.ticks_ms()
    diff = time.ticks_diff(now, last_pressed)
    if (diff < DEBOUNCE_MS):
        return False

    last_pressed = now

def button_flag_down_red(a):
    if debounce() == False:
        return
    time.sleep(0.1)
    if button_flag_red.value == 1:
        pass
    log("rot nimmt ein")
    if flag_status_local[ID] in [0, 15, 16, 17, 18]:  # gray
        flag_status_local[ID] = 7
    elif flag_status_local[ID] in [2]:  # gray
        flag_status_local[ID] = 3
    elif flag_status_local[ID] in [11, 12, 13, 14]:
        flag_status_local[ID] = 1

    update_lcd_flag_status(flag_status_local)

def button_flag_down_blue(a):
    if debounce() == False:
        return
    time.sleep(0.1)
    if button_flag_blue.value == 1:
        pass
    log("Blau nimmt ein")
    if flag_status_local[ID] in [0, 7, 8, 9, 10]:  # gray
        flag_status_local[ID] = 15
    elif flag_status_local[ID] in [1]:
        flag_status_local[ID] = 11
    elif flag_status_local[ID] in [3, 4, 5, 6]:
        flag_status_local[ID] = 2

    update_lcd_flag_status(flag_status_local)

def button_respawn_down(a):
    if debounce() == False:
        return
    log('Respawn Button down')
    if game == GAME_PAIRING: # if Game is in paring mode, send server a start_game message
        send_ready_signal()
    if flag_status_local[ID] in [1, 2]:  # RED or BLUE
        log("Respawning...")
        d_tickets_local[flag_status_local[ID]-1] += RESPAWN_TICKET_COST  # tickets abziehen
        respawn_timer.append(RESPAWN_TIME)

####### Lora #######

def setup_lora_thread():
    _thread.start_new_thread(start_async_lora, ())

def start_async_lora():
    """Starts the async Lora listening part. Should be executed in a thread."""

    try:
        uasyncio.run(initialize_connection())
    except KeyboardInterrupt:
        log('Interrupted')
    finally:
        uasyncio.new_event_loop()

def send_ready_signal():
    swriter = uasyncio.StreamWriter(lora, {})
    msg = [id, MESSAGE_TYPE.READY]
    log("Sending ready signal:", msg)
    s = umsgpack.dumps(msg)
    swriter.write(package(s))
    swriter.drain()
    swriter.close()

async def initialize_connection():
    log("Hi, this is COM" + str(id+3))
    uasyncio.create_task(wait_for_status())
    while True: # print out used memory sometimes and garbage collect
        gc.collect()
        log('mem free', gc.mem_free())
        await uasyncio.sleep(20)

def package(s: bytes) -> bytes:
    """Adds a leading byte to indicate the length of the message

    Args:
        s (bytes): The message to be packaged

    Returns:
        bytes: The packaged message
    """    
    
    return len(s).to_bytes(1, 'big') + s

async def send_update(send_to, update):
    """Sends an update to a specific COM."""
    
    swriter = uasyncio.StreamWriter(lora, {})
    msg = [id, MESSAGE_TYPE.UPDATE, send_to, update]
    log("Sending update:", msg)
    s = umsgpack.dumps(msg)
    swriter.write(package(s))
    await swriter.drain()
    swriter.close()

async def wait_for_status():
    global server_tickets, server_flag_status
    
    sreader = uasyncio.StreamReader(lora)

    while True:
        log("Listening for status(aka. update request)...")
        
        sLock.acquire()
        # first read how many bytes should be read
        lead = await sreader.read(1)
        log("Received leading byte:", lead)
        if lead == b"\x00":  # EOF
            log("EOF")
            continue  # try again

        b = await sreader.read(int.from_bytes(lead, 'big'))
        try:
            res = umsgpack.loads(b)
        except:
            log("WARNING: Recieved not loadable:", b)

        if type(res) == list:
            log("Received from COM" + str(res[0]+3) + ":", res)
            if res[1] == MESSAGE_TYPE.STATUS:
                log("Received message is a status.")
                server_tickets  = res[2][0] 
                server_flag_status = res[2][1]
                log("Server tickets:", server_tickets)
                log("Server flag status:", server_flag_status)

                sreader.close() # close the stream reader
                if id > 1:
                    log("Waiting for", 0.3*(id-1), "s")
                    await uasyncio.sleep(0.3*(id-1))
                update = [d_tickets_local, flag_status_local]
                await send_update(res[0], update)
        else:  # not a useful object
            log('Discarding...')
            log('Recieved', res)
        sLock.release()


######### LCD ########

BLACK = 0x0000
BLUE = 0x001F
RED = 0xF800
GREEN = 0x07E0
CYAN = 0x07FF
MAGENTA = 0xF81F
YELLOW = 0xFFE0
WHITE = 0xFFFF
GRAY = 0x8410

def lcd_status_ini():
    global flag_status_local

    tft.SetFont(3)
    tft.setTextColor(GREEN)
    tft.setTextCursor(0, 20)
    tft.printh("Tickets:")

    tft.setTextCursor(130, 70+ID*70)
    tft.printh("*")

    tft.setTextCursor(145, 70)
    tft.printh("Alpha")

    tft.setTextCursor(145, 140)
    tft.printh("Bravo")

    tft.setTextCursor(145, 210)
    tft.printh("Charlie")

    update_lcd_flag_status(flag_status_local)

def update_lcd_tickets(tickets):

    tft.fillRect(120, 0, 90, 30, BLACK)
    tft.SetFont(3)
    tft.setTextColor(RED)
    tft.setTextCursor(120, 20)
    tft.printh(str(int(tickets[0])))
    tft.setTextColor(BLUE)
    tft.setTextCursor(170, 20)
    tft.printh(str(int(tickets[1])))

def update_win_screen(flag_status, tickets):

    cur = flag_status[0]
    if cur in [1, 2]:
        for f in range(1, len(flag_status)):
            if not cur == flag_status[f]:
                cur = None
                break
    else:
        cur = None
    if tickets[1] == 0:
        cur = 1
    elif tickets[0] == 0:
        cur = 2
    texts = ["* ROT hat gewonnen *", "* BLAU hat gewonnen *"]
    if cur:
        flag_status = [0, 0, 0]
        tft.fillRect(0, 0, 320, 240, BLACK)
        tft.setTextCursor(10, 100)
        tft.setTextColor(WHITE)
        tft.printh(texts[cur-1])
        tim.deinit()
        tim_flags.deinit()
        tim_send.deinit()
        time.sleep(3)
        restart_game()
        log("Restarting game...")

def update_lcd_respawn_timers(respawn_timers):

    tft.fillRect(0, 60, 100, 400, BLACK)
    for i, time in enumerate(respawn_timers):
        tft.SetFont(3)
        tft.setTextColor(WHITE)
        tft.setTextCursor(5, 80+i*30)
        tft.printh(str(i) + ": " + str(time))

def update_lcd_flag_status(flag_status):

    status_colors_converting = [GRAY, RED, BLUE, RED, RED, BLUE, BLUE]

    status_colors = [GRAY, RED, BLUE, BLUE, GRAY, RED, GRAY]

    #tft.fillRect(250, 30, 60, 260, BLACK)
    for i, status in enumerate(flag_status):
        if status > 2:  # converting
            conversion_process = (status-3) % 4
            status = 3+(status-3)//4

        tft.fillRect(250, 30+i*70, 60, 60, status_colors[status])
        if status > 2:
            tft.fillRect(250, 30+i*70, conversion_process*15,
                         60, status_colors_converting[status])

### Update timers ###

# every second: update the respawn timers, and check win conditions
def update(x):
    global displayed_tickets

    update_lcd_tickets(displayed_tickets)

    for i in range(len(respawn_timer)):
        if i >= len(respawn_timer):
            break
        respawn_timer[i] -= 1 # countdown tickets by 1 each second
        if respawn_timer[i] == 0:
            del respawn_timer[i]
            i += 1
    update_lcd_respawn_timers(respawn_timer)
    update_win_screen(flag_status_local, displayed_tickets)

# for flag status animation
def flag_status_update(x):
    global counter
    for i in range(len(flag_status_local)):
        if flag_status_local[i] > 2:
            flag_status_local[i] += 1
            if (flag_status_local[i]-3) % 4 == 0:
                if flag_status_local[i] <= 11:
                    flag_status_local[i] = 1  # ROT
                else:
                    flag_status_local[i] = 2  # BLAU
    update_lcd_flag_status(flag_status_local)

# Jede sekunde vor dem Spielstart
def countdown(x):
    global countdown_time

    countdown_time -= 1
    log(countdown_time)
    if countdown_time == 0:
        tim.deinit()
        start_game()

#### Init Funktionen ####
def start_game():
    # global game
    # screen
    tft.fillscreen(BLACK)
    lcd_status_ini()

    # timers
    # timers for flag conversion updates
    tim_flags.deinit()
    tim_flags.init(period=CONVERSION_TIME//4,
                   mode=Timer.PERIODIC, callback=flag_status_update)

    # timer for game updates
    tim.init(period=1000, mode=Timer.PERIODIC, callback=update)

    #setup thread for lora
    setup_lora_thread()

    # buttons
    button_respawn.irq(handler=button_respawn_down, trigger=Pin.IRQ_RISING)
    button_flag_red.irq(handler=button_flag_down_red, trigger=Pin.IRQ_RISING)
    button_flag_blue.irq(handler=button_flag_down_blue, trigger=Pin.IRQ_RISING)
    log("Game has started.")


def restart_game():
    global flag_status_local, d_tickets_local, respawn_timer, countdown_timer, displayed_tickets, game
    
    flag_status_local = [0, 0, 0]
    d_tickets_local = [0, 0]	
    respawn_timer = []
    countdown_timer = COUNTDOWN_GAME_START
    displayed_tickets = [0, 0]

    # deinit timers
    tim_flags.deinit()
    tim_logic.deinit()
    tim.deinit()

    # screen stays on

def lcd_init():
    global tft
    # init for lcd screen
    log("Initializing LCD...")
    tft = ILI9341.screen(LCD_RD, LCD_WR, LCD_RS, LCD_CS, LCD_RST,
                        LCD_D0, LCD_D1, LCD_D2, LCD_D3, LCD_D4, LCD_D5, LCD_D6, LCD_D7)

    tft.begin()
    tft.setrotation(1)
    tft.fillscreen(BLACK)

    log("LCD initialized.")
    
### Main ###

if __name__ == "__main__":
    lcd_init()

    log("Starting game...")
    start_game()

    
