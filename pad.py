import customtkinter as ctk
from tkinter import filedialog
import serial
import serial.tools.list_ports
import threading
import queue
import json
import os
import keyboard
import time
import webbrowser
import subprocess
import pystray
from PIL import Image, ImageDraw

CONFIG_FILE = "scenarios.json"

# --- НАСТРОЙКИ ДИЗАЙНА ---
ctk.set_appearance_mode("dark")
BG_COLOR = "#0B0C10"
PANEL_COLOR = "#121A21"
NEON_CYAN = "#00F0FF"
HOVER_CYAN = "#00C8D6"
TEXT_MAIN = "#FFFFFF"
TEXT_MUTED = "#A0AAB2"
DANGER = "#FF003C"

data = {
    "port": "",
    "profiles": [
        {"name": "Game", "buttons": [{}, {}, {}, {}, {}, {}]},
        {"name": "Work", "buttons": [{}, {}, {}, {}, {}, {}]},
        {"name": "Social", "buttons": [{}, {}, {}, {}, {}, {}]}
    ]
}

if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Ошибка чтения конфига: {e}")

ser = None
serial_lock = threading.Lock()
action_queue = queue.Queue()


# --- ВОРКЕР ВЫПОЛНЕНИЯ СЦЕНАРИЕВ ---
def scenario_worker():
    while True:
        profile_idx, btn_idx = action_queue.get()
        try:
            scenario = data["profiles"][profile_idx]["buttons"][btn_idx]

            try:
                delay_sec = float(scenario.get("delay", 0))
            except ValueError:
                delay_sec = 0.0

            def step_delay():
                if delay_sec > 0: time.sleep(delay_sec)

            if scenario.get("open"):
                paths = scenario["open"]
                if isinstance(paths, str): paths = [paths]
                for path in paths:
                    if path.strip():
                        try:
                            os.startfile(path.strip())
                            step_delay()
                        except Exception:
                            pass

            if scenario.get("sites"):
                sites = scenario["sites"]
                if isinstance(sites, str): sites = [sites]
                for url in sites:
                    if url.strip():
                        try:
                            webbrowser.open(url.strip())
                            step_delay()
                        except Exception:
                            pass

            if scenario.get("script"):
                script_path = scenario["script"].strip()
                if script_path:
                    try:
                        if script_path.endswith(".ps1"):
                            subprocess.Popen(["powershell", "-ExecutionPolicy", "Bypass", "-File", script_path],
                                             creationflags=0x08000000)
                        elif script_path.endswith(".py"):
                            subprocess.Popen(["python", script_path], creationflags=0x08000000)
                        else:
                            os.startfile(script_path)
                        step_delay()
                    except Exception:
                        pass

            if scenario.get("hotkey"):
                try:
                    keyboard.send(scenario["hotkey"])
                    step_delay()
                except Exception:
                    pass

            if scenario.get("text"):
                keyboard.write(scenario["text"], delay=0.01)

        except Exception as e:
            pass
        action_queue.task_done()


threading.Thread(target=scenario_worker, daemon=True).start()

# --- ФОНОВОЕ ЧТЕНИЕ ПОРТА ---
last_status = ""


def set_status(text, color):
    global last_status
    if text != last_status:
        lbl_status.configure(text=text, text_color=color)
        last_status = text


