import serial
import struct
import time
import threading
import tkinter as tk

# ==============================================================================
# CONFIGURACIÓN DE CALIBRACIÓN Y PUERTO
# ==============================================================================
PUERTO = '/dev/ttyUSB0'
BAUDRATE = 9600
VENTANA_MEDICION = 0.5        # Segundos de captura tras detectar el primer haz

ALTURA_INICIAL_CM = 3.0       # Ajuste de inicio de lectura 0
SEPARACION_HACES_CM = 1.0

# Haces que mantienes tapados fijos para activar la lectura de la cortina
HACES_IGNORADOS = {31, 32}

# Número del primer haz libre que debe activarse para iniciar la medición
HAZ_DISPARO = 1
# ==============================================================================


def decodificar_haces_validos(trama: bytes) -> list:
    """Lee los haces bloqueados (bit en 1) y descarta los haces fijos."""
    b0, b1, b2, b3, b4, b5, d0, d1, d2, d3 = struct.unpack('10B', trama)

    if d0 == 0xFF and d1 == 0xFF and d2 == 0xFF and d3 == 0xFF:
        return []

    haces_detectados = []
    bytes_datos = (d0, d1, d2, d3)

    for idx_byte, byte_val in enumerate(bytes_datos):
        for bit in range(7, -1, -1):
            num_haz = (idx_byte * 8) + (7 - bit) + 1
            if ((byte_val >> bit) & 1) == 1:
                if num_haz not in HACES_IGNORADOS:
                    haces_detectados.append(num_haz)

    return sorted(haces_detectados)


