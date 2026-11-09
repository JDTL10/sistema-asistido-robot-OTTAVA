# Documento técnico — Instalación y replicación de OTTAVA

## 1. ¿Qué es OTTAVA?

OTTAVA es un simulador educativo de un sistema asistido por robot desarrollado en Blender.

El proyecto permite controlar un robot virtual desde una aplicación web, simular la adquisición de una radiografía, generar un archivo DICOM, almacenarlo en Orthanc, procesarlo mediante inteligencia artificial y consultar posteriormente el estudio desde un expediente y OHIF Viewer.

El flujo general es:

```text
Aplicación móvil
      ↓
Blender / Robot
      ↓
Generar RX
      ↓
DICOM
      ↓
Orthanc
      ↓
Inteligencia artificial
      ↓
Expediente
      ↓
OHIF / PDF
```

Este documento explica cómo instalar y ejecutar OTTAVA desde cero.

> OTTAVA es un proyecto educativo y no está destinado a uso clínico.

---

# 2. Antes de comenzar

Para ejecutar OTTAVA se necesita una computadora donde puedan instalarse:

- Blender;
- Python 3;
- Orthanc;
- Docker Desktop;
- un navegador web.

También se recomienda disponer de un teléfono móvil conectado a la misma red Wi-Fi para utilizar la interfaz de control.

Durante el desarrollo se utilizó macOS sobre Apple Silicon.

---

# 3. Descargar OTTAVA

El proyecto se encuentra publicado en GitHub.

Puede descargarse utilizando:

```bash
git clone https://github.com/JDTL10/sistema-asistido-robot-OTTAVA.git
```

También puede utilizarse:

```text
Code → Download ZIP
```

desde GitHub.

Después de descargarlo se obtiene una carpeta llamada:

```text
sistema-asistido-robot-OTTAVA
```

En el resto de este documento esa carpeta será llamada:

```text
<ruta_del_repositorio>
```

Por ejemplo:

```text
/Users/usuario/Documents/sistema-asistido-robot-OTTAVA
```

pero puede encontrarse en cualquier ubicación.

---

# 4. Conocer las carpetas principales

No es necesario comprender todo el código para utilizar OTTAVA.

Las carpetas más importantes son:

```text
sistema-asistido-robot-OTTAVA/
│
├── README.md
├── GUIA_USUARIO.md
│
├── src/
│   └── simulacion/
│       ├── OTTAVA_SIMULATOR.blend
│       │
│       └── api/
│           ├── ottava_api.py
│           ├── requirements.txt
│           ├── index.html
│           │
│           ├── control/
│           │   └── OTTAVA_MASTER_FINAL.py
│           │
│           └── visor/
│               └── ohif/
│
├── datos/
│   ├── pacientes/
│   └── dicom_ejemplo/
│
└── docs/
```

Los archivos principales son:

### `OTTAVA_SIMULATOR.blend`

Contiene la escena 3D, el paciente, brazos robóticos, camilla, cámara y demás elementos de simulación.

### `OTTAVA_MASTER_FINAL.py`

Controla Blender y recibe las instrucciones enviadas desde la aplicación.

### `ottava_api.py`

Comunica la aplicación, Blender, DICOM, inteligencia artificial y expediente.

### `index.html`

Contiene la interfaz web utilizada desde el teléfono o navegador.

---

# 5. Software necesario

## Blender

Instalar Blender compatible con el proyecto.

La versión utilizada durante el desarrollo fue:

```text
Blender 5.2.2 LTS
```

---

## Python

Verificar que Python 3 se encuentre instalado:

```bash
python3 --version
```

Si el comando muestra una versión de Python, puede continuar.

---

## Orthanc

Orthanc funciona como servidor PACS.

Debe descargarse e instalarse de acuerdo con el sistema operativo utilizado.

Una vez ejecutado normalmente podrá accederse desde:

```text
http://localhost:8042
```

Al abrir esta dirección deberá aparecer Orthanc Explorer.

---

## Docker Desktop

Docker se utiliza para ejecutar OHIF Viewer.

Instalar Docker Desktop y abrirlo.

Antes de continuar debe indicar que el motor se encuentra activo.

---

# 6. Preparar la API de OTTAVA

Abrir Terminal.

Ingresar a la carpeta:

```bash
cd <ruta_del_repositorio>/src/simulacion/api
```

Ejemplo:

```bash
cd /Users/usuario/Documents/sistema-asistido-robot-OTTAVA/src/simulacion/api
```

Crear un entorno virtual:

```bash
python3 -m venv .venv
```

Activarlo:

```bash
source .venv/bin/activate
```

Instalar las dependencias:

```bash
pip install -r requirements.txt
```

Este procedimiento únicamente es necesario la primera vez.

En futuras ejecuciones será suficiente activar `.venv`.

---

# 7. Comprobar Orthanc

Antes de ejecutar OTTAVA, iniciar Orthanc.

Después abrir:

```text
http://localhost:8042
```

