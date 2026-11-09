import bpy
import blf
import gpu
import json
import math
import os
import shutil
import tempfile
import time
import socket
import urllib.request

from datetime import datetime
from bpy.props import StringProperty, EnumProperty
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree
from bpy_extras.object_utils import world_to_camera_view
from gpu_extras.batch import batch_for_shader


# ============================================================
# OTTAVA FASE 3 · MASTER FINAL
# Blender 5.2.x
# ============================================================
# - Admisión de paciente
# - Vista externa + Monitor 1 + Monitor 2 integrado
# - 4 brazos desde app móvil
# - Joystick H/V independiente por brazo
# - Profundidad + orientación de herramienta por brazo
# - Pinzas ARM 1 / ARM 2
# - Camilla: desplazamiento + inclinación Twin Motion
# - Collision Guard BVH + último punto seguro
# - Cámara ARM 03: orientación fina + feed LIVE al teléfono
# - Captura RX y visualización clínica + RX compartida con la app
# - V4.2.1 Performance: control UDP 50 Hz + acciones fiables + feed OpenGL estable
# ============================================================

API = "http://127.0.0.1:8000"

ARM_NAMES = ["Arm_01", "Arm_02", "Arm_03", "Arm_04"]
APP_TO_ARM = {
    "arm1": "Arm_01",
    "arm2": "Arm_02",
    "arm3": "Arm_03",
    "arm4": "Arm_04",
}
PART_NAMES = ["Base", "Mid", "Tool"]

TABLE_NAME = "Table_Moving"
TABLE_BASE_NAME = "Table_Base"
PATIENT_NAME = "Surgical_Patient"
CAMERA_NAME = "Arm_03_Camera"
XRAY_NAME = "XRay_Overlay"

# ============================================================
# CASOS RX · V4.7.2 FINAL
# ============================================================
# Los archivos permanecen junto al .blend. No se renombran ni se duplican.
STUDY_CASES = {
    "CASE_01": {
        "label": "Caso 1 · Demostración",
        "filename": "xray_torax.png",
    },
    "CASE_02": {
        "label": "Caso 2 · Estudio A",
        "filename": "Caso2.jpeg",
    },
    "CASE_03": {
        "label": "Caso 3 · Estudio B",
        "filename": "Caso3.jpg",
    },
    "CASE_04": {
        "label": "Caso 4 · Estudio C",
        "filename": "Caso4.jpg.webp",
    },
}

STUDY_CASE_ITEMS = [
    (case_id, data["label"], data["filename"])
    for case_id, data in STUDY_CASES.items()
]

# Tamaño visual normalizado del XRay_Overlay.
# IMPORTANTE: este resize ocurre únicamente en el datablock de Blender;
# los archivos originales en disco NO se modifican. DICOM e IA siguen
# usando la imagen fuente original y el modo manual aplica el recorte
# mediante coordenadas normalizadas sobre esa fuente.
XRAY_DISPLAY_WIDTH = 1122
XRAY_DISPLAY_HEIGHT = 1402


NEEDLE_TIP_NAME = "Suture_Needle_Tip"
DRIVER_NAMES = {
    "Arm_01": "Arm_01_NeedleDriver",
    "Arm_02": "Arm_02_NeedleDriver",
}

JAW_OBJECTS = {
    "Arm_01": {
        "A": "NeedleDriver_Jaw_A",
        "B": "NeedleDriver_Jaw_B",
    },
    "Arm_02": {
        "A": "NeedleDriver_Jaw_A.002",
        "B": "NeedleDriver_Jaw_B.002",
    },
}

JAW_CLOSED_A = -5.0
JAW_CLOSED_B = 5.0
JAW_OPEN_A = 7.0
JAW_OPEN_B = -7.0

# Rangos heredados del Controller V10.6.
ARM_LIMITS = {
    "Arm_01": {
        "Base": (-22.0, 22.0),
        "Mid": (-18.0, 18.0),
        "Tool": (-40.0, 40.0),
    },
    "Arm_02": {
        "Base": (-22.0, 22.0),
        "Mid": (-18.0, 18.0),
        "Tool": (-40.0, 40.0),
    },
    "Arm_03": {
        "Base": (-26.0, 26.0),
        "Mid": (-20.0, 20.0),
        "Tool": (-45.0, 45.0),
    },
    "Arm_04": {
        "Base": (-24.0, 24.0),
        "Mid": (-20.0, 20.0),
        "Tool": (-42.0, 42.0),
    },
}

HORIZONTAL_RANGE = {
    "Arm_01": 21.0,
    "Arm_02": 21.0,
    "Arm_03": 25.0,
    "Arm_04": 23.0,
}

VERTICAL_RANGE = {
    "Arm_01": 17.0,
    "Arm_02": 17.0,
    "Arm_03": 19.0,
    "Arm_04": 19.0,
}

ORIENTATION_RANGE = {
    "Arm_01": 34.0,
    "Arm_02": 34.0,
    "Arm_03": 40.0,
    "Arm_04": 36.0,
}

DEPTH_MASTER_RANGE = 32.0
APPROACH_RATIO = {
    "Base": 0.18,
    "Mid": 0.35,
    "Tool": -0.50,
}

TABLE_SLIDE_LIMIT_MM = 60.0
TABLE_TILT_LIMIT_DEG = 15.0
TWIN_MID_RATIO = 0.45
TWIN_TOOL_RATIO = -0.70

COLLISION_CLEARANCE = {
    "PATIENT": 0.0000,
    "TABLE": 0.00020,
    "ARM": 0.00075,
    "ENV": 0.00040,
}

SAFETY_SEARCH_STEPS = 8

# Velocidades de mando móvil.
ARM_XY_RATE = 0.58
ARM_DEPTH_RATE = 0.46
ARM_TOOL_RATE = 0.58
TABLE_SLIDE_RATE_MM = 28.0
TABLE_TILT_RATE_DEG = 6.5

# La camilla se dibuja al ritmo del control (~50 Hz), pero la validación
# BVH completa se ejecuta a una frecuencia menor. Esto conserva Collision
# Guard / Twin Motion y evita los saltos que producía recalcular todos los
# BVH en cada incremento mínimo.
TABLE_SAFETY_INTERVAL = 0.060

CAMERA_RATE_DEG = 34.0
CAMERA_YAW_LIMIT_DEG = 38.0
CAMERA_PITCH_LIMIT_DEG = 32.0
DEADZONE = 0.08

# Calibración de sentidos desde la app móvil.
# El joystick entrega X positivo a la derecha y Y positivo hacia abajo.
# Estos signos traducen ese gesto al movimiento correcto de cada brazo.
ARM_AXIS_SIGN = {
    "Arm_01": {"x": -1.0, "y": -1.0},
    "Arm_02": {"x": -1.0, "y":  1.0},
    "Arm_03": {"x": -1.0, "y":  1.0},
    "Arm_04": {"x": -1.0, "y": -1.0},
}

CAMERA_AXIS_SIGN = {
    "x": -1.0,
    "y": -1.0,
}

OUTER_RATIO = 0.70
BLANK_IMAGE_NAME = "OTTAVA_MONITOR2_BLANK"

# V4.2.1 · Perfil de rendimiento.
# La API empuja el control a Blender por UDP local; Blender ya no hace
# un GET HTTP en cada ciclo de movimiento.
CONTROL_UDP_HOST = "127.0.0.1"
CONTROL_UDP_PORT = 8766
CONTROL_INTERVAL = 0.020          # objetivo ~50 Hz
CONTROL_DEADMAN = 0.35            # sin paquetes => movimiento a cero

# El control permanece en UDP a ~50 Hz. El feed vuelve a la ruta OpenGL
# comprobada en Blender 5.2, pero vive en un timer separado y a baja frecuencia.
CAMERA_FEED_INTERVAL = 0.25       # ~4 FPS
CAMERA_FEED_WIDTH = 400
CAMERA_FEED_HEIGHT = 225
CAMERA_FEED_QUALITY = 45

SHARED_TEMP = tempfile.gettempdir()
CAMERA_FEED_FILE = os.path.join(
    SHARED_TEMP,
    "ottava_camera_live_v421.jpg",
)
RX_SHARE_FILE = os.path.join(
    SHARED_TEMP,
    "ottava_rx_latest_v421.png",
)
RX_META_FILE = os.path.join(
    SHARED_TEMP,
    "ottava_rx_meta_v421.json",
)
ACTION_STATE_FILE = os.path.join(
    SHARED_TEMP,
    "ottava_actions_v421.json",
)


# ============================================================
# OBJETOS REQUERIDOS
# ============================================================

def get_arm_object(arm, part):
    return bpy.data.objects.get(f"{arm}_{part}")


def get_table():
    return bpy.data.objects.get(TABLE_NAME)


def get_patient():
    return bpy.data.objects.get(PATIENT_NAME)


def get_camera():
    return bpy.data.objects.get(CAMERA_NAME)


def get_overlay():
    return bpy.data.objects.get(XRAY_NAME)


camera = get_camera()
overlay = get_overlay()
table = get_table()
patient = get_patient()

for arm in ARM_NAMES:
    for part in PART_NAMES:
        if get_arm_object(arm, part) is None:
            raise RuntimeError(
                f"OTTAVA: no existe {arm}_{part}"
            )

if camera is None:
    raise RuntimeError(
        f"OTTAVA: no existe {CAMERA_NAME}"
    )

if overlay is None:
    raise RuntimeError(
        f"OTTAVA: no existe {XRAY_NAME}"
    )

if table is None:
    raise RuntimeError(
        f"OTTAVA: no existe {TABLE_NAME}"
    )

for arm in ARM_NAMES:
    for part in PART_NAMES:
        get_arm_object(arm, part).rotation_mode = 'XYZ'

camera.rotation_mode = 'XYZ'

# V4.6.2 · HOME histórico de OTTAVA.
# ARM 02 y ARM 03 deben iniciar con Base / Mid / Tool en rotación XYZ = 0.
# Esto evita que una rotación residual guardada en el .blend sea capturada
# como nueva posición HOME al ejecutar el controlador.
HOME_ZERO_ROTATION_ARMS = {
    "Arm_02",
    "Arm_03",
}

for arm in HOME_ZERO_ROTATION_ARMS:
    for part in PART_NAMES:
        obj = get_arm_object(
            arm,
            part,
        )
        obj.rotation_euler = (
            0.0,
            0.0,
            0.0,
        )

bpy.context.view_layer.update()


# ============================================================
# ESTADO DEL CONTROLADOR
# ============================================================

def zero_arm_values():
    return {
        "H": 0.0,
        "V": 0.0,
        "D": 0.0,
        "O": 0.0,
    }


ARM_STATE = {
    arm: zero_arm_values()
    for arm in ARM_NAMES
}

LAST_SAFE_ARM_STATE = {
    arm: zero_arm_values()
    for arm in ARM_NAMES
}

ARM_INITIAL_ROT = {
    arm: {
        part: get_arm_object(arm, part).rotation_euler.copy()
        for part in PART_NAMES
    }
    for arm in ARM_NAMES
}

CAMERA_INITIAL_ROT = camera.rotation_euler.copy()
CAMERA_STATE = {
    "yaw": 0.0,
    "pitch": 0.0,
}

TABLE_INITIAL_MATRIX_WORLD = table.matrix_world.copy()
PATIENT_INITIAL_MATRIX_WORLD = (
    patient.matrix_world.copy()
    if patient is not None
    else None
)


def is_descendant_of(obj, possible_parent):
    if not obj or not possible_parent:
        return False
    current = obj.parent
    while current:
        if current == possible_parent:
            return True
        current = current.parent
    return False


PATIENT_IS_TABLE_CHILD = is_descendant_of(
    patient,
    table,
)

TABLE_STATE = {
    "slide": 0.0,
    "tilt": 0.0,
}

TABLE_SAFE_STATE = TABLE_STATE.copy()

