#!/usr/bin/env python3
"""
RobotArm — Dual Joystick -> micro:bit (Bluetooth LE UART), no pygame
----------------------------------------------------------------------
Two joysticks, eight keys total. Pressing a key sends that key's character
to the micro:bit over Bluetooth LE UART, and while the key stays held the
same character is re-sent every 500 ms until released — no direction math,
no diagonals, no combining keys. A tkinter window (standard library) shows
both joysticks live and highlights whichever key/pointer is currently held.
Pointers are also clickable (and holdable) with the mouse; same behavior.
A text panel at the bottom shows whatever the micro:bit sends back over
BLE notifications, as it arrives.

Joystick 1 (WASD)   : W->w  A->a  S->s  D->d
Joystick 2 (arrows) : Up->i  Left->j  Down->k  Right->l

Requirements
------------
    pip install bleak pillow
    sudo apt install python3-tk      # tkinter, if not already present

The window must have focus for key presses to register (click it once).

Note on repeat: OS keyboard auto-repeat is unreliable to time directly (it
sends rapid KeyRelease/KeyPress pairs while a key is held, at whatever rate
the OS is configured for). Instead this script tracks "is this key down"
itself and drives its own repeat timer (REPEAT_MS, currently 500 ms).
Without debouncing, the OS's own repeat rate may cause brief flicker in
the on-screen highlight and a few extra sends right at the start of a
hold — harmless, just cosmetic.

micro:bit side
---------------
Flash the micro:bit with a MakeCode or Python program that starts the
Bluetooth UART service and reads until the ':' delimiter this script sends
after every character:

    bluetooth.start_uart_service()
    while True:
        c = uart.read_until(":")
        if c:
            display.show(c)

IMPORTANT: In MakeCode's Bluetooth settings, tick "No pairing required"
before flashing, or you'll need to pair the micro:bit first.

Usage
-----
    python3 RobotArm.py
"""

import asyncio
import math
import os
import queue
import sys
import threading
import tkinter as tk

try:
    from bleak import BleakClient
except ImportError:
    sys.exit("Missing dependency. Install with:  pip install bleak")

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None  # background image becomes optional if Pillow isn't installed

# Photo of the physical robot arm, shown faded behind the controls. Keep this
# file at assets/robot_arm.png, next to RobotArm.py (or change the path below).
BACKGROUND_IMAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "assets", "robot_arm.png")
# Logo banner shown across the top of the window. Keep this file at
# assets/logo.png, next to RobotArm.py (or change the path below).
LOGO_IMAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "assets", "logo.png")

# Nordic UART Service (used by micro:bit's Bluetooth UART service)
UART_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
UART_RX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # write to micro:bit
UART_TX_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # notify from micro:bit

# Set this to your micro:bit's BLE MAC address, e.g. found via:
#   bluetoothctl scan on
MICROBIT_ADDRESS = "F3:37:7F:C0:44:D3"

# keysym -> character sent to the micro:bit. That's the whole mapping.
KEY_TO_CHAR = {
    "w": "w", "a": "a", "s": "s", "d": "d",
    "Up": "i", "Left": "j", "Down": "k", "Right": "l",
}

REPEAT_MS = 500     # resend the held key's character this often
DELIMITER = ":"     # appended after every character sent to the micro:bit

# ---------------------------------------------------------------------------
# BLE — runs its own asyncio event loop in a background thread, since
# tkinter needs the main thread for its GUI loop.
# ---------------------------------------------------------------------------
ble_loop: asyncio.AbstractEventLoop | None = None
ble_queue: "asyncio.Queue[str] | None" = None
recv_queue: "queue.Queue[str]" = queue.Queue()  # incoming text from the micro:bit, for the GUI
status_queue: "queue.Queue[str]" = queue.Queue()  # "connected" / "disconnected", for the GUI


def send_char(ch: str):
    """Thread-safe: queue a character to be written to the micro:bit.
    Drops any character still waiting to be sent first, so a slow BLE
    link can't build up a backlog of stale key presses — only the most
    recent one is ever in flight."""
    if ble_loop is not None and ble_queue is not None:
        ble_loop.call_soon_threadsafe(_replace_queued, ch)


def _replace_queued(ch: str):
    while not ble_queue.empty():
        try:
            ble_queue.get_nowait()
        except asyncio.QueueEmpty:
            break
    ble_queue.put_nowait(ch)


