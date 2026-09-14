import tkinter as tk
import time
import threading
import queue
import os

from PIL import Image, ImageTk, ImageDraw

from microbit_sync import MicrobitGroup

# --- Fill these in with your 6 micro:bits' actual MAC addresses ---
# Find them with `bluetoothctl scan on`. Each one needs to be
# paired/trusted once via bluetoothctl before this will connect --
# see microbit_sync.py for details.
MICROBIT_MAC_ADDRESSES = [
    "CF:60:3C:77:78:EC",
    "C6:07:B9:ED:82:89",
    "DF:32:91:89:12:22",
    "F6:22:E6:CE:EF:0A",
    "FA:63:59:1A:F2:A7",
    "DA:64:65:8C:ED:58",
]

LED_YELLOW = "#e0b400"
LED_GREEN = "#3fbf5f"

# Resolve relative to this script's own folder, not the current working
# directory -- so the image loads correctly no matter where the script is
# launched from (a different cwd is a common reason a relative path like
# "assets/hideseek_bg.png" silently fails to load).
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BG_IMAGE_PATH = os.path.join(SCRIPT_DIR, "assets", "hideseek_bg.png")
BG_OVERLAY_RGBA = (255, 255, 255, 55)  # light overlay so widgets stay readable (halved for a brighter background)
APP_ICON_PATH = os.path.join(SCRIPT_DIR, "assets", "app_icon.png")


def _new_icon_canvas(size, scale=4):
    """Common setup for the fruit icons below: a transparent supersampled
    canvas, returned along with its draw context and the big/small sizes."""
    big = size * scale
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img), big


def make_apple_icon(size=28):
    img, draw, big = _new_icon_canvas(size)
    body_r = big * 0.36
    cx, cy = big * 0.5, big * 0.56
    draw.ellipse([cx - body_r, cy - body_r * 0.95, cx + body_r, cy + body_r * 1.05],
                 fill="#e0342f")
    draw.ellipse([cx - body_r * 0.35, cy - body_r * 1.05, cx + body_r * 0.2, cy - body_r * 0.55],
                 fill="#f2716b")  # highlight
    draw.line([cx + big * 0.02, cy - body_r * 1.05, cx + big * 0.06, cy - body_r * 1.4],
              fill="#6b4a2e", width=int(big * 0.05))
    leaf = [(cx + big * 0.08, cy - body_r * 1.3), (cx + big * 0.32, cy - body_r * 1.45),
            (cx + big * 0.2, cy - body_r * 1.05)]
    draw.polygon(leaf, fill="#4fb85c")
    return img.resize((size, size), Image.LANCZOS)


def make_banana_icon(size=28):
    img, draw, big = _new_icon_canvas(size)
    line_w = int(big * 0.24)
    draw.arc([big * 0.12, big * 0.02, big * 1.15, big * 1.05], start=200, end=330,
              fill="#f2d43c", width=line_w)
    draw.ellipse([big * 0.10, big * 0.66, big * 0.10 + line_w * 0.8, big * 0.66 + line_w * 0.8],
                 fill="#8a6a2e")
    draw.ellipse([big * 0.82, big * 0.14, big * 0.82 + line_w * 0.6, big * 0.14 + line_w * 0.6],
                 fill="#8a6a2e")
    return img.resize((size, size), Image.LANCZOS)


def make_orange_icon(size=28):
    img, draw, big = _new_icon_canvas(size)
    body_r = big * 0.38
    cx, cy = big * 0.5, big * 0.55
    draw.ellipse([cx - body_r, cy - body_r, cx + body_r, cy + body_r], fill="#f2932e")
    draw.ellipse([cx - body_r * 0.4, cy - body_r * 0.7, cx - body_r * 0.05, cy - body_r * 0.3],
                 fill="#f7b86b")  # highlight
    draw.line([cx, cy - body_r, cx, cy - body_r * 1.3], fill="#6b8a3a", width=int(big * 0.05))
    leaf = [(cx, cy - body_r * 1.25), (cx + big * 0.22, cy - body_r * 1.35),
            (cx + big * 0.1, cy - body_r * 1.0)]
    draw.polygon(leaf, fill="#4fb85c")
    return img.resize((size, size), Image.LANCZOS)


