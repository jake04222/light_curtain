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
VENTANA_MEDICION = 2.0        # Segundos de captura tras detectar el primer haz

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

        # Variables compartidas entre el hilo serial y la pantalla
        self.ejecutando = True
        self.estado_conexion = f"Conectando a {PUERTO}..."
        self.color_conexion = "#F59E0B"

        self.estado_medicion = "ESPERANDO MUESTRA..."
        self.color_estado = "#38BDF8"      # Azul claro
        self.valor_grande = "---.- cm"
        self.color_valor = "#F9FAFB"       # Blanco
        self.detalle_haces = f"Base: {ALTURA_INICIAL_CM:.1f} cm  |  Haz disparo: #{HAZ_DISPARO}"

        self._construir_ui()

        # Iniciar lectura serial en segundo plano para no congelar la pantalla
        self.hilo_serial = threading.Thread(target=self._bucle_serial, daemon=True)
        self.hilo_serial.start()

        # Refrescar pantalla cada 30 ms
        self._actualizar_pantalla()

    def _construir_ui(self):
        # --- Barra superior ---
        frame_top = tk.Frame(self.root, bg="#1F2937", height=70)
        frame_top.pack(fill="x", side="top")
        frame_top.pack_propagate(False)

        self.lbl_conexion = tk.Label(
            frame_top,
            text=self.estado_conexion,
            font=("Helvetica", 15, "bold"),
            fg=self.color_conexion,
            bg="#1F2937",
            padx=20
        )
        self.lbl_conexion.pack(side="left", fill="y")

        btn_salir = tk.Button(
            frame_top,
            text="SALIR",
            font=("Helvetica", 14, "bold"),
            bg="#DC2626",
            fg="white",
            activebackground="#991B1B",
            activeforeground="white",
            bd=0,
            padx=25,
            command=self.cerrar
        )
        btn_salir.pack(side="right", fill="y", padx=10, pady=10)

        # --- Contenedor central ---
        frame_centro = tk.Frame(self.root, bg="#111827")
        frame_centro.pack(expand=True, fill="both")

        self.lbl_estado = tk.Label(
            frame_centro,
            text=self.estado_medicion,
            font=("Helvetica", 28, "bold"),
            fg=self.color_estado,
            bg="#111827"
        )
        self.lbl_estado.pack(pady=(30, 10))

        # Número gigante principal
        self.lbl_medida = tk.Label(
            frame_centro,
            text=self.valor_grande,
            font=("Helvetica", 135, "bold"),
            fg=self.color_valor,
            bg="#111827"
        )
        self.lbl_medida.pack(expand=True)

        # --- Barra inferior de diagnóstico ---
        frame_bottom = tk.Frame(self.root, bg="#1F2937", height=55)
        frame_bottom.pack(fill="x", side="bottom")
        frame_bottom.pack_propagate(False)

        self.lbl_detalle = tk.Label(
            frame_bottom,
            text=self.detalle_haces,
            font=("Helvetica", 16),
            fg="#9CA3AF",
            bg="#1F2937"
        )
        self.lbl_detalle.pack(expand=True)

    def _actualizar_pantalla(self):
        if not self.ejecutando:
            return

        self.lbl_conexion.config(text=self.estado_conexion, fg=self.color_conexion)
        self.lbl_estado.config(text=self.estado_medicion, fg=self.color_estado)
        self.lbl_medida.config(text=self.valor_grande, fg=self.color_valor)
        self.lbl_detalle.config(text=self.detalle_haces)

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
                                    self.valor_grande = f"{medida_actual:.1f} cm"
                                    self.color_valor = "#FBBF24"
                                    self.detalle_haces = f"Haz máximo actual: #{haz_max}  |  Haces activos: {len(haces_acumulados)}"

                                # 2. Actualización en vivo durante la ventana de 2 segundos
                                elif midiendo:
                                    if bloqueados:
                                        haces_acumulados.update(bloqueados)
                                        haz_max = max(haces_acumulados)
                                        medida_actual = self._calcular_cm(haz_max)

                                        self.valor_grande = f"{medida_actual:.1f} cm"
                                        self.detalle_haces = f"Haz máximo actual: #{haz_max}  |  Haces activos: {len(haces_acumulados)}"

                                    # 3. Fin de la ventana: bloquear resultado final en pantalla
                                    if (ahora - tiempo_inicio) >= VENTANA_MEDICION:
                                        haz_maximo = max(haces_acumulados)
                                        medida_total_cm = self._calcular_cm(haz_maximo)

                                        self.estado_medicion = "MEDIDA REGISTRADA"
                                        self.color_estado = "#10B981"
                                        self.valor_grande = f"{medida_total_cm:.1f} cm"
                                        self.color_valor = "#34D399"
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