def serial_listener():
    global ser
    while True:
        if not ser or not ser.is_open:
            saved_port = data.get("port")
            if saved_port:
                ports = [p.device for p in serial.tools.list_ports.comports()]
                if saved_port in ports:
                    try:
                        ser = serial.Serial(saved_port, 9600, timeout=0.5, write_timeout=0.1)
                        ser.reset_input_buffer()
                        ser.reset_output_buffer()

                        app.after(0, lambda: set_status(f"Синхронизация с {saved_port}...", "orange"))
                        time.sleep(2.5)

                        with serial_lock:
                            try:
                                ser.write(f"MAX:{len(data['profiles'])}\n".encode('utf-8'))
                                ser.write(f"NAME:{data['profiles'][0]['name']}\n".encode('utf-8'))
                            except Exception:
                                ser.reset_output_buffer()

                        app.after(0, lambda: set_status("СИНХРОНИЗИРОВАНО. СИСТЕМА ГОТОВА.", "#00FF66"))
                    except Exception:
                        if ser:
                            try:
                                ser.close()
                            except:
                                pass
                        ser = None
            if not ser or not ser.is_open:
                app.after(0, lambda: set_status("Ожидание устройства...", TEXT_MUTED))
                time.sleep(1)
                continue

        try:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line:
                if line.startswith("ACTION:"):
                    parts = line.split(":")
                    if len(parts) >= 3:
                        action_queue.put((int(parts[1]), int(parts[2])))

                elif line.startswith("REQ:"):
                    parts = line.split(":")
                    if len(parts) >= 2:
                        prof_idx = int(parts[1])
                        if prof_idx < len(data["profiles"]):
                            prof_name = data["profiles"][prof_idx]["name"]
                            with serial_lock:
                                try:
                                    ser.write(f"MAX:{len(data['profiles'])}\n".encode('utf-8'))
                                    ser.write(f"NAME:{prof_name}\n".encode('utf-8'))
                                except Exception:
                                    ser.reset_output_buffer()
        except serial.SerialException:
            if ser:
                try:
                    ser.close()
                except:
                    pass
            ser = None
            app.after(0, lambda: set_status("Соединение прервано. Переподключение...", DANGER))
        except Exception:
            pass

        time.sleep(0.01)


# --- ФУНКЦИИ ИНТЕРФЕЙСА ---
def get_current_indices():
    p_name = combo_profile_var.get()
    b_name = combo_button_var.get()
    p_idx = next((i for i, p in enumerate(data["profiles"]) if p["name"] == p_name), 0)
    b_idx = int(b_name.replace("Кнопка ", "")) - 1
    return p_idx, b_idx


def connect_port():
    global ser
    port = combo_port_var.get()
    data["port"] = port
    save_data()
    if ser:
        try:
            ser.close()
        except:
            pass
        ser = None
    set_status(f"Поиск {port}...", NEON_CYAN)


def save_data():
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def load_profile_ui(*args):
    p_idx, b_idx = get_current_indices()
    scenario = data["profiles"][p_idx]["buttons"][b_idx]

    entry_script.delete(0, ctk.END)
    if scenario.get("script"): entry_script.insert(0, scenario["script"])

    text_open.delete("1.0", ctk.END)
    paths = scenario.get("open", [])
    if isinstance(paths, str): paths = [paths]
    if paths: text_open.insert("1.0", "\n".join(paths))

    text_sites.delete("1.0", ctk.END)
    sites = scenario.get("sites", [])
    if isinstance(sites, str): sites = [sites]
    if sites: text_sites.insert("1.0", "\n".join(sites))

    entry_hotkey.delete(0, ctk.END)
    if scenario.get("hotkey"): entry_hotkey.insert(0, scenario["hotkey"])

    entry_text.delete(0, ctk.END)
    if scenario.get("text"): entry_text.insert(0, scenario["text"])

    entry_delay.delete(0, ctk.END)
    if scenario.get("delay"): entry_delay.insert(0, scenario["delay"])


def save_scenario():
    p_idx, b_idx = get_current_indices()
    data["profiles"][p_idx]["buttons"][b_idx] = {
        "script": entry_script.get(),
        "open": [p.strip() for p in text_open.get("1.0", ctk.END).split("\n") if p.strip()],
        "sites": [s.strip() for s in text_sites.get("1.0", ctk.END).split("\n") if s.strip()],
        "hotkey": entry_hotkey.get(),
        "text": entry_text.get(),
        "delay": entry_delay.get()
    }
    save_data()
    set_status(f"СЦЕНАРИЙ [КНОПКА {b_idx + 1}] СОХРАНЕН", "#00FF66")


def clear_scenario():
    p_idx, b_idx = get_current_indices()
    data["profiles"][p_idx]["buttons"][b_idx] = {}
    save_data()
    load_profile_ui()
    set_status(f"КНОПКА {b_idx + 1} ОЧИЩЕНА", DANGER)


def browse_exe():
    filename = filedialog.askopenfilename(filetypes=[("Programs", "*.exe"), ("All", "*.*")])
    if filename:
        current = text_open.get("1.0", ctk.END).strip()
        text_open.insert(ctk.END, ("\n" if current else "") + filename)


