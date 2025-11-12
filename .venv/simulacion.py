import pygame, math, wave, struct, os, csv
from pid_controller import PID, PIDGains

# ================= Telegram + métricas =================
from datetime import datetime, date
from dotenv import load_dotenv
import telegram as tg   # usa nuestro telegram.py (no instales el paquete "telegram")

load_dotenv()

# Respeto nombres del .env; variables internas en español
ENVIAR_CAPTURAS        = os.getenv("SEND_SCREENSHOTS", "false").lower() == "true"
HORA_REPORTE_DIARIO    = int(os.getenv("DAILY_REPORT_HOUR", "20"))  # 20 = 8pm
CREAR_ARCHIVOS_REPORTE = os.getenv("CREATE_REPORT_FILES", "true").lower() == "true"
CARPETA_REPORTES       = os.path.join(os.path.dirname(__file__), "reports")
os.makedirs(CARPETA_REPORTES, exist_ok=True)

# Antirebotes
antirebote_alertas = tg.Debouncer(min_interval_sec=30)
antirebote_pid     = tg.Debouncer(min_interval_sec=120)

# --------- Métricas (acumuladas del día) ----------
metricas = {
    "seg_bomba_encendida": 0,
    "litros_bombeados": 0,
    "litros_entrada": 0,
    "litros_consumidos": 0,
    "alertas": 0,
    "protecciones_en_seco": 0,
    "eventos_encendido_bomba": 0,
    "seg_pid_activo": 0,
    "seg_pid_auto_llenado": 0,
    "min_cis_cm": None,
    "max_cis_cm": None,
    "min_sup_cm": None,
    "max_sup_cm": None,
}
_fecha_ultimo_reporte = None
_prev_bomba_encendida = False
_prev_alerta_activa   = False
_hora_ultimo_frame    = None

# --------- Menú de reportes on-demand ---------
menu_visible = False
rect_boton_menu = None
rect_menu = None
rect_menu_rep = None
rect_menu_csv = None
rect_menu_png = None
rect_menu_short = None

# ====== Helpers de texto (solo DISEÑO) ======
def _seguro(v, defecto):
    return v if v is not None else defecto

def _sep():  # separador simple y limpio
    return "<i>────────────────────────</i>\n"

def _h1(t):
    return f"<b>{t}</b>\n{_sep()}"

def _item(nombre, valor):
    return f"• {nombre}: <b>{valor}</b>\n"

def _fmt_tabla(pares, ancho=0):
    """
    pares: [("Etiqueta","Valor"), ...]
    Salida en monoespaciado alineado.
    """
    filas = [f"{k:<{ancho}} {v}" for k, v in pares]
    return "<pre>" + "\n".join(filas) + "</pre>\n"

def _rango(a, b, sufijo=" cm"):
    a = "-" if a is None else f"{a:.2f}"
    b = "-" if b is None else f"{b:.2f}"
    return f"{a}–{b}{sufijo}"


def crear_texto_reporte_diario(hoy: date) -> str:
    estado = [
        ("Bomba encendida:", f"{metricas['seg_bomba_encendida']/60:.1f} min"),
        ("Encendidos:", f"{metricas['eventos_encendido_bomba']}"),
        ("Alertas:", f"{metricas['alertas']}"),
        ("Protección seco:", f"{metricas['protecciones_en_seco']}"),
    ]
    pid = [
        ("PID activo:", f"{metricas['seg_pid_activo']/60:.1f} min"),
        ("Auto llenado:", f"{metricas['seg_pid_auto_llenado']/60:.1f} min"),
    ]
    caudales = [
        ("Bombeado:", f"{metricas['litros_bombeados']:.1f} L"),
        ("Entrada:", f"{metricas['litros_entrada']:.1f} L"),
        ("Consumo:", f"{metricas['litros_consumidos']:.1f} L"),
    ]
    niveles = [
        ("Cisterna min–max:", _rango(metricas['min_cis_cm'], metricas['max_cis_cm'])),
        ("Tanque min–max:", _rango(metricas['min_sup_cm'], metricas['max_sup_cm'])),
    ]

    return (
        _h1(f"📅 Reporte diario — {hoy.strftime('%Y-%m-%d')}") +
        "📋 <b>Estado</b>\n" + _fmt_tabla(estado) +
        "🤖 <b>PID</b>\n" + _fmt_tabla(pid) +
        "💧 <b>Entrada</b>\n" + _fmt_tabla(caudales) +
        "📏 <b>Niveles</b>\n" + _fmt_tabla(niveles)
    )


def crear_texto_resumen_corto(ahora: datetime) -> str:
    filas = [
        ("Cisterna min–max:", _rango(metricas['min_cis_cm'], metricas['max_cis_cm'])),
        ("Tanque min–max:", _rango(metricas['min_sup_cm'], metricas['max_sup_cm'])),
        ("Bombeado hoy:", f"{metricas['litros_bombeados']:.1f} L"),
        ("Alertas:", f"{metricas['alertas']}"),
    ]
    return _h1(f"📝 Resumen {ahora.strftime('%Y-%m-%d %H:%M')}") + _fmt_tabla(filas)


def escribir_csv_diario(hoy: date) -> str:
    # Archivo (acumula por día) – columnas ordenadas y legibles para Excel
    ruta = os.path.join(CARPETA_REPORTES, f"reporte_{hoy.strftime('%Y%m%d')}.csv")
    encabezados = [
        "fecha",
        "seg_bomba_encendida", "eventos_encendido_bomba", "alertas", "protecciones_en_seco",
        "litros_bombeados", "litros_entrada", "litros_consumidos",
        "seg_pid_activo", "seg_pid_auto_llenado",
        "min_cis_cm", "max_cis_cm", "min_sup_cm", "max_sup_cm"
    ]

    nuevo = not os.path.exists(ruta)
    fila = {
        "fecha": hoy.isoformat(),
        "seg_bomba_encendida": f"{metricas['seg_bomba_encendida']:.3f}",
        "eventos_encendido_bomba": metricas["eventos_encendido_bomba"],
        "alertas": metricas["alertas"],
        "protecciones_en_seco": metricas["protecciones_en_seco"],
        "litros_bombeados": f"{metricas['litros_bombeados']:.3f}",
        "litros_entrada": f"{metricas['litros_entrada']:.3f}",
        "litros_consumidos": f"{metricas['litros_consumidos']:.3f}",
        "seg_pid_activo": f"{metricas['seg_pid_activo']:.3f}",
        "seg_pid_auto_llenado": f"{metricas['seg_pid_auto_llenado']:.3f}",
        "min_cis_cm": _seguro(metricas["min_cis_cm"], ""),
        "max_cis_cm": _seguro(metricas["max_cis_cm"], ""),
        "min_sup_cm": _seguro(metricas["min_sup_cm"], ""),
        "max_sup_cm": _seguro(metricas["max_sup_cm"], ""),
    }

    with open(ruta, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=encabezados)
        if nuevo:
            f.write("sep=,\n")
            writer.writeheader()
        writer.writerow(fila)
    return ruta