async def ble_main(q: "asyncio.Queue[str]"):
    print(f"Connecting to micro:bit at {MICROBIT_ADDRESS} ...")
    status_queue.put("disconnected")

    def on_disconnect(_client):
        status_queue.put("disconnected")

    async with BleakClient(MICROBIT_ADDRESS, disconnected_callback=on_disconnect) as client:
        if not client.is_connected:
            print("Failed to connect.")
            return
        print("Connected. Sending key presses.")
        status_queue.put("connected")

        def on_notify(_handle, data: bytearray):
            try:
                text = data.decode("utf-8", errors="replace")
            except Exception:
                text = repr(data)
            recv_queue.put(text)

        try:
            await client.start_notify(UART_TX_CHAR_UUID, on_notify)
            print("Listening for micro:bit notifications.")
        except Exception as e:
            recv_queue.put(f"[could not subscribe to notifications: {e}]")

        while True:
            ch = await q.get()
            await client.write_gatt_char(UART_RX_CHAR_UUID, (ch + DELIMITER).encode("utf-8"))


def ble_thread_main():
    global ble_loop, ble_queue
    ble_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(ble_loop)
    ble_queue = asyncio.Queue()
    try:
        ble_loop.run_until_complete(ble_main(ble_queue))
    except Exception as e:
        print(f"BLE error: {e}")
        status_queue.put("disconnected")


# ---------------------------------------------------------------------------
# GUI — two joystick faces, four keys each. Holding a key or pointer sends
# its character every REPEAT_MS while held; nothing else happens.
# ---------------------------------------------------------------------------
SCALE = 1.5  # bump this up/down to resize the whole controller uniformly

POINTER_RADIUS = round(26 * SCALE)

ARROW_REST_COLOR = "#5b9bd5"
ARROW_ACTIVE_COLOR = "#1f5c9e"
SHADOW_OFFSET = round(3 * SCALE)
SHADOW_COLOR = "#b9c8d6"
TITLE_FONT_SIZE = round(11 * SCALE)
LABEL_FONT_SIZE = round(10 * SCALE)
TITLE_GAP = round(55 * SCALE)


def _point_on_circle(cx, cy, r, theta_deg):
    rad = math.radians(theta_deg)
    return cx + r * math.cos(rad), cy + r * math.sin(rad)


ICON_KIND = {
    "a": "rotate_left", "d": "rotate_right", "w": "reach_in", "s": "reach_out",
    "Up": "reach_in", "Down": "reach_out", "Right": "grab_close", "Left": "grab_open",
}


def draw_key_icon(canvas, px, py, kind, color, icon_r):
    """Draws a static symbol centered at (px, py). Returns the canvas item
    ids so the caller can delete them again on key release."""
    items = []

    if kind in ("rotate_left", "rotate_right"):
        cw = kind == "rotate_right"
        sweep = 250
        steps = 16
        start_angle, end_angle = (-sweep / 2, sweep / 2) if cw else (sweep / 2, -sweep / 2)
        pts = []
        for i in range(steps + 1):
            theta = start_angle + (end_angle - start_angle) * i / steps
            pts.extend(_point_on_circle(px, py, icon_r, theta))
        items.append(canvas.create_line(*pts, fill=color, width=6, smooth=False))

        theta_end = end_angle
        sign = 1 if cw else -1
        rad = math.radians(theta_end)
        tip = _point_on_circle(px, py, icon_r, theta_end)
        tx, ty = -math.sin(rad) * sign, math.cos(rad) * sign
        px_, py_ = -ty, tx
        size = 16
        left = (tip[0] - tx * size + px_ * size * 0.6, tip[1] - ty * size + py_ * size * 0.6)
        right = (tip[0] - tx * size - px_ * size * 0.6, tip[1] - ty * size - py_ * size * 0.6)
        items.append(canvas.create_polygon(tip, left, right, fill=color, outline=""))

    elif kind in ("reach_in", "reach_out"):
        reach_in = kind == "reach_in"
        outer, inner = icon_r, round(icon_r * 0.35)
        if reach_in:
            top_pts = ((px, py - outer), (px, py - inner))
            bottom_pts = ((px, py + outer), (px, py + inner))
        else:
            top_pts = ((px, py - inner), (px, py - outer))
            bottom_pts = ((px, py + inner), (px, py + outer))
        items.append(canvas.create_line(*top_pts[0], *top_pts[1], fill=color, width=6,
                                         arrow=tk.LAST, arrowshape=(18, 22, 8)))
        items.append(canvas.create_line(*bottom_pts[0], *bottom_pts[1], fill=color, width=6,
                                         arrow=tk.LAST, arrowshape=(18, 22, 8)))

    else:  # grab_open / grab_close — two pincer jaws hinged at the bottom
        closed = kind == "grab_close"
        spread = icon_r * 0.15 if closed else icon_r * 0.7
        hinge = (px, py + icon_r * 0.6)
        left_tip = (px - spread, py - icon_r * 0.6)
        right_tip = (px + spread, py - icon_r * 0.6)
        items.append(canvas.create_line(*hinge, *left_tip, fill=color, width=6,
                                         capstyle=tk.ROUND))
        items.append(canvas.create_line(*hinge, *right_tip, fill=color, width=6,
                                         capstyle=tk.ROUND))
        items.append(canvas.create_oval(hinge[0] - 3, hinge[1] - 3, hinge[0] + 3, hinge[1] + 3,
                                         fill=color, outline=""))

    return items