def browse_script():
    filename = filedialog.askopenfilename(filetypes=[("Scripts", "*.bat *.cmd *.ps1 *.py"), ("All", "*.*")])
    if filename:
        entry_script.delete(0, ctk.END)
        entry_script.insert(0, filename)


# --- ЛОГИКА ТРЕЯ (ФОНОВОГО РЕЖИМА) ---
def create_image():
    # Простая иконка-квадратик для трея, если нет своей картинки
    image = Image.new('RGB', (64, 64), color=BG_COLOR)
    draw = ImageDraw.Draw(image)
    draw.rectangle((16, 16, 48, 48), fill=NEON_CYAN)
    return image


def quit_window(icon, item):
    icon.stop()
    app.quit()


def show_window(icon, item):
    icon.stop()
    app.after(0, app.deiconify)


def hide_window():
    app.withdraw()  # Прячем окно
    menu = pystray.Menu(
        pystray.MenuItem('Развернуть настройки', show_window),
        pystray.MenuItem('Выход', quit_window)
    )
    icon = pystray.Icon("StreamPad", create_image(), "Stream Pad Engine", menu)
    threading.Thread(target=icon.run, daemon=True).start()


# --- ГРАФИЧЕСКИЙ ИНТЕРФЕЙС ---
app = ctk.CTk()
app.title("Stream Pad Engine")
app.geometry("540x820")
app.configure(fg_color=BG_COLOR)

# Перехватываем нажатие на "Крестик" и сворачиваем в трей вместо закрытия
app.protocol('WM_DELETE_WINDOW', hide_window)

header = ctk.CTkLabel(app, text="STREAM PAD CONTROL", font=("Arial Black", 20), text_color=NEON_CYAN)
header.pack(pady=(15, 5))

frame_port = ctk.CTkFrame(app, fg_color=PANEL_COLOR, corner_radius=10)
frame_port.pack(fill="x", padx=15, pady=5)
ctk.CTkLabel(frame_port, text="УСТРОЙСТВО:", font=("Arial", 12, "bold"), text_color=TEXT_MUTED).pack(side="left",
                                                                                                     padx=15, pady=10)
ports = [p.device for p in serial.tools.list_ports.comports()]
combo_port_var = ctk.StringVar(
    value=data.get("port", "") if data.get("port") in ports else (ports[0] if ports else "Нет портов"))
combo_port = ctk.CTkOptionMenu(frame_port, variable=combo_port_var, values=ports if ports else ["None"],
                               fg_color=BG_COLOR, button_color=NEON_CYAN, button_hover_color=HOVER_CYAN,
                               text_color=TEXT_MAIN)
combo_port.pack(side="left", padx=5)
ctk.CTkButton(frame_port, text="ПОДКЛЮЧИТЬ", command=connect_port, fg_color=BG_COLOR, border_color=NEON_CYAN,
              border_width=2, text_color=NEON_CYAN, hover_color="#003333", width=100).pack(side="right", padx=15)

lbl_status = ctk.CTkLabel(app, text="ОЖИДАНИЕ УСТРОЙСТВА...", font=("Arial", 11, "bold"), text_color=TEXT_MUTED)
lbl_status.pack(pady=2)

frame_nav = ctk.CTkFrame(app, fg_color=PANEL_COLOR, corner_radius=10)
frame_nav.pack(fill="x", padx=15, pady=10)
combo_profile_var = ctk.StringVar(value=data["profiles"][0]["name"])
ctk.CTkOptionMenu(frame_nav, variable=combo_profile_var, values=[p["name"] for p in data["profiles"]],
                  command=load_profile_ui,
                  fg_color=BG_COLOR, button_color=NEON_CYAN, button_hover_color=HOVER_CYAN, text_color=TEXT_MAIN).pack(
    side="left", padx=15, pady=15, expand=True, fill="x")
combo_button_var = ctk.StringVar(value="Кнопка 1")
ctk.CTkOptionMenu(frame_nav, variable=combo_button_var, values=[f"Кнопка {i + 1}" for i in range(6)],
                  command=load_profile_ui,
                  fg_color=BG_COLOR, button_color=NEON_CYAN, button_hover_color=HOVER_CYAN, text_color=TEXT_MAIN).pack(
    side="right", padx=15, pady=15, expand=True, fill="x")

