import serial
import struct
import time
import threading
import tkinter as tk

# ==============================================================================
# CONFIGURACIÓN DE CALIBRACIÓN, CONSTANTES Y PUERTO
# ==============================================================================
PUERTO = '/dev/ttyUSB0'
BAUDRATE = 9600
VENTANA_ESTABILIZACION = 0.12   # Segundos sin nuevos haces para fijar la medida (120 ms)

ALTURA_INICIAL_CM = 3.0         # Ajuste de inicio de lectura 0
SEPARACION_HACES_CM = 1.0

# Haces que mantienes tapados fijos para activar la lectura de la cortina
HACES_IGNORADOS = {31, 32}

# Número del primer haz libre que debe activarse para iniciar la medición
HAZ_DISPARO = 1

# Constante fija para el tamaño de cabeza
CABEZA_CONSTANTE = 40
# ==============================================================================


def calcular_grado(cabeza: int, tallo: float) -> str:
    """
    Evalúa el grado al finalizar la medición del tallo (rango de 30 cm a 1 cm, cada 2 cm).
    """
    if cabeza != 40 or tallo < 1:
        return "SIN GRADO"

    if tallo >= 30:
        return "G1"
    elif tallo >= 28:
        return "G2"
    elif tallo >= 26:
        return "G3"
    elif tallo >= 24:
        return "G4"
    elif tallo >= 22:
        return "G5"
    elif tallo >= 20:
        return "G6"
    elif tallo >= 18:
        return "G7"
    elif tallo >= 16:
        return "G8"
    elif tallo >= 14:
        return "G9"
    elif tallo >= 12:
        return "G10"
    elif tallo >= 10:
        return "G11"
    elif tallo >= 8:
        return "G12"
    elif tallo >= 6:
        return "G13"
    elif tallo >= 4:
        return "G14"
    elif tallo >= 2:
        return "G15"
    else:
        return "G16"


def decodificar_haces_validos(trama: bytes) -> list:
    """Lee los haces bloqueados (bit en 1) y descarta los haces fijos."""
    _, _, _, _, _, _, d0, d1, d2, d3 = struct.unpack('10B', trama)

    if d0 == 0xFF and d1 == 0xFF and d2 == 0xFF and d3 == 0xFF:
        return []

    haces_detectados = []
    bytes_datos = (d0, d1, d2, d3)

    for idx_byte, byte_val in enumerate(bytes_datos):
        if byte_val == 0:
            continue
        for bit in range(7, -1, -1):
            if (byte_val >> bit) & 1:
                num_haz = (idx_byte * 8) + (7 - bit) + 1
                if num_haz not in HACES_IGNORADOS:
                    haces_detectados.append(num_haz)

    return haces_detectados