Si Orthanc Explorer carga correctamente, el PACS está preparado.

No es necesario crear manualmente pacientes o estudios.

OTTAVA enviará los estudios automáticamente.

---

# 8. Iniciar OHIF

Primero comprobar que Docker Desktop esté abierto.

Después ingresar a:

```bash
cd <ruta_del_repositorio>/src/simulacion/api/visor/ohif
```

Ejecutar el script de inicio incluido para OHIF.

Una vez iniciado, abrir:

```text
http://localhost:3000
```

Si aparece OHIF Viewer, este componente está listo.

OHIF utiliza DICOMweb para consultar los estudios almacenados en Orthanc.

---

# 9. Iniciar la API OTTAVA

Abrir otra Terminal.

Ingresar a:

```bash
cd <ruta_del_repositorio>/src/simulacion/api
```

Activar el entorno virtual:

```bash
source .venv/bin/activate
```

Ejecutar:

```bash
python3 ottava_api.py
```

No cerrar esta Terminal.

La aplicación mostrará una dirección local similar a:

```text
http://192.168.X.X:PUERTO
```

La dirección exacta cambia según la red.

Esta dirección será utilizada posteriormente desde el teléfono.

---

# 10. Abrir la simulación

Abrir Blender.

Después abrir:

```text
<ruta_del_repositorio>/src/simulacion/OTTAVA_SIMULATOR.blend
```

Cuando cargue la escena, ingresar al editor de Scripts.

Abrir:

```text
<ruta_del_repositorio>/src/simulacion/api/control/OTTAVA_MASTER_FINAL.py
```

Ejecutar el script.

Si todo funciona correctamente aparecerá:

```text
Admisión del paciente
```

OTTAVA debe iniciar:

- sin paciente cargado;
- sin estudio activo;
- sin generar una RX automáticamente.

---

# 11. Ingresar un paciente

La ventana de Admisión permite ingresar:

- nombre;
- ID;
- fecha de nacimiento;
- sexo;
- descripción del estudio;
- fecha;
- hora;
- caso de estudio.

Los pacientes deben ser ficticios.

OTTAVA incluye cuatro casos radiográficos.

Después de completar los datos seleccionar:

```text
INICIAR SIMULACIÓN
```

---

# 12. Abrir la aplicación

El teléfono y la computadora deben estar conectados a la misma red local.

En el navegador del teléfono ingresar la dirección mostrada por `ottava_api.py`.

Ejemplo:

```text
http://192.168.X.X:PUERTO
```

No debe copiarse literalmente este ejemplo.

Debe utilizarse la dirección mostrada en la computadora donde se ejecuta OTTAVA.

---

# 13. Comprobar el control

La aplicación contiene controles para:

```text
PINZA 1
PINZA 2
CÁMARA
SOPORTE
CAMILLA
```

Antes de continuar comprobar que al mover un joystick el elemento correspondiente también se mueve dentro de Blender.

También pueden probarse:

- HOME;
- STOP;
- apertura y cierre de pinzas.

Si los movimientos funcionan, la comunicación entre teléfono, API y Blender está correcta.

---

# 14. Generar una radiografía

Seleccionar:

```text
CÁMARA
```

y posicionar `Arm_03_Camera` sobre el tórax del paciente.

La aplicación muestra la vista de la cámara.

OTTAVA dispone de dos modos.

## Autoencuadre activado

Genera la radiografía completa correspondiente al caso seleccionado.

Este es el modo más sencillo para una primera prueba.

## Autoencuadre desactivado

La región visible desde la cámara determina qué porción de la radiografía será utilizada.

Una vez posicionada la cámara seleccionar:

```text
GENERAR RX
```

---

# 15. ¿Qué ocurre después de Generar RX?

El usuario no debe ejecutar manualmente cada etapa.

OTTAVA realiza automáticamente:

```text
Generar RX
   ↓
Crear DICOM
   ↓
Enviar a Orthanc
   ↓
Ejecutar IA
   ↓
Generar segmentación
   ↓
Crear expediente
```

El procesamiento puede tardar algunos segundos dependiendo de la computadora.

---

# 16. Verificar el DICOM

Abrir:

```text
http://localhost:8042
```

Dentro de Orthanc deberá aparecer el paciente ingresado.

Abrir:

```text
Paciente
→ Estudio
→ Serie
```

Si aparece la imagen generada por OTTAVA, significa que:

- la RX fue creada;
- el DICOM es válido;
- Orthanc recibió correctamente el estudio.

---

# 17. Verificar la inteligencia artificial

Después del procesamiento, la aplicación mostrará:

```text
ANÁLISIS DE IA
```

OTTAVA utiliza modelos de radiografía de tórax para:

- clasificación de posibles hallazgos;
- segmentación anatómica.

Los resultados son únicamente educativos.

---

# 18. Consultar el expediente

El expediente reúne:

- datos del paciente;
- información del estudio;
- radiografía;
- resultados de IA;
- segmentación;
- observaciones.

