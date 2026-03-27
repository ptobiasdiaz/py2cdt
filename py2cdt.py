#!/usr/bin/env python3
"""
2CDT - Convierte ficheros binarios a imágenes de cinta CDT/TZX para Amstrad CPC
Port Python de 2CDT (c) Kevin Thacker (GPL v2)

Uso: 2cdt.py [opciones] <fichero_entrada> <salida.cdt>
"""

import struct
import argparse
import sys
import os

# ── Constantes TZX ────────────────────────────────────────────────────────────

TZX_MAGIC              = b"ZXTape!\x1a"
TZX_VERSION_MAJOR      = 1
TZX_VERSION_MINOR      = 10

TZX_STANDARD_SPEED_DATA_BLOCK = 0x10
TZX_TURBO_LOADING_DATA_BLOCK  = 0x11
TZX_PAUSE_BLOCK               = 0x20
TZX_PURE_DATA_BLOCK           = 0x14

TZX_T_STATES = 3_500_000

# ── Constantes de temporización CPC ───────────────────────────────────────────

CPC_NOPS_PER_FRAME   = 19_968
CPC_NOPS_PER_SECOND  = CPC_NOPS_PER_FRAME * 50
CPC_T_STATES         = CPC_NOPS_PER_SECOND * 4          # 3 993 600

# Factor de conversión (aritmética entera idéntica a la versión C)
T_STATE_CONVERSION_FACTOR = (TZX_T_STATES << 8) // (CPC_T_STATES >> 8)

CPC_PILOT_TONE_NUM_WAVES  = 2048
CPC_PILOT_TONE_NUM_PULSES = CPC_PILOT_TONE_NUM_WAVES * 2

CPC_DATA_CHUNK_SIZE       = 256
CPC_DATA_BLOCK_SIZE       = 2048
CPC_PAUSE_AFTER_BLOCK_MS  = 2500

# ── Cabecera de cinta CPC (64 bytes) ──────────────────────────────────────────

CPC_TAPE_HEADER_SIZE             = 64
FIELD_FILENAME                   = 0   # 16 bytes
FIELD_BLOCK_NUMBER               = 16
FIELD_LAST_BLOCK_FLAG            = 17
FIELD_FILE_TYPE                  = 18
FIELD_DATA_LENGTH_LOW            = 19
FIELD_DATA_LENGTH_HIGH           = 20
FIELD_DATA_LOCATION_LOW          = 21
FIELD_DATA_LOCATION_HIGH         = 22
FIELD_FIRST_BLOCK_FLAG           = 23
FIELD_LOGICAL_LENGTH_LOW         = 24
FIELD_LOGICAL_LENGTH_HIGH        = 25
FIELD_EXECUTION_ADDRESS_LOW      = 26
FIELD_EXECUTION_ADDRESS_HIGH     = 27

# ── Métodos de datos CPC ──────────────────────────────────────────────────────

CPC_METHOD_BLOCKS    = 0
CPC_METHOD_HEADERLESS = 1
CPC_METHOD_SPECTRUM  = 2

# ── CRC-16 (polinomio X^16+X^12+X^5+1) ───────────────────────────────────────

_CRC_POLY = 4129  # 0x1021


def _crc_update(crc: int, byte: int) -> int:
    aux = crc ^ ((byte & 0xFF) << 8)
    for _ in range(8):
        if aux & 0x8000:
            aux = ((aux << 1) ^ _CRC_POLY) & 0xFFFF
        else:
            aux = (aux << 1) & 0xFFFF
    return aux


def _crc_block(data: bytes | bytearray) -> int:
    """CRC-16 de un bloque de datos, inicializado a 0xFFFF."""
    crc = 0xFFFF
    for b in data:
        crc = _crc_update(crc, b)
    return crc


# ── Longitudes de pulso ───────────────────────────────────────────────────────

def _pulse_lengths(baud_rate: int) -> tuple[int, int]:
    """Devuelve (zero_pulse_len, one_pulse_len) en T-states TZX."""
    zero_us         = 333_333 // baud_rate
    zero_cpc        = zero_us * 4
    zero_len        = (zero_cpc * (T_STATE_CONVERSION_FACTOR >> 8)) >> 8
    one_len         = zero_len * 2
    return zero_len, one_len


# ── Clase TZXFile ─────────────────────────────────────────────────────────────

