# ======================
# Digital Pet (Teacher Version)
# - Adds Pong Game
# ======================
from PiicoDev_SSD1306 import create_PiicoDev_SSD1306
from PiicoDev_CAP1203 import PiicoDev_CAP1203
from icon import Animate, Icon, Toolbar, Event
from PiicoDev_Unified import sleep_ms
import time
try:
    import urandom as random
except:
    import random

# ----------------------
# CONFIG (Customerise your pet's name and starting values)
# ----------------------
PET_NAME = "Pixel"  # Keep <= 6 chars to fit beside bars
START_HEALTH = 3
START_HAPPINESS = 3
START_ENERGY = 3

ANIM_SPEEDS = {'baby':'normal','babyzzz':'very slow','death':'slow','call':'very slow'}

#Messages
MSG_VITAMINS = "Vitamins!"
MSG_SLEEP_ON = "Night night"
MSG_SLEEP_OFF = "Good morning!"
MSG_CLEANING = "Cleaning..."
MSG_ENERGY_UP = "ENERGY +1"

LOW_STAT_THRESHOLD = 1
SLEEP_RECOVERY_MS = 60_000

TOOLBAR_AT_TOP = True
HUD_STRIP_H = 7

# Max stat shown in bars; teacher version clamps stats to this range
MAX_STAT = 5

# Order of toolbar items (must match build_toolbar)
ITEMS = ["food","lightbulb","game","firstaid","toilet","heart","call"]

# ----------------------
# Extra - PONG Setup
# ----------------------

# Pong tuning
WIN_POINTS = 5
PADDLE_H = 12;
PADDLE_W = 2;
PADDLE_SPEED = 2
BALL_SIZE = 2;
BALL_SPEED_X = 2

# DIFFICULTY: Try EASY / NORMAL / HARD
AI_DIFFICULTY = 'EASY'  # 'EASY', 'NORMAL', or 'HARD'
if AI_DIFFICULTY == 'EASY':
    AI_MAX_SPEED = 1
    AI_REACTION_MS = 220
    AI_NOISE = 6
elif AI_DIFFICULTY == 'HARD':
    AI_MAX_SPEED = 3
    AI_REACTION_MS = 80
    AI_NOISE = 1
else:
    AI_MAX_SPEED = 2
    AI_REACTION_MS = 140
    AI_NOISE = 3
    

# ----------------------
# SETUP
# ----------------------
oled = create_PiicoDev_SSD1306()
TouchSensor = PiicoDev_CAP1203(touchmode='multi', sensitivity=3)
INPUT_COOLDOWN_MS = 250   # adjust: 150–400 ms works well
last_input_ms = 0

health = START_HEALTH
happiness = START_HAPPINESS
energy = START_ENERGY

food = Icon('food.pbm',16,16,"food")
lightbulb = Icon('lightbulb.pbm',16,16,"lightbulb")
game = Icon('game.pbm',16,16,"game")
firstaid_icon = Icon('firstaid.pbm',16,16,"firstaid")
toilet_icon = Icon('toilet.pbm',16,16,"toilet")
heart = Icon('heart.pbm',16,16,"heart")
call = Icon('call.pbm',16,16,"call")

def build_toolbar():
    tb = Toolbar(); tb.spacer = 2
    for it in (food, lightbulb, game, firstaid_icon, toilet_icon, heart, call):
        tb.additem(it)
    return tb

tb = build_toolbar()

# Move pet/poop slightly up to protect bottom HUD
poopy = Animate(x=96,y=40, width=16, height=16, filename='poop')
baby = Animate(x=48,y=8, width=48, height=48, filename='baby_bounce', animation_type='bounce')
eat = Animate(x=48,y=8, width=48, height=48, filename='eat')
babyzzz = Animate(animation_type="loop", x=48,y=8, width=48, height=48, filename='baby_zzz')
death = Animate(animation_type='bounce', x=40,y=8, width=16, height=16, filename="skull")
go_potty = Animate(filename="potty", animation_type='bounce',x=64,y=12, width=48, height=48)
call_animate = Animate(filename='call_animate', width=16, height=16, x=108, y=0)

baby.speed = ANIM_SPEEDS['baby']
babyzzz.speed = ANIM_SPEEDS['babyzzz']
death.speed = ANIM_SPEEDS['death']
call_animate.speed = ANIM_SPEEDS['call']

energy_increase = Event(name="Increase Energy", sprite=heart, value=1)
firstaid_evt = Event(name="First Aid", sprite=firstaid_icon, value=0)
toilet_evt = Event(name="Toilet", sprite=toilet_icon, value=0)
sleep_evt = Event(name="sleep time", sprite=lightbulb, value=1)
heart_status = Event(name="Status", sprite=heart)

baby.bounce()
poopy.bounce()
death.loop(no=-1)
go_potty.loop(no=1)
go_potty.set = True
poopy.set = False
call_animate.set = False