def escribir_csv_instantaneo(ahora: datetime) -> str:
    ruta = os.path.join(CARPETA_REPORTES, f"snapshot_{ahora.strftime('%Y%m%d_%H%M%S')}.csv")
    encabezados = [
        "timestamp",
        "seg_bomba_encendida", "eventos_encendido_bomba", "alertas", "protecciones_en_seco",
        "litros_bombeados", "litros_entrada", "litros_consumidos",
        "seg_pid_activo", "seg_pid_auto_llenado",
        "min_cis_cm", "max_cis_cm", "min_sup_cm", "max_sup_cm"
    ]

    fila = {
        "timestamp": ahora.isoformat(timespec="seconds"),
        "seg_bomba_encendida": f"{metricas['seg_bomba_encendida']:.3f}",
        "eventos_encendido_bomba": metricas["eventos_encendido_bomba"],
        "alertas": metricas["alertas"],
        "protecciones_en_seco": metricas["protecciones_en_seco"],
        "litros_bombeados": f"{metricas['litros_bombeados']:.3f}",
        "litros_entrada": f"{metricas['litros_entrada']:.3f}",
        "litros_consumidos": f"{metricas['litros_consumidos']:.3f}",
        "seg_pid_activo": f"{metricas['seg_pid_activo']:.3f}",
        "seg_pid_auto_llenado": f"{metricas['seg_pid_auto_llenado']:.3f}",
        "min_cis_cm": _seguro(metricas["min_cis_cm"], ""),
        "max_cis_cm": _seguro(metricas["max_cis_cm"], ""),
        "min_sup_cm": _seguro(metricas["min_sup_cm"], ""),
        "max_sup_cm": _seguro(metricas["max_sup_cm"], ""),
    }

    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        f.write("sep=,\n")
        writer = csv.DictWriter(f, fieldnames=encabezados)
        writer.writeheader()
        writer.writerow(fila)
    return ruta


def reiniciar_metricas_diarias():
    global metricas
    metricas = {
        "seg_bomba_encendida": 0,
        "litros_bombeados": 0,
        "litros_entrada": 0,
        "litros_consumidos": 0,
        "alertas": 0,
        "protecciones_en_seco": 0,
        "eventos_encendido_bomba": 0,
        "seg_pid_activo": 0,
        "seg_pid_auto_llenado": 0,
        "min_cis_cm": None,
        "max_cis_cm": None,
        "min_sup_cm": None,
        "max_sup_cm": None,
    }

def _enviar(texto: str):
    tg.send_message(texto)
    if ENVIAR_CAPTURAS:
        try:
            ruta_snap = os.path.join(os.path.dirname(__file__), "_snap.png")
            pygame.image.save(ventana, ruta_snap)
            tg.send_photo(ruta_snap, caption="📷 Estado visual del simulador")
        except Exception:
            pass

def notificar_alerta(texto_alerta: str, msg_pid: str):
    if not texto_alerta and not msg_pid:
        return

    titulo = "🚨 ALERTA" if texto_alerta else "🤖 PID"
    detalle = texto_alerta if texto_alerta else msg_pid

    tabla = _fmt_tabla([
        ("Cisterna:", f"{nivel_cisterna_cm:4.1f}"),
        ("Tanque superior:", f"{nivel_tanque_sup_cm:4.1f}"),
    ])

    texto = _h1(f"{titulo}") + _item("Detalle", detalle) + "\n" + tabla

    if texto_alerta:
        if antirebote_alertas.should_send(f"A|{texto_alerta}|{int(nivel_cisterna_cm)}|{int(nivel_tanque_sup_cm)}"):
            tg.send_message(texto);
            if ENVIAR_CAPTURAS:
                try:
                    ruta_snap = os.path.join(os.path.dirname(__file__), "_snap.png")
                    pygame.image.save(ventana, ruta_snap)
                    tg.send_photo(ruta_snap, caption="📷 Estado visual del simulador")
                except Exception:
                    pass
    else:
        if antirebote_pid.should_send(f"P|{msg_pid}|{int(nivel_tanque_sup_cm)}"):
            tg.send_message(texto)


# ====== Acciones del MENÚ ======
def accion_enviar_reporte_ahora():
    ahora = datetime.now()
    txt = _h1("📊 <b>Reporte inmediato</b>") + crear_texto_reporte_diario(ahora.date())
    tg.send_message(txt)
    if ENVIAR_CAPTURAS:
        try:
            ruta_snap = os.path.join(os.path.dirname(__file__), f"instant_{ahora.strftime('%Y%m%d_%H%M%S')}.png")
            pygame.image.save(ventana, ruta_snap)
            tg.send_photo(ruta_snap, caption="📷 Captura instantánea")
        except Exception:
            pass

def accion_enviar_csv_ahora():
    if not CREAR_ARCHIVOS_REPORTE:
        tg.send_message("️🗒️ CSV deshabilitado")
        return

    ahora = datetime.now()

    try:
        ruta_csv = escribir_csv_instantaneo(ahora)
    except Exception as e:
        tg.send_message(
            "⚠️ No pude crear el CSV instantáneo.\n"
            f"<pre>{type(e).__name__}: {e}</pre>"
        )
        return

    ok = tg.send_document(ruta_csv, caption="📄 CSV instantáneo")
    if not ok:
        tg.send_message(
            "⚠️ No pude enviar el CSV por Telegram.\n"
            "Revisa TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en tu .env."
        )


def accion_enviar_png_ahora():
    try:
        ahora = datetime.now()
        ruta_snap = os.path.join(os.path.dirname(__file__), f"snapshot_{ahora.strftime('%Y%m%d_%H%M%S')}.png")
        pygame.image.save(ventana, ruta_snap)
        tg.send_photo(ruta_snap, caption=f"📷 Captura {ahora.strftime('%H:%M:%S')}")
    except Exception:
        tg.send_message("⚠️ Error al capturar/enviar imagen.")

