# OTTAVA — Sistema Asistido por Robot

**OTTAVA** es un simulador académico de cirugía asistida por robot desarrollado en Blender. El proyecto integra control remoto de brazos robóticos, adquisición radiográfica simulada, generación de estudios DICOM, almacenamiento en PACS, análisis mediante inteligencia artificial y visualización médica.

Su objetivo es demostrar la integración de distintas tecnologías biomédicas dentro de un flujo completamente simulado y reproducible.

![Escena final de OTTAVA](docs/img/escena_final.png)

## Características principales

OTTAVA permite:

- Controlar cuatro brazos robóticos de manera independiente.
- Manipular la cámara y la mesa quirúrgica.
- Registrar pacientes ficticios.
- Seleccionar diferentes casos radiográficos.
- Simular la adquisición de una radiografía.
- Generar estudios en formato DICOM.
- Almacenar estudios en Orthanc PACS.
- Analizar imágenes mediante inteligencia artificial.
- Generar segmentación anatómica.
- Consultar un expediente del estudio.
- Visualizar estudios mediante OHIF.
- Registrar observaciones.
- Generar reportes en PDF.

## Arquitectura del sistema

El flujo general de OTTAVA es:

**Control remoto → Blender → adquisición RX → DICOM → Orthanc PACS → IA → expediente → OHIF → reporte PDF**

![Arquitectura de OTTAVA](docs/arquitectura.png)

## Simulación y control

La escena desarrollada en Blender incluye el robot OTTAVA, paciente, mesa quirúrgica, personal médico y los elementos necesarios para representar el entorno de simulación.

El sistema incorpora una interfaz de admisión para registrar información ficticia del paciente y seleccionar el caso de estudio.

![Admisión del paciente](docs/img/admision_paciente.png)

El control de los brazos, cámara y mesa se realiza mediante una aplicación web conectada a la API local de OTTAVA.

![Aplicación de control](docs/img/app_control.png)

## Adquisición RX y DICOM

El brazo 03 incorpora la cámara utilizada para definir la región de interés dentro de la simulación.

Al utilizar **GENERAR RX**, OTTAVA simula la adquisición radiográfica y construye el estudio correspondiente en formato DICOM.

![Generación de RX](docs/img/generar_rx.png)

Los estudios generados pueden almacenarse en Orthanc PACS.

![Estudio DICOM en Orthanc](docs/img/orthanc_estudio.png)

## Inteligencia artificial

OTTAVA incorpora procesamiento mediante inteligencia artificial para analizar la imagen radiográfica y realizar segmentación anatómica.

El sistema utiliza **DenseNet121** para el análisis de radiografías y **PSPNet** para la segmentación, mediante TorchXRayVision.

![Análisis y segmentación mediante IA](docs/img/analisis_segmentacion_IA.png)

Los resultados generados tienen fines exclusivamente educativos y no constituyen diagnóstico médico.

## Expediente y visualización

El módulo de expediente reúne la información asociada al estudio, incluyendo datos del paciente, radiografía, resultados de IA y observaciones.

![Expediente OTTAVA](docs/img/expediente.png)

Los estudios almacenados en Orthanc también pueden visualizarse mediante OHIF utilizando DICOMweb.

![Visualización en OHIF](docs/img/ohif.png)

OTTAVA permite finalmente generar un reporte PDF con la información principal del estudio.

![Reporte generado](docs/img/reporte_pdf.png)

## Tecnologías utilizadas

- Blender
- Python
- FastAPI
- HTML, CSS y JavaScript
- DICOM / pydicom
- Orthanc PACS
- DICOMweb
- OHIF Viewer
- TorchXRayVision
- DenseNet121
- PSPNet
- Docker

## Estructura del repositorio

```text
sistema-asistido-robot-OTTAVA/
├── datos/
│   ├── pacientes/
│   └── dicom_ejemplo/
├── docs/
│   ├── arquitectura.png
│   ├── documento_tecnico.md
│   └── img/
├── src/
│   └── simulacion/
│       ├── api/
│       ├── modelos/
│       ├── OTTAVA_SIMULATOR.blend
│       └── imágenes de casos
├── GUIA_USUARIO.md
├── LICENSE.md
└── README.md
```

## Documentación

Para instalar, replicar y utilizar OTTAVA consulte:

- [Guía de usuario](GUIA_USUARIO.md)
- [Documento técnico](docs/documento_tecnico.md)

El repositorio también contiene archivos DICOM y resultados ficticios generados durante las simulaciones.

## Video demostrativo

El video presenta el flujo completo:

**Control → simulación → RX → DICOM → PACS → IA → expediente → OHIF → reporte**

🎥 **Video demostrativo:** Próximamente

## Uso académico

OTTAVA fue desarrollado como un proyecto universitario de simulación e integración tecnológica.

No constituye un dispositivo médico, sistema clínico ni herramienta de diagnóstico.

## Autor

**Josue Daniel Tobar Lopez**

## Licencia

Este proyecto se distribuye bajo la licencia MIT. Consulte [LICENSE.md](LICENSE.md).