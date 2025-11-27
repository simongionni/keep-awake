import ctypes
from ctypes import wintypes
import threading
import time
import tkinter as tk

import pystray
from pystray import MenuItem as item
from PIL import Image, ImageDraw

# --- Costanti Windows per evitare lo standby ---
ES_CONTINUOUS        = 0x80000000
ES_SYSTEM_REQUIRED   = 0x00000001
ES_DISPLAY_REQUIRED  = 0x00000002

# --- Tasto "fantasma" F15 ---
VK_F15 = 0x7E
KEYEVENTF_KEYUP = 0x0002

# --- Hotkey Windows ---
MOD_ALT      = 0x0001
MOD_CONTROL  = 0x0002
WM_HOTKEY    = 0x0312
WM_QUIT      = 0x0012

kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

# Ogni quanti secondi pingare
INTERVAL_SECONDS = 60

# Stato globale
app_running = True      # se False il programma termina
enabled = False         # se True tiene sveglio il PC

tray_icon = None
tray_icon_green = None
tray_icon_red = None

root = None
status_label = None
toggle_btn = None
last_ping_label = None
window_visible = False

hotkey_thread_id = None  # id del thread che gestisce le hotkey


def set_keep_awake(on: bool):
    """Chiede a Windows di non andare in standby mentre è attivo."""
    if on:
        kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
        )
    else:
        kernel32.SetThreadExecutionState(ES_CONTINUOUS)


def send_fake_key():
    """Simula una pressione veloce del tasto F15."""
    user32.keybd_event(VK_F15, 0, 0, 0)
    user32.keybd_event(VK_F15, 0, KEYEVENTF_KEYUP, 0)


def worker_loop():
    """Thread che fa i ping periodici."""
    global app_running, enabled
    last_enabled = None

    while app_running:
        # Se ON/OFF è cambiato, aggiorna lo stato di standby
        if enabled != last_enabled:
            set_keep_awake(enabled)
            last_enabled = enabled

        if enabled:
            send_fake_key()
            update_ping_label()

        for _ in range(INTERVAL_SECONDS):
            if not app_running:
                break
            time.sleep(1)

    # Uscita definitiva
    set_keep_awake(False)


def update_ping_label():
    """Aggiorna la label 'Ultimo ping' nella finestra."""
    if root and last_ping_label:
        ts = time.strftime("%H:%M:%S")
        try:
            root.after(0, lambda: last_ping_label.config(text=f"Ultimo ping: {ts}"))
        except tk.TclError:
            pass


def update_gui_state():
    """Aggiorna stato ON/OFF nella finestra."""
    if not root or not status_label or not toggle_btn:
        return

    def _update():
        if enabled:
            status_label.config(text="ON", fg="green")
            toggle_btn.config(text="Stop")
        else:
            status_label.config(text="OFF", fg="red")
            toggle_btn.config(text="Start")

    try:
        root.after(0, _update)
    except tk.TclError:
        pass


def update_tray_icon():
    """Cambia icona e tooltip nella tray in base allo stato."""
    if not tray_icon:
        return
    if enabled:
        tray_icon.icon = tray_icon_green
        tray_icon.title = "Keep Awake: ON"
    else:
        tray_icon.icon = tray_icon_red
        tray_icon.title = "Keep Awake: OFF"
    tray_icon.update_menu()


def toggle_enabled():
    """Start/Stop del keep-awake (usato da bottone, hotkey, tray)."""
    global enabled
    enabled = not enabled
    update_gui_state()
    update_tray_icon()


def show_window():
    """Mostra la finestra se nascosta."""
    global window_visible
    if not root:
        return

    def _show():
        root.deiconify()
        root.lift()
        root.focus_force()

    window_visible = True
    try:
        root.after(0, _show)
    except tk.TclError:
        pass


def hide_window():
    """Nasconde la finestra ma NON chiude il programma."""
    global window_visible
    if not root:
        return

    def _hide():
        root.withdraw()

    window_visible = False
    try:
        root.after(0, _hide)
    except tk.TclError:
        pass


def on_tray_left_click(icon, _):
    """Click sinistro sulla tray: mostra/nasconde la finestra."""
    if window_visible:
        hide_window()
    else:
        show_window()