def accion_enviar_resumen_ahora():
    ahora = datetime.now()
    tg.send_message(crear_texto_resumen_corto(ahora))

# =================== Pygame ===================
def crear_beep_wav(ruta:str, freq=880, dur_s=0.30, vol=0.6, samplerate=44100):
    nframes = int(dur_s * samplerate)
    amp = int(32767 * max(0, min(vol, 1)))
    with wave.open(ruta, "w") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(samplerate)
        for i in range(nframes):
            t = i / samplerate
            wf.writeframes(struct.pack("<h", int(amp * math.sin(2*math.pi*freq*t))))

pygame.mixer.pre_init(44100, -16, 2, 512)
pygame.init()
ancho_ventana, alto_ventana = 1300, 700
ventana = pygame.display.set_mode((ancho_ventana, alto_ventana))
pygame.display.set_caption("Simulación Bomba de Agua + PID")
reloj = pygame.time.Clock()
fuente_titulo = pygame.font.SysFont("consolas", 20, bold=True)
fuente_med    = pygame.font.SysFont("consolas", 16)
fuente_peq    = pygame.font.SysFont("consolas", 14)

# Colores
color_fondo        = (245, 247, 250)
color_linea        = (30, 33, 38)
color_texto        = (32, 36, 40)
color_texto_sec    = (110, 110, 110)
color_agua_oscuro  = (40, 95, 210)
color_agua_medio   = (60, 120, 240)
color_agua_claro   = (90, 160, 255)
color_tubo         = (30, 33, 38)
color_flotador     = (255, 210, 0)
color_bomba_cuerpo = (210, 210, 210)
color_bomba_borde  = (32, 36, 40)
color_hormigon     = (220, 222, 226)
color_hormigon_r   = (170, 170, 175)
color_panel_fondo   = (255, 255, 255)
color_panel_borde   = (206, 210, 220)
color_panel_texto   = (35, 38, 45)
color_panel_sutil   = (225, 229, 236)
color_panel_ok      = (17, 148, 70)
color_panel_alerta  = (206, 148, 18)
color_panel_peligro = (206, 55, 55)
color_acento        = (68, 134, 255)
color_barra_track   = (234, 238, 244)
color_barra_fill    = (68, 134, 255)
color_barra_borde   = (195, 202, 214)
color_boton_fondo   = (40, 42, 48)
color_boton_borde   = (210, 210, 210)
color_boton_texto   = (240, 240, 240)

# Botón “panel”
rect_boton_panel  = pygame.Rect(ancho_ventana - 170, alto_ventana - 54, 150, 38)

y_suelo = 320
ancho_camara_total = 410
alto_cisterna_px   = 220
x_cisterna         = 520
rect_cisterna = pygame.Rect(x_cisterna, y_suelo + 20, ancho_camara_total, alto_cisterna_px)
grosor_muro = 4
def rect_interno(r):
    return pygame.Rect(r.x + grosor_muro, r.y + grosor_muro, r.w - 2*grosor_muro, r.h - 2*grosor_muro)
rect_cisterna_int = rect_interno(rect_cisterna)
ancho_bomba, alto_bomba = 130, 55
rect_bomba = pygame.Rect(rect_cisterna.x + 20, y_suelo - alto_bomba - 12, ancho_bomba, alto_bomba)
rect_tanque_superior = pygame.Rect(170, 70, 280, 220)

# Paneles
panel_visible = False
rect_panel = pygame.Rect(ancho_ventana - 425, 0, 380, 315)
pid_panel_visible = False
rect_pid_panel = pygame.Rect(100, 350, 300, 200)


btn_w, btn_h, btn_gap = 150, 38, 10
rect_boton_panel     = pygame.Rect(ancho_ventana-170, alto_ventana-54, btn_w, btn_h)
rect_btn_vac_cis     = pygame.Rect(rect_boton_panel.x-(btn_w+btn_gap),   alto_ventana-54, btn_w, btn_h)
rect_btn_vac_sup     = pygame.Rect(rect_boton_panel.x-(btn_w+btn_gap)*2, alto_ventana-54, btn_w, btn_h)
rect_btn_pid_panel   = pygame.Rect(rect_boton_panel.x-(btn_w+btn_gap)*3, alto_ventana-54, btn_w, btn_h)
rect_boton_menu      = pygame.Rect(rect_boton_panel.x-(btn_w+btn_gap)*4, alto_ventana-54, btn_w, btn_h)

menu_x, menu_y = 970, 340
menu_w, menu_h = 280, 220

def get_menu_layout():
    global rect_menu, rect_menu_rep, rect_menu_csv, rect_menu_png, rect_menu_short
    rect_menu = pygame.Rect(menu_x, menu_y, menu_w, menu_h)

    # Botones internos (relativos al panel)
    bx, by, bw, bh, gap = menu_x + 16, menu_y + 50, menu_w - 32, 32, 10
    rect_menu_rep   = pygame.Rect(bx, by + 0*(bh+gap), bw, bh)
    rect_menu_csv   = pygame.Rect(bx, by + 1*(bh+gap), bw, bh)
    rect_menu_png   = pygame.Rect(bx, by + 2*(bh+gap), bw, bh)
    rect_menu_short = pygame.Rect(bx, by + 3*(bh+gap), bw, bh)

get_menu_layout()

# Escalas y estados
alto_cisterna_cm   = 200
alto_tanque_sup_cm = 200
px_por_cm_cis = (rect_cisterna.h-2*grosor_muro)/alto_cisterna_cm
px_por_cm_sup = (rect_tanque_superior.h - 20) / alto_tanque_sup_cm
fondo_px_cis  = rect_cisterna.bottom-grosor_muro
fondo_px_sup  = rect_tanque_superior.bottom - 10
def cm_a_y_cis(v): return int(fondo_px_cis - v * px_por_cm_cis)
def cm_a_y_sup(v): return int(fondo_px_sup - v * px_por_cm_sup)

nivel_cisterna_cm       = 140
nivel_tanque_sup_cm     = 30
altura_boca_manguera_cm = 120
bomba_on        = True
velocidad_bomba = 0.6
entrada_on      = False

caudal_entrada_lps_activo = 0.8
caudal_bomba_max_lps      = 1.5
consumo_tanque_sup_lps    = 0.3

area_cisterna_cm2   = 25000
area_tanque_sup_cm2 = 25000