class TZXFile:
    """Construye un fichero TZX/CDT en memoria y lo escribe a disco."""

    def __init__(self):
        self._blocks: list[tuple[bytes, bytes | None]] = []

    # ── Bloques primitivos ────────────────────────────────────────────────────

    def add_pause_block(self, ms: int) -> None:
        hdr = bytes([TZX_PAUSE_BLOCK, ms & 0xFF, (ms >> 8) & 0xFF])
        self._blocks.append((hdr, None))

    def add_turbo_block(self, data: bytes, baud_rate: int, pause: int) -> None:
        zero_len, one_len = _pulse_lengths(baud_rate)
        hdr = bytearray(19)
        hdr[0] = TZX_TURBO_LOADING_DATA_BLOCK
        struct.pack_into('<H', hdr,  1, one_len)               # pilot pulse  (= 1-bit)
        struct.pack_into('<H', hdr,  3, zero_len)              # sync1 pulse  (= 0-bit)
        struct.pack_into('<H', hdr,  5, zero_len)              # sync2 pulse  (= 0-bit)
        struct.pack_into('<H', hdr,  7, zero_len)              # zero bit
        struct.pack_into('<H', hdr,  9, one_len)               # one bit
        struct.pack_into('<H', hdr, 11, CPC_PILOT_TONE_NUM_PULSES)
        hdr[13] = 8                                            # bits usados en último byte
        struct.pack_into('<H', hdr, 14, pause)
        n = len(data)
        hdr[16] = n & 0xFF
        hdr[17] = (n >> 8) & 0xFF
        hdr[18] = (n >> 16) & 0xFF
        self._blocks.append((bytes(hdr), data))

    def add_pure_data_block(self, data: bytes, baud_rate: int, pause: int) -> None:
        zero_len, one_len = _pulse_lengths(baud_rate)
        hdr = bytearray(11)
        hdr[0] = TZX_PURE_DATA_BLOCK
        struct.pack_into('<H', hdr, 1, zero_len)
        struct.pack_into('<H', hdr, 3, one_len)
        hdr[5] = 8
        struct.pack_into('<H', hdr, 6, pause)
        n = len(data)
        hdr[8]  = n & 0xFF
        hdr[9]  = (n >> 8) & 0xFF
        hdr[10] = (n >> 16) & 0xFF
        self._blocks.append((bytes(hdr), data))

    def add_standard_block(self, data: bytes, pause: int) -> None:
        hdr = bytearray(5)
        hdr[0] = TZX_STANDARD_SPEED_DATA_BLOCK
        struct.pack_into('<H', hdr, 1, pause)
        struct.pack_into('<H', hdr, 3, len(data))
        self._blocks.append((bytes(hdr), data))

    # ── Escritura ─────────────────────────────────────────────────────────────

    def _write_blocks(self, fh) -> None:
        for hdr, data in self._blocks:
            fh.write(hdr)
            if data is not None:
                fh.write(data)

    def write(self, filename: str) -> None:
        """Escribe el fichero TZX completo (cabecera + bloques)."""
        with open(filename, 'wb') as f:
            f.write(TZX_MAGIC)
            f.write(bytes([TZX_VERSION_MAJOR, TZX_VERSION_MINOR]))
            self._write_blocks(f)

    def append(self, filename: str) -> None:
        """Añade bloques al final de un fichero TZX existente."""
        with open(filename, 'r+b') as f:
            f.seek(0, 2)
            self._write_blocks(f)


# ── Construcción de datos de cinta ────────────────────────────────────────────

def _build_turbo_data(sync: int, payload: bytes) -> bytes:
    """Construye el contenido de un bloque turbo (sync + chunks + CRC + trailer)."""
    num_chunks = (len(payload) + 255) // 256
    out = bytearray()
    out.append(sync)

    src = bytearray(payload)
    for _ in range(num_chunks):
        chunk = bytearray(256)
        take = min(len(src), 256)
        chunk[:take] = src[:take]
        src = src[take:]
        out.extend(chunk)
        crc = _crc_block(chunk)
        out.append((crc >> 8) ^ 0xFF)
        out.append((crc & 0xFF) ^ 0xFF)

    out.extend(b'\xFF\xFF\xFF\xFF')   # trailer
    return bytes(out)


class _BitWriter:
    """Escritor de bits MSB-first sobre un bytearray."""

    def __init__(self, buf: bytearray):
        self._buf   = buf
        self._byte  = 0
        self._bit   = 0

    def write_bit(self, bit: int) -> None:
        if self._bit == 0:
            self._buf[self._byte] = 0
        if bit:
            self._buf[self._byte] |= 1 << (7 - self._bit)
        self._bit += 1
        if self._bit == 8:
            self._bit = 0
            self._byte += 1

    def write_byte(self, byte: int) -> None:
        for shift in range(7, -1, -1):
            self.write_bit((byte >> shift) & 1)

    @property
    def used_bytes(self) -> int:
        return self._byte + (1 if self._bit > 0 else 0)