index = 0
feeding_time = False
sleeping = False
sleep_started_ms = None

# ----------------------
# HUD & helpers
# ----------------------
HUD_Y = 0 if not TOOLBAR_AT_TOP else (64 - HUD_STRIP_H)

BAR_UNIT = 4  # 5 units * 4px + 2px border = 22px per bar
BAR_X = (50, 78, 106)

def clear():
    oled.fill(0)

def hud_clear():
    oled.fill_rect(0, HUD_Y, 128, HUD_STRIP_H, 0)

def clamp_stat(v):
    if v < 0: return 0
    if v > MAX_STAT: return MAX_STAT
    return v

def draw_tiny_bar(x, y, value):
    v = clamp_stat(value)
    oled.rect(x, y+1, MAX_STAT*BAR_UNIT+2, 6, 1)  # outline
    for i in range(v * BAR_UNIT):                 # fill
        oled.pixel(x+1+i, y+4, 1)

def draw_status():
    hud_clear()
    oled.text(PET_NAME, 0, HUD_Y)
    draw_tiny_bar(BAR_X[0], HUD_Y, health)
    draw_tiny_bar(BAR_X[1], HUD_Y, happiness)
    draw_tiny_bar(BAR_X[2], HUD_Y, energy)

# Timed sleep recovery (every SLEEP_RECOVERY_MS while sleeping)

def update_sleep_recovery():
    global energy, sleep_started_ms
    if not sleeping:
        sleep_started_ms = None
        return
    if sleep_started_ms is None:
        sleep_started_ms = time.ticks_ms()
        return
    now = time.ticks_ms()
    if time.ticks_diff(now, sleep_started_ms) >= SLEEP_RECOVERY_MS:
        energy = clamp_stat(energy + 1)
        energy_increase.message = MSG_ENERGY_UP
        energy_increase.popup(oled)
        sleep_started_ms = now

# Introduce input delay 
def input_allowed():
    global last_input_ms
    now = time.ticks_ms()
    if time.ticks_diff(now, last_input_ms) >= INPUT_COOLDOWN_MS:
        last_input_ms = now
        return True
    return False

# ----------------------
# Extra - PONG
# ----------------------