distancia_suelo_segura_cm      = 50
distancia_superficie_segura_cm = 20
factor_tiempo_simulacion       = 8

# Alarmas
umbral_sin_agua_cm = 1
proteccion_seco_on = True
alarma_mute = False
alarma_vol  = 0.9
parpadeo_t  = 0

# PID
pid_enabled   = False
pid_target_cm = 120
pid = PID(PIDGains(kp=0.08, ki=0.02, kd=0.04), umin=0, umax=1, tau=0.08)

# Auto-llenado PID
auto_llenado_activo     = False
entrada_forzada_por_pid = False
umbral_auto_on  = 50
umbral_auto_off = 60
allow_pid_auto_start = True

# Audio
ruta_beep = os.path.join(os.path.dirname(__file__), "_beep_temp.wav")
try:
    crear_beep_wav(ruta_beep, 900, 0.35, 1)
    sonido_beep  = pygame.mixer.Sound(ruta_beep)
    sonido_beep.set_volume(alarma_vol)
    canal_alarma = pygame.mixer.Channel(0)
except Exception:
    sonido_beep = None
    canal_alarma = None

def limitar(v, a, b):
    if v < a: return a
    if v > b: return b
    return v

def dibujar_texto(s, t, x, y, c=(32,36,40), f=None):
    f = f or fuente_med
    s.blit(f.render(t, True, c), (x, y))

def agua_gradiente(s, x, y, w, h):
    if h <= 0: return
    pygame.draw.rect(s, color_agua_oscuro, (x, y, w, h))
    h2 = int(h*0.6)
    if h2>0: pygame.draw.rect(s, color_agua_medio, (x, y, w, h2))
    h3 = int(h*0.3)
    if h3>0: pygame.draw.rect(s, color_agua_claro, (x, y, w, h3))

def superficie(s, x0, x1, yb, t, col):
    pts, paso, x = [], 10, x0
    while x <= x1:
        off = math.sin((x*0.08) + t*3) * 2
        pts.append((x, yb + off)); x += paso
    if len(pts) >= 2: pygame.draw.lines(s, col, False, pts, 2)

def barra_h(s, x, y, w, h, p):
    pygame.draw.rect(s, color_barra_track, (x, y, w, h), border_radius=6)
    w2 = int(w * (p/100))
    if w2>0: pygame.draw.rect(s, color_barra_fill, (x, y, w2, h), border_radius=6)
    pygame.draw.rect(s, color_barra_borde, (x, y, w, h), 2, border_radius=6)

def sombra_rect(s, r, dx, dy, rad):
    surf = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
    pygame.draw.rect(surf, (0,0,0,20), pygame.Rect(0,0,r.w,r.h), border_radius=rad)
    s.blit(surf, (r.x + dx, r.y + dy))