def _build_pure_data(sync: int, payload: bytes) -> bytes:
    """
    Construye el contenido de un bloque Pure Data:
    pilot tone (2048 × '1') + sync '0' + sync_byte + chunks + CRC + trailer.
    """
    num_chunks = (len(payload) + 255) // 256

    total_bits = (
        CPC_PILOT_TONE_NUM_WAVES        # pilot
        + 1                             # sync bit 0
        + 8                             # sync byte
        + num_chunks * 256 * 8          # datos de chunks
        + num_chunks * 2  * 8           # CRC por chunk (2 bytes)
        + 32                            # trailer (32 × '1')
    )
    buf = bytearray((total_bits + 7) // 8)
    bw  = _BitWriter(buf)

    # Pilot tone
    for _ in range(CPC_PILOT_TONE_NUM_WAVES):
        bw.write_bit(1)

    # Sync
    bw.write_bit(0)
    bw.write_byte(sync)

    # Chunks + CRC
    src = bytearray(payload)
    for _ in range(num_chunks):
        chunk = bytearray(256)
        take  = min(len(src), 256)
        chunk[:take] = src[:take]
        src   = src[take:]

        crc = _crc_block(chunk)
        for b in chunk:
            bw.write_byte(b)

        crc ^= 0xFFFF
        bw.write_byte(crc >> 8)
        bw.write_byte(crc & 0xFF)

    # Trailer
    for _ in range(32):
        bw.write_bit(1)

    return bytes(buf[:bw.used_bytes])


# ── Escritura de bloques de alto nivel ────────────────────────────────────────

def _write_standard_block(tzx: TZXFile, sync: int, data: bytes, pause: int) -> None:
    """Bloque Standard Speed con sync byte y checksum XOR."""
    out      = bytearray([sync])
    checksum = sync
    for b in data:
        checksum ^= b
        out.append(b)
    out.append(checksum & 0xFF)
    tzx.add_standard_block(bytes(out), pause)


def _write_cpc_block(
    tzx: TZXFile,
    sync: int,
    data: bytes,
    pause: int,
    baud_rate: int,
    tzx_method: int,
) -> None:
    """Escribe un bloque CPC según el método TZX elegido."""
    if tzx_method == TZX_TURBO_LOADING_DATA_BLOCK:
        tzx.add_turbo_block(_build_turbo_data(sync, data), baud_rate, pause)
    elif tzx_method == TZX_PURE_DATA_BLOCK:
        tzx.add_pure_data_block(_build_pure_data(sync, data), baud_rate, pause)
    # TZX_STANDARD_SPEED_DATA_BLOCK no se usa en métodos CPC (igual que en C)


# ── Utilidades de argparse ────────────────────────────────────────────────────

def _parse_number(s: str) -> int:
    """Acepta decimal, &HHHH, $HHHH o 0xHHHH. Prefijo sin dígitos se trata como 0."""
    s = s.strip()
    if s.startswith(('&', '$')):
        digits = s[1:]
        return int(digits, 16) if digits else 0
    if s.lower().startswith('0x'):
        digits = s[2:]
        return int(digits, 16) if digits else 0
    return int(s) if s else 0


def _amsdos_checksum(data: bytes | bytearray) -> int:
    return sum(data[:67]) & 0xFFFF


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog='py2cdt',
        description='Convierte ficheros a imágenes de cinta CDT/TZX para Amstrad CPC',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  py2cdt -n -r loader loader.bin cinta.cdt    # nueva cinta con loader
  py2cdt -r code   game.bin   cinta.cdt       # añade código
  py2cdt -m 1      raw.bin    cinta.cdt       # sin cabecera (headerless)
  py2cdt -m 2      spec.bin   cinta.cdt       # formato Spectrum
""",
    )
    parser.add_argument('input_file',  help='Fichero binario de entrada')
    parser.add_argument('output_file', help='Fichero CDT/TZX de salida')
    parser.add_argument('-n', dest='blank', action='store_true',
                        help='Crear nueva cinta (sobreescribir si existe)')
    parser.add_argument('-b', dest='baud_rate', type=int, default=2000,
                        metavar='RATE',
                        help='Velocidad en baudios (por defecto: 2000)')
    parser.add_argument('-s', dest='speed_write', type=int, choices=[0, 1],
                        metavar='0|1',
                        help='Speed write: 0 = 1000 baudios, 1 = 2000 baudios')
    parser.add_argument('-t', dest='tzx_method', type=int, default=1,
                        choices=[0, 1, 2], metavar='0-2',
                        help='Método TZX: 0=Pure Data, 1=Turbo (defecto), 2=Standard Speed')
    parser.add_argument('-m', dest='cpc_method', type=int, default=0,
                        choices=[0, 1, 2], metavar='0-2',
                        help='Método de datos: 0=bloques (defecto), 1=sin cabecera, 2=Spectrum')
    parser.add_argument('-r', dest='tape_filename', metavar='NOMBRE',
                        help='Nombre del fichero en la cinta (máx. 16 caracteres)')
    parser.add_argument('-X', dest='exec_addr', metavar='DIR',
                        help='Dirección de ejecución (hex con &, $ o 0x)')
    parser.add_argument('-L', dest='load_addr', metavar='DIR',
                        help='Dirección de carga (hex con &, $ o 0x)')
    parser.add_argument('-F', dest='file_type', type=int, metavar='TIPO',
                        help='Tipo de fichero (0=BASIC, 2=Binario). Solo método 0')
    parser.add_argument('-p', dest='pause', type=int, default=3000,
                        metavar='MS',
                        help='Pausa inicial en milisegundos (por defecto: 3000)')
    parser.add_argument('-P', dest='buggy_emu', action='store_true',
                        help='Añadir pausa extra de 1 ms para emuladores con fallos')

    args = parser.parse_args()

    # ── Parámetros derivados ──────────────────────────────────────────────────

    baud_rate = args.baud_rate
    if args.speed_write is not None:
        baud_rate = 2000 if args.speed_write == 1 else 1000
    if not (1 <= baud_rate < 6000):
        parser.error(f'Velocidad fuera de rango: {baud_rate} (debe estar entre 1 y 5999)')

    tzx_method_map = {
        0: TZX_PURE_DATA_BLOCK,
        1: TZX_TURBO_LOADING_DATA_BLOCK,
        2: TZX_STANDARD_SPEED_DATA_BLOCK,
    }
    tzx_method = tzx_method_map[args.tzx_method]

    exec_addr          = 0x1000
    exec_addr_override = False
    if args.exec_addr is not None:
        exec_addr          = _parse_number(args.exec_addr) & 0xFFFF
        exec_addr_override = True

    load_addr          = 0x1000
    load_addr_override = False
    if args.load_addr is not None:
        load_addr          = _parse_number(args.load_addr) & 0xFFFF
        load_addr_override = True

    file_type      = 2   # Binario por defecto
    type_override  = False
    if args.file_type is not None:
        file_type     = args.file_type & 0xFF
        type_override = True

    pause = max(0, args.pause)

    # ── Cargar fichero ────────────────────────────────────────────────────────

    try:
        with open(args.input_file, 'rb') as f:
            raw_data = f.read()
    except OSError as e:
        sys.exit(f'Error: No se puede abrir "{args.input_file}": {e}')

    if not raw_data:
        sys.exit('Error: El fichero de entrada está vacío')

    # ── Crear estructura TZX ──────────────────────────────────────────────────

    tzx = TZXFile()

    if args.blank:
        if args.buggy_emu:
            tzx.add_pause_block(1)
        tzx.add_pause_block(pause)

    # ── Detectar cabecera AMSDOS ──────────────────────────────────────────────

    tape_hdr = bytearray(CPC_TAPE_HEADER_SIZE)

    has_amsdos = (
        len(raw_data) >= 69
        and _amsdos_checksum(raw_data)
            == ((raw_data[67] & 0xFF) | ((raw_data[68] & 0xFF) << 8))
    )

    file_offset = 0

    if has_amsdos:
        # Copiar metadatos de la cabecera AMSDOS
        tape_hdr[FIELD_FILE_TYPE]             = raw_data[FIELD_FILE_TYPE]
        tape_hdr[FIELD_EXECUTION_ADDRESS_LOW] = raw_data[FIELD_EXECUTION_ADDRESS_LOW]
        tape_hdr[FIELD_EXECUTION_ADDRESS_HIGH]= raw_data[FIELD_EXECUTION_ADDRESS_HIGH]
        tape_hdr[FIELD_DATA_LOCATION_LOW]     = raw_data[FIELD_DATA_LOCATION_LOW]
        tape_hdr[FIELD_DATA_LOCATION_HIGH]    = raw_data[FIELD_DATA_LOCATION_HIGH]
        file_offset = 128   # saltar la cabecera AMSDOS de 128 bytes

        if exec_addr_override:
            tape_hdr[FIELD_EXECUTION_ADDRESS_LOW]  = exec_addr & 0xFF
            tape_hdr[FIELD_EXECUTION_ADDRESS_HIGH] = (exec_addr >> 8) & 0xFF
        if type_override:
            tape_hdr[FIELD_FILE_TYPE] = file_type
        if load_addr_override:
            tape_hdr[FIELD_DATA_LOCATION_LOW]  = load_addr & 0xFF
            tape_hdr[FIELD_DATA_LOCATION_HIGH] = (load_addr >> 8) & 0xFF
    else:
        tape_hdr[FIELD_FILE_TYPE]             = file_type
        tape_hdr[FIELD_EXECUTION_ADDRESS_LOW] = exec_addr & 0xFF
        tape_hdr[FIELD_EXECUTION_ADDRESS_HIGH]= (exec_addr >> 8) & 0xFF
        tape_hdr[FIELD_DATA_LOCATION_LOW]     = load_addr & 0xFF
        tape_hdr[FIELD_DATA_LOCATION_HIGH]    = (load_addr >> 8) & 0xFF

    # Nombre en la cinta
    if args.tape_filename:
        name = args.tape_filename[:16].upper()
        for i, ch in enumerate(name):
            tape_hdr[i] = ord(ch)

    file_data   = raw_data[file_offset:]
    file_length = len(file_data)

    tape_hdr[FIELD_LOGICAL_LENGTH_LOW]  = file_length & 0xFF
    tape_hdr[FIELD_LOGICAL_LENGTH_HIGH] = (file_length >> 8) & 0xFF

    block_location = (
        tape_hdr[FIELD_DATA_LOCATION_LOW]
        | (tape_hdr[FIELD_DATA_LOCATION_HIGH] << 8)
    )

    # ── Escribir bloques de datos ─────────────────────────────────────────────

    if args.cpc_method == CPC_METHOD_SPECTRUM:
        _write_standard_block(tzx, 0xFF, file_data, 1000)

    else:
        block_index  = 1
        first_block  = True
        remaining    = file_length
        offset       = 0

        while remaining > 0:
            if args.cpc_method == CPC_METHOD_BLOCKS:
                if remaining > CPC_DATA_BLOCK_SIZE:
                    block_size = CPC_DATA_BLOCK_SIZE
                    last_block = False
                else:
                    block_size = remaining
                    last_block = True
            else:  # CPC_METHOD_HEADERLESS
                block_size = remaining
                last_block = True

            # Rellenar cabecera de bloque
            tape_hdr[FIELD_BLOCK_NUMBER]      = block_index
            tape_hdr[FIELD_FIRST_BLOCK_FLAG]  = 0xFF if first_block else 0x00
            tape_hdr[FIELD_LAST_BLOCK_FLAG]   = 0xFF if last_block  else 0x00
            tape_hdr[FIELD_DATA_LENGTH_LOW]   = block_size & 0xFF
            tape_hdr[FIELD_DATA_LENGTH_HIGH]  = (block_size >> 8) & 0xFF
            tape_hdr[FIELD_DATA_LOCATION_LOW] = block_location & 0xFF
            tape_hdr[FIELD_DATA_LOCATION_HIGH]= (block_location >> 8) & 0xFF

            first_block = False

            # Bloque de cabecera (no en modo headerless)
            if args.cpc_method != CPC_METHOD_HEADERLESS:
                _write_cpc_block(tzx, 0x2C, bytes(tape_hdr), 10,
                                 baud_rate, tzx_method)

            # Bloque de datos
            _write_cpc_block(tzx, 0x16,
                             file_data[offset:offset + block_size],
                             CPC_PAUSE_AFTER_BLOCK_MS,
                             baud_rate, tzx_method)

            block_location += block_size
            block_index    += 1
            offset         += block_size
            remaining      -= block_size

    # ── Escribir fichero de salida ────────────────────────────────────────────

    try:
        if args.blank or not os.path.exists(args.output_file):
            tzx.write(args.output_file)
        else:
            tzx.append(args.output_file)
    except OSError as e:
        sys.exit(f'Error: No se puede escribir "{args.output_file}": {e}')


if __name__ == '__main__':
    main()
