# Guía de Usuario — OTTAVA

OTTAVA es un simulador educativo de un sistema asistido por robot que integra control remoto, adquisición radiográfica simulada, DICOM, inteligencia artificial y visualización de expedientes.

> **Uso exclusivamente educativo. Los resultados generados por IA no constituyen diagnóstico médico.**

---

## 1. Convención de rutas

En esta guía:

```text
<ruta_del_repositorio>
```

representa la carpeta donde el usuario clonó o descargó:

```text
sistema-asistido-robot-OTTAVA
```

Por lo tanto, la ubicación puede variar entre computadoras.

---

## 2. Requisitos

Antes de utilizar OTTAVA se requiere:

- Blender 5.2.2 LTS
- Python 3
- Orthanc
- Docker Desktop
- navegador web
- teléfono o dispositivo conectado a la misma red local

Las instrucciones completas de instalación se encuentran en:

```text
docs/documento_tecnico.md
```

---

## 3. Iniciar OTTAVA

Los servicios deben iniciarse en este orden:

```text
Orthanc
   ↓
Docker Desktop
   ↓
OHIF Viewer
   ↓
API OTTAVA
   ↓
Blender
   ↓
Aplicación móvil
```

### Orthanc

Iniciar Orthanc desde su carpeta de instalación.

La interfaz normalmente estará disponible en:

```text
http://localhost:8042
```

### OHIF

Desde:

```bash
cd <ruta_del_repositorio>/src/simulacion/api/visor/ohif
```

ejecutar el script de inicio incluido.

OHIF estará disponible en:

```text
http://localhost:3000
```

### API OTTAVA

Ingresar a:

```bash
cd <ruta_del_repositorio>/src/simulacion/api
```

Activar el entorno:

```bash
source .venv/bin/activate
```

Ejecutar:

```bash
python3 ottava_api.py
```

La Terminal mostrará la dirección IP para acceder a la aplicación desde otro dispositivo conectado a la misma red.

### Blender

Abrir:

```text
<ruta_del_repositorio>/src/simulacion/OTTAVA_SIMULATOR.blend
```

Ejecutar desde Blender:

```text
OTTAVA_MASTER_FINAL.py
```

---

## 4. Admisión del paciente

Al iniciar OTTAVA aparece la ventana **Admisión del paciente**.

Ingresar:

- nombre;
- ID;
- fecha de nacimiento;
- sexo;
- descripción del estudio;
- fecha;
- hora;
- caso de estudio.

Utilizar exclusivamente pacientes ficticios.

OTTAVA incluye cuatro casos radiográficos:

```text
Caso 1 · Demostración
Caso 2 · Estudio A
Caso 3 · Estudio B
Caso 4 · Estudio C
```

Después seleccionar:

```text
INICIAR SIMULACIÓN
```

---

## 5. Aplicación móvil

Abrir desde el teléfono la dirección mostrada por la API.

El teléfono y la computadora deben encontrarse conectados a la misma red.

La aplicación permite controlar:

- **PINZA 1**
- **PINZA 2**
- **CÁMARA**
- **SOPORTE**
- **CAMILLA**

También dispone de:

- HOME;
- STOP;
- apertura y cierre de pinzas;
- control de cámara;
- Twin Motion;
- generación de RX.

---

## 6. Generar una radiografía

Posicionar `Arm_03_Camera` sobre la región torácica.

OTTAVA dispone de dos modos:

### Autoencuadre desactivado

La región observada por la cámara determina qué parte de la radiografía será adquirida.

### Autoencuadre activado

OTTAVA utiliza automáticamente la radiografía completa asociada al caso seleccionado.

Para realizar la adquisición seleccionar:

```text
GENERAR RX
```

El sistema ejecuta automáticamente:

```text
RX
 ↓
DICOM
 ↓
Orthanc
 ↓
IA
 ↓
Segmentación
 ↓
Expediente
```

---

## 7. DICOM e inteligencia artificial

La radiografía generada se convierte automáticamente a formato DICOM y se envía a Orthanc.

Después OTTAVA ejecuta:

- análisis de patologías mediante **DenseNet121**;
- segmentación anatómica mediante **PSPNet**.

Los resultados tienen únicamente fines educativos.

---

## 8. Expediente y OHIF

El expediente muestra:

- datos del paciente;
- información del estudio;
- radiografía;
- segmentación;
- resultados de IA;
- observaciones profesionales.

Para visualizar el estudio DICOM seleccionar:

```text
ABRIR EN OHIF
```

Para registrar información profesional:

```text
GUARDAR OBSERVACIONES
```

Después puede generarse el reporte mediante:

```text
DESCARGAR PDF
```

---

## 9. Nueva simulación

Para comenzar un estudio diferente seleccionar:

```text
NUEVA SIMULACIÓN
```

OTTAVA limpia la sesión activa y vuelve a abrir Admisión.

Los estudios almacenados previamente en Orthanc no se eliminan.

---

## 10. Problemas frecuentes

### La aplicación móvil no abre

Comprobar que:

- la API esté activa;
- teléfono y computadora estén en la misma red;
- se esté utilizando la IP mostrada por OTTAVA.

### Los brazos no responden

Verificar que:

```text
OTTAVA_MASTER_FINAL.py
```

y:

```text
ottava_api.py
```

continúen ejecutándose.

### GENERAR RX no funciona

Verificar:

- paciente admitido;
- caso seleccionado;
- simulación iniciada;
- cámara posicionada sobre la región torácica.

### El estudio no aparece en Orthanc

Comprobar:

```text
http://localhost:8042
```

y verificar que Orthanc continúe activo.

### OHIF no abre

Comprobar que:

- Docker esté activo;
- OHIF esté iniciado;
- Orthanc esté funcionando;
- el estudio exista en Orthanc.

### No puede descargarse el PDF

Primero seleccionar:

```text
GUARDAR OBSERVACIONES
```

y posteriormente:

```text
DESCARGAR PDF
```

---

## Evidencias

Las capturas finales de funcionamiento se incorporarán posteriormente en:

```text
docs/img/
```

La documentación técnica completa del proyecto se encuentra en:

```text
docs/documento_tecnico.md
```