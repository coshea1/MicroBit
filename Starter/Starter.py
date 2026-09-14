"""
F1 Starting Lights Simulator
-----------------------------
Mimics the Formula 1 race start light sequence:
  - 5 columns of red lights illuminate one column at a time (roughly 1s apart)
  - Once all 5 columns are lit, they stay on for a random "hold" period
    (just like a real F1 start, to prevent drivers anticipating the start)
  - All lights go out simultaneously ("lights out") -> race starts!
  - At that same moment, a 'G:' command is sent over Bluetooth LE to two
    micro:bit boards (identified by MAC address) so they can react too.

Dependencies:
  pip install Pillow bleak

Before running, set MICROBIT_1_MAC / MICROBIT_2_MAC below to your boards'
actual Bluetooth MAC addresses (on macOS these are UUIDs instead of MACs;
bleak accepts either). The micro:bits must already be running firmware that
exposes a UART-style write characteristic listening for 'G:' commands.

Run with:  python f1_start_lights.py
"""

import os
import sys
import time
import math
import struct
import wave
import tempfile
import subprocess
import random
import threading
import asyncio
import tkinter as tk

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    from bleak import BleakClient
    BLE_AVAILABLE = True
except ImportError:
    BLE_AVAILABLE = False

CADENCE_LOGO_FILENAME = os.path.join("assets", "logo.png")
F1_LOGO_FILENAME = os.path.join("assets", "f1-logo.png")
HEADER_LOGO_GAP = 20         # px between the two logos
HEADER_WIDTH_RATIO = 0.85    # logos row targets this fraction of the canvas width
HEADER_MIN_HEIGHT = 36       # px, floor so tiny logos don't disappear
HEADER_MAX_HEIGHT = 90       # px, ceiling so logos don't dominate the window

NUM_COLUMNS = 5
LIGHTS_PER_COLUMN = 2
LIT_COLOR = "#ff0000"
LIT_GLOW = "#ff5555"
UNLIT_COLOR = "#3a0f0f"
GREEN_COLOR = "#00b140"
BG_COLOR = "#e5e5e5"        # light grey window background
TEXT_COLOR = "#1a1a1a"      # dark text for contrast on light background
RIG_COLOR = "#1a1a1a"       # dark panels behind the lights, unchanged
BTN_COLOR = "#1a1a1a"
BTN_ACTIVE_COLOR = "#3a3a3a"
BTN_FONT = ("Helvetica", 14, "bold")
BTN_PADX = 20
BTN_PADY = 8
BTN_WIDTH_CHARS = 6  # fixed character width so START and Stop render at the same size
GO_COLOR = "#0a8a3c"
BLE_STATUS_COLOR = "#555555"
LED_IDLE_COLOR = "#999999"
LED_CONNECTING_COLOR = "#d9b400"
LED_CONNECTED_COLOR = "#2ecc71"
LED_FAILED_COLOR = "#e74c3c"
CAR_BOX_COLORS = {1: "#1e63d1", 2: "#1e9e4f"}   # Car 1 = blue, Car 2 = green
CAR_BOX_TEXT_COLOR = "#ffffff"

STEP_DELAY_MS = 1000        # time between each column lighting up
MIN_HOLD_MS = 3000           # min random hold after all lights are on
MAX_HOLD_MS = 5000           # max random hold after all lights are on
TIMER_UPDATE_MS = 50         # how often the running car timers redraw

# --- Beep (played on each red light, and a long one when green shows) ------
BEEP_FREQ_HZ = 880
GREEN_BEEP_FREQ_HZ = BEEP_FREQ_HZ * 1.2  # 20% higher pitch than the red beep
BEEP_DURATION_S = 0.12
GREEN_BEEP_DURATION_S = 1.0  # long beep when the lights turn green
BEEP_SAMPLE_RATE = 44100
BEEP_VOLUME = 0.5  # 0.0 - 1.0
GREEN_BEEP_VOLUME = min(1.0, BEEP_VOLUME * 1.2)  # 20% louder than the red beep