class InterfazCortinaHMI:
    def _init_(self, root: tk.Tk):
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

        # --- Variables de los 3 campos en pantalla ---
        self.valor_cabeza = f"{CABEZA_CONSTANTE} mm"
        self.valor_tallo = "---.- cm"
        self.valor_grado = "--"

        self.color_tallo = "#F9FAFB"
        self.borde_tallo = "#38BDF8"
        self.color_grado = "#6B7280"
        self.borde_grado = "#374151"

        self.detalle_haces = (
            f"Base: {ALTURA_INICIAL_CM:.1f} cm  |  "
            f"Haz disparo: #{HAZ_DISPARO}  |  Cabeza fija: {CABEZA_CONSTANTE} mm"
        )

        # Caché para evitar redibujos innecesarios en Tkinter
        self._cache_ui = {}

        self._construir_ui()

        # Iniciar lectura serial en segundo plano
        self.hilo_serial = threading.Thread(target=self._bucle_serial, daemon=True)
        self.hilo_serial.start()

        # Refrescar pantalla cada 40 ms (25 FPS estables sin saturar X11)
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

        frame_main.columnconfigure(0, weight=6)
        frame_main.columnconfigure(1, weight=4)
        frame_main.rowconfigure(0, weight=1)

        # 1. Panel izquierdo: 3 bloques apilados (Cabeza, Tallo, GRADO)
        frame_izq = tk.Frame(frame_main, bg="#111827")
        frame_izq.grid(row=0, column=0, sticky="nsew", padx=(0, 24))
        frame_izq.columnconfigure(0, weight=1)
        frame_izq.rowconfigure(0, weight=1)
        frame_izq.rowconfigure(1, weight=1)
        frame_izq.rowconfigure(2, weight=2)

        # Bloque 1: Cabeza (constante 40)
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

        # Bloque 2: Tallo (dato de la cortina)
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

        # Bloque 3: GRADO (aparece al estabilizar el tallo)
        self.card_grado, self.lbl_val_grado = self._crear_tarjeta(
            parent=frame_izq,
            fila=2,
            titulo="GRADO",
            valor_inicial=self.valor_grado,
            color_titulo="#FACC15",
            color_valor=self.color_grado,
            tamano_titulo=36,
            tamano_valor=88,
            borde=self.borde_grado,
            fondo="#1E293B"
        )

        # 2. Panel derecho: Dibujo vertical a color de la rosa
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
        self._dibujar_rosa_vertical()

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
        # Evita que el cambio de texto recalcule el tamaño de toda la pantalla
        card.pack_propagate(False)

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

    def _dibujar_rosa_vertical(self):
        c = self.canvas_rosa
        x_tallo = 150
        y_inicio_tallo = 156
        y_fin_tallo = 452

        # 1. Tallo
        c.create_line(
            x_tallo, y_inicio_tallo, x_tallo, y_fin_tallo,
            fill="#10B981", width=9, capstyle=tk.ROUND
        )
        c.create_line(
            x_tallo + 2, y_inicio_tallo + 4, x_tallo + 2, y_fin_tallo - 2,
            fill="#059669", width=3, capstyle=tk.ROUND
        )

        # 2. Espinas
        c.create_polygon(
            x_tallo - 4, 228, x_tallo - 16, 222, x_tallo - 4, 238,
            fill="#059669", outline=""
        )
        c.create_polygon(
            x_tallo + 4, 375, x_tallo + 16, 369, x_tallo + 4, 385,
            fill="#059669", outline=""
        )

        # 3. Hoja izquierda
        c.create_line(x_tallo - 3, 276, x_tallo - 34, 258, fill="#059669", width=4)
        c.create_polygon(
            x_tallo - 30, 260,
            x_tallo - 62, 232,
            x_tallo - 98, 244,
            x_tallo - 72, 274,
            fill="#10B981", outline="#059669", width=2, smooth=True
        )
        c.create_line(x_tallo - 34, 258, x_tallo - 86, 247, fill="#34D399", width=2)

        # 4. Hoja derecha
        c.create_line(x_tallo + 3, 326, x_tallo + 34, 308, fill="#059669", width=4)
        c.create_polygon(
            x_tallo + 30, 310,
            x_tallo + 62, 282,
            x_tallo + 98, 294,
            x_tallo + 72, 324,
            fill="#10B981", outline="#059669", width=2, smooth=True
        )
        c.create_line(x_tallo + 34, 308, x_tallo + 86, 297, fill="#34D399", width=2)

        # 5. Cabeza de la rosa
        c.create_polygon(
            x_tallo - 30, 74, x_tallo - 14, 58, x_tallo + 14, 58,
            x_tallo + 30, 74, x_tallo + 24, 96, x_tallo - 24, 96,
            fill="#9F1239", outline="#881337", width=2, smooth=True
        )
        c.create_polygon(
            x_tallo - 26, 72, x_tallo - 8, 60, x_tallo + 24, 66,
            x_tallo + 14, 78, x_tallo - 18, 78,
            fill="#FDA4AF", outline="#BE123C", width=1.8, smooth=True
        )
        c.create_polygon(
            x_tallo - 18, 72, x_tallo, 66, x_tallo + 20, 74,
            x_tallo + 10, 86, x_tallo - 14, 84,
            fill="#FB7185", outline="#BE123C", width=1.8, smooth=True
        )
        c.create_polygon(
            x_tallo - 34, 76, x_tallo - 36, 118, x_tallo - 22, 150,
            x_tallo, 156, x_tallo + 22, 150, x_tallo + 36, 118,
            x_tallo + 34, 76, x_tallo + 14, 86, x_tallo - 14, 86,
            fill="#BE123C", outline="#9F1239", width=2, smooth=True
        )
        c.create_polygon(
            x_tallo - 36, 78, x_tallo - 42, 108, x_tallo - 26, 148,
            x_tallo, 156, x_tallo + 14, 128, x_tallo + 4, 92, x_tallo - 18, 82,
            fill="#E11D48", outline="#9F1239", width=2, smooth=True
        )
        c.create_polygon(
            x_tallo + 36, 78, x_tallo + 42, 108, x_tallo + 26, 148,
            x_tallo, 156, x_tallo - 16, 130, x_tallo - 4, 94, x_tallo + 18, 82,
            fill="#F43F5E", outline="#BE123C", width=2, smooth=True
        )
        c.create_arc(
            x_tallo - 16, 65, x_tallo + 16, 81,
            start=15, extent=190, style=tk.ARC, outline="#9F1239", width=2
        )

        # 6. Cáliz
        c.create_polygon(
            x_tallo, 156, x_tallo - 24, 156, x_tallo - 42, 142,
            x_tallo - 26, 162, x_tallo - 4, 162,
            fill="#059669", outline="#047857", width=1.5, smooth=True
        )
        c.create_polygon(
            x_tallo, 156, x_tallo + 24, 156, x_tallo + 42, 142,
            x_tallo + 26, 162, x_tallo + 4, 162,
            fill="#059669", outline="#047857", width=1.5, smooth=True
        )
        c.create_polygon(
            x_tallo - 12, 153, x_tallo, 171, x_tallo + 12, 153,
            fill="#10B981", outline="#059669", width=1.5
        )

    def _actualizar_widget(self, clave: str, widget, **kwargs):
        """Solo llama a .config() si algún atributo visual cambió."""
        if self._cache_ui.get(clave) != kwargs:
            self._cache_ui[clave] = kwargs
            widget.config(**kwargs)

    def _actualizar_pantalla(self):
        if not self.ejecutando:
            return

        self._actualizar_widget("conn", self.lbl_conexion, text=self.estado_conexion, fg=self.color_conexion)
        self._actualizar_widget("est", self.lbl_estado, text=self.estado_medicion, fg=self.color_estado)
        self._actualizar_widget("det", self.lbl_detalle, text=self.detalle_haces)

        self._actualizar_widget("cab", self.lbl_val_cabeza, text=self.valor_cabeza)
        self._actualizar_widget("tal", self.lbl_val_tallo, text=self.valor_tallo, fg=self.color_tallo)
        self._actualizar_widget("card_tal", self.card_tallo, highlightbackground=self.borde_tallo)

        self._actualizar_widget("gra", self.lbl_val_grado, text=self.valor_grado, fg=self.color_grado)
        self._actualizar_widget("card_gra", self.card_grado, highlightbackground=self.borde_grado)

        self.root.after(40, self._actualizar_pantalla)

    def _calcular_cm(self, haz_maximo: int) -> float:
        return ALTURA_INICIAL_CM + ((haz_maximo - HAZ_DISPARO + 1) * SEPARACION_HACES_CM)

    def _bucle_serial(self):
        buffer = bytearray()
        midiendo = False
        esperando_retiro = False
        tiempo_ultimo_cambio = 0.0
        haz_max_actual = 0
        haces_acumulados = set()

        while self.ejecutando:
            try:
                with serial.Serial(
                    port=PUERTO,
                    baudrate=BAUDRATE,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=0.05,
                    rtscts=False,
                    dsrdtr=False,
                    xonxoff=False
                ) as ser:
                    ser.reset_input_buffer()
                    self.estado_conexion = f"● CONECTADO ({PUERTO})"
                    self.color_conexion = "#10B981"

                    while self.ejecutando:
                        disponibles = ser.in_waiting
                        if disponibles < 10:
                            # Cede CPU a Tkinter mientras llega una trama completa (~10.4 ms a 9600 bps)
                            time.sleep(0.015)
                            continue

                        datos = ser.read(disponibles)
                        if datos:
                            buffer.extend(datos)

                        # Evitar acumulación si llega ruido
                        if len(buffer) > 200:
                            del buffer[:-50]

                        # Extraer todas las tramas válidas disponibles en el lote actual
                        tramas_validas = []
                        idx = 0
                        limite = len(buffer) - 10
                        while idx <= limite:
                            if buffer[idx] == 0xC0 and buffer[idx + 4] == 0x22 and buffer[idx + 5] == 0x0A:
                                tramas_validas.append(bytes(buffer[idx:idx + 10]))
                                idx += 10
                            else:
                                idx += 1

                        if idx > 0:
                            del buffer[:idx]

                        if not tramas_validas:
                            continue

                        # Último estado real de la cortina + unión de haces vistos en el lote
                        ultimo_bloqueados = decodificar_haces_validos(tramas_validas[-1])
                        todos_bloqueados = set(ultimo_bloqueados)
                        for t in tramas_validas[:-1]:
                            todos_bloqueados.update(decodificar_haces_validos(t))

                        ahora = time.monotonic()

                        # 0. Si ya se registró una medida, esperar a que retiren la rosa
                        if esperando_retiro:
                            if HAZ_DISPARO not in ultimo_bloqueados:
                                esperando_retiro = False
                                self.estado_medicion = "ESPERANDO MUESTRA..."
                                self.color_estado = "#38BDF8"
                            continue

                        # 1. Inicio inmediato de medición
                        if not midiendo and (HAZ_DISPARO in todos_bloqueados):
                            midiendo = True
                            tiempo_ultimo_cambio = ahora
                            haces_acumulados.clear()
                            haces_acumulados.update(todos_bloqueados)
                            haz_max_actual = max(haces_acumulados)
                            medida_actual = self._calcular_cm(haz_max_actual)

                            self.estado_medicion = "MIDIENDO..."
                            self.color_estado = "#F59E0B"
                            self.valor_tallo = f"{medida_actual:.1f} cm"
                            self.color_tallo = "#FBBF24"
                            self.borde_tallo = "#F59E0B"

                            self.valor_grado = "--"
                            self.color_grado = "#6B7280"
                            self.borde_grado = "#374151"

                            self.detalle_haces = (
                                f"Haz máximo actual: #{haz_max_actual}  |  "
                                f"Haces activos: {len(haces_acumulados)}"
                            )

                        # 2. Estabilización dinámica
                        elif midiendo:
                            if todos_bloqueados:
                                haces_acumulados.update(todos_bloqueados)
                                nuevo_max = max(haces_acumulados)

                                if nuevo_max > haz_max_actual:
                                    haz_max_actual = nuevo_max
                                    tiempo_ultimo_cambio = ahora
                                    medida_actual = self._calcular_cm(haz_max_actual)

                                    self.valor_tallo = f"{medida_actual:.1f} cm"
                                    self.detalle_haces = (
                                        f"Haz máximo actual: #{haz_max_actual}  |  "
                                        f"Haces activos: {len(haces_acumulados)}"
                                    )

                            # 3. Al estabilizarse durante 120 ms, fijar medida y GRADO
                            if (ahora - tiempo_ultimo_cambio) >= VENTANA_ESTABILIZACION:
                                medida_total_cm = self._calcular_cm(haz_max_actual)

                                self.estado_medicion = "MEDIDA REGISTRADA (Retire muestra)"
                                self.color_estado = "#10B981"
                                self.valor_tallo = f"{medida_total_cm:.1f} cm"
                                self.color_tallo = "#34D399"
                                self.borde_tallo = "#10B981"

                                self.valor_grado = calcular_grado(CABEZA_CONSTANTE, medida_total_cm)
                                self.color_grado = "#FACC15"
                                self.borde_grado = "#F59E0B"

                                self.detalle_haces = (
                                    f"Última lectura -> Haz máx: #{haz_max_actual}  |  "
                                    f"Haces detectados: {len(haces_acumulados)}"
                                )

                                midiendo = False
                                esperando_retiro = True
                                haces_acumulados.clear()

            except (serial.SerialException, OSError):
                self.estado_conexion = f"● SIN CONEXIÓN EN {PUERTO} (Reintentando...)"
                self.color_conexion = "#EF4444"
                self.borde_tallo = "#38BDF8"
                midiendo = False
                esperando_retiro = False
                buffer.clear()
                time.sleep(1.0)

    def cerrar(self):
        self.ejecutando = False
        self.root.destroy()


if _name_ == '_main_':
    root = tk.Tk()
    app = InterfazCortinaHMI(root)
    root.mainloop()
