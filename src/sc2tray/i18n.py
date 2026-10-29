"""Spanish or English: the Windows display language, unless the settings pick one."""
import ctypes

LANGUAGES = {"es": "Español", "en": "English"}     # each in its own language, for the menu
LANG_SPANISH = 0x0A         # primary language id of every Spanish locale


def system_language():
    try:
        lang = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except (OSError, AttributeError):
        return "en"
    return "es" if lang & 0x3FF == LANG_SPANISH else "en"


current = system_language()


def use(choice):
    """Switches the language: "system" or a key of LANGUAGES."""
    global current
    current = choice if choice in LANGUAGES else system_language()


def t(key, **values):
    es, en = STRINGS[key]
    return (es if current == "es" else en).format(**values)


# key: (Spanish, English)
STRINGS = {
    # tooltip and tray menu header
    "header": ("Steam Controller 2: {n} %", "Steam Controller 2: {n}%"),
    "header_reading": ("Steam Controller 2: leyendo batería…", "Steam Controller 2: reading battery…"),
    "header_off": ("Steam Controller 2: sin conexión", "Steam Controller 2: disconnected"),
    "status_dock_off": ("Apagado en el dock · cargando", "Off on the dock · charging"),
    "status_off": ("Mando apagado o fuera de alcance", "Controller off or out of range"),
    "status_no_receiver": ("Receptor no conectado", "Receiver not connected"),
    "status_on_battery": ("Con batería", "On battery"),
    "status_on_dock": ("en el dock", "on the dock"),
    "signal_4": ("Señal excelente ({dbm} dBm)", "Excellent signal ({dbm} dBm)"),
    "signal_3": ("Señal buena ({dbm} dBm)", "Good signal ({dbm} dBm)"),
    "signal_2": ("Señal regular ({dbm} dBm)", "Fair signal ({dbm} dBm)"),
    "signal_1": ("Señal débil ({dbm} dBm)", "Weak signal ({dbm} dBm)"),
    "full_in": ("Lleno en ~{time}", "Full in ~{time}"),
    "time_left": ("Quedan ~{time}", "~{time} left"),
    "last_level": ("Último nivel: {n} %", "Last level: {n}%"),
    # panel status lines (short: they sit beside the link icon)
    "on_dock": ("En el dock", "On the dock"),
    "disconnected": ("Sin conexión", "Disconnected"),
    "reading": ("Leyendo…", "Reading…"),
    "charged": ("Cargado", "Charged"),
    "charging": ("Cargando", "Charging"),
    "low_battery": ("Batería baja", "Low battery"),
    "connected": ("Conectado", "Connected"),
    "data_from": ("Dato de {time}", "As of {time}"),
    "last_value": ("Último valor", "Last value"),
    # actions and settings
    "find": ("Buscar mando", "Find controller"),
    "find_tune": ("Buscar con melodía", "Find with a tune"),
    "vibration_only": ("Solo vibración", "Vibration only"),
    "melody_ticktock": ("Tic-tac", "Tick-tock"),
    "melody_bird": ("Pájaro", "Bird"),
    "melody_ringing": ("Timbre", "Ringing"),
    "melody_sos": ("SOS", "SOS"),
    "melody_alarm": ("Alarma", "Alarm"),
    "notify_low": ("Avisar con batería baja ({n} %)", "Notify on low battery ({n}%)"),
    "notify_full": ("Avisar al terminar la carga", "Notify when fully charged"),
    "notify_disconnect": ("Avisar al desconectarse", "Notify on disconnect"),
    "autostart": ("Iniciar con Windows", "Start with Windows"),
    "language": ("Idioma", "Language"),
    "language_system": ("Según el sistema", "System default"),
    "quit": ("Salir", "Quit"),
    # notifications
    "low_title": ("Batería baja: {n} %", "Low battery: {n}%"),
    "low_eta": ("Quedan ~{time}. ", "~{time} left. "),
    "low_body": ("Pon el mando en el puck o conéctalo por USB-C.",
                 "Put the controller on the puck or plug it in over USB-C."),
    "full_title": ("Carga completa", "Fully charged"),
    "full_body": ("El Steam Controller está al 100 %.", "The Steam Controller is at 100%."),
    "gone_title": ("Mando desconectado", "Controller disconnected"),
    "gone_last": ("Último nivel conocido: {n} %.", "Last known level: {n}%."),
    "gone_body": ("El mando se apagó o perdió la conexión.", "The controller switched off or lost its link."),
    "find_failed": ("No se pudo enviar la señal al mando.", "Couldn't reach the controller."),
    "autostart_failed": ("No se pudo cambiar el inicio automático.", "Couldn't change the autostart setting."),
}