def _build_beep_wav(duration=BEEP_DURATION_S, freq=BEEP_FREQ_HZ, volume=BEEP_VOLUME):
    """Synthesizes a sine-wave beep to a temp WAV file (stdlib only, no
    audio packages required) and returns its path."""
    fd, path = tempfile.mkstemp(suffix=".wav", prefix="f1_beep_")
    os.close(fd)
    n_samples = int(BEEP_SAMPLE_RATE * duration)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(BEEP_SAMPLE_RATE)
        frames = bytearray()
        for i in range(n_samples):
            t = i / BEEP_SAMPLE_RATE
            envelope = 1.0 - (i / n_samples)  # fade out to avoid an end-click
            sample = volume * envelope * math.sin(2 * math.pi * freq * t)
            frames += struct.pack("<h", int(sample * 32767))
        wf.writeframes(bytes(frames))
    return path


def _play_beep_blocking(path):
    try:
        if sys.platform.startswith("win"):
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME)
        elif sys.platform == "darwin":
            subprocess.run(["afplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            for player in ("paplay", "aplay"):
                try:
                    subprocess.run(
                        [player, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        check=True
                    )
                    return
                except (FileNotFoundError, subprocess.CalledProcessError):
                    continue
    except Exception:
        pass  # audio is a nice-to-have; never let a beep failure crash the app


def play_beep(path):
    """Fire-and-forget: plays the beep without blocking the UI thread."""
    threading.Thread(target=_play_beep_blocking, args=(path,), daemon=True).start()

# --- Bluetooth (micro:bit) config -------------------------------------------
# Replace these with your two micro:bits' real MAC addresses.
MICROBIT_1_MAC = "F1:EB:DE:11:A3:97"   # <-- replace with micro:bit #1 MAC
MICROBIT_2_MAC = "F5:16:D8:76:73:54"   # <-- replace with micro:bit #2 MAC
MICROBIT_MAC_ADDRESSES = [MICROBIT_1_MAC, MICROBIT_2_MAC]

# GATT characteristic to write commands to. Defaults to the Nordic UART
# Service RX characteristic, which the micro:bit's built-in UART BLE service
# also uses. Adjust if your micro:bit firmware exposes a different one.
UART_TX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
GO_COMMAND = "G:"
BLE_CONNECT_TIMEOUT = 10.0  # seconds


class BLEController:
    """Runs a background asyncio event loop and manages BLE connections to
    the micro:bits, so BLE I/O never blocks the tkinter UI thread.

    status_callback is invoked as status_callback(mac, state, message):
      - mac is the board's address, or None for a general/non-board message
      - state is one of: "unavailable", "connecting", "connected",
        "failed", "disconnected", "sent"
      - message is a human-readable string for the status label
    """

    def __init__(self, mac_addresses, char_uuid, status_callback=None):
        self.mac_addresses = mac_addresses
        self.char_uuid = char_uuid
        self.status_callback = status_callback or (lambda mac, state, msg: None)
        self.clients = {}  # mac -> BleakClient
        self.loop = None
        self.thread = None
        self._loop_ready = threading.Event()

    def start(self):
        """Starts the background event loop thread and blocks briefly until
        the loop exists, so a connect_all() called right after is safe."""
        if not BLE_AVAILABLE:
            self.status_callback(None, "unavailable", "Bluetooth: 'bleak' not installed (pip install bleak)")
            return
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        self._loop_ready.wait(timeout=5)

    def _run_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._loop_ready.set()
        self.loop.run_forever()

    def connect_all(self):
        """Kicks off (non-blocking) connection attempts to both micro:bits."""
        if not (BLE_AVAILABLE and self.loop):
            return
        asyncio.run_coroutine_threadsafe(self._connect_all(), self.loop)

    async def _connect_all(self):
        for mac in self.mac_addresses:
            await self._connect_one(mac)

    async def _connect_one(self, mac):
        self.status_callback(mac, "connecting", f"Bluetooth: connecting to {mac}...")
        try:
            client = BleakClient(mac)
            await client.connect(timeout=BLE_CONNECT_TIMEOUT)
            if client.is_connected:
                self.clients[mac] = client
                self.status_callback(mac, "connected", f"Bluetooth: connected to {mac}")
            else:
                self.status_callback(mac, "failed", f"Bluetooth: failed to connect to {mac}")
        except Exception as exc:
            self.status_callback(mac, "failed", f"Bluetooth: error connecting to {mac} ({exc})")

    def send_command(self, text):
        """Fire-and-forget: sends `text` to every connected micro:bit."""
        if not (BLE_AVAILABLE and self.loop):
            return
        asyncio.run_coroutine_threadsafe(self._send_command(text), self.loop)

    async def _send_command(self, text):
        data = text.encode("utf-8")
        if not self.clients:
            self.status_callback(None, "failed", "Bluetooth: no micro:bits connected, nothing sent")
            return
        for mac, client in list(self.clients.items()):
            try:
                if client.is_connected:
                    await client.write_gatt_char(self.char_uuid, data)
                    self.status_callback(mac, "sent", f"Bluetooth: sent '{text}' to {mac}")
                else:
                    self.status_callback(mac, "disconnected", f"Bluetooth: {mac} not connected, skipped")
            except Exception as exc:
                self.status_callback(mac, "failed", f"Bluetooth: send error to {mac} ({exc})")

    def stop(self):
        """Disconnects all clients and stops the background loop."""
        if not (BLE_AVAILABLE and self.loop):
            return

        async def _disconnect_all():
            for client in self.clients.values():
                try:
                    if client.is_connected:
                        await client.disconnect()
                except Exception:
                    pass

        fut = asyncio.run_coroutine_threadsafe(_disconnect_all(), self.loop)
        try:
            fut.result(timeout=5)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)


class F1StartLights(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("F1 Start Lights")
        self.configure(bg=BG_COLOR)
        self.resizable(False, False)

        self.canvas_width = 620
        self.canvas_height = 260

        self.ble_leds = {}  # mac -> (canvas, oval_id)
        self._build_ble_leds()
        self._build_header()

        self.canvas = tk.Canvas(
            self, width=self.canvas_width, height=self.canvas_height,
            bg=BG_COLOR, highlightthickness=0
        )
        self.canvas.pack(padx=20, pady=(20, 5))

        self.status = tk.Label(
            self, text="Press START to begin the sequence",
            fg=TEXT_COLOR, bg=BG_COLOR, font=("Helvetica", 16, "bold")
        )
        # Not packed: kept only so the sequence logic below can still set its
        # text without errors, but no message is shown above the START button.

        self.car_timers = {}         # car_id -> {"running", "start", "elapsed", "after_id"}
        self.timer_labels = {}       # car_id -> Label
        self.timer_stop_buttons = {} # car_id -> Button

        control_row = tk.Frame(self, bg=BG_COLOR, relief="groove", borderwidth=2)
        control_row.pack(pady=(0, 20))

        car1_box = self._build_car_timer_box(control_row, car_id=1)

        self.start_btn = tk.Button(
            control_row, text="START", command=self.start_sequence,
            font=BTN_FONT, bg=BTN_COLOR, fg="white",
            activebackground=BTN_ACTIVE_COLOR, activeforeground="white",
            padx=BTN_PADX, pady=BTN_PADY, width=BTN_WIDTH_CHARS, relief="flat",
            borderwidth=0, highlightthickness=0
        )
        self.start_btn.pack(side="left", padx=24, anchor="center")

        car2_box = self._build_car_timer_box(control_row, car_id=2)

        # Make both car boxes the same size (symmetrical), taking the larger
        # of each dimension so neither box's content gets clipped.
        self.update_idletasks()
        box_w = max(car1_box.winfo_reqwidth(), car2_box.winfo_reqwidth())
        box_h = max(car1_box.winfo_reqheight(), car2_box.winfo_reqheight())
        for box in (car1_box, car2_box):
            box.pack_propagate(False)
            box.configure(width=box_w, height=box_h)

        # Stretch the box to exactly the light canvas's width via internal
        # padding, so its border lines up with the rig above it.
        self.update_idletasks()
        extra_width = max(0, self.canvas_width - control_row.winfo_reqwidth())
        control_row.pack_configure(ipadx=extra_width // 2, ipady=10)

        self.lights = []  # [ [circle_id, circle_id], ... ] per column
        self.after_ids = []
        self._draw_rig()

        try:
            self._beep_path = _build_beep_wav()
            self._long_beep_path = _build_beep_wav(
                duration=GREEN_BEEP_DURATION_S, freq=GREEN_BEEP_FREQ_HZ, volume=GREEN_BEEP_VOLUME
            )
        except Exception:
            self._beep_path = None
            self._long_beep_path = None  # beeps are a nice-to-have; never block startup

        self.ble = BLEController(
            MICROBIT_MAC_ADDRESSES, UART_TX_CHAR_UUID,
            status_callback=self._on_ble_status
        )
        self.ble.start()
        self.ble.connect_all()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_ble_status(self, mac, state, message):
        # status_callback fires from the BLE background thread; hop back to
        # the tkinter thread before touching any widgets.
        self.after(0, lambda: self._apply_ble_status(mac, state, message))

    def _apply_ble_status(self, mac, state, message):
        color = {
            "unavailable": LED_IDLE_COLOR,
            "connecting": LED_CONNECTING_COLOR,
            "connected": LED_CONNECTED_COLOR,
            "sent": LED_CONNECTED_COLOR,
            "failed": LED_FAILED_COLOR,
            "disconnected": LED_FAILED_COLOR,
        }.get(state, LED_IDLE_COLOR)

        if mac is not None and mac in self.ble_leds:
            canvas, oval_id = self.ble_leds[mac]
            canvas.itemconfig(oval_id, fill=color)
        elif mac is None:
            # general/broadcast message (e.g. bleak missing) -> reflect on all LEDs
            for canvas, oval_id in self.ble_leds.values():
                canvas.itemconfig(oval_id, fill=color)

    def _build_ble_leds(self):
        """Top-most row: one small LED per micro:bit showing its BLE state."""
        row = tk.Frame(self, bg=BG_COLOR)
        row.pack(pady=(16, 0))

        for i, mac in enumerate(MICROBIT_MAC_ADDRESSES, start=1):
            item = tk.Frame(row, bg=BG_COLOR)
            item.pack(side="left", padx=12)

            canvas = tk.Canvas(item, width=16, height=16, bg=BG_COLOR, highlightthickness=0)
            oval_id = canvas.create_oval(2, 2, 14, 14, fill=LED_IDLE_COLOR, outline="#333333")
            canvas.pack(side="left", padx=(0, 6))

            label = tk.Label(
                item, text=f"micro:bit {i}",
                fg=TEXT_COLOR, bg=BG_COLOR, font=("Helvetica", 10)
            )
            label.pack(side="left")

            self.ble_leds[mac] = (canvas, oval_id)

    def _on_close(self):
        self.ble.stop()
        for state in self.car_timers.values():
            if state["after_id"] is not None:
                self.after_cancel(state["after_id"])
        for path in (self._beep_path, self._long_beep_path):
            if path:
                try:
                    os.remove(path)
                except OSError:
                    pass
        self.destroy()

    def _build_header(self):
        """Top row: Cadence logo next to the Formula 1 logo, both scaled to fit."""
        header = tk.Frame(self, bg=BG_COLOR)
        header.pack(pady=(20, 10))

        cadence_img = self._load_cropped_image(CADENCE_LOGO_FILENAME)
        f1_img = self._load_cropped_image(F1_LOGO_FILENAME)

        shared_height = self._best_fit_height(cadence_img, f1_img)

        self._header_images = []  # keep references so they aren't garbage collected
        for img in (cadence_img, f1_img):
            if img is None:
                continue
            w, h = img.size
            new_w = max(1, int(w * (shared_height / h)))
            resized = img.resize((new_w, shared_height), Image.LANCZOS)
            photo = ImageTk.PhotoImage(resized)
            self._header_images.append(photo)
            label = tk.Label(header, image=photo, bg=BG_COLOR)
            label.pack(side="left", padx=(0, HEADER_LOGO_GAP))

    def _load_cropped_image(self, relative_path):
        """Loads a PNG, trims transparent padding, returns a PIL Image (or None)."""
        if not PIL_AVAILABLE:
            return None
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)
        if not os.path.exists(path):
            return None
        img = Image.open(path).convert("RGBA")
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)
        return img

    def _best_fit_height(self, *images):
        """Picks a shared logo height so the row of logos best fits the window width."""
        aspect_ratios = [img.size[0] / img.size[1] for img in images if img is not None]
        if not aspect_ratios:
            return HEADER_MIN_HEIGHT
        gap_total = HEADER_LOGO_GAP * len(aspect_ratios)
        target_width = self.canvas_width * HEADER_WIDTH_RATIO - gap_total
        height = target_width / sum(aspect_ratios)
        return int(max(HEADER_MIN_HEIGHT, min(HEADER_MAX_HEIGHT, height)))

    def _build_car_timer_box(self, parent, car_id):
        """A bordered box holding one car's run timer and its Stop button,
        laid out horizontally: title, elapsed time, Stop button. Returns the
        box widget so callers can equalize sizes across boxes."""
        self.car_timers[car_id] = {
            "running": False, "start": None, "elapsed": 0.0, "after_id": None
        }

        box_color = CAR_BOX_COLORS.get(car_id, BG_COLOR)

        box = tk.Frame(
            parent, bg=box_color, relief="groove", borderwidth=2
        )
        box.pack(side="left", padx=10, ipadx=12, ipady=8, anchor="center")

        # Inner frame keeps the content centered even after `box` is later
        # resized to a fixed width/height to match its sibling box.
        content = tk.Frame(box, bg=box_color)
        content.pack(expand=True)

        title = tk.Label(
            content, text=f"Car {car_id}",
            fg=CAR_BOX_TEXT_COLOR, bg=box_color, font=("Helvetica", 12, "bold")
        )
        title.pack(side="left", anchor="center", padx=(0, 10))

        time_label = tk.Label(
            content, text=self._format_time(0.0),
            fg=CAR_BOX_TEXT_COLOR, bg=box_color, font=("Helvetica", 22, "bold")
        )
        time_label.pack(side="left", anchor="center", padx=(0, 10))
        self.timer_labels[car_id] = time_label

        stop_btn = tk.Button(
            content, text="Stop", command=lambda c=car_id: self._stop_timer(c),
            font=BTN_FONT, bg=BTN_COLOR, fg="white",
            activebackground=BTN_ACTIVE_COLOR, activeforeground="white",
            padx=BTN_PADX, pady=BTN_PADY, width=BTN_WIDTH_CHARS, relief="flat", state="disabled",
            borderwidth=0, highlightthickness=0
        )
        stop_btn.pack(side="left", anchor="center")
        self.timer_stop_buttons[car_id] = stop_btn

        return box

    @staticmethod
    def _format_time(seconds):
        return f"{seconds:0.2f}s"

    def _reset_timers(self):
        for car_id, state in self.car_timers.items():
            if state["after_id"] is not None:
                self.after_cancel(state["after_id"])
            state.update(running=False, start=None, elapsed=0.0, after_id=None)
            self.timer_labels[car_id].config(text=self._format_time(0.0))
            self.timer_stop_buttons[car_id].config(state="disabled")

    def _start_timers(self):
        now = time.perf_counter()
        for car_id, state in self.car_timers.items():
            state["running"] = True
            state["start"] = now
            state["elapsed"] = 0.0
            self.timer_stop_buttons[car_id].config(state="normal")
            self._tick_timer(car_id)

    def _tick_timer(self, car_id):
        state = self.car_timers[car_id]
        if not state["running"]:
            return
        elapsed = time.perf_counter() - state["start"]
        self.timer_labels[car_id].config(text=self._format_time(elapsed))
        state["after_id"] = self.after(TIMER_UPDATE_MS, self._tick_timer, car_id)

    def _stop_timer(self, car_id):
        state = self.car_timers[car_id]
        if not state["running"]:
            return
        state["elapsed"] = time.perf_counter() - state["start"]
        state["running"] = False
        if state["after_id"] is not None:
            self.after_cancel(state["after_id"])
            state["after_id"] = None
        self.timer_labels[car_id].config(text=self._format_time(state["elapsed"]))
        self.timer_stop_buttons[car_id].config(state="disabled")
        self._maybe_reenable_start()

    def _maybe_reenable_start(self):
        """START stays disabled after a race until both car timers have
        been individually stopped."""
        if not any(state["running"] for state in self.car_timers.values()):
            self.start_btn.config(state="normal")

    def _draw_rig(self):
        col_width = self.canvas_width / NUM_COLUMNS
        radius = 28
        gap_y = 70
        top_y = 70

        for col in range(NUM_COLUMNS):
            cx = col_width * col + col_width / 2
            # dark panel behind each column
            self.canvas.create_rectangle(
                cx - radius - 10, top_y - radius - 15,
                cx + radius + 10, top_y + gap_y + radius + 15,
                fill=RIG_COLOR, outline="#333333", width=2
            )
            column_ids = []
            for row in range(LIGHTS_PER_COLUMN):
                cy = top_y + row * gap_y
                circle = self.canvas.create_oval(
                    cx - radius, cy - radius, cx + radius, cy + radius,
                    fill=UNLIT_COLOR, outline="#000000", width=3
                )
                column_ids.append(circle)
            self.lights.append(column_ids)

    def _set_column(self, col_index, lit):
        color = LIT_COLOR if lit else UNLIT_COLOR
        self._set_column_color(col_index, color)

    def _set_column_color(self, col_index, color):
        for circle_id in self.lights[col_index]:
            self.canvas.itemconfig(circle_id, fill=color)

    def _all_off(self):
        for col in range(NUM_COLUMNS):
            self._set_column(col, False)

    def _all_green(self):
        for col in range(NUM_COLUMNS):
            self._set_column_color(col, GREEN_COLOR)

    def start_sequence(self):
        # cancel anything pending and reset
        for aid in self.after_ids:
            self.after_cancel(aid)
        self.after_ids.clear()
        self._all_off()
        self._reset_timers()
        self.start_btn.config(state="disabled")
        self.status.config(text="Get ready...")

        # schedule each column lighting up, one per second
        for i in range(NUM_COLUMNS):
            aid = self.after(STEP_DELAY_MS * (i + 1), self._light_column, i)
            self.after_ids.append(aid)

        # after all 5 are lit, hold for a random delay then kill all lights
        all_lit_time = STEP_DELAY_MS * NUM_COLUMNS
        hold_time = random.randint(MIN_HOLD_MS, MAX_HOLD_MS)
        aid = self.after(all_lit_time + hold_time, self._lights_out)
        self.after_ids.append(aid)

    def _light_column(self, col_index):
        self._set_column(col_index, True)
        self.status.config(text=f"{col_index + 1} / {NUM_COLUMNS} lights on")
        if self._beep_path:
            play_beep(self._beep_path)

    def _lights_out(self):
        self._all_green()
        self.status.config(text="GO! GO! GO!", fg=GO_COLOR)
        if self._long_beep_path:
            play_beep(self._long_beep_path)
        self.ble.send_command(GO_COMMAND)
        self._start_timers()
        self.after(2500, self._reset_status)

    def _reset_status(self):
        self.status.config(text="Press START to begin the sequence", fg=TEXT_COLOR)


if __name__ == "__main__":
    app = F1StartLights()
    app.mainloop()