class JoystickPanel:
    """Purely visual: draws the dial and exposes pointer circles by keysym."""

    def __init__(self, canvas, cx, cy, r, labels, title, on_press, on_release,
                 rest_color=ARROW_REST_COLOR, active_color=ARROW_ACTIVE_COLOR):
        self.canvas = canvas
        self.pointers = {}  # keysym -> circle id
        self.rest_color = rest_color
        self.active_color = active_color

        canvas.create_oval(cx - r, cy - r, cx + r, cy + r, outline="#dddddd",
                            width=round(4 * SCALE), fill="#dddddd")
        canvas.create_text(cx, cy - r - TITLE_GAP, text=title,
                            font=("Sans", TITLE_FONT_SIZE, "bold"))

        offsets = {"N": (0, -1), "E": (1, 0), "S": (0, 1), "W": (-1, 0)}
        keysym_by_pos = {"N": labels["N_key"], "E": labels["E_key"],
                          "S": labels["S_key"], "W": labels["W_key"]}
        for pos, (ox, oy) in offsets.items():
            keysym = keysym_by_pos[pos]
            px, py = cx + ox * r, cy + oy * r
            circle = canvas.create_oval(px - POINTER_RADIUS, py - POINTER_RADIUS,
                                         px + POINTER_RADIUS, py + POINTER_RADIUS,
                                         fill=rest_color, outline="black",
                                         width=round(3 * SCALE))
            # Glossy highlight so the button reads as raised/3D against any background
            canvas.create_oval(px - POINTER_RADIUS * 0.55, py - POINTER_RADIUS * 0.7,
                                px - POINTER_RADIUS * 0.05, py - POINTER_RADIUS * 0.2,
                                fill="white", outline="", stipple="gray25")
            label = canvas.create_text(px, py, text=labels[pos],
                                        font=("Sans", LABEL_FONT_SIZE, "bold"), fill="white")
            canvas.tag_bind(circle, "<ButtonPress-1>", lambda e, k=keysym: on_press(k))
            canvas.tag_bind(label, "<ButtonPress-1>", lambda e, k=keysym: on_press(k))
            canvas.tag_bind(circle, "<ButtonRelease-1>", lambda e, k=keysym: on_release(k))
            canvas.tag_bind(label, "<ButtonRelease-1>", lambda e, k=keysym: on_release(k))
            self.pointers[keysym] = circle


