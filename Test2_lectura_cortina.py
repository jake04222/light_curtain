#Clasificacion manual test 2, lectura del grado
#x!/usr/bin/env python3
import serial
import time

# ==============================================================================
# CONFIGURACIÓN DE NOMBRES / PALABRAS PARA CADA HAZ
# Modifica el texto entre comillas para cada haz según tu necesidad.
# ==============================================================================

MAPEO_HACES = {
    1:  "32", #31cm
    2:  "32", #32cm
    3:  "32", #33cm
    4:  "32", #34cm
    5:  "32", #35cm
    6:  "36", #36cm
    7:  "36", #37cm
    8:  "36", #38cm
    9:  "36", #39cm
    10: "40", #40cm
    11: "40", #41cm
    12: "40", #42cm
    13: "43", #43cm
    14: "45", #45cm
    15: "45", #46cm
    16: "47", #47cm
    17: "47", #48cm
    18: "47", #49cm
    19: "50", #50cm
    20: "50", #51cm
    21: "50", #52cm
    22: "53", #53cm
    23: "53", #54cm
    24: "53", #55cm
    25: "53", #56cm
    26: "53", #57cm
    27: "53", #58cm
    28: "53", #59cm
    29: "60", #60cm
    30: "60", #61cm
    31: "60", #62cm
    32: "60", #63cm
    33: "60", #64cm
    34: "60", #65cm
}

# CONFIGURACIÓN DEL PUERTO Y CORTINA
PORT = '/dev/ttyUSB0'  # Cambiar a '/dev/ttyS0' si usas el puerto GPIO de la Raspberry
BAUDRATE = 9600        # Velocidad RS485 de la cortina
SLAVE_ID = 1           # Dirección del esclavo Modbus


def calculate_crc16(data: bytes) -> bytes:
    """Calcula el CRC-16 Modbus RTU (polinomio 0xA001)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def build_read_request(slave_id: int, start_address: int, register_count: int) -> bytes:
    """Construye la trama de lectura Modbus RTU (Función 03)."""
    pdu = bytes([
        slave_id,
        0x03,  # Read Holding Registers
        (start_address >> 8) & 0xFF,
        start_address & 0xFF,
        (register_count >> 8) & 0xFF,
        register_count & 0xFF
    ])
    return pdu + calculate_crc16(pdu)


def parse_and_display(response: bytes):
    """Decodifica la respuesta e imprime la palabra asignada al haz interrumpido."""
    # Validación de longitud mínima (13 bytes)
    if len(response) < 13:
        return

    # Validar CRC
    if response[-2:] != calculate_crc16(response[:-2]):
        print("Error de trama / CRC incorrecto.")
        return

    # Extracción de los registros de la cortina
    first_beam = (response[5] << 8) | response[6]
    last_beam = (response[7] << 8) | response[8]
    total_interrupted = (response[9] << 8) | response[10]

    print("-" * 50)
    if total_interrupted == 0 or first_beam == 0:
        print("Estado: TODOS LOS HACES LIBRES")
    else:
        # Obtener las palabras asociadas a cada haz intermitente/bloqueado
        words_list = []
        for beam in range(first_beam, last_beam + 1):
            # Obtiene la palabra del diccionario, o una por defecto si no existe
            word = MAPEO_HACES.get(beam, f"HAZ_{beam}")
            words_list.append(word)

        if len(words_list) == 1:
            print(f"¡OBSTÁCULO DETECTADO!")
            print(f" -> Haz tapado: {words_list[0]} (Haz #{first_beam})")
        else:
            words_formatted = ", ".join(words_list)
            print(f"¡OBSTÁCULO DETECTADO! ({total_interrupted} haces tapados)")
            print(f" -> Haces tapados: {words_formatted}")


def main():
    try:
        ser = serial.Serial(
            port=PORT,
            baudrate=BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.5
        )
        print(f"Conectado a {PORT} a {BAUDRATE} baudios. Monitoreando cortina...")

        # Solicitud para leer los registros desde el offset 0x0000
        request_frame = build_read_request(SLAVE_ID, start_address=0x0000, register_count=4)

        while True:
            ser.reset_input_buffer()
            ser.write(request_frame)
            time.sleep(0.05)

            if ser.in_waiting > 0:
                response = ser.read(ser.in_waiting)
                parse_and_display(response)
            else:
                print("Sin respuesta de la cortina...")

            time.sleep(0.2)

    except serial.SerialException as err:
        print(f"Error en puerto serie: {err}")
    except KeyboardInterrupt:
        print("\nLectura detenida.")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()


if __name__ == '__main__':
    main()