# Cache del contacto de la última pose segura. Evita recalcular el estado
# base con BVH antes de cada pequeño incremento del joystick.
LAST_SAFE_ARM_CONTACTS = {
    arm: None
    for arm in ARM_NAMES
}

RUNTIME = {
    "main_window_ptr": bpy.context.window.as_pointer(),
    "main_rect": None,
    "monitor_column_rect": None,
    "monitor1_area_ptr": None,
    "monitor2_area_ptr": None,

    "last_time": time.time(),
    "last_status_push": 0.0,
    "status_message": "OTTAVA listo",
    "status_until": 0.0,

    "seq_initialized": False,
    "last_capture_seq": 0,
    "last_new_sim_seq": 0,
    "last_home_all_seq": 0,
    "last_table_center_seq": 0,
    "last_arm_home_seq": {
        key: 0
        for key in APP_TO_ARM
    },
    "last_jaw_seq": {
        "arm1": 0,
        "arm2": 0,
    },

    "last_camera_feed": 0.0,
    "camera_feed_busy": False,
    "latest_state": None,
    "last_udp_packet": 0.0,
    "last_camera_watch_packet": 0.0,
    "last_action_file_version": 0,
    "action_emergency_stop": False,

    # Camilla V4.6.2
    "last_table_safety_check": 0.0,
    "table_was_moving": False,
}

namespace = bpy.app.driver_namespace

generation = namespace.get(
    "OTTAVA_MASTER_GEN",
    0,
) + 1
namespace["OTTAVA_MASTER_GEN"] = generation

# Detiene receiver móvil antiguo si quedó activo.
namespace["OTTAVA_MOBILE_GEN"] = namespace.get(
    "OTTAVA_MOBILE_GEN",
    0,
) + 1

# Socket UDP no bloqueante. Si se vuelve a ejecutar el maestro,
# cerrar primero el socket anterior guardado en driver_namespace.
old_udp_socket = namespace.get("OTTAVA_CONTROL_UDP_SOCKET")
if old_udp_socket is not None:
    try:
        old_udp_socket.close()
    except Exception:
        pass
    namespace.pop("OTTAVA_CONTROL_UDP_SOCKET", None)

CONTROL_SOCKET = socket.socket(
    socket.AF_INET,
    socket.SOCK_DGRAM,
)
CONTROL_SOCKET.setsockopt(
    socket.SOL_SOCKET,
    socket.SO_REUSEADDR,
    1,
)
CONTROL_SOCKET.setblocking(False)
try:
    CONTROL_SOCKET.bind((CONTROL_UDP_HOST, CONTROL_UDP_PORT))
except OSError as error:
    CONTROL_SOCKET.close()
    raise RuntimeError(
        f"OTTAVA: no se pudo abrir UDP {CONTROL_UDP_PORT}: {error}"
    )
namespace["OTTAVA_CONTROL_UDP_SOCKET"] = CONTROL_SOCKET


old_handler = namespace.get(
    "OTTAVA_MONITOR2_DRAW_HANDLER"
)
if old_handler is not None:
    try:
        bpy.types.SpaceImageEditor.draw_handler_remove(
            old_handler,
            'WINDOW',
        )
    except Exception:
        pass
    namespace.pop(
        "OTTAVA_MONITOR2_DRAW_HANDLER",
        None,
    )


# ============================================================
# UTILIDADES
# ============================================================

def clamp(value, minimum, maximum):
    return max(
        minimum,
        min(maximum, value),
    )


def dz(value):
    value = float(value)
    return 0.0 if abs(value) < DEADZONE else value


def lerp(a, b, t):
    return a + (b - a) * t


def interpolate_arm_values(a, b, t):
    return {
        key: lerp(a[key], b[key], t)
        for key in ("H", "V", "D", "O")
    }


def now_values():
    now = datetime.now()
    return (
        now.strftime("%d/%m/%Y"),
        now.strftime("%H:%M:%S"),
    )