frame_scen = ctk.CTkScrollableFrame(app, fg_color=PANEL_COLOR, corner_radius=10)
frame_scen.pack(fill="both", expand=True, padx=15, pady=5)


def create_label(text): return ctk.CTkLabel(frame_scen, text=text, font=("Arial", 12, "bold"), text_color=TEXT_MAIN)

# --- ПУНКТЫ МЕНЮ В НОВОМ ПОРЯДКЕ ---

create_label("1. СКРИПТ (.bat, .ps1, .py)").pack(anchor="w", padx=10, pady=(10, 0))
f3 = ctk.CTkFrame(frame_scen, fg_color="transparent")
f3.pack(fill="x", padx=10, pady=(2, 5))
entry_script = ctk.CTkEntry(f3, fg_color=BG_COLOR, border_color=NEON_CYAN, border_width=1, text_color=TEXT_MAIN)
entry_script.pack(side="left", fill="x", expand=True)
ctk.CTkButton(f3, text="ОБЗОР", command=browse_script, width=60, fg_color=BG_COLOR, border_color=NEON_CYAN,
              border_width=1, text_color=NEON_CYAN, hover_color="#003333").pack(side="left", padx=(10, 0))

create_label("2. ПРОГРАММЫ (каждая с новой строки)").pack(anchor="w", padx=10, pady=(5, 0))
f1 = ctk.CTkFrame(frame_scen, fg_color="transparent")
f1.pack(fill="x", padx=10, pady=(2, 5))
text_open = ctk.CTkTextbox(f1, height=50, fg_color=BG_COLOR, border_color=NEON_CYAN, border_width=1,
                           text_color=TEXT_MAIN)
text_open.pack(side="left", fill="x", expand=True)
ctk.CTkButton(f1, text="ОБЗОР", command=browse_exe, width=60, fg_color=BG_COLOR, border_color=NEON_CYAN, border_width=1,
              text_color=NEON_CYAN, hover_color="#003333").pack(side="left", padx=(10, 0))

create_label("3. САЙТЫ / ССЫЛКИ").pack(anchor="w", padx=10, pady=(5, 0))
text_sites = ctk.CTkTextbox(frame_scen, height=50, fg_color=BG_COLOR, border_color=NEON_CYAN, border_width=1,
                            text_color=TEXT_MAIN)
text_sites.pack(fill="x", padx=10, pady=(2, 5))

create_label("4. ХОТКЕЙ (напр. ctrl+shift+esc)").pack(anchor="w", padx=10, pady=(5, 0))
entry_hotkey = ctk.CTkEntry(frame_scen, fg_color=BG_COLOR, border_color=NEON_CYAN, border_width=1, text_color=TEXT_MAIN)
entry_hotkey.pack(fill="x", padx=10, pady=(2, 5))

create_label("5. НАПЕЧАТАТЬ ТЕКСТ").pack(anchor="w", padx=10, pady=(5, 0))
entry_text = ctk.CTkEntry(frame_scen, fg_color=BG_COLOR, border_color=NEON_CYAN, border_width=1, text_color=TEXT_MAIN)
entry_text.pack(fill="x", padx=10, pady=(2, 5))

create_label("6. ЗАДЕРЖКА (секунды, напр. 1.5)").pack(anchor="w", padx=10, pady=(5, 0))
entry_delay = ctk.CTkEntry(frame_scen, fg_color=BG_COLOR, border_color=NEON_CYAN, border_width=1, text_color=TEXT_MAIN)
entry_delay.pack(fill="x", padx=10, pady=(2, 15))

frame_action = ctk.CTkFrame(app, fg_color="transparent")
frame_action.pack(fill="x", padx=15, pady=10)

ctk.CTkButton(frame_action, text="СОХРАНИТЬ", command=save_scenario, font=("Arial Black", 14),
              fg_color=NEON_CYAN, text_color="black", hover_color=HOVER_CYAN, height=45).pack(side="left", expand=True,
                                                                                              fill="x", padx=(0, 10))
ctk.CTkButton(frame_action, text="СБРОСИТЬ", command=clear_scenario, font=("Arial Black", 14),
              fg_color="transparent", border_color=DANGER, border_width=2, text_color=DANGER, hover_color="#330000",
              height=45).pack(side="right", fill="x")

load_profile_ui()
threading.Thread(target=serial_listener, daemon=True).start()
app.mainloop()