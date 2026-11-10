#Clasificación manual - prueba de cortina de medicion de luz


#z!/usr/bin/env python3
import serial
import time

# CONFIGURACIÓN DEL PUERTO Y CORTINA
PORT = '/dev/ttyUSB0'  # Cambiar a '/dev/ttyS0' si usas el HAT RS485 en GPIO
BAUDRATE = 9600        # Velocidad estándar DADISICK
SLAVE_ID = 1           # Dirección del esclavo por defecto
TOTAL_BEAMS = 34       # Haces ópticos de la cortina DK-QL34-10-330

def calculate_crc16(data: bytes) -> bytes:
    """Calcula el CRC-16 Modbus RTU para la trama dada."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    # Retorna los 2 bytes en formato Little Endian (Low Byte, High Byte)
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])

def build_read_request(slave_id: int, start_address: int, register_count: int) -> bytes:
    """Construye la trama Modbus RTU (Función 03) con su CRC16."""
    pdu = bytes([
        slave_id,
        0x03,  # Read Holding Registers
        (start_address >> 8) & 0xFF,
        start_address & 0xFF,
        (register_count >> 8) & 0xFF,
        register_count & 0xFF
    ])
    crc = calculate_crc16(pdu)
    return pdu + crc

def parse_curtain_response(response: bytes):
    """
    Decodifica la respuesta de la cortina DADISICK DK-QL34-10-330.
    Registros recibidos:
      - Reg 0: Estado / Errores
      - Reg 1: Primer haz interrumpido (1 a 34)
      - Reg 2: Último haz interrumpido (1 a 34)
      - Reg 3: Cantidad total de haces interrumpidos
      - Reg 4: Máscara parcial de haces
    """
    # Verificación básica de longitud mínima y cabecera
    if len(response) < 13:  # 3 bytes cabecera + 10 bytes datos (5 reg * 2) + 2 bytes CRC
        print("Respuesta incompleta o trama corrupta.")
        return

    # Verificar CRC
    data_payload = response[:-2]
    received_crc = response[-2:]
    expected_crc = calculate_crc16(data_payload)
    if received_crc != expected_crc:
        print("Error de checksum (CRC no coincide).")
        return

    # Extracción de valores de registros (cada registro son 2 bytes en Big Endian)
    first_beam = (response[5] << 8) | response[6]
    last_beam = (response[7] << 8) | response[8]
    total_interrupted = (response[9] << 8) | response[10]

    # Evaluación y reporte en texto
    print("-" * 50)
    if total_interrupted == 0 or first_beam == 0:
        print("Estado: TODOS LOS HACES LIBRES (Sin interrupción)")
    else:
        print(f"Estado: ¡OBSTÁCULO DETECTADO!")
        print(f" • Total de haces interrumpidos: {total_interrupted} de {TOTAL_BEAMS}")
        print(f" • Primer haz interrumpido     : Haz #{first_beam}")
        print(f" • Último haz interrumpido    : Haz #{last_beam}")

        # Si solo un haz está interrumpido o un rango continuo
        if first_beam == last_beam:
            print(f" • Haces específicos cortados  : [{first_beam}]")
        else:
            print(f" • Rango de haces cortados    : Del Haz #{first_beam} al Haz #{last_beam}")

def main():
    try:
        # Configuración del puerto serie con PySerial
        ser = serial.Serial(
            port=PORT,
            baudrate=BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.5
        )
        print(f"Conectado a puerto {PORT} ({BAUDRATE} bps). Iniciando lectura de cortina...")

        # Construir solicitud para consultar 5 registros desde el offset 0x0000
        request_frame = build_read_request(SLAVE_ID, start_address=0x0000, register_count=5)

        while True:
            # Limpiar buffers
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            # Enviar trama
            ser.write(request_frame)
            time.sleep(0.05)  # Tiempo de respuesta de la cortina

            # Leer respuesta
            if ser.in_waiting > 0:
                response = ser.read(ser.in_waiting)
                parse_curtain_response(response)
            else:
                print("Sin respuesta de la cortina. Verifique energía y conexiones A/B.")

            time.sleep(0.3)  # Intervalo de muestreo

    except serial.SerialException as err:
        print(f"Error en puerto serie: {err}")
    except KeyboardInterrupt:
        print("\nLectura finalizada por el usuario.")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()

if __name__ == '__main__':
    main()