def parse_date_dicom(value):
    value = value.strip()
    for fmt in (
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(
                value,
                fmt,
            ).strftime("%Y%m%d")
        except ValueError:
            pass
    return ""


def parse_time_dicom(value):
    value = value.strip()
    for fmt in (
        "%H:%M:%S",
        "%H:%M",
    ):
        try:
            return datetime.strptime(
                value,
                fmt,
            ).strftime("%H%M%S")
        except ValueError:
            pass
    return ""


def find_window(pointer):
    for window in bpy.context.window_manager.windows:
        if window.as_pointer() == pointer:
            return window
    return None


def get_main_window():
    return find_window(
        RUNTIME["main_window_ptr"]
    )


def get_window_region(area):
    for region in area.regions:
        if region.type == 'WINDOW':
            return region
    return None


def rect_of(area):
    return (
        area.x,
        area.y,
        area.width,
        area.height,
    )


def area_center(area):
    return (
        int(area.x + area.width / 2),
        int(area.y + area.height / 2),
    )


def largest_view3d(window):
    areas = [
        area
        for area in window.screen.areas
        if area.type == 'VIEW_3D'
    ]
    if not areas:
        return None
    return max(
        areas,
        key=lambda area:
        area.width * area.height,
    )


def find_main_workspace():
    for name in (
        "Genérico",
        "Generico",
        "Layout",
        "General",
    ):
        workspace = bpy.data.workspaces.get(name)
        if workspace:
            return workspace

    for workspace in bpy.data.workspaces:
        if "script" not in workspace.name.lower():
            return workspace
    return None


def area_by_pointer(pointer):
    window = get_main_window()
    if window is None or pointer is None:
        return None
    for area in window.screen.areas:
        if area.as_pointer() == pointer:
            return area
    return None


def has_ancestor_named(obj, names):
    current = obj
    while current:
        if current.name in names:
            return True
        current = current.parent
    return False


def belongs_to_arm(obj, arm):
    current = obj
    while current:
        if current.name.startswith(arm + "_"):
            return True
        current = current.parent
    return False


def set_status(message, hold=1.5):
    RUNTIME["status_message"] = message
    RUNTIME["status_until"] = time.time() + hold


# ============================================================
# API / TRANSPORTE V4.2
# ============================================================

def receive_latest_udp_state():
    """
    Drena todos los datagramas pendientes y conserva únicamente el último.
    Es no bloqueante: si no hay paquete, Blender continúa inmediatamente.
    """
    latest = None

    while True:
        try:
            data, _address = CONTROL_SOCKET.recvfrom(65535)
        except BlockingIOError:
            break
        except OSError:
            break

        try:
            latest = json.loads(
                data.decode("utf-8")
            )
        except Exception:
            continue

    if latest is not None:
        RUNTIME["latest_state"] = latest
        packet_time = time.perf_counter()
        RUNTIME["last_udp_packet"] = packet_time
        if latest.get("camera_watch", False):
            RUNTIME["last_camera_watch_packet"] = packet_time

    return RUNTIME["latest_state"]


def api_status(message):
    # Estado de baja frecuencia. Se mantiene por HTTP porque sólo ocurre
    # aproximadamente una vez por segundo y no forma parte del lazo de mando.
    data = json.dumps(
        {"message": message}
    ).encode("utf-8")
    request = urllib.request.Request(
        API + "/api/blender-status",
        data=data,
        headers={
            "Content-Type": "application/json"
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(
            request,
            timeout=0.15,
        ).read()
    except Exception:
        pass


def write_shared_rx(source_path, filename, acquisition_time):
    """La API y Blender corren en el mismo Mac: compartir archivo evita
    volver a subir la RX por HTTP desde Blender a la propia máquina."""
    temp_rx = RX_SHARE_FILE + ".tmp.png"
    shutil.copyfile(source_path, temp_rx)
    os.replace(temp_rx, RX_SHARE_FILE)

    metadata = {
        "version": time.time_ns(),
        "filename": filename,
        "acquisition_time": acquisition_time,
    }
    temp_meta = RX_META_FILE + ".tmp"
    with open(temp_meta, "w", encoding="utf-8") as handle:
        json.dump(metadata, handle)
    os.replace(temp_meta, RX_META_FILE)


def read_action_state():
    """Lee acciones discretas desde archivo local fiable.

    El movimiento continuo sigue por UDP; HOME, pinzas, STOP y CAPTURAR RX
    no dependen de que un datagrama individual llegue a Blender.
    """
    try:
        version = os.stat(ACTION_STATE_FILE).st_mtime_ns
    except OSError:
        return None

    if version == RUNTIME["last_action_file_version"]:
        return None

    try:
        with open(ACTION_STATE_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return None

    RUNTIME["last_action_file_version"] = version
    return data


def fetch_action_state_http():
    """Canal autoritativo para acciones discretas.

    Es un GET localhost pequeño; el movimiento continúa por UDP a ~50 Hz.
    """
    try:
        request = urllib.request.Request(
            API + "/api/actions",
            headers={"Cache-Control": "no-cache"},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=0.15) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


# ============================================================
# PINZAS
# ============================================================

def get_jaws(arm):
    names = JAW_OBJECTS.get(arm)
    if not names:
        return None, None
    return (
        bpy.data.objects.get(names["A"]),
        bpy.data.objects.get(names["B"]),
    )


def set_jaw_rotation(obj, y_degrees):
    if obj:
        obj.rotation_euler = (
            obj.rotation_euler.x,
            math.radians(y_degrees),
            obj.rotation_euler.z,
        )


def set_parent_keep_world(obj, parent):
    if not obj:
        return
    world = obj.matrix_world.copy()
    obj.parent = parent
    obj.matrix_world = world


def jaw_action(arm, action):
    jaw_a, jaw_b = get_jaws(arm)
    if not jaw_a or not jaw_b:
        set_status(f"{arm}: pinza no localizada", 2.0)
        return

    if action == "OPEN":
        set_jaw_rotation(jaw_a, JAW_OPEN_A)
        set_jaw_rotation(jaw_b, JAW_OPEN_B)

        tip = bpy.data.objects.get(NEEDLE_TIP_NAME)
        driver_name = DRIVER_NAMES.get(arm)
        driver = bpy.data.objects.get(driver_name) if driver_name else None
        if tip and driver and is_descendant_of(tip, driver):
            set_parent_keep_world(tip, None)

        set_status(f"{arm.replace('_', ' ')} · pinza abierta")

    else:
        set_jaw_rotation(jaw_a, JAW_CLOSED_A)
        set_jaw_rotation(jaw_b, JAW_CLOSED_B)

        tip = bpy.data.objects.get(NEEDLE_TIP_NAME)
        driver_name = DRIVER_NAMES.get(arm)
        driver = bpy.data.objects.get(driver_name) if driver_name else None
        if tip and driver:
            set_parent_keep_world(tip, driver)

        set_status(f"{arm.replace('_', ' ')} · pinza cerrada")

    bpy.context.view_layer.update()


# ============================================================
# MOVIMIENTO COORDINADO DE BRAZOS
# ============================================================

def calculate_arm_angles(arm, values):
    h = values["H"]
    v = values["V"]
    d = values["D"]
    o = values["O"]

    # Conserva la inversión histórica de ARM 03.
    depth_sign = -1.0 if arm == "Arm_03" else 1.0

    base_angle = (
        h * HORIZONTAL_RANGE[arm]
        + d
        * DEPTH_MASTER_RANGE
        * APPROACH_RATIO["Base"]
        * depth_sign
    )

    mid_angle = (
        -v * VERTICAL_RANGE[arm]
        + d
        * DEPTH_MASTER_RANGE
        * APPROACH_RATIO["Mid"]
        * depth_sign
    )

    tool_angle = (
        v * VERTICAL_RANGE[arm] * 0.30
        + d
        * DEPTH_MASTER_RANGE
        * APPROACH_RATIO["Tool"]
        * depth_sign
        + o * ORIENTATION_RANGE[arm]
    )

    # Twin Motion siempre activo en V4.
    tilt = TABLE_STATE["tilt"]
    side = 1.0 if arm in {"Arm_01", "Arm_04"} else -1.0
    mid_angle += tilt * TWIN_MID_RATIO * side
    tool_angle += tilt * TWIN_TOOL_RATIO * side

    return {
        "Base": clamp(
            base_angle,
            *ARM_LIMITS[arm]["Base"],
        ),
        "Mid": clamp(
            mid_angle,
            *ARM_LIMITS[arm]["Mid"],
        ),
        "Tool": clamp(
            tool_angle,
            *ARM_LIMITS[arm]["Tool"],
        ),
    }


def apply_arm_angles(arm, values):
    angles = calculate_arm_angles(
        arm,
        values,
    )

    for part in PART_NAMES:
        obj = get_arm_object(arm, part)
        initial = ARM_INITIAL_ROT[arm][part]
        obj.rotation_euler = (
            initial.x,
            initial.y + math.radians(angles[part]),
            initial.z,
        )


# ============================================================
# COLLISION GUARD · V10.6
# ============================================================

def arm_self_objects(arm):
    result = set()

    # Base omitida como en V10.6 para reducir falsos positivos.
    for part in ("Mid", "Tool"):
        root = get_arm_object(arm, part)
        if root:
            result.add(root)
            result.update(root.children_recursive)

    driver_name = DRIVER_NAMES.get(arm)
    if driver_name:
        driver = bpy.data.objects.get(driver_name)
        if driver:
            result.add(driver)
            result.update(driver.children_recursive)

    return result


def arm_collision_meshes(arm):
    return [
        obj
        for obj in arm_self_objects(arm)
        if obj.type == "MESH"
        and not obj.hide_viewport
        and obj.name != XRAY_NAME
    ]


def classify_obstacle(obj):
    lower = obj.name.lower()

    if (
        has_ancestor_named(obj, {PATIENT_NAME})
        or "patient" in lower
        or "paciente" in lower
    ):
        return "PATIENT"

    if (
        has_ancestor_named(
            obj,
            {TABLE_NAME, TABLE_BASE_NAME},
        )
        or obj.name.startswith("Table_")
        or "camilla" in lower
    ):
        return "TABLE"

    for arm in ARM_NAMES:
        if belongs_to_arm(obj, arm):
            return "ARM"

    return "ENV"


def arm_collision_obstacles(arm):
    own = arm_self_objects(arm)
    result = []

    for obj in bpy.context.scene.objects:
        if obj in own:
            continue
        if obj.type != "MESH" or obj.hide_viewport:
            continue
        if obj.name == XRAY_NAME:
            continue
        if obj.name.startswith("OTTAVA_Suture_"):
            continue
        if obj.name.startswith("Suture_Target_"):
            continue
        result.append(obj)

    return result


def table_assembly_objects():
    result = set()
    current_table = get_table()
    current_patient = get_patient()

    if current_table:
        result.add(current_table)
        result.update(current_table.children_recursive)

    if current_patient:
        result.add(current_patient)
        result.update(current_patient.children_recursive)

    return result


def table_collision_meshes():
    return [
        obj
        for obj in table_assembly_objects()
        if obj.type == "MESH"
        and not obj.hide_viewport
        and obj.name != XRAY_NAME
        and not obj.name.startswith("Suture_Target_")
        and not obj.name.startswith("OTTAVA_Suture_")
    ]


def table_collision_obstacles():
    own = table_assembly_objects()
    result = []

    for obj in bpy.context.scene.objects:
        if obj in own:
            continue
        if obj.type != "MESH" or obj.hide_viewport:
            continue
        if obj.name == XRAY_NAME:
            continue
        if obj.name.startswith("OTTAVA_Suture_"):
            continue
        if obj.name.startswith("Suture_Target_"):
            continue
        if obj.name == TABLE_BASE_NAME:
            continue
        if has_ancestor_named(obj, {TABLE_BASE_NAME}):
            continue
        result.append(obj)

    return result


def world_aabb(obj):
    points = [
        obj.matrix_world @ Vector(corner)
        for corner in obj.bound_box
    ]
    minimum = Vector((
        min(p.x for p in points),
        min(p.y for p in points),
        min(p.z for p in points),
    ))
    maximum = Vector((
        max(p.x for p in points),
        max(p.y for p in points),
        max(p.z for p in points),
    ))
    return minimum, maximum


def aabb_near(obj_a, obj_b, margin):
    min_a, max_a = world_aabb(obj_a)
    min_b, max_b = world_aabb(obj_b)

    return not (
        max_a.x + margin < min_b.x - margin
        or max_b.x + margin < min_a.x - margin
        or max_a.y + margin < min_b.y - margin
        or max_b.y + margin < min_a.y - margin
        or max_a.z + margin < min_b.z - margin
        or max_b.z + margin < min_a.z - margin
    )


def evaluated_world_geometry(obj, depsgraph):
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    if not mesh:
        return None, None

    try:
        vertices = [
            evaluated.matrix_world @ vertex.co
            for vertex in mesh.vertices
        ]
        polygons = [
            tuple(poly.vertices)
            for poly in mesh.polygons
        ]
        return vertices, polygons
    finally:
        evaluated.to_mesh_clear()


def get_cached_bvh(obj, depsgraph, cache):
    key = obj.as_pointer()
    if key in cache:
        return cache[key]

    vertices, polygons = evaluated_world_geometry(
        obj,
        depsgraph,
    )
    if not vertices or not polygons:
        cache[key] = (None, None)
        return cache[key]

    bvh = BVHTree.FromPolygons(
        vertices,
        polygons,
        all_triangles=False,
    )
    cache[key] = (bvh, vertices)
    return cache[key]


def sampled_points(vertices, maximum=40):
    if not vertices:
        return []
    step = max(
        1,
        len(vertices) // maximum,
    )
    return vertices[::step]


def objects_too_close(
    obj_a,
    obj_b,
    clearance,
    depsgraph,
    cache,
):
    if not aabb_near(
        obj_a,
        obj_b,
        clearance,
    ):
        return False

    bvh_a, verts_a = get_cached_bvh(
        obj_a,
        depsgraph,
        cache,
    )
    bvh_b, verts_b = get_cached_bvh(
        obj_b,
        depsgraph,
        cache,
    )

    if not bvh_a or not bvh_b:
        return False

    if bvh_a.overlap(bvh_b):
        return True

    if clearance <= 0.0:
        return False

    for point in sampled_points(verts_a):
        nearest = bvh_b.find_nearest(
            point,
            clearance,
        )
        if (
            nearest
            and nearest[0] is not None
            and nearest[3] <= clearance
        ):
            return True

    for point in sampled_points(verts_b):
        nearest = bvh_a.find_nearest(
            point,
            clearance,
        )
        if (
            nearest
            and nearest[0] is not None
            and nearest[3] <= clearance
        ):
            return True

    return False


def collision_pairs(
    moving_meshes,
    obstacles,
    moving_is_table=False,
):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    cache = {}
    contacts = set()

    for moving in moving_meshes:
        for obstacle in obstacles:
            if moving == obstacle:
                continue

            obstacle_type = classify_obstacle(obstacle)

            if moving_is_table:
                clearance = (
                    COLLISION_CLEARANCE["ARM"]
                    if obstacle_type == "ARM"
                    else COLLISION_CLEARANCE["ENV"]
                )
            else:
                clearance = COLLISION_CLEARANCE[obstacle_type]

            if objects_too_close(
                moving,
                obstacle,
                clearance,
                depsgraph,
                cache,
            ):
                contacts.add(
                    (moving.name, obstacle.name)
                )

    return contacts


def collision_state_for_arm(arm):
    return collision_pairs(
        arm_collision_meshes(arm),
        arm_collision_obstacles(arm),
        moving_is_table=False,
    )


def collision_state_for_table():
    return collision_pairs(
        table_collision_meshes(),
        table_collision_obstacles(),
        moving_is_table=True,
    )


def candidate_is_safe(
    baseline_contacts,
    candidate_contacts,
):
    return len(
        candidate_contacts - baseline_contacts
    ) == 0


def first_new_contact(
    baseline_contacts,
    candidate_contacts,
):
    contacts = sorted(
        candidate_contacts - baseline_contacts
    )
    return contacts[0] if contacts else None


def apply_arm_candidate(arm, values):
    ARM_STATE[arm] = values.copy()
    apply_arm_angles(arm, values)
    bpy.context.view_layer.update()
    return collision_state_for_arm(arm)


def move_arm_to_requested_values(
    arm,
    requested_values,
):
    previous_values = LAST_SAFE_ARM_STATE[arm].copy()

    # V4.2: la pose anterior ya fue validada. Reusar sus contactos elimina
    # una segunda reconstrucción BVH en cada ciclo de movimiento.
    baseline_contacts = LAST_SAFE_ARM_CONTACTS.get(arm)
    if baseline_contacts is None:
        baseline_contacts = collision_state_for_arm(arm)
        LAST_SAFE_ARM_CONTACTS[arm] = set(baseline_contacts)

    requested_contacts = apply_arm_candidate(
        arm,
        requested_values,
    )

    if candidate_is_safe(
        baseline_contacts,
        requested_contacts,
    ):
        LAST_SAFE_ARM_STATE[arm] = requested_values.copy()
        ARM_STATE[arm] = requested_values.copy()
        LAST_SAFE_ARM_CONTACTS[arm] = set(requested_contacts)
        return True

    blocked_pair = first_new_contact(
        baseline_contacts,
        requested_contacts,
    )

    low = 0.0
    high = 1.0
    best_values = previous_values.copy()
    best_contacts = set(baseline_contacts)

    apply_arm_candidate(
        arm,
        previous_values,
    )

    for _ in range(SAFETY_SEARCH_STEPS):
        middle = (low + high) * 0.5
        candidate = interpolate_arm_values(
            previous_values,
            requested_values,
            middle,
        )
        contacts = apply_arm_candidate(
            arm,
            candidate,
        )

        if candidate_is_safe(
            baseline_contacts,
            contacts,
        ):
            best_values = candidate
            best_contacts = set(contacts)
            low = middle
        else:
            high = middle

    apply_arm_candidate(
        arm,
        best_values,
    )
    LAST_SAFE_ARM_STATE[arm] = best_values.copy()
    ARM_STATE[arm] = best_values.copy()
    LAST_SAFE_ARM_CONTACTS[arm] = best_contacts

    if blocked_pair:
        set_status(
            f"LÍMITE {arm.replace('_', ' ')} · "
            f"{blocked_pair[0]} ↔ {blocked_pair[1]}",
            2.2,
        )
    else:
        set_status(
            f"LÍMITE DE SEGURIDAD · {arm.replace('_', ' ')}",
            2.2,
        )

    return False


# ============================================================
# CAMILLA + TWIN MOTION
# ============================================================

def desired_table_matrix(
    slide_mm=None,
    tilt_deg=None,
):
    if slide_mm is None:
        slide_mm = TABLE_STATE["slide"]
    if tilt_deg is None:
        tilt_deg = TABLE_STATE["tilt"]

    slide_mm = clamp(
        slide_mm,
        -TABLE_SLIDE_LIMIT_MM,
        TABLE_SLIDE_LIMIT_MM,
    )
    tilt_deg = clamp(
        tilt_deg,
        -TABLE_TILT_LIMIT_DEG,
        TABLE_TILT_LIMIT_DEG,
    )

    local_slide = Matrix.Translation((
        0.0,
        slide_mm / 1000.0,
        0.0,
    ))
    local_tilt = Matrix.Rotation(
        math.radians(tilt_deg),
        4,
        "X",
    )

    return (
        TABLE_INITIAL_MATRIX_WORLD
        @ local_slide
        @ local_tilt
    )


def combined_table_safety_state():
    contacts = {
        ("TABLE",) + pair
        for pair in collision_state_for_table()
    }

    # Twin Motion siempre activo.
    for arm in ARM_NAMES:
        contacts.update({
            (arm,) + pair
            for pair in collision_state_for_arm(arm)
        })

    return contacts


def apply_table_transform(
    slide_mm,
    tilt_deg,
):
    """Aplica visualmente camilla + paciente + Twin Motion sin BVH completo."""
    current_table = get_table()
    current_patient = get_patient()

    TABLE_STATE["slide"] = float(
        slide_mm
    )
    TABLE_STATE["tilt"] = float(
        tilt_deg
    )

    new_table_matrix = desired_table_matrix(
        slide_mm,
        tilt_deg,
    )
    current_table.matrix_world = (
        new_table_matrix
    )

    if (
        current_patient
        and PATIENT_INITIAL_MATRIX_WORLD is not None
        and not PATIENT_IS_TABLE_CHILD
    ):
        delta = (
            new_table_matrix
            @ TABLE_INITIAL_MATRIX_WORLD.inverted()
        )
        current_patient.matrix_world = (
            delta
            @ PATIENT_INITIAL_MATRIX_WORLD
        )

    # Twin Motion simultáneo.
    for arm in ARM_NAMES:
        apply_arm_angles(
            arm,
            ARM_STATE[arm],
        )

    bpy.context.view_layer.update()

    # La relación espacial cambió; los brazos deben reconstruir su contacto
    # base cuando reciban su siguiente orden.
    for arm in ARM_NAMES:
        LAST_SAFE_ARM_CONTACTS[
            arm
        ] = None


def apply_table_candidate(
    slide_mm,
    tilt_deg,
):
    apply_table_transform(
        slide_mm,
        tilt_deg,
    )
    return combined_table_safety_state()


def interpolate_table_pose(
    start_slide,
    start_tilt,
    end_slide,
    end_tilt,
    t,
):
    return (
        lerp(start_slide, end_slide, t),
        lerp(start_tilt, end_tilt, t),
    )


def move_table_to_requested(
    requested_slide,
    requested_tilt,
):
    previous_slide = TABLE_SAFE_STATE["slide"]
    previous_tilt = TABLE_SAFE_STATE["tilt"]

    # La vista puede estar unos milisegundos por delante de la última pose
    # validada. Para una comprobación autoritativa, regresar primero a SAFE.
    apply_table_transform(
        previous_slide,
        previous_tilt,
    )
    baseline_contacts = (
        combined_table_safety_state()
    )

    requested_contacts = apply_table_candidate(
        requested_slide,
        requested_tilt,
    )

    if candidate_is_safe(
        baseline_contacts,
        requested_contacts,
    ):
        TABLE_SAFE_STATE["slide"] = requested_slide
        TABLE_SAFE_STATE["tilt"] = requested_tilt
        return True

    new_contacts = sorted(
        requested_contacts - baseline_contacts
    )
    blocked = new_contacts[0] if new_contacts else None

    low = 0.0
    high = 1.0
    best_slide = previous_slide
    best_tilt = previous_tilt

    apply_table_candidate(
        previous_slide,
        previous_tilt,
    )

    for _ in range(SAFETY_SEARCH_STEPS):
        middle = (low + high) * 0.5
        slide, tilt = interpolate_table_pose(
            previous_slide,
            previous_tilt,
            requested_slide,
            requested_tilt,
            middle,
        )
        contacts = apply_table_candidate(
            slide,
            tilt,
        )

        if candidate_is_safe(
            baseline_contacts,
            contacts,
        ):
            best_slide = slide
            best_tilt = tilt
            low = middle
        else:
            high = middle

    apply_table_candidate(
        best_slide,
        best_tilt,
    )
    TABLE_SAFE_STATE["slide"] = best_slide
    TABLE_SAFE_STATE["tilt"] = best_tilt

    if blocked:
        if blocked[0] == "TABLE":
            set_status(
                f"LÍMITE CAMILLA · {blocked[1]} ↔ {blocked[2]}",
                2.2,
            )
        else:
            set_status(
                f"LÍMITE TWIN · {blocked[1]} ↔ {blocked[2]}",
                2.2,
            )
    else:
        set_status(
            "LÍMITE DE SEGURIDAD DE CAMILLA",
            2.2,
        )

    return False


# ============================================================
# ORIENTACIÓN FINA DE CÁMARA
# ============================================================

def apply_camera_pose():
    camera.rotation_euler = (
        CAMERA_INITIAL_ROT.x
        + math.radians(CAMERA_STATE["pitch"]),
        CAMERA_INITIAL_ROT.y,
        CAMERA_INITIAL_ROT.z
        + math.radians(CAMERA_STATE["yaw"]),
    )
    bpy.context.view_layer.update()


def camera_home():
    CAMERA_STATE["yaw"] = 0.0
    CAMERA_STATE["pitch"] = 0.0
    apply_camera_pose()


# ============================================================
# HOME
# ============================================================

def home_arm(arm):
    move_arm_to_requested_values(
        arm,
        zero_arm_values(),
    )
    set_status(
        f"{arm.replace('_', ' ')} · HOME"
    )


def center_table():
    move_table_to_requested(
        0.0,
        0.0,
    )
    set_status("CAMILLA · CENTRADA")


def home_all():
    center_table()
    for arm in ARM_NAMES:
        move_arm_to_requested_values(
            arm,
            zero_arm_values(),
        )
    camera_home()
    set_status("HOME GENERAL · COMPLETADO")



# ============================================================
# DICOM / ORTHANC · CAPA AÑADIDA SOBRE V4.2.1 ESTABLE
# ============================================================

def store_capture_in_pacs(image_path, acquisition_time):
    """Genera el DICOM en la API local y lo almacena en Orthanc.

    IMPORTANTE:
    Esta función se ejecuta DESPUÉS de que la adquisición RX de V4.2.1
    ya terminó correctamente. No interviene en joystick, feed, capture_seq,
    action_timer ni en la lógica que ayer fue validada.
    """
    scene = bpy.context.scene

    payload = {
        "image_path": image_path,
        "output_dir": bpy.path.abspath("//OTTAVA_DICOM"),
        "patient_name": scene.get("ottava_patient_name", ""),
        "patient_id": scene.get("ottava_patient_id", ""),
        "patient_birth_date": scene.get("ottava_dicom_birth_date", ""),
        "patient_sex": scene.get("ottava_patient_sex", "O"),
        "study_description": (
            scene.get(
                "ottava_study_description",
                "Radiografía de tórax"
            )
            + " · "
            + scene.get(
                "ottava_case_label",
                "Caso 1 · Demostración"
            )
        ),
        "study_date": scene.get("ottava_dicom_study_date", ""),
        "study_time": scene.get("ottava_dicom_study_time", ""),
        "acquisition_time_display": acquisition_time,
    }

    request = urllib.request.Request(
        API + "/api/dicom/store",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=8.0) as response:
            result = json.loads(response.read().decode("utf-8"))

        if not result.get("ok"):
            raise RuntimeError(
                result.get("error", "Error DICOM/PACS")
            )

        scene["ottava_pacs_status"] = "EN ORTHANC"
        scene["ottava_last_dicom_path"] = result.get("dicom_path", "")
        scene["ottava_orthanc_instance_id"] = result.get(
            "orthanc_instance_id", ""
        )
        scene["ottava_orthanc_study_id"] = result.get(
            "orthanc_study_id", ""
        )
        scene["ottava_orthanc_series_id"] = result.get(
            "orthanc_series_id", ""
        )

        set_status(
            f"RX + DICOM EN ORTHANC · {acquisition_time}",
            4.0,
        )

        print("")
        print("=" * 58)
        print("OTTAVA · DICOM / ORTHANC")
        print("=" * 58)
        print("✓ DICOM:", result.get("dicom_path", ""))
        print("✓ Orthanc:", result.get("orthanc_status", ""))
        print("✓ Study:", result.get("orthanc_study_id", ""))
        print("✓ Series:", result.get("orthanc_series_id", ""))
        print("✓ Instance:", result.get("orthanc_instance_id", ""))
        print("=" * 58)

        return True

    except Exception as error:
        scene["ottava_pacs_status"] = "ERROR PACS"
        scene["ottava_pacs_error"] = str(error)

        # La RX local YA fue adquirida correctamente. PACS es una capa posterior.
        set_status(
            "RX ADQUIRIDA · ERROR DICOM/PACS",
            4.0,
        )
        print("OTTAVA · error DICOM/PACS:", error)
        return False


# ============================================================
# MONITOR 2 · DIBUJO CLÍNICO
# ============================================================

def sex_display():
    value = bpy.context.scene.get(
        "ottava_patient_sex",
        "",
    )
    return {
        "M": "Masculino",
        "F": "Femenino",
        "O": "Otro",
    }.get(value, value)


def get_blank_image():
    image = bpy.data.images.get(
        BLANK_IMAGE_NAME
    )
    if image is None:
        image = bpy.data.images.new(
            BLANK_IMAGE_NAME,
            width=1024,
            height=768,
            alpha=True,
        )
        try:
            image.generated_color = (
                0.025,
                0.030,
                0.040,
                1.0,
            )
        except Exception:
            pass
    return image


def draw_rect(x, y, width, height, color):
    shader = gpu.shader.from_builtin(
        'UNIFORM_COLOR'
    )
    vertices = (
        (x, y),
        (x + width, y),
        (x + width, y + height),
        (x, y + height),
    )
    batch = batch_for_shader(
        shader,
        'TRI_FAN',
        {"pos": vertices},
    )
    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_float(
        "color",
        color,
    )
    batch.draw(shader)
    gpu.state.blend_set('NONE')


def draw_text(
    text,
    x,
    y,
    size,
    color=(1.0, 1.0, 1.0, 1.0),
):
    font_id = 0
    blf.size(font_id, float(size))
    blf.color(
        font_id,
        color[0],
        color[1],
        color[2],
        color[3],
    )
    blf.position(
        font_id,
        float(x),
        float(y),
        0.0,
    )
    blf.draw(font_id, str(text))


def monitor2_draw_callback(target_area_ptr):
    area = bpy.context.area
    region = bpy.context.region

    if area is None or region is None:
        return
    if area.as_pointer() != target_area_ptr:
        return
    if region.type != 'WINDOW':
        return

    scene = bpy.context.scene
    width = region.width
    height = region.height

    if width <= 10 or height <= 10:
        return

    acquired = bool(
        scene.get(
            "ottava_image_acquired",
            False,
        )
    )

    margin = 16
    header_height = min(
        150,
        max(112, int(height * 0.24)),
    )

    draw_rect(
        0,
        height - header_height,
        width,
        header_height,
        (0.015, 0.020, 0.030, 0.86),
    )

    title_y = height - 28
    draw_text(
        "OTTAVA · MONITOR CLÍNICO",
        margin,
        title_y,
        17,
    )

    name = scene.get(
        "ottava_patient_name",
        "",
    )
    patient_id = scene.get(
        "ottava_patient_id",
        "",
    )
    birth = scene.get(
        "ottava_birth_date",
        "",
    )
    study = scene.get(
        "ottava_study_description",
        "",
    )
    study_date = scene.get(
        "ottava_study_date",
        "",
    )
    study_time = scene.get(
        "ottava_study_time",
        "",
    )

    y = title_y - 30
    draw_text(
        f"{name}  ·  ID {patient_id}",
        margin,
        y,
        14,
    )
    y -= 24
    draw_text(
        f"Nacimiento: {birth}  ·  {sex_display()}",
        margin,
        y,
        12,
        (0.82, 0.86, 0.92, 1.0),
    )
    y -= 23
    draw_text(
        study,
        margin,
        y,
        12,
        (0.82, 0.86, 0.92, 1.0),
    )
    y -= 22
    draw_text(
        f"Estudio: {study_date}  {study_time}",
        margin,
        y,
        11,
        (0.72, 0.78, 0.86, 1.0),
    )

    if acquired:
        acquisition_time = scene.get(
            "ottava_last_capture_time",
            "",
        )
        draw_text(
            "●  IMAGEN ADQUIRIDA",
            max(margin, width - 190),
            title_y,
            12,
            (0.55, 0.92, 0.68, 1.0),
        )
        draw_text(
            acquisition_time,
            max(margin, width - 100),
            title_y - 24,
            11,
            (0.80, 0.84, 0.90, 1.0),
        )
    else:
        box_width = min(
            width - 40,
            330,
        )
        box_height = 88
        box_x = (width - box_width) / 2
        box_y = (
            height
            - header_height
            - box_height
        ) / 2

        draw_rect(
            box_x,
            box_y,
            box_width,
            box_height,
            (0.015, 0.020, 0.030, 0.78),
        )
        draw_text(
            "●  EXPLORACIÓN EN CURSO",
            box_x + 26,
            box_y + 54,
            13,
            (0.82, 0.90, 1.0, 1.0),
        )
        draw_text(
            "Esperando adquisición de imagen...",
            box_x + 26,
            box_y + 25,
            13,
        )


def install_monitor2_draw_handler(area):
    old = namespace.get(
        "OTTAVA_MONITOR2_DRAW_HANDLER"
    )
    if old is not None:
        try:
            bpy.types.SpaceImageEditor.draw_handler_remove(
                old,
                'WINDOW',
            )
        except Exception:
            pass

    handler = (
        bpy.types.SpaceImageEditor.draw_handler_add(
            monitor2_draw_callback,
            (area.as_pointer(),),
            'WINDOW',
            'POST_PIXEL',
        )
    )
    namespace[
        "OTTAVA_MONITOR2_DRAW_HANDLER"
    ] = handler
    RUNTIME[
        "monitor2_area_ptr"
    ] = area.as_pointer()
    area.tag_redraw()


# ============================================================
# LAYOUT
# ============================================================

def configure_external(area):
    area.type = 'VIEW_3D'
    space = area.spaces.active
    try:
        space.overlay.show_overlays = False
    except Exception:
        pass
    try:
        space.show_gizmo = False
    except Exception:
        pass
    try:
        space.shading.type = 'MATERIAL'
    except Exception:
        pass
    area.tag_redraw()


def configure_monitor1(area):
    area.type = 'VIEW_3D'
    space = area.spaces.active
    space.use_local_camera = True
    space.camera = camera

    try:
        space.overlay.show_overlays = False
    except Exception:
        pass
    try:
        space.show_gizmo = False
    except Exception:
        pass
    try:
        space.show_region_ui = False
    except Exception:
        pass
    try:
        space.show_region_toolbar = False
    except Exception:
        pass
    try:
        space.shading.type = 'MATERIAL'
    except Exception:
        pass
    try:
        space.region_3d.view_perspective = 'CAMERA'
    except Exception:
        pass

    RUNTIME[
        "monitor1_area_ptr"
    ] = area.as_pointer()
    area.tag_redraw()


def fit_monitor2_image(area):
    window = get_main_window()
    if window is None:
        return None
    if area not in window.screen.areas:
        return None
    region = get_window_region(area)
    if region is None:
        return None

    try:
        with bpy.context.temp_override(
            window=window,
            screen=window.screen,
            area=area,
            region=region,
        ):
            bpy.ops.image.view_all(
                fit_view=True
            )
    except Exception:
        pass
    return None


def configure_monitor2(area):
    area.type = 'IMAGE_EDITOR'
    space = area.spaces.active

    try:
        space.show_region_header = False
    except Exception:
        pass
    try:
        space.show_region_ui = False
    except Exception:
        pass
    try:
        space.show_region_toolbar = False
    except Exception:
        pass
    try:
        space.use_image_pin = True
    except Exception:
        pass

    bpy.context.scene[
        "ottava_image_acquired"
    ] = False
    space.image = get_blank_image()

    install_monitor2_draw_handler(area)
    bpy.app.timers.register(
        lambda: fit_monitor2_image(area),
        first_interval=0.15,
    )


def detect_layout(screen):
    view3d = [
        area
        for area in screen.areas
        if area.type == 'VIEW_3D'
    ]

    if len(view3d) < 2:
        return None

    external = max(
        view3d,
        key=lambda area:
        area.width * area.height,
    )

    right_viewports = [
        area
        for area in view3d
        if area != external
        and area.x > external.x
    ]

    if not right_viewports:
        return None

    monitor1 = max(
        right_viewports,
        key=lambda area: area.y,
    )

    lower = [
        area
        for area in screen.areas
        if area != monitor1
        and abs(area.x - monitor1.x) <= 10
        and abs(area.width - monitor1.width) <= 14
        and area.y < monitor1.y
    ]
    lower.sort(key=lambda area: area.y)

    return external, monitor1, lower


def join_two_areas(source_area, target_area):
    window = get_main_window()
    if window is None:
        return False

    region = get_window_region(source_area)
    if region is None:
        return False

    try:
        with bpy.context.temp_override(
            window=window,
            screen=window.screen,
            area=source_area,
            region=region,
        ):
            bpy.ops.screen.area_join(
                source_xy=area_center(source_area),
                target_xy=area_center(target_area),
            )
        return True
    except Exception as error:
        print(
            "OTTAVA · no pude unir áreas automáticamente:",
            error,
        )
        return False


def finish_existing_layout():
    window = get_main_window()
    if window is None:
        return None

    layout = detect_layout(window.screen)
    if layout is None:
        return None

    external, monitor1, lower = layout
    configure_external(external)
    configure_monitor1(monitor1)

    if len(lower) == 1:
        configure_monitor2(lower[0])
        start_receiver()
        print_ready()
        return None

    if len(lower) >= 2:
        if join_two_areas(
            lower[0],
            lower[1],
        ):
            bpy.app.timers.register(
                finish_existing_layout,
                first_interval=0.40,
            )
        return None

    return None


def finish_right_column_split():
    window = get_main_window()
    if window is None:
        return None

    x, y, w, h = RUNTIME[
        "monitor_column_rect"
    ]
    candidates = [
        area
        for area in window.screen.areas
        if area.x >= x - 3
        and area.x + area.width <= x + w + 3
        and area.y >= y - 3
        and area.y + area.height <= y + h + 3
        and abs(area.width - w) <= 8
    ]

    if len(candidates) < 2:
        print(
            "OTTAVA: no pude identificar Monitor 1 / Monitor 2"
        )
        return None

    candidates.sort(key=lambda area: area.y)
    monitor2 = candidates[0]
    monitor1 = candidates[-1]

    view3d = [
        area
        for area in window.screen.areas
        if area.type == 'VIEW_3D'
        and area not in candidates
    ]
    if not view3d:
        return None

    external = max(
        view3d,
        key=lambda area:
        area.width * area.height,
    )

    configure_external(external)
    configure_monitor1(monitor1)
    configure_monitor2(monitor2)
    start_receiver()
    print_ready()
    return None


def split_right_column():
    window = get_main_window()
    if window is None:
        return None

    x0, y0, w0, h0 = RUNTIME["main_rect"]
    candidates = [
        area
        for area in window.screen.areas
        if abs(area.y - y0) <= 4
        and abs(area.height - h0) <= 8
        and area.x >= x0 - 3
        and area.x + area.width <= x0 + w0 + 3
        and area.type == 'VIEW_3D'
    ]

    if len(candidates) < 2:
        print(
            "OTTAVA: no pude identificar división 70/30"
        )
        return None

    external = max(
        candidates,
        key=lambda area: area.width,
    )
    right_column = min(
        candidates,
        key=lambda area: area.width,
    )

    configure_external(external)
    RUNTIME[
        "monitor_column_rect"
    ] = rect_of(right_column)

    region = get_window_region(right_column)
    if region is None:
        return None

    with bpy.context.temp_override(
        window=window,
        screen=window.screen,
        area=right_column,
        region=region,
    ):
        bpy.ops.screen.area_split(
            direction='HORIZONTAL',
            factor=0.50,
        )

    bpy.app.timers.register(
        finish_right_column_split,
        first_interval=0.35,
    )
    return None


def create_layout():
    window = get_main_window()
    if window is None:
        return None

    main_area = largest_view3d(window)
    if main_area is None:
        print(
            "OTTAVA: Viewport principal no localizado"
        )
        return None

    RUNTIME["main_rect"] = rect_of(main_area)
    region = get_window_region(main_area)
    if region is None:
        return None

    with bpy.context.temp_override(
        window=window,
        screen=window.screen,
        area=main_area,
        region=region,
    ):
        bpy.ops.screen.area_split(
            direction='VERTICAL',
            factor=OUTER_RATIO,
        )

    bpy.app.timers.register(
        split_right_column,
        first_interval=0.35,
    )
    return None


def build_or_repair_layout():
    window = get_main_window()
    if window is None:
        return None

    layout = detect_layout(window.screen)
    if layout is not None:
        external, monitor1, lower = layout
        if (
            external.width
            > monitor1.width * 1.45
            and len(lower) >= 1
        ):
            bpy.app.timers.register(
                finish_existing_layout,
                first_interval=0.15,
            )
            return None

    create_layout()
    return None


# ============================================================
# CASOS DE ESTUDIO · CAMBIO DE RX
# ============================================================

def study_case_path(case_id):
    data = STUDY_CASES.get(case_id)
    if not data:
        return None
    return bpy.path.abspath(
        "//" + data["filename"]
    )


def apply_study_case(case_id):
    """Activa la RX del caso y normaliza SOLO su visualización en Blender.

    Todas las imágenes ocupan el mismo lienzo visual 1122x1402 dentro de
    XRay_Overlay. Esto puede distorsionar la vista del overlay, pero NO
    altera el archivo original en disco. El flujo DICOM/IA conserva la
    fuente original; el modo manual usa coordenadas normalizadas para
    recortar la región equivalente del original.
    """
    data = STUDY_CASES.get(case_id)
    if not data:
        raise RuntimeError(
            f"Caso de estudio no válido: {case_id}"
        )

    source = study_case_path(case_id)
    if not source or not os.path.exists(source):
        raise FileNotFoundError(
            f"No se encontró {data['filename']} junto al archivo .blend"
        )

    try:
        image = bpy.data.images.load(
            source,
            check_existing=True,
        )
        # Recuperar primero los píxeles originales desde disco y luego
        # estirar únicamente el datablock en memoria para XRay_Overlay.
        try:
            image.reload()
        except Exception:
            pass

        image.scale(
            XRAY_DISPLAY_WIDTH,
            XRAY_DISPLAY_HEIGHT,
        )
        image.update()

    except Exception as error:
        raise RuntimeError(
            f"No se pudo preparar la RX del caso: {error}"
        )

    assigned = False
    for slot in overlay.material_slots:
        material = slot.material
        if not material or not material.use_nodes:
            continue
        for node in material.node_tree.nodes:
            if node.type == 'TEX_IMAGE':
                node.image = image
                assigned = True

    if not assigned:
        raise RuntimeError(
            "XRay_Overlay no tiene un nodo Image Texture disponible."
        )

    scene = bpy.context.scene
    scene["ottava_case_id"] = case_id
    scene["ottava_case_label"] = data["label"]
    scene["ottava_case_source"] = source
    scene["ottava_case_display_width"] = XRAY_DISPLAY_WIDTH
    scene["ottava_case_display_height"] = XRAY_DISPLAY_HEIGHT

    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type in {'VIEW_3D', 'IMAGE_EDITOR'}:
                area.tag_redraw()

    print(
        f"OTTAVA · {data['label']} · RX activa = {source}"
    )
    print(
        f"OTTAVA · Visual XRay_Overlay = "
        f"{XRAY_DISPLAY_WIDTH}x{XRAY_DISPLAY_HEIGHT} "
        "(fuente original intacta)"
    )
    return source


# ============================================================
# CAPTURA RX · ENCUADRE / AUTOENCUADRE
# ============================================================

def find_xray_image_path():
    # Prioridad: archivo ORIGINAL del caso activo. El datablock mostrado
    # en XRay_Overlay puede estar redimensionado en memoria a 1122x1402.
    scene = bpy.context.scene
    active_source = scene.get("ottava_case_source", "")
    if active_source:
        active_source = bpy.path.abspath(str(active_source))
        if os.path.exists(active_source):
            return active_source

    for slot in overlay.material_slots:
        material = slot.material
        if material and material.use_nodes:
            for node in material.node_tree.nodes:
                if (
                    node.type == 'TEX_IMAGE'
                    and node.image
                ):
                    path = bpy.path.abspath(
                        node.image.filepath
                    )
                    if os.path.exists(path):
                        return path

    fallback = bpy.path.abspath(
        "//xray_torax.png"
    )
    return (
        fallback
        if os.path.exists(fallback)
        else None
    )


def camera_center_hits_overlay():
    """Chequeo original: el rayo central de la cámara cruza XRay_Overlay."""
    mesh = overlay.data

    if len(mesh.vertices) < 3:
        return False

    origin = camera.matrix_world.translation.copy()

    direction = (
        camera.matrix_world.to_quaternion()
        @ Vector((0, 0, -1))
    )
    direction.normalize()

    v0 = overlay.matrix_world @ mesh.vertices[0].co
    v1 = overlay.matrix_world @ mesh.vertices[1].co
    v2 = overlay.matrix_world @ mesh.vertices[2].co

    normal = (v1 - v0).cross(v2 - v0)

    if normal.length < 1e-9:
        return False

    normal.normalize()

    denominator = direction.dot(normal)

    if abs(denominator) < 1e-7:
        return False

    distance = (
        (v0 - origin).dot(normal)
        / denominator
    )

    if distance <= 0:
        return False

    hit_world = origin + direction * distance

    hit_local = (
        overlay.matrix_world.inverted()
        @ hit_world
    )

    xs = [
        vertex.co.x
        for vertex in mesh.vertices
    ]

    ys = [
        vertex.co.y
        for vertex in mesh.vertices
    ]

    return (
        min(xs) <= hit_local.x <= max(xs)
        and min(ys) <= hit_local.y <= max(ys)
    )


def camera_sees_overlay():
    """Validación clínica tolerante.

    La V4.2.1 exigía que el CENTRO EXACTO de la cámara tocara el plano RX.
    Eso hacía que una imagen torácica claramente visible pudiera rechazarse.

    Ahora se acepta si:
    - el centro de cámara cae en el overlay, O
    - una parte significativa del overlay está dentro del encuadre.
    """
    if camera_center_hits_overlay():
        return True

    scene = bpy.context.scene
    mesh = overlay.data

    if not mesh.vertices:
        return False

    projected = []

    for vertex in mesh.vertices:
        world = overlay.matrix_world @ vertex.co
        co = world_to_camera_view(
            scene,
            camera,
            world,
        )

        # Delante de la cámara.
        if co.z > 0:
            projected.append(
                (
                    float(co.x),
                    float(co.y),
                )
            )

    if len(projected) < 3:
        return False

    xs = [point[0] for point in projected]
    ys = [point[1] for point in projected]

    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)

    visible_width = max(
        0.0,
        min(max_x, 1.0)
        -
        max(min_x, 0.0),
    )

    visible_height = max(
        0.0,
        min(max_y, 1.0)
        -
        max(min_y, 0.0),
    )

    visible_area = (
        visible_width
        *
        visible_height
    )

    projected_area = max(
        (max_x - min_x)
        *
        (max_y - min_y),
        1e-9,
    )

    visible_fraction = (
        visible_area
        /
        projected_area
    )

    # Suficientemente visible para una adquisición clínica simulada.
    return (
        visible_area >= 0.004
        and
        visible_fraction >= 0.02
    )


def camera_visible_crop_box():
    """Devuelve la región visible de XRay_Overlay en coordenadas normalizadas.

    Formato de retorno: (left, top, right, bottom), con origen de imagen
    en la esquina superior izquierda, listo para Pillow en la API.

    La estimación usa la proyección actual del overlay dentro del encuadre
    de Arm_03_Camera. No renderiza nada y sólo se calcula al generar RX.
    """
    scene = bpy.context.scene
    mesh = overlay.data

    if not mesh.vertices:
        return None

    projected = []
    for vertex in mesh.vertices:
        world = overlay.matrix_world @ vertex.co
        co = world_to_camera_view(
            scene,
            camera,
            world,
        )
        if co.z > 0:
            projected.append(
                (float(co.x), float(co.y))
            )

    if len(projected) < 3:
        return None

    xs = [p[0] for p in projected]
    ys = [p[1] for p in projected]

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    width = max_x - min_x
    height = max_y - min_y
    if width <= 1e-9 or height <= 1e-9:
        return None

    inter_left = max(0.0, min_x)
    inter_right = min(1.0, max_x)
    inter_bottom = max(0.0, min_y)
    inter_top = min(1.0, max_y)

    if inter_right <= inter_left or inter_top <= inter_bottom:
        return None

    # Convertir el rectángulo de cámara a fracción de la textura RX.
    u0 = (inter_left - min_x) / width
    u1 = (inter_right - min_x) / width
    v0 = (inter_bottom - min_y) / height
    v1 = (inter_top - min_y) / height

    u0 = clamp(u0, 0.0, 1.0)
    u1 = clamp(u1, 0.0, 1.0)
    v0 = clamp(v0, 0.0, 1.0)
    v1 = clamp(v1, 0.0, 1.0)

    # Pillow mide Y desde arriba; Blender/UV desde abajo.
    left = u0
    right = u1
    top = 1.0 - v1
    bottom = 1.0 - v0

    # Evitar recortes degenerados por posiciones extremas.
    if (right - left) < 0.03 or (bottom - top) < 0.03:
        return None

    return (left, top, right, bottom)


def process_xray_image(source, destination, auto_frame):
    """Pide a la API local crear un PNG real desde PNG/JPG/WEBP.

    - auto_frame=True: conserva el estudio completo.
    - auto_frame=False: recorta según el encuadre actual de la cámara.
    """
    if auto_frame:
        crop_box = [0.0, 0.0, 1.0, 1.0]
        mode = "AUTOENCUADRE"
    else:
        crop = camera_visible_crop_box()
        if crop is None:
            raise RuntimeError(
                "No se pudo calcular el encuadre RX. Apunta la cámara al tórax."
            )
        crop_box = list(crop)
        mode = "ENCUADRE"

    payload = {
        "image_path": source,
        "output_path": destination,
        "crop_box": crop_box,
        "auto_frame": bool(auto_frame),
    }

    request = urllib.request.Request(
        API + "/api/rx/process",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=8.0,
    ) as response:
        result = json.loads(
            response.read().decode("utf-8")
        )

    if not result.get("ok"):
        raise RuntimeError(
            result.get("error", "Error procesando RX")
        )

    return mode, result


def acquire_full_xray(auto_frame=False):
    mode_label = (
        "AUTOENCUADRE"
        if auto_frame
        else "ENCUADRE DE CÁMARA"
    )
    print(
        f"OTTAVA · GENERAR RX recibido · {mode_label}"
    )
    set_status(
        "RX · solicitud recibida",
        1.5,
    )
    api_status(
        "RX · solicitud recibida"
    )

    if not camera_sees_overlay():
        message = (
            "RX BLOQUEADA · apunta la cámara al tórax"
        )
        set_status(
            message,
            3.5,
        )
        api_status(
            message
        )
        print(
            "OTTAVA · captura rechazada: "
            "área RX fuera del encuadre"
        )
        return

    set_status(
        "RX · adquiriendo imagen...",
        2.0,
    )
    api_status(
        "RX · adquiriendo imagen..."
    )

    source = find_xray_image_path()
    if not source:
        set_status(
            "RX · no se encontró xray_torax.png",
            2.5,
        )
        return

    folder = bpy.path.abspath(
        "//OTTAVA_Capturas"
    )
    os.makedirs(folder, exist_ok=True)

    timestamp = time.strftime(
        "%Y%m%d_%H%M%S"
    )
    acquisition_time = time.strftime(
        "%H:%M:%S"
    )
    scene = bpy.context.scene
    case_token = scene.get(
        "ottava_case_id",
        "CASE_01",
    )
    capture_token = (
        "AUTO"
        if auto_frame
        else "CAM"
    )
    filename = (
        f"OTTAVA_RX_{case_token}_{capture_token}_{timestamp}.png"
    )
    destination = os.path.join(
        folder,
        filename,
    )

    try:
        process_mode, process_result = process_xray_image(
            source,
            destination,
            auto_frame=auto_frame,
        )
    except Exception as error:
        print(
            "OTTAVA · error procesando RX:",
            error,
        )
        set_status(
            "RX · error de encuadre",
            3.0,
        )
        api_status(
            f"RX · error de encuadre: {error}"
        )
        return

    scene["ottava_capture_mode"] = process_mode
    scene["ottava_capture_crop"] = json.dumps(
        process_result.get("crop_box", [])
    )

    # Compartir RX con la API mediante archivo local atómico.
    try:
        write_shared_rx(
            destination,
            filename,
            acquisition_time,
        )
    except Exception as error:
        print(
            "OTTAVA · no se pudo compartir RX con app:",
            error,
        )

    try:
        image = bpy.data.images.load(
            destination,
            check_existing=False,
        )
    except Exception as error:
        print(
            "OTTAVA · error cargando RX:",
            error,
        )
        set_status(
            "RX guardada, pero no pudo mostrarse",
            2.5,
        )
        return

    monitor2 = area_by_pointer(
        RUNTIME["monitor2_area_ptr"]
    )
    if monitor2 is None:
        set_status(
            "RX guardada · Monitor 2 no localizado",
            2.5,
        )
        return

    monitor2.type = 'IMAGE_EDITOR'
    monitor2.spaces.active.image = image

    scene = bpy.context.scene
    scene["ottava_image_acquired"] = True
    scene["ottava_last_capture_path"] = destination
    scene["ottava_last_capture_time"] = acquisition_time
    scene["ottava_last_capture_filename"] = filename

    monitor2.tag_redraw()
    bpy.app.timers.register(
        lambda: fit_monitor2_image(monitor2),
        first_interval=0.15,
    )

    set_status(
        f"RX ADQUIRIDA · {acquisition_time}",
        2.5,
    )

    # Capa PACS posterior a la adquisición ya validada.
    store_capture_in_pacs(
        destination,
        acquisition_time,
    )


# ============================================================
# FEED LIVE HACIA EL TELÉFONO · V4.2
# ============================================================

def capture_camera_feed():
    """Feed estable para Blender 5.2.

    Usa la misma ruta OpenGL que ya funcionaba en V4.1, pero separada del
    timer de movimiento y escribiendo directamente al archivo local que sirve
    la API. Así preservamos la fluidez de V4.2 sin depender de screenshot().
    """
    if RUNTIME["camera_feed_busy"]:
        return

    window = get_main_window()
    monitor1 = area_by_pointer(
        RUNTIME["monitor1_area_ptr"]
    )
    if window is None or monitor1 is None:
        return

    region = get_window_region(monitor1)
    if region is None:
        return

    RUNTIME["camera_feed_busy"] = True
    scene = bpy.context.scene

    old_path = scene.render.filepath
    old_x = scene.render.resolution_x
    old_y = scene.render.resolution_y
    old_pct = scene.render.resolution_percentage
    old_format = scene.render.image_settings.file_format
    old_quality = scene.render.image_settings.quality

    temp_path = os.path.join(
        SHARED_TEMP,
        "ottava_camera_live_v421_tmp.jpg",
    )

    try:
        scene.render.filepath = temp_path
        scene.render.resolution_x = CAMERA_FEED_WIDTH
        scene.render.resolution_y = CAMERA_FEED_HEIGHT
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = 'JPEG'
        scene.render.image_settings.quality = CAMERA_FEED_QUALITY

        with bpy.context.temp_override(
            window=window,
            screen=window.screen,
            area=monitor1,
            region=region,
        ):
            if not bpy.ops.render.opengl.poll():
                return
            bpy.ops.render.opengl(
                write_still=True,
                view_context=True,
            )

        if os.path.exists(temp_path):
            os.replace(
                temp_path,
                CAMERA_FEED_FILE,
            )

    except Exception as error:
        print(
            "OTTAVA · feed cámara V4.2.1:",
            error,
        )

    finally:
        scene.render.filepath = old_path
        scene.render.resolution_x = old_x
        scene.render.resolution_y = old_y
        scene.render.resolution_percentage = old_pct
        scene.render.image_settings.file_format = old_format
        scene.render.image_settings.quality = old_quality
        RUNTIME["camera_feed_busy"] = False


def camera_feed_timer():
    if (
        namespace.get("OTTAVA_MASTER_GEN")
        != generation
    ):
        return None

    now = time.perf_counter()
    watch_recent = (
        now - RUNTIME.get("last_camera_watch_packet", 0.0)
        <= 2.2
    )

    if watch_recent:
        capture_camera_feed()

    return CAMERA_FEED_INTERVAL


# ============================================================
# PROCESAMIENTO DE MANDO MÓVIL
# ============================================================

def clamp_arm_values(values):
    return {
        key: clamp(
            float(values[key]),
            -1.0,
            1.0,
        )
        for key in ("H", "V", "D", "O")
    }


def process_arm_control(
    arm,
    command,
    dt,
):
    x = dz(command.get("x", 0.0))
    y = dz(command.get("y", 0.0))
    depth = dz(command.get("depth", 0.0))
    tool_control = dz(command.get("tool", 0.0))

    if not any((x, y, depth, tool_control)):
        return

    signs = ARM_AXIS_SIGN[arm]

    requested = ARM_STATE[arm].copy()
    requested["H"] += (
        x
        * signs["x"]
        * ARM_XY_RATE
        * dt
    )
    requested["V"] += (
        y
        * signs["y"]
        * ARM_XY_RATE
        * dt
    )
    requested["D"] += depth * ARM_DEPTH_RATE * dt
    requested["O"] += tool_control * ARM_TOOL_RATE * dt
    requested = clamp_arm_values(requested)

    move_arm_to_requested_values(
        arm,
        requested,
    )


def process_camera_control(command, dt):
    x = dz(command.get("x", 0.0))
    y = dz(command.get("y", 0.0))

    if not x and not y:
        return

    CAMERA_STATE["yaw"] = clamp(
        CAMERA_STATE["yaw"]
        + x
        * CAMERA_AXIS_SIGN["x"]
        * CAMERA_RATE_DEG
        * dt,
        -CAMERA_YAW_LIMIT_DEG,
        CAMERA_YAW_LIMIT_DEG,
    )
    CAMERA_STATE["pitch"] = clamp(
        CAMERA_STATE["pitch"]
        + y
        * CAMERA_AXIS_SIGN["y"]
        * CAMERA_RATE_DEG
        * dt,
        -CAMERA_PITCH_LIMIT_DEG,
        CAMERA_PITCH_LIMIT_DEG,
    )
    apply_camera_pose()


def process_table_control(command, dt):
    slide_input = dz(
        command.get("slide", 0.0)
    )
    tilt_input = dz(
        command.get("tilt", 0.0)
    )

    # Al soltar el control, validar una última vez la pose visual alcanzada.
    if not slide_input and not tilt_input:
        if RUNTIME[
            "table_was_moving"
        ]:
            target_slide = TABLE_STATE[
                "slide"
            ]
            target_tilt = TABLE_STATE[
                "tilt"
            ]

            move_table_to_requested(
                target_slide,
                target_tilt,
            )

            RUNTIME[
                "table_was_moving"
            ] = False
            RUNTIME[
                "last_table_safety_check"
            ] = time.perf_counter()

        return

    RUNTIME[
        "table_was_moving"
    ] = True

    requested_slide = clamp(
        TABLE_STATE["slide"]
        + slide_input
        * TABLE_SLIDE_RATE_MM
        * dt,
        -TABLE_SLIDE_LIMIT_MM,
        TABLE_SLIDE_LIMIT_MM,
    )
    requested_tilt = clamp(
        TABLE_STATE["tilt"]
        + tilt_input
        * TABLE_TILT_RATE_DEG
        * dt,
        -TABLE_TILT_LIMIT_DEG,
        TABLE_TILT_LIMIT_DEG,
    )

    now_perf = time.perf_counter()

    # Movimiento visual fluido en cada ciclo.
    apply_table_transform(
        requested_slide,
        requested_tilt,
    )

    # Validación completa periódica.
    if (
        now_perf
        -
        RUNTIME[
            "last_table_safety_check"
        ]
        >=
        TABLE_SAFETY_INTERVAL
    ):
        move_table_to_requested(
            requested_slide,
            requested_tilt,
        )
        RUNTIME[
            "last_table_safety_check"
        ] = now_perf


def initialize_sequences(state):
    RUNTIME["last_capture_seq"] = int(
        state.get("capture_seq", 0)
    )
    RUNTIME["last_new_sim_seq"] = int(
        state.get("new_sim_seq", 0)
    )
    RUNTIME["last_home_all_seq"] = int(
        state.get("home_all_seq", 0)
    )
    RUNTIME["last_table_center_seq"] = int(
        state.get("table_center_seq", 0)
    )

    arm_home = state.get(
        "arm_home_seq",
        {},
    )
    for key in APP_TO_ARM:
        RUNTIME["last_arm_home_seq"][key] = int(
            arm_home.get(key, 0)
        )

    jaw_seq = state.get(
        "jaw_seq",
        {},
    )
    for key in ("arm1", "arm2"):
        RUNTIME["last_jaw_seq"][key] = int(
            jaw_seq.get(key, 0)
        )

    RUNTIME["seq_initialized"] = True



def clear_active_study_in_blender():
    """Limpia sólo la sesión activa; no elimina DICOM ni estudios de Orthanc."""
    scene = bpy.context.scene

    keys = [
        "ottava_patient_name",
        "ottava_patient_id",
        "ottava_birth_date",
        "ottava_patient_sex",
        "ottava_study_description",
        "ottava_study_date",
        "ottava_study_time",
        "ottava_dicom_birth_date",
        "ottava_dicom_study_date",
        "ottava_dicom_study_time",
        "ottava_case_id",
        "ottava_case_label",
        "ottava_case_source",
        "ottava_last_capture_path",
        "ottava_last_capture_time",
        "ottava_last_capture_filename",
        "ottava_capture_mode",
        "ottava_capture_crop",
    ]
    for key in keys:
        try:
            del scene[key]
        except Exception:
            pass

    scene["ottava_image_acquired"] = False

    monitor2 = area_by_pointer(
        RUNTIME.get("monitor2_area_ptr", 0)
    )
    if monitor2 is not None:
        try:
            monitor2.type = 'IMAGE_EDITOR'
            monitor2.spaces.active.image = None
            monitor2.tag_redraw()
        except Exception:
            pass


def begin_new_simulation():
    """Reinicia posición/estudio activo y vuelve a abrir Admisión."""
    print("OTTAVA · NUEVA SIMULACIÓN solicitada")
    set_status("NUEVA SIMULACIÓN · preparando admisión", 3.0)
    api_status("NUEVA SIMULACIÓN · preparando admisión")

    # Estado mecánico conocido y seguro.
    home_all()
    try:
        jaw_action("Arm_01", "CLOSE")
        jaw_action("Arm_02", "CLOSE")
    except Exception as error:
        print("OTTAVA · aviso reiniciando pinzas:", error)

    clear_active_study_in_blender()

    # Abrir el formulario desde un timer evita invocarlo dentro del timer de acciones.
    bpy.app.timers.register(
        show_form,
        first_interval=0.25,
    )


def process_actions(state):
    if not RUNTIME["seq_initialized"]:
        initialize_sequences(state)
        return

    # V4.5:
    # Los contadores sólo disparan acciones cuando AVANZAN.
    # Si la API se reinicia, sus secuencias vuelven a 0. Antes Blender
    # interpretaba ese descenso como una nueva acción y podía disparar
    # automáticamente CAPTURAR RX al iniciar Terminal.
    #
    # Ahora:
    # incoming < last  -> resincronizar, NO ejecutar.
    # incoming == last -> nada.
    # incoming > last  -> ejecutar exactamente una vez.

    new_sim_seq = int(
        state.get("new_sim_seq", 0)
    )
    if new_sim_seq < RUNTIME["last_new_sim_seq"]:
        RUNTIME["last_new_sim_seq"] = new_sim_seq
    elif new_sim_seq > RUNTIME["last_new_sim_seq"]:
        RUNTIME["last_new_sim_seq"] = new_sim_seq
        begin_new_simulation()

    capture_seq = int(
        state.get("capture_seq", 0)
    )
    if capture_seq < RUNTIME["last_capture_seq"]:
        RUNTIME["last_capture_seq"] = capture_seq
    elif capture_seq > RUNTIME["last_capture_seq"]:
        RUNTIME["last_capture_seq"] = capture_seq
        acquire_full_xray(
            auto_frame=bool(
                state.get(
                    "capture_auto_frame",
                    False,
                )
            )
        )

    home_all_seq = int(
        state.get("home_all_seq", 0)
    )
    if home_all_seq < RUNTIME["last_home_all_seq"]:
        RUNTIME["last_home_all_seq"] = home_all_seq
    elif home_all_seq > RUNTIME["last_home_all_seq"]:
        RUNTIME["last_home_all_seq"] = home_all_seq
        home_all()

    table_center_seq = int(
        state.get("table_center_seq", 0)
    )
    if table_center_seq < RUNTIME["last_table_center_seq"]:
        RUNTIME["last_table_center_seq"] = table_center_seq
    elif table_center_seq > RUNTIME["last_table_center_seq"]:
        RUNTIME["last_table_center_seq"] = table_center_seq
        center_table()

    arm_home = state.get(
        "arm_home_seq",
        {},
    )
    for key, arm in APP_TO_ARM.items():
        seq = int(arm_home.get(key, 0))
        last = RUNTIME["last_arm_home_seq"][key]

        if seq < last:
            RUNTIME["last_arm_home_seq"][key] = seq
        elif seq > last:
            RUNTIME["last_arm_home_seq"][key] = seq
            home_arm(arm)

    jaw_seq = state.get("jaw_seq", {})
    jaw_state = state.get("jaw_action", {})

    for key in ("arm1", "arm2"):
        seq = int(jaw_seq.get(key, 0))
        last = RUNTIME["last_jaw_seq"][key]

        if seq < last:
            RUNTIME["last_jaw_seq"][key] = seq
        elif seq > last:
            RUNTIME["last_jaw_seq"][key] = seq
            jaw_action(
                APP_TO_ARM[key],
                jaw_state.get(key, "CLOSE"),
            )


# ============================================================
# ACCIONES DISCRETAS · CANAL LOCAL FIABLE
# ============================================================

def action_timer():
    if (
        namespace.get("OTTAVA_MASTER_GEN")
        != generation
    ):
        return None

    # Fuente autoritativa: HTTP local. El archivo compartido queda de respaldo.
    action_state = fetch_action_state_http()

    if action_state is None:
        action_state = read_action_state()

    if action_state is not None:
        RUNTIME["action_emergency_stop"] = bool(
            action_state.get("emergency_stop", False)
        )
        process_actions(action_state)

    return 0.10


# ============================================================
# TIMER PRINCIPAL
# ============================================================

def control_timer():
    if (
        namespace.get("OTTAVA_MASTER_GEN")
        != generation
    ):
        return None

    now_perf = time.perf_counter()
    now_wall = time.time()
    dt = min(
        now_perf - RUNTIME["last_time"],
        0.050,
    )
    RUNTIME["last_time"] = now_perf

    # Recibir la orden más reciente sin bloquear el hilo de Blender.
    state = receive_latest_udp_state()

    if state is None:
        return CONTROL_INTERVAL

    # Respaldo adicional: las secuencias también viajan en los paquetes UDP.
    # process_actions compara contadores, por lo que no duplica acciones.
    process_actions(state)

    command_fresh = (
        now_perf - RUNTIME["last_udp_packet"]
        <= CONTROL_DEADMAN
    )
    emergency = bool(
        state.get("emergency_stop", False)
        or RUNTIME.get("action_emergency_stop", False)
    )

    # Dead-man: si desaparece la app o la Wi-Fi, no se conserva una orden
    # de joystick antigua.
    if command_fresh and not emergency:
        arms = state.get("arms", {})
        for app_key, arm in APP_TO_ARM.items():
            process_arm_control(
                arm,
                arms.get(app_key, {}),
                dt,
            )

        process_camera_control(
            state.get("camera", {}),
            dt,
        )
        process_table_control(
            state.get("table", {}),
            dt,
        )

    # El estado hacia la app es de baja frecuencia y no interviene en el
    # lazo de movimiento.
    if (
        now_wall - RUNTIME["last_status_push"]
        >= 1.0
    ):
        if emergency:
            message = "STOP ACTIVO · movimientos bloqueados"
        elif not command_fresh:
            message = "CONTROL EN ESPERA · señal móvil no recibida"
        elif now_wall <= RUNTIME["status_until"]:
            message = RUNTIME["status_message"]
        else:
            message = (
                "SEGURIDAD ACTIVA · TWIN MOTION ACTIVO · 50 Hz"
            )
        api_status(message)
        RUNTIME["last_status_push"] = now_wall

    monitor2 = area_by_pointer(
        RUNTIME["monitor2_area_ptr"]
    )
    if monitor2 is not None:
        monitor2.tag_redraw()

    return CONTROL_INTERVAL


def start_receiver():
    if (
        namespace.get(
            "OTTAVA_MASTER_RECEIVER_STARTED"
        )
        == generation
    ):
        return

    namespace[
        "OTTAVA_MASTER_RECEIVER_STARTED"
    ] = generation

    RUNTIME["last_time"] = time.perf_counter()
    RUNTIME["last_status_push"] = 0.0
    RUNTIME["last_udp_packet"] = 0.0
    RUNTIME["last_camera_watch_packet"] = 0.0
    RUNTIME["latest_state"] = None
    RUNTIME["last_action_file_version"] = 0
    RUNTIME["action_emergency_stop"] = False
    RUNTIME["seq_initialized"] = False
    RUNTIME["last_table_safety_check"] = 0.0
    RUNTIME["table_was_moving"] = False

    # V4.3.5:
    # Inicializar las secuencias AHORA, antes de que el usuario pulse
    # cualquier botón. En V4.2.1, la primera acción recibida se usaba
    # únicamente para inicializar estos contadores y se descartaba.
    initial_actions = fetch_action_state_http()

    if initial_actions is None:
        initial_actions = read_action_state()

    if initial_actions is not None:
        initialize_sequences(
            initial_actions
        )
        RUNTIME[
            "action_emergency_stop"
        ] = bool(
            initial_actions.get(
                "emergency_stop",
                False,
            )
        )

        try:
            RUNTIME[
                "last_action_file_version"
            ] = os.stat(
                ACTION_STATE_FILE
            ).st_mtime_ns
        except OSError:
            pass

        print(
            "✓ Secuencias de acciones inicializadas"
        )

    bpy.app.timers.register(
        control_timer,
        first_interval=0.05,
        persistent=True,
    )
    bpy.app.timers.register(
        action_timer,
        first_interval=0.08,
        persistent=True,
    )
    bpy.app.timers.register(
        camera_feed_timer,
        first_interval=0.30,
        persistent=True,
    )

    print(
        "✓ Receptor móvil MASTER FINAL activado · casos RX + encuadre/autoencuadre + DICOM/PACS"
    )


# ============================================================
# FORMULARIO DE ADMISIÓN
# ============================================================

class OTTAVA_OT_patient_admission(
    bpy.types.Operator
):
    bl_idname = "ottava.patient_admission"
    bl_label = "Admisión del paciente"

    patient_name: StringProperty(
        name="Nombre del paciente",
        default="",
    )
    patient_id: StringProperty(
        name="ID del paciente",
        default="OTTAVA-",
    )
    birth_date: StringProperty(
        name="Fecha de nacimiento",
        description="DD/MM/AAAA o DD-MM-AAAA",
        default="",
    )
    patient_sex: EnumProperty(
        name="Sexo",
        items=[
            ("M", "Masculino", ""),
            ("F", "Femenino", ""),
            ("O", "Otro", ""),
        ],
        default="M",
    )
    study_description: StringProperty(
        name="Descripción del estudio",
        default="Radiografía de tórax",
    )
    study_date: StringProperty(
        name="Fecha del estudio",
        description="DD/MM/AAAA",
        default="",
    )
    study_time: StringProperty(
        name="Hora del estudio",
        description="HH:MM:SS",
        default="",
    )
    study_case: EnumProperty(
        name="Caso de estudio",
        description="Selecciona la radiografía asociada a la simulación",
        items=STUDY_CASE_ITEMS,
        default="CASE_01",
    )

    def invoke(self, context, event):
        date_now, time_now = now_values()
        scene = context.scene

        self.patient_name = scene.get(
            "ottava_patient_name",
            "",
        )
        self.patient_id = scene.get(
            "ottava_patient_id",
            "OTTAVA-",
        )
        self.birth_date = scene.get(
            "ottava_birth_date",
            "",
        )
        self.patient_sex = scene.get(
            "ottava_patient_sex",
            "M",
        )
        self.study_description = scene.get(
            "ottava_study_description",
            "Radiografía de tórax",
        )
        self.study_date = date_now
        self.study_time = time_now
        self.study_case = scene.get(
            "ottava_case_id",
            "CASE_01",
        )
        if self.study_case not in STUDY_CASES:
            self.study_case = "CASE_01"

        return (
            context.window_manager.invoke_props_dialog(
                self,
                width=480,
                title="OTTAVA · Admisión del paciente",
                confirm_text="INICIAR SIMULACIÓN",
            )
        )

    def draw(self, context):
        layout = self.layout

        patient_box = layout.box()
        patient_box.label(
            text="DATOS DEL PACIENTE",
            icon='USER',
        )
        patient_box.prop(
            self,
            "patient_name",
        )
        patient_box.prop(
            self,
            "patient_id",
        )
        patient_box.prop(
            self,
            "birth_date",
        )
        patient_box.prop(
            self,
            "patient_sex",
        )

        study_box = layout.box()
        study_box.label(
            text="DATOS DEL ESTUDIO",
            icon='IMAGE_DATA',
        )
        study_box.prop(
            self,
            "study_description",
        )
        row = study_box.row(align=True)
        row.prop(self, "study_date")
        row.prop(self, "study_time")

        case_box = layout.box()
        case_box.label(
            text="CASO DE ESTUDIO",
            icon='FILE_IMAGE',
        )
        case_box.prop(
            self,
            "study_case",
            text="Radiografía",
        )

    def execute(self, context):
        if not self.patient_name.strip():
            self.report(
                {'ERROR'},
                "Ingresa el nombre del paciente.",
            )
            return {'CANCELLED'}

        if not self.patient_id.strip():
            self.report(
                {'ERROR'},
                "Ingresa el ID del paciente.",
            )
            return {'CANCELLED'}

        if not self.birth_date.strip():
            self.report(
                {'ERROR'},
                "Ingresa la fecha de nacimiento.",
            )
            return {'CANCELLED'}

        birth_dicom = parse_date_dicom(
            self.birth_date
        )
        study_date_dicom = parse_date_dicom(
            self.study_date
        )
        study_time_dicom = parse_time_dicom(
            self.study_time
        )

        if not birth_dicom:
            self.report(
                {'ERROR'},
                "Fecha de nacimiento inválida. Usa DD/MM/AAAA.",
            )
            return {'CANCELLED'}
        if not study_date_dicom:
            self.report(
                {'ERROR'},
                "Fecha del estudio inválida.",
            )
            return {'CANCELLED'}
        if not study_time_dicom:
            self.report(
                {'ERROR'},
                "Hora del estudio inválida.",
            )
            return {'CANCELLED'}

        # Activar la radiografía seleccionada sin mover ni escalar el overlay.
        try:
            apply_study_case(
                self.study_case
            )
        except Exception as error:
            self.report(
                {'ERROR'},
                str(error),
            )
            return {'CANCELLED'}

        scene = context.scene
        scene["ottava_patient_name"] = self.patient_name.strip()
        scene["ottava_patient_id"] = self.patient_id.strip()
        scene["ottava_birth_date"] = self.birth_date.strip()
        scene["ottava_patient_sex"] = self.patient_sex
        scene["ottava_study_description"] = self.study_description.strip()
        scene["ottava_study_date"] = self.study_date.strip()
        scene["ottava_study_time"] = self.study_time.strip()
        scene["ottava_case_id"] = self.study_case
        scene["ottava_case_label"] = STUDY_CASES[self.study_case]["label"]
        scene["ottava_case_source"] = study_case_path(self.study_case)

        scene["ottava_dicom_birth_date"] = birth_dicom
        scene["ottava_dicom_study_date"] = study_date_dicom
        scene["ottava_dicom_study_time"] = study_time_dicom
        scene["ottava_image_acquired"] = False

        bpy.app.timers.register(
            build_or_repair_layout,
            first_interval=0.45,
        )

        return {'FINISHED'}


# ============================================================
# ARRANQUE
# ============================================================

def show_form():
    window = get_main_window()
    if window is None:
        return None

    area = largest_view3d(window)
    if area is None:
        print(
            "OTTAVA: no encontré Viewport 3D en Genérico"
        )
        return None

    region = get_window_region(area)
    if region is None:
        return None

    with bpy.context.temp_override(
        window=window,
        screen=window.screen,
        area=area,
        region=region,
    ):
        bpy.ops.ottava.patient_admission(
            'INVOKE_DEFAULT'
        )
    return None


def prepare_workspace():
    window = get_main_window()
    if window is None:
        return None

    # MASTER FINAL · inicio limpio.
    # El .blend puede conservar propiedades personalizadas de la última sesión.
    # Se limpian únicamente paciente/estudio/RX activos antes de abrir Admisión.
    # No genera capturas, no mueve el sistema y no elimina estudios de Orthanc.
    clear_active_study_in_blender()

    workspace = find_main_workspace()
    if workspace:
        window.workspace = workspace
        print(
            "OTTAVA · workspace =",
            workspace.name,
        )

    bpy.app.timers.register(
        show_form,
        first_interval=0.50,
    )
    return None


def print_ready():
    print("")
    print("=" * 58)
    print("OTTAVA FASE 3 · MASTER FINAL")
    print("=" * 58)
    print("✓ ARM 1 / ARM 2 / ARM 3 / ARM 4")
    print("✓ Profundidad + orientación de herramienta")
    print("✓ Pinzas ARM 1 / ARM 2")
    print("✓ Collision Guard BVH")
    print("✓ Camilla + Twin Motion")
    print("✓ Cámara ARM 03 + feed móvil")
    print("✓ Monitor clínico + captura RX")
    print("=" * 58)


old_class = getattr(
    bpy.types,
    "OTTAVA_OT_patient_admission",
    None,
)
if old_class:
    try:
        bpy.utils.unregister_class(old_class)
    except Exception:
        pass

bpy.utils.register_class(
    OTTAVA_OT_patient_admission
)

print("")
print("=" * 58)
print("OTTAVA FASE 3 · MASTER FINAL")
print("Preparando control integral...")
print("=" * 58)

bpy.app.timers.register(
    prepare_workspace,
    first_interval=0.20,
)