def chip_estado(surf, x, y, texto, activo, font=None):
    font = font or fuente_peq
    pad_x=12; h=22
    tw,th = font.size(texto)
    w = max(100, 26 + tw + 8)
    r=pygame.Rect(x,y,w,h)
    pygame.draw.rect(surf, (234,238,244), r, border_radius=10)
    pygame.draw.rect(surf, (195,202,214), r, 1, border_radius=10)
    col=(20,160,90) if activo else (150,150,150)
    pygame.draw.circle(surf, col, (r.x+12, r.y+h//2), 6)
    surf.blit(font.render(texto, True, color_panel_texto), (r.x+26, r.y+(h-th)//2))
    return r.right

def dibujar_chips_en_filas(surf, x, y, datos, chips_por_fila=3, gap_x=10, gap_y=30):
    """
    datos: lista de tuplas (texto, activo)
    chips_por_fila: cuántos chips por fila (3 => 2 filas para 6 chips)
    Devuelve la nueva coordenada y tras pintar los chips.
    """
    x_inicio = x
    en_fila = 0
    for texto, activo in datos:
        right = chip_estado(surf, x, y, texto, activo)
        x = right + gap_x
        en_fila += 1
        if en_fila >= chips_por_fila:
            y += gap_y
            x = x_inicio
            en_fila = 0
    if en_fila > 0:
        y += gap_y
    return y


def dibujar_texto_envuelto(surf, texto, x, y, max_w, color=color_panel_texto, font=None, gap=4):
    font = font or fuente_peq
    if not texto: return y
    palabras = texto.split(' ')
    linea = ""
    for w in palabras:
        t = (linea + (" " if linea else "") + w)
        if font.size(t)[0] <= max_w:
            linea = t
        else:
            surf.blit(font.render(linea, True, color), (x, y))
            y += font.get_linesize() + gap
            linea = w
    if linea:
        surf.blit(font.render(linea, True, color), (x, y))
        y += font.get_linesize() + gap
    return y

def dibujar_etiqueta_valor(surf, x, y, w, etiqueta, valor, font=None, color=color_panel_texto):
    font = font or fuente_peq
    lw, lh = font.size(etiqueta)
    vw, _  = font.size(valor)
    surf.blit(font.render(etiqueta, True, color), (x, y))
    surf.blit(font.render(valor, True, color), (x + w - vw, y))
    return y + font.get_linesize() + 2

def crear_superficie_panel(rect, titulo):
    sombra_rect(ventana, rect, 5, 5, 5)
    pygame.draw.rect(ventana, color_panel_fondo, rect, border_radius=12)
    pygame.draw.rect(ventana, color_panel_borde, rect, 7, border_radius=12)
    surf = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
    padding = 16
    inner = pygame.Rect(padding, padding, rect.w - 2*padding, rect.h - 2*padding)
    surf.set_clip(inner)
    y_titulo = padding
    t_surf = fuente_titulo.render(titulo, True, color_panel_texto)
    surf.blit(t_surf, (padding, y_titulo))
    sep_y = y_titulo + t_surf.get_height() + 8
    pygame.draw.line(surf, color_panel_sutil, (padding, sep_y), (rect.w - padding, sep_y), 1)
    return surf, padding, sep_y + 12, inner

def pegar_superficie_panel(surf, rect):
    ventana.blit(surf, rect.topleft)

def dibujar_tanque_superior(nivel, t):
    pygame.draw.rect(ventana, (240,240,240), rect_tanque_superior, border_radius=6)
    pygame.draw.rect(ventana, color_linea, rect_tanque_superior, 2, border_radius=6)
    m = 10; x = rect_tanque_superior.x + m; y = rect_tanque_superior.y + m
    w = rect_tanque_superior.w - 2*m; h = rect_tanque_superior.h - 2*m
    ys = cm_a_y_sup(nivel); yi = y + h
    if ys < yi:
        agua_gradiente(ventana, x, ys, w, yi-ys)
        superficie(ventana, x, x+w, ys, t, color_linea)
    dibujar_texto(ventana, "Tanque superior", rect_tanque_superior.x, rect_tanque_superior.y - 24, (32,36,40), fuente_peq)

def dibujar_cisterna(nivel, boca, t, entrada_activa):
    pygame.draw.rect(ventana, color_linea, rect_cisterna, grosor_muro, border_radius=4)
    y_sup = cm_a_y_cis(nivel)
    yi = rect_cisterna_int.bottom
    if y_sup < yi:
        agua_gradiente(ventana, rect_cisterna_int.x, y_sup, rect_cisterna_int.w, yi - y_sup)
        superficie(ventana, rect_cisterna_int.x, rect_cisterna_int.right, y_sup, t, color_linea)
    fx = rect_cisterna_int.x + int(rect_cisterna_int.w * 0.62)
    fy = y_sup - 8
    pygame.draw.circle(ventana, (255,210,0), (fx, fy), 12)
    pygame.draw.circle(ventana, color_linea, (fx, fy), 12, 2)
    xt = rect_cisterna_int.x + int(rect_cisterna_int.w * 0.78)
    yt = rect_cisterna_int.y + 15
    yb = cm_a_y_cis(boca)
    pygame.draw.line(ventana, color_tubo, (xt, yt), (xt, yb), 6)
    pygame.draw.circle(ventana, color_tubo, (xt, yb), 8)
    y_tubo = rect_cisterna_int.y + 35
    x_izq  = rect_cisterna.x - 100
    x_codo = rect_cisterna_int.x + 15
    pygame.draw.line(ventana, color_tubo, (x_izq, y_tubo), (x_codo, y_tubo), 10)
    if entrada_activa:
        pygame.draw.line(ventana, color_acento, (x_izq+2, y_tubo), (x_codo-2, y_tubo), 5)
        pygame.draw.line(ventana, color_acento, (x_codo, y_tubo-2), (x_codo, y_tubo+175), 5)
    dibujar_texto(ventana, "Entrada de agua", x_izq, y_tubo - 20, (110,110,110), fuente_peq)

def dibujar_losa_y_terreno():
    rect_losa = pygame.Rect(rect_cisterna.x, y_suelo, rect_cisterna.right - rect_cisterna.x, 14)
    pygame.draw.rect(ventana, color_hormigon, rect_losa)
    dx = rect_losa.x - 40
    while dx < rect_losa.right + 40:
        pygame.draw.line(ventana, color_hormigon_r, (dx, rect_losa.y+2), (dx-26, rect_losa.bottom-2), 1)
        dx += 12
    h = 30
    pygame.draw.rect(ventana, color_linea, (rect_cisterna.x + 20, y_suelo - h, 10, h))
    pygame.draw.rect(ventana, color_linea, (rect_cisterna.x + 20, y_suelo - h, 70, 10))
    pygame.draw.rect(ventana, color_linea, (rect_cisterna.right - 30, y_suelo - h, 10, h))
    pygame.draw.rect(ventana, color_linea, (rect_cisterna.right - 30, y_suelo - h, 70, 10))
    pygame.draw.line(ventana, (140,140,140), (100, y_suelo), (ancho_ventana-100, y_suelo), 3)

def dibujar_bomba_y_tuberias():
    x_toma = rect_cisterna_int.x + int(rect_cisterna_int.w * 0.78)
    y_linea_bomba = rect_bomba.centery
    pygame.draw.line(ventana, color_tubo, (x_toma, y_suelo), (x_toma, y_linea_bomba), 8)
    pygame.draw.line(ventana, color_tubo, (x_toma, y_linea_bomba), (rect_bomba.x, y_linea_bomba), 8)
    pygame.draw.rect(ventana, color_bomba_cuerpo, rect_bomba, border_radius=6)
    rect_cabezal = pygame.Rect(rect_bomba.right - 5, rect_bomba.centery - 15, 28, 30)
    pygame.draw.ellipse(ventana, color_bomba_cuerpo, rect_cabezal)
    pygame.draw.ellipse(ventana, color_bomba_borde, rect_cabezal, 2)
    rect_asa = pygame.Rect(rect_bomba.centerx - 15, rect_bomba.y - 10, 30, 10)
    pygame.draw.rect(ventana, color_bomba_cuerpo, rect_asa, border_radius=4)
    pygame.draw.rect(ventana, color_bomba_borde, rect_asa, 2, border_radius=4)
    dibujar_texto(ventana, "Bomba", rect_bomba.x + 8, rect_bomba.y - 24, (32,36,40), fuente_peq)
    x_salida = rect_cabezal.right
    y_salida = rect_bomba.centery
    y_altura_tanque = rect_tanque_superior.y + rect_tanque_superior.h // 2
    pygame.draw.line(ventana, color_tubo, (x_salida, y_salida), (x_salida, y_altura_tanque), 8)
    pygame.draw.line(ventana, color_tubo, (x_salida, y_altura_tanque), (rect_tanque_superior.x, y_altura_tanque), 6)
    pygame.draw.line(ventana, color_tubo, (rect_tanque_superior.x, y_altura_tanque),
                     (rect_tanque_superior.x, rect_tanque_superior.y + 24), 6)

def dibujar_controles():
    t = "[ESPACIO] bomba  [↑/↓] velocidad  [W/S] manguera  [I] entrada  [R] reset  [M] mute [V/T/X] vaciar [Q] PID [F] Panel PID  [H] Menú"
    y = rect_cisterna.bottom + 30
    w, h = fuente_peq.size(t)
    x = (ancho_ventana//2) - (w//2)
    px, py = 16, 10
    r = pygame.Rect(x-px, y-py, w+2*px, h+2*py)
    pygame.draw.rect(ventana, (235,238,245), r, border_radius=8)
    pygame.draw.rect(ventana, (180,184,192), r, 2, border_radius=8)
    dibujar_texto(ventana, t, x, y, (70,75,85), fuente_peq)

def dibujar_boton_panel(activo):
    pygame.draw.rect(ventana, color_boton_fondo, rect_boton_panel, border_radius=8)
    pygame.draw.rect(ventana, color_boton_borde, rect_boton_panel, 2, border_radius=8)
    etiqueta = "Ocultar panel" if activo else "Mostrar panel"
    dibujar_texto(ventana, etiqueta, rect_boton_panel.x + 18, rect_boton_panel.y + 10, color_boton_texto, fuente_med)

def dibujar_boton(r, txt):
    pygame.draw.rect(ventana, color_boton_fondo, r, border_radius=8)
    pygame.draw.rect(ventana, color_boton_borde, r, 2, border_radius=8)
    w,h = fuente_med.size(txt)
    dibujar_texto(ventana, txt, r.x+(r.w-w)//2, r.y+(r.h-h)//2, color_boton_texto, fuente_med)

def dibujar_panel_general(q_bomba_lps, q_entrada_lps, texto_alerta):
    if not panel_visible: return
    surf, pad, y, inner = crear_superficie_panel(rect_panel, "Panel de simulación")
    x = pad; w = inner.w
    datos_chips = [
        ("Bomba", bomba_on),
        ("Entrada", entrada_on),
        ("Protección", proteccion_seco_on),
        ("Alarma", not alarma_mute),
        ("PID", pid_enabled),
        ("Panel PID", pid_panel_visible),
    ]
    y = dibujar_chips_en_filas(surf, x, y, datos_chips, chips_por_fila=3, gap_x=10, gap_y=30)
    y = dibujar_etiqueta_valor(surf, x, y, w, "Velocidad bomba", f"{velocidad_bomba*100:5.1f}%")
    barra_h(surf, x, y, w, 10, velocidad_bomba*100); y += 18
    y = dibujar_etiqueta_valor(surf, x, y, w, "Cisterna", f"{nivel_cisterna_cm:5.1f} cm")
    barra_h(surf, x, y, w, 10, (nivel_cisterna_cm/alto_cisterna_cm)*100); y += 18
    y = dibujar_etiqueta_valor(surf, x, y, w, "Tanque sup", f"{nivel_tanque_sup_cm:5.1f} cm")
    barra_h(surf, x, y, w, 10, (nivel_tanque_sup_cm/alto_tanque_sup_cm)*100); y += 10
    y += 8
    y = dibujar_etiqueta_valor(surf, x, y, w, "Bomba",   f"{q_bomba_lps*60:5.1f} L/min")
    y = dibujar_etiqueta_valor(surf, x, y, w, "Entrada", f"{q_entrada_lps*60:5.1f} L/min")
    y += 6
    if texto_alerta:
        y = dibujar_texto_envuelto(surf, texto_alerta, x, y, w, color_panel_peligro, fuente_peq, gap=2)
    else:
        y = dibujar_texto_envuelto(surf, "Sin alertas", x, y, w, color_panel_ok, fuente_peq, gap=2)
    pegar_superficie_panel(surf, rect_panel)

def dibujar_panel_pid():
    if not pid_panel_visible: return
    surf, pad, y, inner = crear_superficie_panel(rect_pid_panel, "Panel PID")
    x = pad; w = inner.w
    chip_estado(surf, x, y, "PID", pid_enabled); y += 30
    if pid_enabled:
        y = dibujar_etiqueta_valor(surf, x, y, w, "Setpoint (SP)", f"{pid_target_cm:5.1f} cm")
        y = dibujar_etiqueta_valor(surf, x, y, w, "Proceso (PV)",  f"{nivel_tanque_sup_cm:5.1f} cm")
        e = pid_target_cm - nivel_tanque_sup_cm
        y = dibujar_etiqueta_valor(surf, x, y, w, "Error (SP-PV)", f"{e:5.1f} cm")
        y += 4
        y = dibujar_texto_envuelto(surf, f"Kp:{pid.kp:.3f}    Ki:{pid.ki:.3f}    Kd:{pid.kd:.3f}",
                              x, y, w, color_panel_texto, fuente_peq, gap=2)
        y = dibujar_etiqueta_valor(surf, x, y, w, "Salida u", f"{velocidad_bomba*100:5.1f} %")
    else:
        y = dibujar_texto_envuelto(surf, "PID desactivado (pulsa Q).", x, y, w, (110,110,110), fuente_peq)
    pegar_superficie_panel(surf, rect_pid_panel)

def dibujar_banner_alerta(texto,t):
    fase=(math.sin(t*8)+1)/2; alpha=int(80+120*fase)
    surf=pygame.Surface((ancho_ventana,38),pygame.SRCALPHA)
    pygame.draw.rect(surf,(255,40,40,alpha),surf.get_rect()); ventana.blit(surf,(0,0))
    dibujar_texto(ventana,texto,16,10,(255,255,255),fuente_med)

def dibujar_banner_pid(texto,t,offset_y=40):
    fase=(math.sin(t*6)+1)/2; alpha=int(60+110*fase)
    surf=pygame.Surface((ancho_ventana,30),pygame.SRCALPHA)
    pygame.draw.rect(surf,(68,134,255,alpha),surf.get_rect()); ventana.blit(surf,(0,offset_y))
    dibujar_texto(ventana,texto,16,offset_y+6,(255,255,255),fuente_peq)

def dibujar_menu():
    if not menu_visible: return
    sombra_rect(ventana, rect_menu, 5, 5, 5)
    pygame.draw.rect(ventana, (255,255,255), rect_menu, border_radius=12)
    pygame.draw.rect(ventana, (206,210,220), rect_menu, 6, border_radius=12)
    dibujar_texto(ventana, "Menú de reportes", rect_menu.x+16, rect_menu.y+14, (35,38,45), fuente_titulo)

    def _dibujar_boton(rr, label):
        pygame.draw.rect(ventana, color_boton_fondo, rr, border_radius=8)
        pygame.draw.rect(ventana, color_boton_borde, rr, 2, border_radius=8)
        w,h = fuente_med.size(label)
        dibujar_texto(ventana, label, rr.x + (rr.w - w)//2, rr.y + (rr.h - h)//2, color_boton_texto, fuente_med)

    _dibujar_boton(rect_menu_rep,   "Reporte inmediato")
    _dibujar_boton(rect_menu_csv,   "CSV instantáneo")
    _dibujar_boton(rect_menu_png,   "Captura PNG")
    _dibujar_boton(rect_menu_short, "Resumen corto")

ejecutando = True
tiempo_total = 0
while ejecutando:
    dt = reloj.tick(60)/1000
    tiempo_total += dt
    parpadeo_t += dt
    dt_fisica = dt * factor_tiempo_simulacion

    ahora_real = datetime.now()
    if _hora_ultimo_frame is None:
        dt_real_frame = 0
    else:
        dt_real_frame = (ahora_real - _hora_ultimo_frame).total_seconds()
    _hora_ultimo_frame = ahora_real

    for e in pygame.event.get():
        if e.type == pygame.QUIT:
            ejecutando = False

        elif e.type == pygame.KEYDOWN:
            if e.key == pygame.K_SPACE: bomba_on = not bomba_on
            elif e.key == pygame.K_i:   entrada_on = not entrada_on
            elif e.key == pygame.K_p:   proteccion_seco_on = not proteccion_seco_on
            elif e.key == pygame.K_m:   alarma_mute = not alarma_mute
            elif e.key in (pygame.K_PLUS, pygame.K_EQUALS):
                alarma_vol = limitar(alarma_vol+0.1, 0, 1)
                if 'sonido_beep' in locals() and sonido_beep: sonido_beep.set_volume(alarma_vol)
            elif e.key == pygame.K_MINUS:
                alarma_vol = limitar(alarma_vol-0.1, 0, 1)
                if 'sonido_beep' in locals() and sonido_beep: sonido_beep.set_volume(alarma_vol)
            elif e.key == pygame.K_v: nivel_cisterna_cm = 0
            elif e.key == pygame.K_t: nivel_tanque_sup_cm = 0
            elif e.key == pygame.K_x: nivel_cisterna_cm = 0; nivel_tanque_sup_cm = 0
            elif e.key == pygame.K_q: pid_enabled = not pid_enabled; pid.reset()
            elif e.key == pygame.K_LEFTBRACKET:  pid_target_cm = limitar(pid_target_cm-5, 0, alto_tanque_sup_cm)
            elif e.key == pygame.K_RIGHTBRACKET: pid_target_cm = limitar(pid_target_cm+5, 0, alto_tanque_sup_cm)
            elif e.key == pygame.K_1: pid.set_gains(kp=pid.kp-0.01)
            elif e.key == pygame.K_2: pid.set_gains(kp=pid.kp+0.01)
            elif e.key == pygame.K_3: pid.set_gains(ki=pid.ki-0.005)
            elif e.key == pygame.K_4: pid.set_gains(ki=pid.ki+0.005)
            elif e.key == pygame.K_5: pid.set_gains(kd=pid.kd-0.01)
            elif e.key == pygame.K_6: pid.set_gains(kd=pid.kd+0.01)
            elif e.key == pygame.K_f: pid_panel_visible = not pid_panel_visible
            elif e.key == pygame.K_a: allow_pid_auto_start = not allow_pid_auto_start
            elif e.key == pygame.K_h: menu_visible = not menu_visible
            elif e.key == pygame.K_r:
                nivel_cisterna_cm, nivel_tanque_sup_cm = 140, 30
                altura_boca_manguera_cm = 120
                bomba_on = True; velocidad_bomba = 0.6; entrada_on = False
                pid_enabled = False; pid_panel_visible = True; panel_visible = True
                auto_llenado_activo = False; entrada_forzada_por_pid = False
                allow_pid_auto_start = True
                menu_visible = False
                pid.reset()

        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if rect_boton_panel.collidepoint(e.pos): panel_visible = not panel_visible
            elif rect_btn_vac_cis.collidepoint(e.pos): nivel_cisterna_cm = 0
            elif rect_btn_vac_sup.collidepoint(e.pos): nivel_tanque_sup_cm = 0
            elif rect_btn_pid_panel.collidepoint(e.pos): pid_panel_visible = not pid_panel_visible
            elif rect_boton_menu.collidepoint(e.pos): menu_visible = not menu_visible
            elif menu_visible and rect_menu and rect_menu.collidepoint(e.pos):
                if rect_menu_rep.collidepoint(e.pos):
                    accion_enviar_reporte_ahora()
                elif rect_menu_csv.collidepoint(e.pos):
                    accion_enviar_csv_ahora()
                elif rect_menu_png.collidepoint(e.pos):
                    accion_enviar_png_ahora()
                elif rect_menu_short.collidepoint(e.pos):
                    accion_enviar_resumen_ahora()

    teclas = pygame.key.get_pressed()
    if not pid_enabled:
        if teclas[pygame.K_UP]:   velocidad_bomba += 0.7*dt
        if teclas[pygame.K_DOWN]: velocidad_bomba -= 0.7*dt
    if teclas[pygame.K_w]: altura_boca_manguera_cm += 45*dt
    if teclas[pygame.K_s]: altura_boca_manguera_cm -= 45*dt

    li = distancia_suelo_segura_cm
    ls = max(li, nivel_cisterna_cm - distancia_superficie_segura_cm)
    altura_boca_manguera_cm = limitar(altura_boca_manguera_cm, li, ls)
    velocidad_bomba = limitar(velocidad_bomba, 0, 1)

    entrada_lps = caudal_entrada_lps_activo if entrada_on else 0
    boca_sumergida  = nivel_cisterna_cm > (altura_boca_manguera_cm + 2)
    factor_sumergida= 1 if boca_sumergida else 0.05
    elevacion_base_tanque_cm = 250
    altura_entrega_cm = elevacion_base_tanque_cm + nivel_tanque_sup_cm - altura_boca_manguera_cm
    if altura_entrega_cm < 0: altura_entrega_cm = 0
    factor_presion = 1 - (altura_entrega_cm/400)
    factor_presion = limitar(factor_presion, 0.3, 1)

    sin_agua_cis = (nivel_cisterna_cm <= umbral_sin_agua_cm)
    sin_agua_sup = (nivel_tanque_sup_cm <= umbral_sin_agua_cm)

    if pid_enabled:
        if sin_agua_cis and not auto_llenado_activo:
            auto_llenado_activo = True
            entrada_forzada_por_pid = True
        if auto_llenado_activo:
            entrada_on = True
            velocidad_bomba = 0
            if nivel_cisterna_cm >= umbral_auto_off:
                auto_llenado_activo = False
                if entrada_forzada_por_pid:
                    entrada_on = False
                    entrada_forzada_por_pid = False
                if allow_pid_auto_start and (nivel_cisterna_cm > altura_boca_manguera_cm + 2):
                    bomba_on = True
        else:
            if not bomba_on:
                if allow_pid_auto_start and (nivel_cisterna_cm > altura_boca_manguera_cm + 2):
                    bomba_on = True
            if bomba_on:
                u_pid = pid.step(pid_target_cm, nivel_tanque_sup_cm, dt_fisica)
                velocidad_bomba = limitar(u_pid, 0, 1)

    caudal_bomba_lps = (velocidad_bomba if bomba_on else 0) * caudal_bomba_max_lps * factor_sumergida * factor_presion

    delta_vol_cis_cm3 = (entrada_lps - caudal_bomba_lps) * 1000 * dt_fisica
    nivel_cisterna_cm = limitar(nivel_cisterna_cm + delta_vol_cis_cm3/area_cisterna_cm2, 0, alto_cisterna_cm)

    delta_vol_sup_cm3 = (caudal_bomba_lps - consumo_tanque_sup_lps) * 1000 * dt_fisica
    nivel_tanque_sup_cm = limitar(nivel_tanque_sup_cm + delta_vol_sup_cm3/area_tanque_sup_cm2, 0, alto_tanque_sup_cm)

    if metricas["min_cis_cm"] is None or nivel_cisterna_cm < metricas["min_cis_cm"]:
        metricas["min_cis_cm"] = round(nivel_cisterna_cm, 2)
    if metricas["max_cis_cm"] is None or nivel_cisterna_cm > metricas["max_cis_cm"]:
        metricas["max_cis_cm"] = round(nivel_cisterna_cm, 2)
    if metricas["min_sup_cm"] is None or nivel_tanque_sup_cm < metricas["min_sup_cm"]:
        metricas["min_sup_cm"] = round(nivel_tanque_sup_cm, 2)
    if metricas["max_sup_cm"] is None or nivel_tanque_sup_cm > metricas["max_sup_cm"]:
        metricas["max_sup_cm"] = round(nivel_tanque_sup_cm, 2)

    if bomba_on and not _prev_bomba_encendida:
        metricas["eventos_encendido_bomba"] += 1
    _prev_bomba_encendida = bomba_on
    if bomba_on and dt_real_frame > 0:
        metricas["seg_bomba_encendida"] += dt_real_frame

    if dt_fisica > 0:
        metricas["litros_bombeados"]   += max(caudal_bomba_lps, 0) * dt_fisica
        metricas["litros_entrada"]     += max(entrada_lps, 0) * dt_fisica
        metricas["litros_consumidos"]  += max(consumo_tanque_sup_lps, 0) * dt_fisica

    texto_alerta = ""
    if sin_agua_cis:
        texto_alerta = "CRÍTICO: Cisterna sin agua"
    elif sin_agua_sup:
        texto_alerta = "Alerta: Tanque superior sin agua"

    disparo_seco = False
    if (not boca_sumergida) and bomba_on:
        if texto_alerta == "":
            texto_alerta = "PELIGRO: succión de aire"
        if proteccion_seco_on:
            bomba_on = False
            disparo_seco = True

    alerta_activa = (texto_alerta != "")
    if alerta_activa and not _prev_alerta_activa:
        metricas["alertas"] += 1
    _prev_alerta_activa = alerta_activa
    if disparo_seco:
        metricas["protecciones_en_seco"] += 1

    quiere_alarma = (texto_alerta != "") and (not alarma_mute)
    if sonido_beep and canal_alarma:
        if quiere_alarma:
            if not canal_alarma.get_busy():
                canal_alarma.play(sonido_beep, loops=-1)
        else:
            if canal_alarma.get_busy():
                canal_alarma.stop()

    msg_pid = ""
    if pid_enabled:
        if auto_llenado_activo:
            msg_pid = "PID corrigiendo: auto-llenando cisterna"
        elif not bomba_on:
            msg_pid = "PID en espera: bomba apagada"
        elif sin_agua_sup:
            msg_pid = "PID corrigiendo: recuperando tanque superior"
        if dt_real_frame > 0:
            metricas["seg_pid_activo"] += dt_real_frame
            if auto_llenado_activo:
                metricas["seg_pid_auto_llenado"] += dt_real_frame

    notificar_alerta(texto_alerta, msg_pid)

    ventana.fill(color_fondo)
    dibujar_tanque_superior(nivel_tanque_sup_cm, tiempo_total)
    dibujar_bomba_y_tuberias()
    dibujar_cisterna(nivel_cisterna_cm, altura_boca_manguera_cm, tiempo_total, entrada_on)
    dibujar_losa_y_terreno()
    dibujar_controles()

    dibujar_boton(rect_boton_menu, "Menú")
    dibujar_boton(rect_btn_pid_panel, "Panel PID")
    dibujar_boton(rect_btn_vac_sup, "Vaciar tanque")
    dibujar_boton(rect_btn_vac_cis, "Vaciar cisterna")
    dibujar_boton_panel(panel_visible)

    dibujar_panel_general(caudal_bomba_lps, entrada_lps, texto_alerta)
    dibujar_panel_pid()
    dibujar_menu()

    if texto_alerta:
        dibujar_banner_alerta(texto_alerta, parpadeo_t)
        if msg_pid:
            dibujar_banner_pid(msg_pid, parpadeo_t, offset_y=40)
    else:
        if msg_pid:
            dibujar_banner_pid(msg_pid, parpadeo_t, offset_y=10)

    ahora = datetime.now()
    hoy = ahora.date()
    if ahora.hour == HORA_REPORTE_DIARIO and (_fecha_ultimo_reporte != hoy):
        texto_reporte = crear_texto_reporte_diario(hoy)
        tg.send_message(texto_reporte)
        if CREAR_ARCHIVOS_REPORTE:
            try:
                ruta_csv = escribir_csv_diario(hoy)
                tg.send_document(ruta_csv, caption="📄 CSV del reporte diario")
            except Exception:
                pass
        if ENVIAR_CAPTURAS:
            try:
                ruta_snap = os.path.join(os.path.dirname(__file__), f"reporte_{hoy.strftime('%Y%m%d')}.png")
                pygame.image.save(ventana, ruta_snap)
                tg.send_photo(ruta_snap, caption="🖼 Captura del estado al cierre")
            except Exception:
                pass
        _fecha_ultimo_reporte = hoy
        reiniciar_metricas_diarias()

    pygame.display.flip()

try:
    if canal_alarma and canal_alarma.get_busy(): canal_alarma.stop()
except: pass
pygame.quit()
try:
    if os.path.exists(ruta_beep): os.remove(ruta_beep)
except: pass