def make_strawberry_icon(size=28):
    img, draw, big = _new_icon_canvas(size)
    cx, top_y, bottom_y = big * 0.5, big * 0.28, big * 0.92
    width_top = big * 0.34
    body = [
        (cx - width_top, top_y + big * 0.06), (cx - width_top * 0.9, top_y - big * 0.02),
        (cx, top_y - big * 0.06), (cx + width_top * 0.9, top_y - big * 0.02),
        (cx + width_top, top_y + big * 0.06),
        (cx + width_top * 0.55, bottom_y * 0.55 + top_y * 0.1),
        (cx, bottom_y), (cx - width_top * 0.55, bottom_y * 0.55 + top_y * 0.1),
    ]
    draw.polygon(body, fill="#e6453c")
    for sx, sy in [(-0.14, 0.25), (0.14, 0.25), (0, 0.4), (-0.2, 0.5), (0.2, 0.5), (0, 0.62)]:
        draw.ellipse([cx + sx * big - big * 0.02, top_y + sy * big - big * 0.02,
                      cx + sx * big + big * 0.02, top_y + sy * big + big * 0.02], fill="#f2d43c")
    calyx = [(cx, top_y - big * 0.05), (cx - big * 0.22, top_y - big * 0.18),
             (cx - big * 0.08, top_y + big * 0.02), (cx, top_y - big * 0.14),
             (cx + big * 0.08, top_y + big * 0.02), (cx + big * 0.22, top_y - big * 0.18)]
    draw.polygon(calyx, fill="#4fb85c")
    return img.resize((size, size), Image.LANCZOS)


def make_grapes_icon(size=28):
    img, draw, big = _new_icon_canvas(size)
    r = big * 0.15
    centers = [
        (0.32, 0.35), (0.5, 0.35), (0.68, 0.35),
        (0.4, 0.55), (0.6, 0.55),
        (0.5, 0.75),
    ]
    for cx_f, cy_f in centers:
        cx, cy = cx_f * big, cy_f * big
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#a15ce0")
    draw.line([big * 0.5, big * 0.2, big * 0.5, big * 0.35], fill="#6b4a2e", width=int(big * 0.05))
    leaf = [(big * 0.5, big * 0.18), (big * 0.7, big * 0.08), (big * 0.58, big * 0.28)]
    draw.polygon(leaf, fill="#4fb85c")
    return img.resize((size, size), Image.LANCZOS)


def make_watermelon_icon(size=28):
    img, draw, big = _new_icon_canvas(size)
    cx, cy, r = big * 0.5, big * 0.15, big * 0.78
    # rind (green outer arc), pith (white ring), flesh (red) -- drawn as
    # nested pie-slices forming a wedge/slice pointing downward
    draw.pieslice([cx - r, cy - r, cx + r, cy + r], start=20, end=160, fill="#4fb85c")
    r2 = r * 0.90
    draw.pieslice([cx - r2, cy - r2, cx + r2, cy + r2], start=20, end=160, fill="#f2f2e6")
    r3 = r * 0.80
    draw.pieslice([cx - r3, cy - r3, cx + r3, cy + r3], start=20, end=160, fill="#e6453c")
    for sx, sy in [(-0.14, 0.42), (0.05, 0.5), (0.2, 0.4), (-0.02, 0.62), (0.15, 0.6)]:
        seed_cx, seed_cy = cx + sx * big, cy + sy * big
        draw.ellipse([seed_cx - big * 0.025, seed_cy - big * 0.04,
                      seed_cx + big * 0.025, seed_cy + big * 0.04], fill="#3a2a1a")
    return img.resize((size, size), Image.LANCZOS)


FRUIT_ICON_MAKERS = [
    make_apple_icon,
    make_banana_icon,
    make_orange_icon,
    make_strawberry_icon,
    make_grapes_icon,
    make_watermelon_icon,
]