def run_gui():
    root = tk.Tk()
    root.title("RobotArm — dual joystick")

    # Joystick ring size and layout — back to the original fixed sizing.
    RING_R = round(100 * SCALE)
    CANVAS_W = round(560 * SCALE)
    CANVAS_H = round(340 * SCALE)
    js1_cx = round(130 * SCALE)
    js2_cx = round(430 * SCALE)
    icon_r = round(POINTER_RADIUS * 0.7)
    js_cy = round(190 * SCALE)

    if Image is not None and os.path.exists(LOGO_IMAGE):
        try:
            logo_img = Image.open(LOGO_IMAGE).convert("RGBA")
            bbox = logo_img.getbbox()  # trim the large transparent padding around the wordmark
            if bbox:
                logo_img = logo_img.crop(bbox)
            target_w = CANVAS_W
            scale = target_w / logo_img.width
            logo_img = logo_img.resize((target_w, round(logo_img.height * scale)), Image.LANCZOS)
            logo_photo = ImageTk.PhotoImage(logo_img)
            logo_label = tk.Label(root, image=logo_photo)
            logo_label.image = logo_photo  # keep a reference so it isn't garbage-collected
            logo_label.pack(pady=(12, 0))
        except Exception as e:
            print(f"Could not load logo image: {e}")
    elif Image is not None:
        print(f"Logo image not found at {LOGO_IMAGE}")

    status_row = tk.Frame(root)
    status_row.pack(fill="x", padx=12, pady=(12, 0))
    led_canvas = tk.Canvas(status_row, width=16, height=16, highlightthickness=0)
    led_canvas.pack(side="left")
    led = led_canvas.create_oval(2, 2, 14, 14, fill="#d8b400", outline="")
    status_label = tk.Label(status_row, text="Bluetooth: connecting...")
    status_label.pack(side="left", padx=(6, 0))

    canvas = tk.Canvas(root, width=CANVAS_W, height=CANVAS_H, highlightthickness=0)
    canvas.pack(padx=12, pady=12)

    if Image is not None and os.path.exists(BACKGROUND_IMAGE):
        try:
            from PIL import ImageEnhance
            canvas_w, canvas_h = CANVAS_W, CANVAS_H
            bg = Image.open(BACKGROUND_IMAGE).convert("RGB")
            # "Cover" scaling: scale up to fill the whole frame, then
            # center-crop the overflow, instead of fitting inside it and
            # leaving empty margins on the sides.
            cover_scale = max(canvas_w / bg.width, canvas_h / bg.height)
            new_w, new_h = round(bg.width * cover_scale), round(bg.height * cover_scale)
            bg = bg.resize((new_w, new_h), Image.LANCZOS)
            left = (new_w - canvas_w) // 2
            top = (new_h - canvas_h) // 2
            bg = bg.crop((left, top, left + canvas_w, top + canvas_h))
            bg = ImageEnhance.Brightness(bg).enhance(1.35)
            bg = ImageEnhance.Contrast(bg).enhance(0.9)
            bg = Image.blend(bg, Image.new("RGB", bg.size, "white"), 0.45)
            bg_photo = ImageTk.PhotoImage(bg)
            canvas.create_image(0, 0, anchor="nw", image=bg_photo)
            canvas.bg_photo = bg_photo  # keep a reference so it isn't garbage-collected
            print(f"Loaded background image from {BACKGROUND_IMAGE}")
        except Exception as e:
            print(f"Could not load background image: {e}")
    elif Image is None:
        print("Pillow not installed — skipping background image (pip install pillow)")
    else:
        print(f"Background image not found at {BACKGROUND_IMAGE}")

    panels = []
    active = set()
    icon_items = {}

    js1_cy, js1_r = js_cy, RING_R
    js2_cy, js2_r = js_cy, RING_R
    key_positions = {
        "w": (js1_cx, js1_cy - js1_r),
        "d": (js1_cx + js1_r, js1_cy),
        "s": (js1_cx, js1_cy + js1_r),
        "a": (js1_cx - js1_r, js1_cy),
        "Up": (js2_cx, js2_cy - js2_r),
        "Right": (js2_cx + js2_r, js2_cy),
        "Down": (js2_cx, js2_cy + js2_r),
        "Left": (js2_cx - js2_r, js2_cy),
    }

    # All 8 keys show their symbol permanently, offset toward each
    # joystick's center (inward) from the button so nothing runs off the
    # canvas edge. Drawn after the panels below so it layers on top of the
    # dial fill instead of being covered by it.
    ICON_COLOR = "#6A1B9A"  # deep purple — reads clearly against both the cyan and orange buttons
    STATIC_ICON_DIR = {
        "w": (0, 1), "s": (0, -1), "a": (1, 0), "d": (-1, 0),
        "Up": (0, 1), "Down": (0, -1), "Left": (1, 0), "Right": (-1, 0),
    }
    gap = round(10 * SCALE)

    def draw_static_icons():
        for keysym, (dx, dy) in STATIC_ICON_DIR.items():
            px, py = key_positions[keysym]
            offset = POINTER_RADIUS + icon_r + gap
            draw_key_icon(canvas, px + dx * offset, py + dy * offset,
                          ICON_KIND[keysym], ICON_COLOR, icon_r)

    def highlight(keysym, on):
        for panel in panels:
            if keysym in panel.pointers:
                panel.canvas.itemconfig(panel.pointers[keysym],
                                         fill=panel.active_color if on else panel.rest_color)

    def repeat_tick(keysym):
        if keysym not in active:
            return
        send_char(KEY_TO_CHAR[keysym])
        root.after(REPEAT_MS, lambda: repeat_tick(keysym))

    def start(keysym):
        if keysym not in KEY_TO_CHAR:
            return
        if keysym not in active:
            active.add(keysym)
            highlight(keysym, True)
            if (keysym in ICON_KIND and keysym in key_positions
                    and keysym not in icon_items and keysym not in STATIC_ICON_DIR):
                px, py = key_positions[keysym]
                icon_items[keysym] = draw_key_icon(canvas, px, py, ICON_KIND[keysym],
                                                    "white", icon_r)
            repeat_tick(keysym)  # sends immediately, then every REPEAT_MS

    def stop(keysym):
        if keysym not in KEY_TO_CHAR:
            return
        active.discard(keysym)
        highlight(keysym, False)
        if keysym in icon_items:
            canvas.delete(*icon_items.pop(keysym))

    js1 = JoystickPanel(canvas, js1_cx, js1_cy, js1_r,
                         {"N": "W", "E": "D", "S": "S", "W": "A",
                          "N_key": "w", "E_key": "d", "S_key": "s", "W_key": "a"},
                         "Joystick 1 (WASD)", start, stop,
                         rest_color="#00BCD4", active_color="#006A75")
    js2 = JoystickPanel(canvas, js2_cx, js2_cy, js2_r,
                         {"N": "^", "E": ">", "S": "v", "W": "<",
                          "N_key": "Up", "E_key": "Right", "S_key": "Down", "W_key": "Left"},
                         "Joystick 2 (arrows)", start, stop,
                         rest_color="#FF9800", active_color="#B85C00")
    panels.extend([js1, js2])
    draw_static_icons()

    tk.Label(root, text="Click the window, then hold a key — or hold a pointer.",
             fg="#888").pack(pady=(0, 8))

    tk.Label(root, text="From micro:bit:", anchor="w").pack(fill="x", padx=12)
    log_frame = tk.Frame(root)
    log_frame.pack(fill="both", padx=12, pady=(0, 12))
    scrollbar = tk.Scrollbar(log_frame)
    scrollbar.pack(side="right", fill="y")
    log_text = tk.Text(log_frame, height=6, width=68, state="disabled",
                        yscrollcommand=scrollbar.set)
    log_text.pack(side="left", fill="both", expand=True)
    scrollbar.config(command=log_text.yview)

    def poll_recv():
        try:
            while True:
                text = recv_queue.get_nowait()
                log_text.config(state="normal")
                log_text.insert("end", text)
                log_text.see("end")
                log_text.config(state="disabled")
        except queue.Empty:
            pass
        root.after(50, poll_recv)

    def poll_status():
        try:
            while True:
                state = status_queue.get_nowait()
                if state == "connected":
                    led_canvas.itemconfig(led, fill="#2fa84f")
                    status_label.config(text="Bluetooth: connected")
                else:
                    led_canvas.itemconfig(led, fill="#d8b400")
                    status_label.config(text="Bluetooth: no connection")
        except queue.Empty:
            pass
        root.after(200, poll_status)

    root.after(50, poll_recv)
    root.after(200, poll_status)

    root.bind("<KeyPress>", lambda e: start(e.keysym))
    root.bind("<KeyRelease>", lambda e: stop(e.keysym))
    root.focus_set()

    root.mainloop()


def main():
    if MICROBIT_ADDRESS == "AA:BB:CC:DD:EE:FF":
        sys.exit("Set MICROBIT_ADDRESS at the top of this script to your micro:bit's MAC address.")

    threading.Thread(target=ble_thread_main, daemon=True).start()
    run_gui()


if __name__ == "__main__":
    main()