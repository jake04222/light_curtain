# Este codigo muestra cual es el haz que esta activado y enviando la cortina, para que funcione toca tener activo el ultimo haz de la cortina (el que esta mas lejos al cable)
import serial
import struct

PUERTO = 'COM8'
BAUDRATE = 9600

def monitor_puro():
    buffer = bytearray()
    ultima_trama = b""

    try:
        ser = serial.Serial(
            port=PUERTO,
            baudrate=BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.1
        )
        print(f"Conectado a {PUERTO}. Mostrando cada cambio de trama:\n")

        while True:
            datos = ser.read(ser.in_waiting or 1)
            if datos:
                buffer.extend(datos)

            while len(buffer) >= 10:
                # Verificar si el primer byte es 0xC0
                if next(iter(buffer)) != 0xC0:
                    buffer.pop(0)
                    continue

                trama = bytes(buffer[:10])
                b0, b1, b2, b3, b4, b5, d0, d1, d2, d3 = struct.unpack('10B', trama)

                # Validar cabecera de 34 haces (0x22) y 10mm (0x0A)
                if b4 == 0x22 and b5 == 0x0A:
                    del buffer[:10]
                    
                    if trama != ultima_trama:
                        hex_str = trama.hex(' ').upper()
                        # Mostrar los últimos 4 bytes en binario para ver exactamente qué bit cambia
                        bin_str = f"{d0:08b} {d1:08b} {d2:08b} {d3:08b}"
                        print(f"HEX: {hex_str}  |  BITS (d0..d3): {bin_str}")
                        ultima_trama = trama
                else:
                    buffer.pop(0)

    except serial.SerialException as e:
        print(f"Error en puerto {PUERTO}: {e}")
    except KeyboardInterrupt:
        print("\nMonitor detenido.")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()

if __name__ == '__main__':
    monitor_puro()