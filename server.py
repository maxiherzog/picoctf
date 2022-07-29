from time import sleep_ms, ticks_ms, ticks_diff
import _thread  # threading?
import json
import ILI9341
from random import getrandbits, randint
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

class MESSAGE_TYPE():
    REQUEST_UPDATE = 0
    UPDATE = 1
    STATUS = 2
    OK = 3
    SYNC = 4

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

# SPIELEINSTELLUNG
RESPAWN_TIME = 30
CONVERSION_TIME = 10000
RESPAWN_TICKET_COST = 5
INITIAL_TICKET_AMOUNT = 100
TICKET_DECAY_PERIOD = 5000
COUNTDOWN_GAME_START = 10

# Flaggennummer
ID = 0 # THIS FLAG

#Variablen
last_on2 = 0
other_IDs = [0, 1]
pingback_stat = [0, 0, 0]
lora_buffer = ""
flag_status = [0, 0, 0]
respawn_timer = []
tickets = [INITIAL_TICKET_AMOUNT, INITIAL_TICKET_AMOUNT]

# Spielstatus
GAME_WAITING = 0  # Wartet, bis beide Teams die Buttons drücken
GAME_RUNNING = 1
game = 0
countdown_time = 10

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

    global last_on2

    now = time.ticks_ms()
    diff = time.ticks_diff(now, last_on2)
    if (diff < 400):

        return False

    last_on2 = now


def button_flag_down_red(a):
    if debounce() == False:
        return
    time.sleep(0.1)
    if button_flag_red.value == 1:
        pass
    log("rot nimmt ein")
    if flag_status[ID] in [0, 15, 16, 17, 18]:  # gray
        flag_status[ID] = 7
    elif flag_status[ID] in [2]:  # gray
        flag_status[ID] = 3
    elif flag_status[ID] in [11, 12, 13, 14]:
        flag_status[ID] = 1

    update_lcd_flag_status(flag_status)

    #TODO: Senden
    #lora_send(flag_status, tickets,0,[other_IDs[0],other_IDs[1]])
    #log("timer started")
    #tim_send.init(period=3000, mode=Timer.PERIODIC, callback=lora_send_repeat)


def button_flag_down_blue(a):
    if debounce() == False:
        return
    time.sleep(0.1)
    if button_flag_blue.value == 1:
        pass
    log("Blau nimmt ein")
    if flag_status[ID] in [0, 7, 8, 9, 10]:  # gray
        flag_status[ID] = 15
    elif flag_status[ID] in [1]:
        flag_status[ID] = 11
    elif flag_status[ID] in [3, 4, 5, 6]:
        flag_status[ID] = 2

    update_lcd_flag_status(flag_status)

    #TODO: Senden
    #lora_send(flag_status, tickets,0,[other_IDs[0],other_IDs[1]])
    #log("timer started")
    #tim_send.init(period=3000, mode=Timer.PERIODIC, callback=lora_send_repeat)


def button_respawn_down(a):

    if debounce() == False:
        return
    log('Button down')
    if flag_status[ID] in [1, 2]:  # RED or BLUE

        tickets[flag_status[ID]-1] -= RESPAWN_TICKET_COST  # tickets abziehen
        respawn_timer.append(RESPAWN_TIME)

    #TODO: Senden
    #lora_send(flag_status, tickets,0,[other_IDs[0],other_IDs[1]])
    #log("timer started")
    #tim_send.init(period=3000, mode=Timer.PERIODIC, callback=lora_send_repeat)


####### Lora #######
start_tickets = [INITIAL_TICKET_AMOUNT, INITIAL_TICKET_AMOUNT]
d_tickets = [[0,0], [0,0], [0,0]] # differential amount of tickets, 
flags_status = [0,0,0] # flags

def setup_lora():
    global lora

    log("Starting server...")
    tim_1s_server.init(period=3000, mode=Timer.PERIODIC, callback=routine)


async def broadcast(status):
    swriter = uasyncio.StreamWriter(lora, {})
    log("Sending", status)
    s = umsgpack.dumps(status)  # Synchronous serialisation
    swriter.write(package(s))
    await swriter.drain()  # Asynchonous transmissi


def package(s):
    return len(s).to_bytes(1, 'big') + s


