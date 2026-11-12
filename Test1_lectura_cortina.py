import serial
import struct
import time

PUERTO = 'COM8'          # En Raspberry Pi cámbialo a '/dev/ttyUSB0'
BAUDRATE = 9600
TOTAL_HACES = 34
VENTANA_MEDICION = 2.0

def decodificar_haces_reales(trama: bytes) -> list:
    """
    Lee los 34 haces en orden de izquierda a derecha (MSB -> LSB).
    Según el volcado real: bit en 1 = HAZ BLOQUEADO, bit en 0 = HAZ LIBRE.
    """
    b0, b1, b2, b3, b4, b5, d0, d1, d2, d3 = struct.unpack('10B', trama)

    # Si todos los bytes están en 0xFF (estado de espera/sin sincronía), ignorar
    if d0 == 0xFF and d1 == 0xFF and d2 == 0xFF and d3 == 0xFF:
        return []

    haces_bloqueados = []
    bytes_datos = (d0, d1, d2, d3)

    # 1. Leer los 32 bits principales de izquierda a derecha (bit 7 down to bit 0)
    for idx_byte, byte_val in enumerate(bytes_datos):
        for bit in range(7, -1, -1):
            num_haz = (idx_byte * 8) + (7 - bit) + 1
            if ((byte_val >> bit) & 1) == 1:
                haces_bloqueados.append(num_haz)

    # 2. Haces 33 y 34 (bits de estado en b1/b2 si aplican)
    # Nota: el bit 0 de d3 (haz 32) siempre estaba en 1 en tu prueba por tapar el último haz
    return sorted(haces_bloqueados)

def iniciar_lectura():
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
        print(f"Conectado a {PUERTO}. Esperando objeto...\n")

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
                    bloqueados = decodificar_haces_reales(trama)
                    ahora = time.time()

                    if not midiendo and len(bloqueados) > 0:
                        midiendo = True
                        tiempo_inicio = ahora
                        haces_acumulados.clear()
                        print("Inicio de lectura 5seg")

                    if midiendo:
                        if bloqueados:
                            haces_acumulados.update(bloqueados)

                        if (ahora - tiempo_inicio) >= VENTANA_MEDICION:
                            resultado = sorted(list(haces_acumulados))
                            print(f"Haces activados: {resultado}\n")
                            midiendo = False
                            haces_acumulados.clear()
                else:
                    buffer.pop(0)

    except serial.SerialException as e:
        print(f"Error en puerto {PUERTO}: {e}")
    except KeyboardInterrupt:
        print("\nLectura detenida.")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()

if __name__ == '__main__':
    iniciar_lectura()
