# SC2 Tray

Icono de bandeja para Windows 11 que muestra la batería y la conexión del
**Steam Controller 2** (2026): nivel, carga, tipo de enlace (puck, Bluetooth,
USB-C), señal y tiempo restante.

Basado en la ingeniería inversa del protocolo HID de
[steam-controller-plasma-widget](https://github.com/jahrekza/steam-controller-plasma-widget)
(ver [NOTICE.md](NOTICE.md)).

## Uso

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e .[dev]
.\.venv\Scripts\pythonw -m sc2tray          # icono en la bandeja
.\.venv\Scripts\python -m sc2tray --headless  # estado en JSON por consola
.\.venv\Scripts\python -m sc2tray --find ticktock
```

- **Panel (clic izquierdo)**: tarjeta oscura al estilo del widget de Plasma, con
  sus iconos: ilustración del mando, nivel grande, batería vertical del color del
  LED (blanco puck, azul Bluetooth, verde USB-C, naranja apagado en el dock, rojo
  batería baja), y bajo el nivel el estado, la señal del puck (barras y dBm) y el
  tiempo estimado, junto al icono del enlace (puck, Steam Machine, Bluetooth o
  USB-C). La batería va de la parte superior de la ilustración a la última
  línea, y la altura de la tarjeta sigue al contenido (una línea más solo si
  hay tiempo estimado). Abajo, "Buscar mando" hace vibrar el mando y "⋯" abre
  encima las melodías y los ajustes. Se cierra al hacer clic fuera o con Esc.
- **Tooltip**: nivel, estado de carga, enlace, señal (dBm) y tiempo estimado.
- **Menú (clic derecho)**: Buscar mando (vibración o melodía en los actuadores
  hápticos), avisos de batería baja / carga completa / desconexión, Iniciar con Windows.
- Funciona con Steam abierto: la lectura HID es compartida.

Ajustes en `%APPDATA%\SC2Tray\config.json`; historial de 24 h en
`%LOCALAPPDATA%\SC2Tray\history.json`.

## Ejecutable

```powershell
.\.venv\Scripts\python tools\build_exe.py
```

Genera `dist\SC2Tray.exe` (un solo archivo, ~20 MB, sin necesidad de Python).
Cópialo donde quieras y actívale "Iniciar con Windows" desde el menú: el
autoarranque apunta a la ruta del `.exe`, así que si lo mueves, vuelve a
activarlo. `--find` funciona también con el `.exe`; `--headless` no, porque
no tiene consola.

## Estructura

| Archivo | Función |
|---|---|
| `src/sc2tray/protocol.py` | IDs, decodificación de `0x43`/`0x7b`, consulta del dock, reports hápticos (puro, sin E/S) |
| `src/sc2tray/device.py` | hidapi: colección vendor activa, dock (MI_06), "Buscar mando" |
| `src/sc2tray/monitor.py` | hilo lector + sondeo del dock → `ControllerState` |
| `src/sc2tray/state.py` | estado, estimación de tiempo, historial |
| `src/sc2tray/icons.py` | icono variante A (barra de nivel) dibujado con Pillow |
| `src/sc2tray/tray.py` | pystray: icono, tooltip, menú, notificaciones |
| `src/sc2tray/panel.py` | panel emergente (tkinter + Pillow) |
| `src/sc2tray/assets/` | máscaras PNG de los iconos del panel, teñidas en tiempo de ejecución |
| `assets/upstream/` | SVG originales del widget de Plasma (MIT) |
| `src/sc2tray/text.py` | textos del tooltip, el menú y el panel |
| `src/sc2tray/config.py` | ajustes, autoarranque (HKCU Run), instancia única, tema |
| `tools/hid_probe.py` | lista las colecciones HID y muestrea reports (diagnóstico) |
| `tools/build_exe.py` | icono de la app + PyInstaller → `dist\SC2Tray.exe` |
| `tools/import_icons.py` | copia los SVG del repo original y los rasteriza a máscaras (resvg-py, solo desarrollo) |

## Protocolo en Windows

Windows divide cada interfaz del puck (`28de:1304`) en colecciones: ratón,
teclado (ambas bloqueadas por el sistema) y **vendor `0xFF00`**, que es la que
transporta los reports. El mando enlazado aparece en uno de los slots MI_02–MI_05;
MI_06 es el dock.

| Report | Bytes usados |
|---|---|
| `0x43` batería | `[1]` 1 batería · 2 cargando · 3 validando · 4 completo; `[2]` % |
| `0x7b` radio | `[9]` señal en dBm con signo (solo vía puck) |
| feature `0x02` cmd `0xB4` (MI_06) | respuesta `02 b4 01 <2 = en el dock>` |

## Tests

```powershell
.\.venv\Scripts\python -m pytest
```