def play_pong_ai():
    global happiness
    WIDTH, HEIGHT = 128, 64
    TOP, BOTTOM = 0, HEIGHT

    s_h = 0; s_ai = 0
    p_h_y = (HEIGHT - PADDLE_H)//2
    p_ai_y = p_h_y
    bx = WIDTH//2; by = HEIGHT//2
    vx = 0; vy = 0

    clear()
    oled.text(PET_NAME + ' vs AI', 15, 6)
    oled.text('A=Up X=Down', 8, 22)
    oled.text('B=Exit', 8, 38)
    oled.show()

    # wait serve
    while True:
        s = TouchSensor.read()
        a,b,x = s[1],s[2],s[3]
        if a == 1 or x == 1:
            vx = BALL_SPEED_X if random.getrandbits(1) else -BALL_SPEED_X
            vy = (random.getrandbits(8)%3) - 1
            break
        sleep_ms(10)

    last_ai_tick = time.ticks_ms()
    ai_target_y = p_ai_y

    while s_h < WIN_POINTS and s_ai < WIN_POINTS:
        s = TouchSensor.read()
        a,b,x = s[1],s[2],s[3]
        if b == 1: break

        if a == 1: p_h_y -= PADDLE_SPEED
        if x == 1: p_h_y += PADDLE_SPEED
        if p_h_y < TOP: p_h_y = TOP
        if p_h_y > BOTTOM - PADDLE_H: p_h_y = BOTTOM - PADDLE_H

        now = time.ticks_ms()
        if time.ticks_diff(now, last_ai_tick) >= AI_REACTION_MS:
            last_ai_tick = now
            if vx > 0:
                noise = (random.getrandbits(8) % (2*AI_NOISE+1)) - AI_NOISE
                ai_target_y = by + noise - PADDLE_H//2
            else:
                ai_target_y = (HEIGHT - PADDLE_H)//2

        if p_ai_y < ai_target_y: p_ai_y += AI_MAX_SPEED
        elif p_ai_y > ai_target_y: p_ai_y -= AI_MAX_SPEED
        if p_ai_y < TOP: p_ai_y = TOP
        if p_ai_y > BOTTOM - PADDLE_H: p_ai_y = BOTTOM - PADDLE_H

        bx += vx; by += vy
        if by <= TOP: by = TOP; vy = -vy
        if by >= BOTTOM - BALL_SIZE: by = BOTTOM - BALL_SIZE; vy = -vy

        if bx <= 2 + PADDLE_W:
            if p_h_y - 1 <= by <= p_h_y + PADDLE_H:
                bx = 2 + PADDLE_W + 1; vx = abs(vx)
                off = by - (p_h_y + PADDLE_H//2)
                vy = -1 if off < -3 else (1 if off > 3 else 0)
            else:
                s_ai += 1; bx = WIDTH//2; by = HEIGHT//2; vx = -BALL_SPEED_X; vy = 0

        if bx >= WIDTH - PADDLE_W - BALL_SIZE - 2:
            if p_ai_y - 1 <= by <= p_ai_y + PADDLE_H:
                bx = WIDTH - PADDLE_W - BALL_SIZE - 3; vx = -abs(vx)
                off = by - (p_ai_y + PADDLE_H//2)
                vy = -1 if off < -3 else (1 if off > 3 else 0)
            else:
                s_h += 1; bx = WIDTH//2; by = HEIGHT//2; vx = BALL_SPEED_X; vy = 0

        clear()
        for yy in range(0, HEIGHT, 4): oled.pixel(WIDTH//2, yy, 1)
        oled.rect(0,0,WIDTH,HEIGHT,1)
        oled.fill_rect(2, p_h_y, PADDLE_W, PADDLE_H, 1)
        oled.fill_rect(WIDTH-2-PADDLE_W, p_ai_y, PADDLE_W, PADDLE_H, 1)
        oled.fill_rect(int(bx), int(by), BALL_SIZE, BALL_SIZE, 1)
        oled.text(str(s_h), WIDTH//2 - 18, 0)
        oled.text(str(s_ai), WIDTH//2 + 12, 0)
        oled.show(); sleep_ms(15)

    # Reward
    total = s_h + s_ai
    reward = 1 + (total // 6)
    happiness += reward
    heart_status.message = "+HAPPY x" + str(reward); heart_status.popup(oled)
    clear()
    

# ----------------------------------------------
# Main Game Loop
# ----------------------------------------------

tb.select(index, oled)
while True:
    s = TouchSensor.read()
    button_a = s[1]
    button_b = s[2]
    button_x = s[3]

    # Navigate
    tb.unselect(index, oled)
    if button_a == 1 and input_allowed():
        index = (index - 1) % 7
    if button_x == 1 and input_allowed():
            index = (index + 1) % 7
    if index >= 0:
        tb.select(index, oled)

    # Determine current item from index
    current_item = ITEMS[index] if index >= 0 else None

    # Activate
    if button_b == 1 and current_item is not None:
        if current_item == "food":
            feeding_time = True
            sleeping = False
            baby.unload()
        elif current_item == "game":
            play_pong_ai()
        elif current_item == "toilet":
            toilet_evt.message = MSG_CLEANING
            toilet_evt.popup(oled=oled)
            poopy.set = False
            baby.set = True
            happiness = clamp_stat(happiness + 1)
            poopy.unload()
            clear()
        elif current_item == "lightbulb":
            if not sleeping:
                sleeping = True
                babyzzz.load()
                sleep_evt.message = MSG_SLEEP_ON; sleep_evt.popup(oled)
                sleep_started_ms = time.ticks_ms()
            else:
                sleeping = False
                babyzzz.unload()
                sleep_evt.message = MSG_SLEEP_OFF; sleep_evt.popup(oled)
            clear()
        elif current_item == "firstaid":
            firstaid_evt.message = MSG_VITAMINS; firstaid_evt.popup(oled=oled)
            health = clamp_stat(health + 1)
            clear()
        elif current_item == "heart":
            heart_status.message = "health = " + str(health); heart_status.popup(oled)
            heart_status.message = "happy = " + str(happiness); heart_status.popup(oled)
            heart_status.message = "energy = " + str(energy); heart_status.popup(oled)
            clear()
        elif current_item == "call":
            pass

    # Animations
    if feeding_time:
        eat.load()
        if not eat.done:
            eat.animate(oled)
        if feeding_time and eat.done:
            feeding_time = False
            energy_increase.message = MSG_ENERGY_UP; energy_increase.popup(oled=oled)
            energy = clamp_stat(energy + 1)
            eat.unload(); baby.load(); clear()
    else:
        if sleeping:
            babyzzz.animate(oled)
            update_sleep_recovery()
        else:
            if baby.set:
                baby.load(); baby.animate(oled)

    if go_potty.set:
        go_potty.animate(oled)
        if go_potty.done:
            go_potty.set = False
            poopy.set = True
            baby.load(); baby.bounce(no=-1); baby.set = True

    # States
    death.set = (energy <= 1 and happiness <= 1 and health <= 1)
    call_animate.set = (energy <= LOW_STAT_THRESHOLD or happiness <= LOW_STAT_THRESHOLD or health <= LOW_STAT_THRESHOLD)

    if poopy.set:
        poopy.load(); poopy.animate(oled)
    if death.set:
        death.animate(oled)

    # Toolbar & call indicator
    tb.show(oled)
    if index == 6:
        tb.select(index, oled)
    elif call_animate.set:
        call_animate.animate(oled)

    # HUD last
    draw_status()

    oled.show()
    sleep_ms(1)