def exit_app():
    """Chiusura completa (hotkey o menu tray)."""
    global app_running, hotkey_thread_id

    if not app_running:
        return

    app_running = False

    # ferma la tray
    if tray_icon:
        try:
            tray_icon.stop()
        except Exception:
            pass

    # chiudi la finestra Tk
    if root:
        try:
            root.after(0, root.destroy)
        except tk.TclError:
            pass

    # fai uscire il thread delle hotkey dal GetMessageW
    if hotkey_thread_id is not None:
        user32.PostThreadMessageW(hotkey_thread_id, WM_QUIT, 0, 0)


def create_image(color):
    """Crea una piccola icona circolare 16x16 RGBA."""
    img = Image.new('RGBA', (16, 16), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, 14, 14), fill=color)
    return img


def create_tray_icon():
    """Crea e avvia l'icona nella system tray."""
    global tray_icon, tray_icon_green, tray_icon_red

    tray_icon_green = create_image((0, 200, 0, 255))
    tray_icon_red = create_image((200, 0, 0, 255))

    tray_icon = pystray.Icon(
        "KeepAwake",
        tray_icon_red,
        "Keep Awake: OFF",
        menu=pystray.Menu(
            item('Mostra finestra', lambda: show_window()),
            item('Start/Stop', lambda: toggle_enabled()),
            item('Esci', lambda: exit_app())
        ),
        on_click=on_tray_left_click
    )

    # Parte in un thread separato, il main thread resta per Tkinter
    tray_icon.run_detached()


def on_close_window():
    """Click sulla X della finestra: solo nasconde."""
    hide_window()


def setup_gui():
    """Crea la finestra (inizialmente nascosta)."""
    global root, status_label, toggle_btn, last_ping_label, window_visible

    root = tk.Tk()
    root.title("Keep Awake")
    root.attributes("-topmost", True)
    root.resizable(False, False)
    root.geometry("200x90+40+40")

    status_label = tk.Label(root, text="OFF", fg="red",
                            font=("Segoe UI", 16, "bold"))
    status_label.pack(pady=(8, 0))

    last_ping_label = tk.Label(root, text="Ultimo ping: -",
                               font=("Segoe UI", 9))
    last_ping_label.pack(pady=(2, 2))

    toggle_btn = tk.Button(root, text="Start", width=10, command=toggle_enabled)
    toggle_btn.pack(pady=(0, 4))

    info_label = tk.Label(root, text="CTRL+ALT+J: Start/Stop\nCTRL+ALT+Q: Esci",
                          font=("Segoe UI", 8))
    info_label.pack()

    root.protocol("WM_DELETE_WINDOW", on_close_window)
    root.withdraw()
    window_visible = False


def hotkey_loop():
    """Thread dedicato alle hotkey globali Windows (CTRL+ALT+J / Q)."""
    global hotkey_thread_id

    # salva l'id del thread per poter mandare WM_QUIT
    hotkey_thread_id = kernel32.GetCurrentThreadId()

    # registra CTRL+ALT+J (id = 1)
    if not user32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_ALT, ord('J')):
        print("Impossibile registrare CTRL+ALT+J")

    # registra CTRL+ALT+Q (id = 2)
    if not user32.RegisterHotKey(None, 2, MOD_CONTROL | MOD_ALT, ord('Q')):
        print("Impossibile registrare CTRL+ALT+Q")

    msg = wintypes.MSG()

    while True:
        ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
        if ret == 0:  # WM_QUIT
            break
        if ret == -1:
            # errore in GetMessage
            break

        if msg.message == WM_HOTKEY:
            if msg.wParam == 1:   # CTRL+ALT+J
                toggle_enabled()
            elif msg.wParam == 2: # CTRL+ALT+Q
                exit_app()

    user32.UnregisterHotKey(None, 1)
    user32.UnregisterHotKey(None, 2)


def main():
    setup_gui()

    # Thread che fa i ping periodici
    worker = threading.Thread(target=worker_loop, daemon=True)
    worker.start()

    # Thread per le hotkey globali
    hk_thread = threading.Thread(target=hotkey_loop, daemon=True)
    hk_thread.start()

    # Tray icon
    create_tray_icon()

    # Event loop Tk (anche se la finestra all’inizio è nascosta)
    root.mainloop()


if __name__ == "__main__":
    main()