class InterfazCortinaHMI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Clasificación Manual - Lectura de Grado")
        self.root.configure(bg="#111827")

        # Pantalla completa para HMI táctil (Esc sale de pantalla completa)
        self.root.attributes("-fullscreen", True)
        self.root.bind("<Escape>", lambda e: self.root.attributes("-fullscreen", False))

        # --- Estado de conexión y proceso ---
        self.ejecutando = True
        self.estado_conexion = f"● Conectando a {PUERTO}..."
        self.color_conexion = "#F59E0B"

        self.estado_medicion = "ESPERANDO MUESTRA..."
        self.color_estado = "#38BDF8"

        # ======================================================================
        # VARIABLES DE LOS 3 CAMPOS EN PANTALLA (Conectar aquí tus datos)
        # ======================================================================
        self.valor_cabeza = "-- mm"       # <-- AQUÍ PONES TU VARIABLE DE CABEZA
        self.valor_tallo = "---.- cm"     # <-- SE ACTUALIZA CON LA CORTINA
        self.valor_grado = "--"           # <-- AQUÍ PONES TU VARIABLE DE GRADO

        self.color_tallo = "#F9FAFB"
        self.borde_tallo = "#38BDF8"
        self.detalle_haces = f"Base: {ALTURA_INICIAL_CM:.1f} cm  |  Haz disparo: #{HAZ_DISPARO}"

        self._construir_ui()

        # Iniciar lectura serial en segundo plano
        self.hilo_serial = threading.Thread(target=self._bucle_serial, daemon=True)
        self.hilo_serial.start()

        # Refrescar pantalla cada 30 ms
        self._actualizar_pantalla()

    def _construir_ui(self):
        # --- Barra superior ---
        frame_top = tk.Frame(self.root, bg="#1F2937", height=62)
        frame_top.pack(fill="x", side="top")
        frame_top.pack_propagate(False)

        self.lbl_conexion = tk.Label(
            frame_top,
            text=self.estado_conexion,
            font=("Helvetica", 14, "bold"),
            fg=self.color_conexion,
            bg="#1F2937",
            padx=20
        )
        self.lbl_conexion.pack(side="left", fill="y")

        self.lbl_estado = tk.Label(
            frame_top,
            text=self.estado_medicion,
            font=("Helvetica", 18, "bold"),
            fg=self.color_estado,
            bg="#1F2937"
        )
        self.lbl_estado.pack(side="left", expand=True)

        btn_salir = tk.Button(
            frame_top,
            text="SALIR",
            font=("Helvetica", 13, "bold"),
            bg="#DC2626",
            fg="white",
            activebackground="#991B1B",
            activeforeground="white",
            bd=0,
            padx=22,
            command=self.cerrar
        )
        btn_salir.pack(side="right", fill="y", padx=10, pady=8)

        # --- Barra inferior de diagnóstico ---
        frame_bottom = tk.Frame(self.root, bg="#1F2937", height=44)
        frame_bottom.pack(fill="x", side="bottom")
        frame_bottom.pack_propagate(False)

        self.lbl_detalle = tk.Label(
            frame_bottom,
            text=self.detalle_haces,
            font=("Helvetica", 14),
            fg="#9CA3AF",
            bg="#1F2937"
        )
        self.lbl_detalle.pack(expand=True)

        # --- Cuerpo principal (Izquierda = Datos, Derecha = Rosa) ---
        frame_main = tk.Frame(self.root, bg="#111827", padx=32, pady=22)
        frame_main.pack(expand=True, fill="both")

        frame_main.columnconfigure(0, weight=6)  # Columna izquierda: 3 datos
        frame_main.columnconfigure(1, weight=4)  # Columna derecha: dibujo rosa
        frame_main.rowconfigure(0, weight=1)

        # 1. Panel izquierdo: 3 bloques apilados (Cabeza, Tallo, GRADO)
        frame_izq = tk.Frame(frame_main, bg="#111827")
        frame_izq.grid(row=0, column=0, sticky="nsew", padx=(0, 24))
        frame_izq.columnconfigure(0, weight=1)
        frame_izq.rowconfigure(0, weight=1)
        frame_izq.rowconfigure(1, weight=1)
        frame_izq.rowconfigure(2, weight=2)  # Mayor espacio vertical para GRADO

        # Bloque 1: Cabeza
        self.card_cabeza, self.lbl_val_cabeza = self._crear_tarjeta(
            parent=frame_izq,
            fila=0,
            titulo="Cabeza",
            valor_inicial=self.valor_cabeza,
            color_titulo="#D1D5DB",
            color_valor="#F9FAFB",
            tamano_titulo=26,
            tamano_valor=42,
            borde="#374151"
        )

        # Bloque 2: Tallo (Dato en vivo de la cortina)
        self.card_tallo, self.lbl_val_tallo = self._crear_tarjeta(
            parent=frame_izq,
            fila=1,
            titulo="Tallo",
            valor_inicial=self.valor_tallo,
            color_titulo="#38BDF8",
            color_valor=self.color_tallo,
            tamano_titulo=28,
            tamano_valor=56,
            borde=self.borde_tallo
        )

        # Bloque 3: GRADO (Más grande y color llamativo)
        self.card_grado, self.lbl_val_grado = self._crear_tarjeta(
            parent=frame_izq,
            fila=2,
            titulo="GRADO",
            valor_inicial=self.valor_grado,
            color_titulo="#FACC15",      # Amarillo dorado brillante
            color_valor="#FACC15",       # Amarillo dorado brillante
            tamano_titulo=36,
            tamano_valor=86,
            borde="#F59E0B",
            fondo="#1E293B"
        )

        # 2. Panel derecho: Dibujo minimalista de la rosa
        frame_der = tk.Frame(frame_main, bg="#111827")
        frame_der.grid(row=0, column=1, sticky="nsew")

        self.canvas_rosa = tk.Canvas(
            frame_der,
            width=300,
            height=490,
            bg="#111827",
            highlightthickness=0
        )
        self.canvas_rosa.pack(expand=True)
        self._dibujar_rosa_minimalista()

    def _crear_tarjeta(
        self,
        parent,
        fila,
        titulo,
        valor_inicial,
        color_titulo,
        color_valor,
        tamano_titulo,
        tamano_valor,
        borde="#374151",
        fondo="#1F2937"
    ):
        card = tk.Frame(
            parent,
            bg=fondo,
            highlightbackground=borde,
            highlightthickness=2,
            padx=28,
            pady=12
        )
        card.grid(row=fila, column=0, sticky="nsew", pady=9)

        lbl_titulo = tk.Label(
            card,
            text=titulo,
            font=("Helvetica", tamano_titulo, "bold"),
            fg=color_titulo,
            bg=fondo,
            anchor="w"
        )
        lbl_titulo.pack(side="left", fill="y")

        lbl_valor = tk.Label(
            card,
            text=valor_inicial,
            font=("Helvetica", tamano_valor, "bold"),
            fg=color_valor,
            bg=fondo,
            anchor="e"
        )
        lbl_valor.pack(side="right", fill="y", expand=True)

        return card, lbl_valor

    def _dibujar_rosa_minimalista(self):
        """Dibuja una rosa estilo line-art con manchas tipo acuarela."""
        c = self.canvas_rosa
        cx = 150

        # --- 1. Manchas tipo acuarela (Verde: tallo y hoja derecha) ---
        # Mancha vertical del tallo
        c.create_polygon(
            cx - 7, 165,
            cx + 8, 168,
            cx + 6, 260,
            cx + 10, 355,
            cx + 7, 452,
            cx - 8, 455,
            cx - 11, 350,
            cx - 6, 255,
            fill="#059669", outline="", smooth=True
        )
        c.create_polygon(
            cx - 4, 175,
            cx + 5, 175,
            cx + 4, 445,
            cx - 5, 442,
            fill="#10B981", outline="", smooth=True
        )

        # Mancha de la hoja derecha
        c.create_polygon(
            cx + 2, 238,
            cx + 32, 204,
            cx + 68, 196,
            cx + 56, 232,
            cx + 22, 248,
            fill="#10B981", outline="", smooth=True
        )

        # --- 2. Manchas tipo acuarela (Rosa coral: botón de la flor) ---
        c.create_polygon(
            cx - 48, 72,
            cx - 10, 48,
            cx + 44, 58,
            cx + 58, 108,
            cx + 35, 158,
            cx - 26, 162,
            cx - 54, 120,
            fill="#E11D48", outline="", smooth=True
        )
        c.create_polygon(
            cx - 38, 64,
            cx + 22, 54,
            cx + 48, 96,
            cx + 20, 148,
            cx - 36, 142,
            fill="#FB7185", outline="", smooth=True
        )

        # --- 3. Trazo continuo minimalista (Line-Art) ---
        color_trazo = "#F9FAFB"
        grosor = 3.0

        # Espiral central y pétalos envolventes
        trazo_flor = [
            cx + 2, 92,
            cx + 12, 86,
            cx + 16, 98,
            cx + 4, 108,
            cx - 14, 102,
            cx - 16, 82,
            cx + 6, 72,
            cx + 28, 84,
            cx + 26, 114,
            cx - 4, 126,
            cx - 34, 112,
            cx - 36, 76,
            cx - 6, 56,
            cx + 36, 66,
            cx + 48, 104,
            cx + 22, 138,
            cx - 24, 146,
            cx - 48, 114,
            cx - 42, 82,
            cx - 16, 118,
            cx + 24, 124,
            cx + 42, 96,
            cx + 14, 152,
            cx, 164
        ]
        c.create_line(trazo_flor, fill=color_trazo, width=grosor, smooth=True, capstyle=tk.ROUND)

        # Tallo superior + contorno hoja derecha + tallo inferior
        trazo_tallo_hoja = [
            cx, 164,
            cx, 244,
            cx + 26, 238,
            cx + 58, 202,
            cx + 24, 212,
            cx, 244,
            cx, 444
        ]
        c.create_line(
            trazo_tallo_hoja,
            fill=color_trazo,
            width=grosor,
            smooth=False,
            capstyle=tk.ROUND,
            joinstyle=tk.ROUND
        )

        # Nervadura suave dentro de la hoja
        c.create_line(
            cx + 3, 241, cx + 44, 211,
            fill=color_trazo, width=2.0, capstyle=tk.ROUND
        )

    def _actualizar_pantalla(self):
        if not self.ejecutando:
            return

        self.lbl_conexion.config(text=self.estado_conexion, fg=self.color_conexion)
        self.lbl_estado.config(text=self.estado_medicion, fg=self.color_estado)
        self.lbl_detalle.config(text=self.detalle_haces)

        # Actualizar los 3 valores en sus bloques
        self.lbl_val_cabeza.config(text=self.valor_cabeza)
        self.lbl_val_tallo.config(text=self.valor_tallo, fg=self.color_tallo)
        self.lbl_val_grado.config(text=self.valor_grado)
        self.card_tallo.config(highlightbackground=self.borde_tallo)

        self.root.after(30, self._actualizar_pantalla)

    def _calcular_cm(self, haz_maximo: int) -> float:
        return ALTURA_INICIAL_CM + ((haz_maximo - HAZ_DISPARO + 1) * SEPARACION_HACES_CM)

    def _bucle_serial(self):
        buffer = bytearray()
        midiendo = False
        tiempo_inicio = 0.0
        haces_acumulados = set()

        while self.ejecutando:
            try:
                with serial.Serial(
                    port=PUERTO,
                    baudrate=BAUDRATE,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=0.1
                ) as ser:
                    self.estado_conexion = f"● CONECTADO ({PUERTO})"
                    self.color_conexion = "#10B981"

                    while self.ejecutando:
                        datos = ser.read(ser.in_waiting or 1)
                        if datos:
                            buffer.extend(datos)

                        while len(buffer) >= 10:
                            if buffer[0] != 0xC0:
                                buffer.pop(0)
                                continue

                            trama = bytes(buffer[:10])
                            b0, b1, b2, b3, b4, b5, d0, d1, d2, d3 = struct.unpack('10B', trama)

                            if b4 == 0x22 and b5 == 0x0A:
                                del buffer[:10]
                                bloqueados = decodificar_haces_validos(trama)
                                ahora = time.time()

                                # 1. Inicio inmediato de medición
                                if not midiendo and (HAZ_DISPARO in bloqueados):
                                    midiendo = True
                                    tiempo_inicio = ahora
                                    haces_acumulados.clear()
                                    haces_acumulados.update(bloqueados)

                                    haz_max = max(haces_acumulados)
                                    medida_actual = self._calcular_cm(haz_max)

                                    self.estado_medicion = "MIDIENDO (2.0 s)..."
                                    self.color_estado = "#F59E0B"
                                    self.valor_tallo = f"{medida_actual:.1f} cm"
                                    self.color_tallo = "#FBBF24"
                                    self.borde_tallo = "#F59E0B"
                                    self.detalle_haces = f"Haz máximo actual: #{haz_max}  |  Haces activos: {len(haces_acumulados)}"

                                # 2. Actualización en vivo durante la ventana de 2 segundos
                                elif midiendo:
                                    if bloqueados:
                                        haces_acumulados.update(bloqueados)
                                        haz_max = max(haces_acumulados)
                                        medida_actual = self._calcular_cm(haz_max)

                                        self.valor_tallo = f"{medida_actual:.1f} cm"
                                        self.detalle_haces = f"Haz máximo actual: #{haz_max}  |  Haces activos: {len(haces_acumulados)}"

                                    # 3. Fin de la ventana: fijar resultado final en pantalla
                                    if (ahora - tiempo_inicio) >= VENTANA_MEDICION:
                                        haz_maximo = max(haces_acumulados)
                                        medida_total_cm = self._calcular_cm(haz_maximo)

                                        self.estado_medicion = "MEDIDA REGISTRADA"
                                        self.color_estado = "#10B981"
                                        self.valor_tallo = f"{medida_total_cm:.1f} cm"
                                        self.color_tallo = "#34D399"
                                        self.borde_tallo = "#10B981"
                                        self.detalle_haces = (
                                            f"Última lectura -> Haz máx: #{haz_maximo}  |  "
                                            f"Haces detectados: {len(haces_acumulados)}"
                                        )

                                        midiendo = False
                                        haces_acumulados.clear()
                            else:
                                buffer.pop(0)

            except serial.SerialException:
                self.estado_conexion = f"● SIN CONEXIÓN EN {PUERTO} (Reintentando...)"
                self.color_conexion = "#EF4444"
                self.borde_tallo = "#38BDF8"
                midiendo = False
                buffer.clear()
                time.sleep(2.0)

    def cerrar(self):
        self.ejecutando = False
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    app = InterfazCortinaHMI(root)
    root.mainloop()
