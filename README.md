# 2CDT — Python port

> Port a Python de **2CDT** © Kevin Thacker
> Python port by Tobias Diaz
> Código C original: mayo 2000 — publicado mayo 2001

---

## Descripción

**2CDT** es una utilidad para insertar ficheros binarios en una imagen de cinta
`.CDT` con el formato que utiliza el sistema operativo del Amstrad CPC.

Un fichero `.CDT` es una imagen de cinta que describe el contenido de un
cassette. El formato es idéntico al `.TZX`; la extensión diferencia imágenes
del Amstrad de las del Spectrum.

Esta herramienta permite:

- Crear una nueva cinta o añadir ficheros a una cinta existente.
- Elegir entre varios métodos de grabación (turbo, pure data, standard speed).
- Especificar baudrate, direcciones de carga/ejecución y tipo de fichero.
- Detectar y aprovechar automáticamente la cabecera AMSDOS si el fichero la incluye.

---

## Requisitos

- Python **3.6** o superior
- Sin dependencias externas

---

## Instalación

### Desde PyPI (cuando esté publicado)

```bash
pip install 2cdt
```

### Desde el código fuente

```bash
pip install .
```

### Sin instalar

```bash
python py2cdt.py [opciones] <fichero_entrada> <salida.cdt>
```

---

## Uso

```
2cdt [opciones] <fichero_entrada> <salida.cdt>
```

### Opciones

| Opción | Descripción |
|--------|-------------|
| `-n` | Crear nueva cinta (sobreescribir si ya existe). Sin esta opción el fichero se añade al final de una cinta existente. |
| `-b RATE` | Velocidad en baudios (por defecto: **2000**, rango: 1–5999). |
| `-s 0\|1` | Speed write: `0` = 1000 baudios, `1` = 2000 baudios. Equivale a `SPEED WRITE` en BASIC. Sobreescribe `-b`. |
| `-t 0-2` | Método TZX: `0` = Pure Data, `1` = Turbo Loading (por defecto), `2` = Standard Speed. |
| `-m 0-2` | Método de datos: `0` = bloques con cabecera (por defecto), `1` = sin cabecera (*headerless*), `2` = Spectrum ROM loader. |
| `-r NOMBRE` | Nombre del fichero en la cinta (máx. 16 caracteres). Solo con método 0. |
| `-X DIR` | Dirección de ejecución (decimal, `&HHHH`, `$HHHH` o `0xHHHH`). Por defecto `&1000`. |
| `-L DIR` | Dirección de carga. Por defecto `&1000`. |
| `-F TIPO` | Tipo de fichero: `0` = BASIC, `2` = Binario (por defecto). Solo con método 0. |
| `-p MS` | Pausa inicial en milisegundos (por defecto: **3000**). |
| `-P` | Añade pausa extra de 1 ms para emuladores con fallos. No recomendado. |

### Métodos de datos (`-m`)

| Valor | Nombre | Descripción |
|-------|--------|-------------|
| `0` | Bloques | Formato estándar del SO Amstrad. Genera cabecera + datos por cada bloque de 2 KB. |
| `1` | Headerless | Bloque único sin cabecera. Se carga con `CAS READ` (`&BCA1`). No accesible desde BASIC. |
| `2` | Spectrum | Bloque Standard Speed con sync byte `0xFF`. Compatible con el ROM loader del Spectrum. |

---

## Ejemplos

### Cinta maestra del juego *Stranded*

```bash
# Nueva cinta con el loader binario
2cdt -n -r stranded strandlod.bin stranded.cdt

# Añadir la pantalla de carga
2cdt -r screen loading.bin stranded.cdt

# Añadir el código del juego
2cdt -r code stranded.bin stranded.cdt
```

### Juego con bloque *headerless*

```bash
# Nueva cinta con el loader
2cdt -n -r loader colload.bin columns.cdt

# Código en modo headerless (un solo bloque continuo)
2cdt -m 1 colcode.bin columns.cdt
```

### Direcciones de carga/ejecución personalizadas

```bash
2cdt -n -r miprog -L &4000 -X &4000 miprog.bin miprog.cdt
```

---

## Detección de cabecera AMSDOS

Si el fichero de entrada contiene una cabecera AMSDOS válida (128 bytes
iniciales con checksum correcto sobre los primeros 67 bytes), la herramienta
la detecta automáticamente y extrae el tipo de fichero, la dirección de carga
y la de ejecución. Los 128 bytes de cabecera se omiten del contenido grabado
en la cinta.

Las opciones `-X`, `-L` y `-F` sobreescriben los valores de la cabecera
AMSDOS si está presente.

---

## Licencia

GNU General Public License v3 — ver [LICENSE](LICENSE).
