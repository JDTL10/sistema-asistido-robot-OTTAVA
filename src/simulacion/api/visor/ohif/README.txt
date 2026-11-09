OTTAVA OHIF V2
===============

CORRECCIÓN
La V1 montaba app-config.js y default.conf directamente dentro del
contenedor OHIF. El entrypoint oficial de OHIF intenta modificar ambos
archivos al arrancar, por lo que aparecían errores de sistema de archivos
de solo lectura.

V2 usa:
- Contenedor 1: OHIF oficial, configurado mediante APP_CONFIG.
- Contenedor 2: Nginx como reverse proxy.
- El navegador ve TODO bajo http://localhost:3000.
- /dicom-web se redirige al Orthanc nativo de macOS en puerto 8042.

ARRANQUE
1. Iniciar Orthanc.
2. Confirmar:
   http://localhost:8042/dicom-web/studies
3. Iniciar Docker Desktop.
4. Terminal:

   cd <ruta_del_repositorio>/src/simulacion/api/visor/ohif
chmod +x start-ohif.command stop-ohif.command
./start-ohif.command

5. Abrir:
   http://localhost:3000

DETENER
./stop-ohif.command

PRUEBAS
- http://localhost:3000/dicom-web/studies
- http://localhost:3000/app-config.js

OHIF debe mostrar la lista de estudios OTTAVA.