def routine():

    log("")
    log("Routine ------------------------------------------------")
    # STATUS
    # send game state
    log("Delta tickets", d_tickets)
    displayed_tickets = [INITIAL_TICKET_AMOUNT, INITIAL_TICKET_AMOUNT]
    for i in range(2):
        for node in range(3):
            displayed_tickets[i] -= d_tickets[node][i]
    game = [id, MESSAGE_TYPE.STATUS,
            [displayed_tickets, flags_status]]  # send displayed_tickets and flags_status
    uasyncio.run(broadcast(game))
    # wait a bit TODO: wie lang?
    time.sleep(2)

    # then read possibly arrived updates
    #sreader = uasyncio.StreamReader(lora)
    while True:
        # first read how many bytes should be read
        lead = lora.read(1)
        if lead == None:
            break
        b = lora.read(int.from_bytes(lead, 'big'))
        log(b)
        try:
            res = umsgpack.loads(b)
        except:
           log("WARNING: Recieved not loadable:", b)
        log("Received from COM"+str(3+res[0]) + ":", res)
        # check if update is correct
        if type(res) == list:
            # UPDATE
            if res[1] == MESSAGE_TYPE.UPDATE and res[2] == ID:
                log("Update received:", res[3])
                update = res[3]
                d_tickets[res[0]] = update[0]  # local d_tickets
                flags_status[res[0]] = update[1]  # local flags_status

        else:
           log("Discarding...")

######### LCD ########

# Colors
BLACK = 0x0000
BLUE = 0x001F
RED = 0xF800
GREEN = 0x07E0
CYAN = 0x07FF
MAGENTA = 0xF81F
YELLOW = 0xFFE0
WHITE = 0xFFFF
GRAY = 0x8410


def update_lcd(signal):

    tft.fillRect(0, 0, 320, 75, BLACK)
    tft.setTextColor(GREEN)
    tft.SetFont(3)
    tft.setTextCursor(0, 20)
    tft.printh(str(signal))


def lcd_status_ini():
    global flag_status

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

    update_lcd_flag_status(flag_status)


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

# jede Sekunde:
# * respawn timer
# * lcd update
def update(x):
    global tickets
    #log(tickets)
    #log(respawn_timer)
    update_lcd_tickets(tickets)

    for i in range(len(respawn_timer)):
        if i >= len(respawn_timer):
            break
        respawn_timer[i] -= 1
        if respawn_timer[i] == 0:
            del respawn_timer[i]
            i += 1
    update_lcd_respawn_timers(respawn_timer)
    update_win_screen(flag_status, tickets)

# jede CONVERSION_TIME/4 Sekunden:
# * flaggenstatus aktualisieren
# * lcd update
def flag_status_update(x):
    global counter
    for i in range(len(flag_status)):
        if flag_status[i] > 2:
            flag_status[i] += 1
            if (flag_status[i]-3) % 4 == 0:
                if flag_status[i] <= 11:
                    flag_status[i] = 1  # ROT
                else:
                    flag_status[i] = 2  # BLAU
    update_lcd_flag_status(flag_status)

# Jede sekunde VOR dem Spielstart
def pre_game_countdown(x):
    global countdown_time

    countdown_time -= 1
    log(countdown_time)
    if countdown_time == 0:
        tim.deinit()
        start_game()

#### Init Funktionen ####

# start the game
def start_game():
    global game

    game = True
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

    #setup lora
    setup_lora()

    # buttons
    button_respawn.irq(handler=button_respawn_down, trigger=Pin.IRQ_RISING)
    button_flag_red.irq(handler=button_flag_down_red, trigger=Pin.IRQ_RISING)
    button_flag_blue.irq(handler=button_flag_down_blue, trigger=Pin.IRQ_RISING)
    log("Game has started.")


def restart_game():
    global flag_status, tickets
    global game

    flag_status = [0, 0, 0]
    tickets = [INITIAL_TICKET_AMOUNT, INITIAL_TICKET_AMOUNT]
    d_tickets = [[0,0], [0,0], [0,0]]

    tim_flags.deinit()
    tim_logic.deinit()
    tim.deinit()
    game = False

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

def __main__():
    lcd_init()

    log("Starting game...")
    start_game()
