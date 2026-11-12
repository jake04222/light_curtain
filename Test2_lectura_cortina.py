#Clasificacion manual test 2, lectura del grado

import serial
import struct
import time

# ==============================================================================
# CONFIGURACIÓN DE CALIBRACIÓN Y PUERTO
# ==============================================================================
PUERTO = 'COM8'               # En Raspberry Pi cámbialo a '/dev/ttyUSB0'
BAUDRATE = 9600
VENTANA_MEDICION = 2.0        # Segundos de captura tras detectar el primer haz

ALTURA_INICIAL_CM = 3.0      # <-- AJUSTA AQUÍ: cm desde el suelo hasta el primer haz libre
SEPARACION_HACES_CM = 1.0     # Distancia entre cada haz (1.0 cm)

# Haces que mantienes tapados fijos para activar la lectura de la cortina
HACES_IGNORADOS = {31, 32}

# Número del primer haz libre que debe activarse para iniciar los 5 segundos
HAZ_DISPARO = 1
# ==============================================================================

def decodificar_haces_validos(trama: bytes) -> list:
    """
    Lee los haces bloqueados (bit en 1) y descarta los haces fijos de referencia.
    """
    b0, b1, b2, b3, b4, b5, d0, d1, d2, d3 = struct.unpack('10B', trama)

    # Ignorar trama en estado de reposo sin sincronía (todo en 0xFF)
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

def iniciar_medicion():
    buffer = bytearray()
    midiendo = False
    tiempo_inicio = 0.0
    haces_acumulados = set()

    try:
        ser = serial.Serial(
            port=PUERTO,
            baudrate=BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.1
        )
        print(f"Conectado a {PUERTO} | Altura base: {ALTURA_INICIAL_CM} cm")
        print(f"Esperando activación del primer haz (Haz #{HAZ_DISPARO})...\n")

        while True:
            datos = ser.read(ser.in_waiting or 1)
            if datos:
                buffer.extend(datos)

            while len(buffer) >= 10:
                if next(iter(buffer)) != 0xC0:
                    buffer.pop(0)
                    continue

                trama = bytes(buffer[:10])
                b0, b1, b2, b3, b4, b5, d0, d1, d2, d3 = struct.unpack('10B', trama)

                if b4 == 0x22 and b5 == 0x0A:
                    del buffer[:10]
                    bloqueados = decodificar_haces_validos(trama)
                    ahora = time.time()

                    # CONDICIÓN ESTRICTA: Solo inicia si el HAZ_DISPARO está bloqueado
                    if not midiendo and (HAZ_DISPARO in bloqueados):
                        midiendo = True
                        tiempo_inicio = ahora
                        haces_acumulados.clear()
                        print("Inicio de lectura 5seg")

                    # Una vez iniciado por el primer haz, acumula todos los haces durante 5s
                    if midiendo:
                        if bloqueados:
                            haces_acumulados.update(bloqueados)

                        if (ahora - tiempo_inicio) >= VENTANA_MEDICION:
                            haz_maximo = max(haces_acumulados)
                            cantidad_haces = len(haces_acumulados)
                            
                            # Cálculo de medida: Altura base + recorrido desde el primer haz
                            medida_total_cm = ALTURA_INICIAL_CM + ((haz_maximo - HAZ_DISPARO + 1) * SEPARACION_HACES_CM)
                            largo_objeto_cm = cantidad_haces * SEPARACION_HACES_CM

                            print(f"Medida total: {medida_total_cm:.1f} cm")
                            print(f"Largo detectado en cortina: {largo_objeto_cm:.1f} cm\n")

                            midiendo = False
                            haces_acumulados.clear()
                else:
                    buffer.pop(0)

    except serial.SerialException as e:
        print(f"Error en puerto {PUERTO}: {e}")
    except KeyboardInterrupt:
        print("\nPrograma detenido.")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()

if __name__ == '__main__':
    iniciar_medicion()