def prepare_background_image(path, size):
    """Scales the image DOWN (or up) to fit entirely within `size` with no
    cropping -- the whole picture stays visible, letterboxed on the
    shorter axis -- then bakes in a light overlay. Returns a PIL Image
    (RGBA), kept as PIL (not yet a Tk PhotoImage) so pieces of it can
    later be cropped out to fake per-widget transparency. Returns None if
    the image can't load."""
    try:
        img = Image.open(path).convert("RGB")
    except Exception as exc:
        print(f"[background] could not load '{path}': {exc}")
        return None

    # Fit-to-contain: scale so the whole image fits inside `size` with no
    # cropping, centered, letterboxed with a soft sky-blue fill matching
    # the illustration's own palette.
    target_w, target_h = size
    src_w, src_h = img.size
    scale = min(target_w / src_w, target_h / src_h)
    new_w, new_h = round(src_w * scale), round(src_h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("RGB", size, (214, 234, 248))
    offset = ((target_w - new_w) // 2, (target_h - new_h) // 2)
    canvas.paste(img, offset)

    overlay = Image.new("RGBA", size, BG_OVERLAY_RGBA)
    return Image.alpha_composite(canvas.convert("RGBA"), overlay)


class SixButtonApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Six Button App")
        self.root.geometry("952x770")
        self.root.resizable(False, False)

        try:
            self.icon_photo = tk.PhotoImage(file=APP_ICON_PATH)
            self.root.iconphoto(True, self.icon_photo)
        except tk.TclError as exc:
            print(f"[icon] could not load '{APP_ICON_PATH}': {exc}")

        # Background image -- created first so every widget added after
        # this stacks visually on top of it. Kept as a PIL image (not just
        # a PhotoImage) so we can crop matching patches for the LEDs later.
        self.bg_image_pil = prepare_background_image(BG_IMAGE_PATH, (952, 770))
        self.bg_photo = ImageTk.PhotoImage(self.bg_image_pil) if self.bg_image_pil else None
        if self.bg_photo is not None:
            bg_label = tk.Label(root, image=self.bg_photo, bd=0, highlightthickness=0)
            bg_label.place(x=0, y=0, relwidth=1, relheight=1)

        self.timer_text = tk.StringVar(value="Elapsed: 0.0 s")
        self.timer_label = tk.Label(
            root, textvariable=self.timer_text, relief="sunken",
            padx=11, pady=8, font=("TkDefaultFont", 15, "bold"), bg="white"
        )
        self.timer_label.pack(fill="x", padx=14, pady=(14, 21))

        self.flash_job = None       # holds the scheduled `after` callback id
        self.flash_on = False       # tracks current flash color state
        self.flashing = False       # True while the display should keep flashing
        self.pending_action = None  # the button's real action, run after flashing

        self.timer_running = False
        self.timer_start = None
        self.timer_job = None

        self.active_button = None   # the button that started the current run

        buttons = [
            ("Find MicroBit 1", self.on_button_1),
            ("Find MicroBit 2", self.on_button_2),
            ("Find MicroBit 3", self.on_button_3),
            ("Find MicroBit 4", self.on_button_4),
            ("Find MicroBit 5", self.on_button_5),
            ("Find MicroBit 6", self.on_button_6),
        ]

        # mac -> (canvas, oval_id) so we can flip that button's LED to
        # green once we hear back that its micro:bit connected
        self.led_by_mac = {}
        self.row_frames = []  # the Frame wrapping each button+LED pair
        self._button_icons = []  # keep PhotoImage references alive
        self.find_buttons = []  # the 6 "Find MicroBit" buttons, disabled until all connect
        self.button_time_vars = {}  # button widget -> StringVar showing its elapsed time
        self.button_numbers = {}  # button widget -> its number (1-6)

        for number, (text, handler) in enumerate(buttons, start=1):
            row = tk.Frame(root, bd=0, highlightthickness=0)
            row.pack(pady=6)
            self.row_frames.append(row)

            icon_maker = FRUIT_ICON_MAKERS[(number - 1) % len(FRUIT_ICON_MAKERS)]
            icon_photo = ImageTk.PhotoImage(icon_maker(size=39))
            self._button_icons.append(icon_photo)

            btn = tk.Button(
                row, text=text, image=icon_photo, compound="left",
                width=238, height=45, anchor="w", padx=14, pady=6,
                state="disabled",
            )
            btn.config(command=lambda h=handler, b=btn, n=number: self.trigger(h, b, n))
            btn.pack(side="left")
            self.find_buttons.append(btn)
            self.button_numbers[btn] = number

            time_var = tk.StringVar(value="")
            time_box_frame = tk.Frame(row, width=72, height=45)
            time_box_frame.pack_propagate(False)  # keep the fixed size even though the Label inside is small
            time_box_frame.pack(side="left", padx=(11, 0))
            time_box = tk.Label(
                time_box_frame, textvariable=time_var, relief="sunken",
                bg="white", anchor="center"
            )
            time_box.pack(fill="both", expand=True)
            self.button_time_vars[btn] = time_var

            led = tk.Canvas(row, width=25, height=25, highlightthickness=0, bd=0)
            oval = led.create_oval(3, 3, 22, 22, fill=LED_YELLOW, outline="#666666")
            led.pack(side="left", padx=(11, 0))

            self.led_by_mac[MICROBIT_MAC_ADDRESSES[number - 1]] = (led, oval)

        tk.Button(
            root, text="Found", width=30, pady=8,
            bg="#ffdddd", command=self.on_found
        ).pack(pady=(14, 6))

        tk.Button(
            root, text="Reset (disconnect micro:bits)", width=30, pady=8,
            bg="#ffe8bb", command=self.on_reset
        ).pack(pady=(6, 6))

        # --- Bluetooth setup ---
        # The window is fully built and about to be shown via mainloop()
        # below. We start connecting only now, in a background thread, so
        # the window appears immediately instead of waiting on Bluetooth.
        self._ble_events = queue.Queue()  # (mac, kind, success, error) from the BLE thread

        def _on_unexpected_disconnect(mac):
            # Fires for ANY disconnect -- including ones we asked for via
            # Finished/Reset (which also report through their own
            # on_result callback -- a harmless duplicate) -- but crucially
            # also for a surprise drop, which is the case this exists for.
            self._ble_events.put((mac, "disconnect", True, None))

        self.ble = MicrobitGroup(MICROBIT_MAC_ADDRESSES, on_disconnect=_on_unexpected_disconnect)
        self._ble_thread = threading.Thread(target=self._connect_in_background, daemon=True)
        self._ble_thread.start()
        self._poll_ble_events()

        # Fake per-widget transparency for the LED canvases: crop the exact
        # patch of the background image that sits behind each one and use
        # that as its own background, so it blends in instead of showing a
        # mismatched solid box. Needs layout finalized first to know each
        # LED's real on-screen position.
        self.root.update_idletasks()
        self._apply_led_transparency()
        self._apply_row_transparency()

    def _apply_led_transparency(self):
        if self.bg_image_pil is None:
            return
        self._led_bg_photos = []  # keep references alive (Tk drops unreferenced PhotoImages)
        root_x, root_y = self.root.winfo_rootx(), self.root.winfo_rooty()
        for canvas, oval in self.led_by_mac.values():
            w, h = canvas.winfo_width(), canvas.winfo_height()
            if w <= 1 or h <= 1:
                continue  # layout not realized for this widget yet
            x = canvas.winfo_rootx() - root_x
            y = canvas.winfo_rooty() - root_y
            patch = self.bg_image_pil.crop((x, y, x + w, y + h))
            photo = ImageTk.PhotoImage(patch)
            self._led_bg_photos.append(photo)
            img_id = canvas.create_image(0, 0, anchor="nw", image=photo)
            canvas.tag_lower(img_id, oval)  # keep the oval drawn on top

    def _apply_row_transparency(self):
        """Same trick as the LED canvases, applied to each row Frame --
        without this, the gap between the button and its LED (and any
        margin around them) shows the Frame's flat system background
        color instead of the photo behind it."""
        if self.bg_image_pil is None:
            return
        self._row_bg_photos = []
        root_x, root_y = self.root.winfo_rootx(), self.root.winfo_rooty()
        for row in self.row_frames:
            w, h = row.winfo_width(), row.winfo_height()
            if w <= 1 or h <= 1:
                continue
            x = row.winfo_rootx() - root_x
            y = row.winfo_rooty() - root_y
            patch = self.bg_image_pil.crop((x, y, x + w, y + h))
            photo = ImageTk.PhotoImage(patch)
            self._row_bg_photos.append(photo)
            bg_label = tk.Label(row, image=photo, bd=0, highlightthickness=0)
            bg_label.place(x=0, y=0, relwidth=1, relheight=1)
            bg_label.lower()  # sit behind the button/LED already in this row

    # ------------------------------------------------------------- BLE --
    def _connect_in_background(self):
        def on_result(mac, success, error):
            self._ble_events.put((mac, "connect", success, error))
        self.ble.connect_all(on_result=on_result)

    def _disconnect_in_background(self):
        def worker():
            def on_result(mac, success, error):
                self._ble_events.put((mac, "disconnect", success, error))
            self.ble.disconnect_all(on_result=on_result)
        threading.Thread(target=worker, daemon=True).start()

    def _poll_ble_events(self):
        try:
            while True:
                mac, kind, success, error = self._ble_events.get_nowait()
                led, oval = self.led_by_mac.get(mac, (None, None))
                if kind == "connect" and success:
                    if led is not None:
                        led.itemconfig(oval, fill=LED_GREEN)
                    print(f"[BLE] connected: {mac}")
                elif kind == "connect" and not success:
                    print(f"[BLE] failed to connect: {mac} ({error})")
                elif kind == "disconnect" and success:
                    if led is not None:
                        led.itemconfig(oval, fill=LED_YELLOW)
                    print(f"[BLE] disconnected: {mac}")
                elif kind == "disconnect" and not success:
                    print(f"[BLE] error disconnecting: {mac} ({error})")
        except queue.Empty:
            pass

        connected_count = sum(1 for c in self.ble.clients.values() if c.is_connected)
        total = len(MICROBIT_MAC_ADDRESSES)

        all_connected = connected_count == total
        new_state = "normal" if all_connected else "disabled"
        for btn in self.find_buttons:
            if str(btn["state"]) != new_state:
                btn.config(state=new_state)

        self.root.after(200, self._poll_ble_events)

    # ------------------------------------------------------------- UI --
    def on_reset(self):
        """Disconnects every currently connected micro:bit (each one's LED
        turns back to yellow as it actually disconnects). Unlike Finished,
        this doesn't touch the display, timer, or button-disabled state --
        it's Bluetooth-only."""
        self._disconnect_in_background()

    def on_found(self):
        """Stops both the flashing display and the timer, writes the
        elapsed time into the time box next to whichever button started
        this run, sends '0' to that button's micro:bit over BLE UART, and
        disables that button. (Does not disconnect any micro:bits -- use
        Reset for that.)"""
        elapsed = None
        if self.timer_start is not None:
            elapsed = time.time() - self.timer_start

        self.stop_flashing()
        self.stop_timer()

        if self.active_button is not None:
            if elapsed is not None:
                time_var = self.button_time_vars.get(self.active_button)
                if time_var is not None:
                    time_var.set(f"{elapsed:.1f} s")

            number = self.button_numbers.get(self.active_button)
            if number is not None:
                mac = MICROBIT_MAC_ADDRESSES[number - 1]
                if self.ble.is_connected(mac):
                    self.ble.send(mac, "0:")
                else:
                    print(f"[BLE] Found: {mac} not connected, skipping '0' send")

            self.active_button.config(state="disabled")
            self.active_button = None

    def stop_flashing(self):
        self.flashing = False
        if self.flash_job is not None:
            self.root.after_cancel(self.flash_job)
            self.flash_job = None
        self.timer_label.config(bg="white")

    def start_timer(self):
        self.timer_start = time.time()
        self.timer_running = True
        self._tick()

    def _tick(self):
        if not self.timer_running:
            return
        elapsed = time.time() - self.timer_start
        self.timer_text.set(f"Elapsed: {elapsed:.1f} s")
        self.timer_job = self.root.after(100, self._tick)

    def stop_timer(self):
        self.timer_running = False
        if self.timer_job is not None:
            self.root.after_cancel(self.timer_job)
            self.timer_job = None

    def trigger(self, action, button, number):
        """Runs on every button press: flash the elapsed time box
        green/white until Found is pressed, and (if its micro:bit is
        connected) send that button's number over BLE UART."""
        self.pending_action = action
        self.active_button = button
        self.flashing = True

        time_var = self.button_time_vars.get(button)
        if time_var is not None:
            time_var.set("")

        self.start_timer()
        self._flash_step()

        self._send_for_button(number)

    def _send_for_button(self, number):
        """Sends the button number to its mapped micro:bit. If that
        micro:bit isn't connected yet, the send is just skipped -- the
        button's local behavior (flash/timer) still works either way."""
        mac = MICROBIT_MAC_ADDRESSES[number - 1]
        if self.ble.is_connected(mac):
            self.ble.send(mac, f"{number}:")
        else:
            print(f"[BLE] button {number}: {mac} not connected yet, skipping send")

    def _flash_step(self):
        if self.flash_job is not None:
            self.root.after_cancel(self.flash_job)
            self.flash_job = None

        if not self.flashing:
            self.timer_label.config(bg="white")
            return

        self.flash_on = not self.flash_on
        self.timer_label.config(bg="green" if self.flash_on else "white")
        self.flash_job = self.root.after(500, self._flash_step)

    # Each button's underlying action, run once flashing finishes.
    # (No longer changes the display text — it stays on "Start Now".)
    def on_button_1(self):
        pass

    def on_button_2(self):
        pass

    def on_button_3(self):
        pass

    def on_button_4(self):
        pass

    def on_button_5(self):
        pass

    def on_button_6(self):
        pass


if __name__ == "__main__":
    root = tk.Tk()
    app = SixButtonApp(root)
    root.mainloop()