Desde esta misma pantalla puede utilizarse:

```text
ABRIR EN OHIF
```

---

# 19. Comprobar OHIF

Al seleccionar:

```text
ABRIR EN OHIF
```

deberá abrirse el estudio correspondiente.

Si OHIF muestra la radiografía, significa que el flujo:

```text
OTTAVA
→ DICOM
→ Orthanc
→ DICOMweb
→ OHIF
```

está funcionando correctamente.

---

# 20. Observaciones y PDF

En el expediente pueden ingresarse:

- nombre del profesional;
- rol;
- observaciones.

Después seleccionar:

```text
GUARDAR OBSERVACIONES
```

y posteriormente:

```text
DESCARGAR PDF
```

El reporte incorpora los datos del estudio, imágenes, resultados de IA y observaciones.

---

# 21. Iniciar otro estudio

Para utilizar OTTAVA nuevamente no es necesario reiniciar todos los servicios.

Seleccionar:

```text
NUEVA SIMULACIÓN
```

El sistema vuelve a:

```text
Admisión del paciente
```

y permite ingresar un paciente y caso nuevos.

Los estudios anteriores permanecen guardados en Orthanc.

---

# 22. Cómo saber si OTTAVA está instalado correctamente

Una instalación puede considerarse exitosa si se cumplen estas cinco comprobaciones:

```text
1. Blender responde a los controles de la aplicación.
2. GENERAR RX crea una imagen.
3. El estudio aparece en Orthanc.
4. Se generan resultados de IA y segmentación.
5. El estudio puede abrirse en OHIF.
```

Si las cinco funcionan, el flujo principal está correctamente instalado.

---

# 23. Problemas frecuentes

## La aplicación no abre desde el teléfono

Verificar que:

- `ottava_api.py` esté ejecutándose;
- ambos dispositivos estén en la misma red;
- se esté utilizando la IP mostrada por la API.

---

## Blender no responde

Comprobar que:

```text
OTTAVA_MASTER_FINAL.py
```

esté ejecutándose dentro de Blender.

---

## GENERAR RX no produce resultados

Comprobar:

- paciente admitido;
- simulación iniciada;
- caso seleccionado;
- cámara ubicada sobre el tórax.

Para una primera prueba utilizar Autoencuadre.

---

## El estudio no aparece en Orthanc

Comprobar que:

```text
http://localhost:8042
```

esté disponible.

Si no abre, Orthanc no está ejecutándose.

---

## OHIF no funciona

Comprobar:

1. Docker Desktop activo.
2. OHIF iniciado.
3. Orthanc activo.
4. El estudio presente en Orthanc.

---

## La IA no muestra resultados

Revisar la Terminal donde se ejecuta:

```text
ottava_api.py
```

Los mensajes mostrados allí permiten identificar errores de dependencias o procesamiento.

---

# 24. Arquitectura del proyecto

Después de completar la instalación resulta más sencillo comprender cómo se conectan los componentes:

```text
Teléfono
   ↓
FastAPI
   ↓
Blender
   ↓
Arm_03_Camera
   ↓
DICOM
   ↓
Orthanc
   ↓
IA
   ↓
Expediente
   ↓
OHIF
```

El diagrama completo se encuentra en:

```text
docs/arquitectura.png
```

---

# 25. Tecnologías principales

OTTAVA utiliza:

- Blender;
- Python;
- FastAPI;
- HTML/CSS/JavaScript;
- pydicom;
- Orthanc;
- DICOMweb;
- PyTorch;
- TorchXRayVision;
- DenseNet121;
- PSPNet;
- OHIF Viewer;
- Docker.

---

# 26. Limitaciones

OTTAVA es un simulador.

Por ello:

- no genera radiación real;
- la radiografía es simulada;
- la IA puede producir resultados incorrectos;
- no representa un dispositivo médico certificado;
- no debe utilizarse para diagnóstico o tratamiento.

---

# 27. Datos de prueba

Para pruebas y demostraciones deben utilizarse únicamente:

- pacientes ficticios;
- imágenes anonimizadas;
- conjuntos públicos destinados a investigación o educación.

Nunca deben almacenarse datos reales identificables.

---

# 28. Pruebas finales del proyecto

Las evidencias utilizadas para validar OTTAVA se almacenarán en:

```text
docs/img/
```

Los archivos DICOM de ejemplo se encontrarán en:

```text
datos/dicom_ejemplo/
```

El repositorio incluirá al menos tres estudios DICOM generados mediante el propio sistema.

---

# 29. Licencia

OTTAVA se distribuye bajo licencia:

```text
MIT
```

Consultar:

```text
LICENSE.md
```

Las herramientas y bibliotecas externas conservan sus respectivas licencias.

---

# 30. Soporte documental

Para aprender únicamente a utilizar OTTAVA consultar:

```text
GUIA_USUARIO.md
```

Para conocer la presentación general del proyecto consultar:

```text
README.md
```