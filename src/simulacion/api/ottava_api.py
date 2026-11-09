from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from pathlib import Path
from datetime import datetime
import json
import io
import os
import socket
import tempfile
import time
import uvicorn
import urllib.request
import urllib.error
import traceback
import shutil
import urllib.parse

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image as RLImage,
    KeepTogether,
)
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid
import pydicom

BASE_DIR = Path(__file__).resolve().parent
INDEX_FILE = BASE_DIR / "index.html"

app = FastAPI(title="OTTAVA MASTER FINAL · Casos RX + Autoencuadre")

ARM_IDS = ("arm1", "arm2", "arm3", "arm4")
UDP_TARGET = ("127.0.0.1", 8766)
UDP_SOCKET = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

SHARED_TEMP = Path(tempfile.gettempdir())
CAMERA_FILE = SHARED_TEMP / "ottava_camera_live_v421.jpg"
RX_FILE = SHARED_TEMP / "ottava_rx_latest_v421.png"
RX_META_FILE = SHARED_TEMP / "ottava_rx_meta_v421.json"
ACTION_FILE = SHARED_TEMP / "ottava_actions_v421.json"

ORTHANC_BASE = os.environ.get(
    "OTTAVA_ORTHANC_URL",
    "http://127.0.0.1:8042"
).rstrip("/")

DX_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.1.1"


AI_MODEL_NAME = "densenet121-res224-all"
AI_RESULTS_DIR = BASE_DIR / "OTTAVA_AI_RESULTS"
AI_RESULTS_DIR.mkdir(exist_ok=True)

RECORDS_DIR = BASE_DIR / "OTTAVA_RECORDS"
RECORDS_DIR.mkdir(exist_ok=True)

RECORD_IMAGES_DIR = RECORDS_DIR / "images"
RECORD_IMAGES_DIR.mkdir(exist_ok=True)

REPORTS_DIR = BASE_DIR / "OTTAVA_REPORTS"
REPORTS_DIR.mkdir(exist_ok=True)

OHIF_PORT = int(
    os.environ.get("OTTAVA_OHIF_PORT", "3000")
)

# Modelo lazy-loaded: la API puede arrancar aunque TorchXRayVision
# todavía no haya sido usado en esta sesión.
_AI_MODEL = None
_AI_DEVICE = None
_AI_XRV = None
_AI_TORCH = None
_AI_TORCHVISION = None

# Segmentación anatómica PSPNet · TorchXRayVision
_SEG_MODEL = None
_SEG_DEVICE = None

SEGMENTATION_TARGETS = [
    "Left Clavicle",
    "Right Clavicle",
    "Left Scapula",
    "Right Scapula",
    "Left Lung",
    "Right Lung",
    "Left Hilus Pulmonis",
    "Right Hilus Pulmonis",
    "Heart",
    "Aorta",
    "Facies Diaphragmatica",
    "Mediastinum",
    "Weasand",
    "Spine",
]

# Colores RGB para overlay. Una paleta fija permite comparar estudios.
SEGMENTATION_COLORS = [
    (250, 196, 70),
    (255, 151, 72),
    (178, 132, 255),
    (220, 105, 234),
    (65, 184, 255),
    (64, 224, 190),
    (78, 135, 255),
    (73, 196, 238),
    (255, 91, 112),
    (255, 159, 70),
    (102, 226, 129),
    (190, 112, 255),
    (241, 210, 83),
    (132, 177, 255),
]


def arm_state():
    return {"x": 0.0, "y": 0.0, "depth": 0.0, "tool": 0.0}


state = {
    "arms": {arm: arm_state() for arm in ARM_IDS},
    "camera": {"x": 0.0, "y": 0.0},
    "table": {"slide": 0.0, "tilt": 0.0},

    "capture_seq": 0,
    "new_sim_seq": 0,
    "capture_auto_frame": False,
    "home_all_seq": 0,
    "arm_home_seq": {arm: 0 for arm in ARM_IDS},
    "table_center_seq": 0,
    "jaw_seq": {"arm1": 0, "arm2": 0},
    "jaw_action": {"arm1": "CLOSE", "arm2": "CLOSE"},

    "stop_seq": 0,
    "resume_seq": 0,
    "emergency_stop": False,

    "blender_connected": False,
    "blender_message": "Esperando Blender...",
    "blender_last_seen": 0.0,

    "camera_watch_last_seen": 0.0,

    "orthanc_connected": False,
    "orthanc_last_check": 0.0,
    "orthanc_name": "",

    # IA integrada
    "ai_status": "idle",
    "ai_message": "Esperando estudio",
    "ai_model": AI_MODEL_NAME,
    "ai_instance_id": "",
    "ai_results": [],
    "ai_result_file": "",
    "ai_error": "",
    "ai_updated_at": 0.0,
    "last_orthanc_instance_id": "",

    # Segmentación anatómica
    "segmentation_status": "idle",
    "segmentation_message": "Esperando estudio",
    "segmentation_image": "",
    "segmentation_version": 0,
    "segmentation_targets": SEGMENTATION_TARGETS,
    "segmentation_error": "",

    # Componente 5 · expediente
    "current_exam": {},
    "record_original_image": "",
    "record_original_version": 0,
    "record_observation": {
        "professional_name": "",
        "professional_role": "Radiólogo",
        "observations": "",
        "saved_at": "",
    },
    "record_last_report": "",
}


class ArmPacket(BaseModel):
    x: float = 0.0
    y: float = 0.0
    depth: float = 0.0
    tool: float = 0.0


class CameraPacket(BaseModel):
    x: float = 0.0
    y: float = 0.0


class TablePacket(BaseModel):
    slide: float = 0.0
    tilt: float = 0.0


class ControlPacket(BaseModel):
    arm1: ArmPacket = Field(default_factory=ArmPacket)
    arm2: ArmPacket = Field(default_factory=ArmPacket)
    arm3: ArmPacket = Field(default_factory=ArmPacket)
    arm4: ArmPacket = Field(default_factory=ArmPacket)
    camera: CameraPacket = Field(default_factory=CameraPacket)
    table: TablePacket = Field(default_factory=TablePacket)


class BlenderStatus(BaseModel):
    message: str = "Blender conectado"


class DicomStoreRequest(BaseModel):
    image_path: str
    output_dir: str
    patient_name: str
    patient_id: str
    patient_birth_date: str = ""
    patient_sex: str = "O"
    study_description: str = "Radiografía de tórax"
    study_date: str
    study_time: str
    acquisition_time_display: str = ""


class RxProcessRequest(BaseModel):
    image_path: str
    output_path: str
    crop_box: list[float] = Field(
        default_factory=lambda: [0.0, 0.0, 1.0, 1.0]
    )
    auto_frame: bool = False



class ObservationRequest(BaseModel):
    professional_name: str = ""
    professional_role: str = "Radiólogo"
    observations: str = ""



def format_dicom_date(value):
    value = str(value or "").strip()
    if len(value) == 8 and value.isdigit():
        return f"{value[6:8]}/{value[4:6]}/{value[0:4]}"
    return value


def format_dicom_time(value):
    value = str(value or "").strip()
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) >= 6:
        return f"{digits[0:2]}:{digits[2:4]}:{digits[4:6]}"
    if len(digits) >= 4:
        return f"{digits[0:2]}:{digits[2:4]}"
    return value


def calculate_age(birth_date, study_date):
    try:
        birth = datetime.strptime(
            str(birth_date),
            "%Y%m%d",
        ).date()
        study = datetime.strptime(
            str(study_date),
            "%Y%m%d",
        ).date()
        years = (
            study.year
            -
            birth.year
            -
            (
                (study.month, study.day)
                <
                (birth.month, birth.day)
            )
        )
        return max(0, years)
    except Exception:
        return None


def safe_record_key(study_uid):
    value = str(study_uid or "").strip()
    if not value:
        return "unknown"
    return "".join(
        ch
        if ch.isalnum() or ch in "._-"
        else "_"
        for ch in value
    )


def observation_file_for(study_uid):
    return (
        RECORDS_DIR
        /
        f"OBS_{safe_record_key(study_uid)}.json"
    )


def load_observation_for(study_uid):
    default = {
        "professional_name": "",
        "professional_role": "Radiólogo",
        "observations": "",
        "saved_at": "",
    }

    path = observation_file_for(
        study_uid
    )

    if not path.exists():
        return default

    try:
        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        return {
            "professional_name": str(
                data.get(
                    "professional_name",
                    ""
                )
            ),
            "professional_role": str(
                data.get(
                    "professional_role",
                    "Radiólogo"
                )
            ),
            "observations": str(
                data.get(
                    "observations",
                    ""
                )
            ),
            "saved_at": str(
                data.get(
                    "saved_at",
                    ""
                )
            ),
        }

    except Exception:
        return default


def current_ohif_url():
    exam = state.get(
        "current_exam",
        {}
    )
    uid = str(
        exam.get(
            "study_instance_uid",
            ""
        )
    ).strip()

    base = (
        f"http://{local_ip()}:{OHIF_PORT}"
    )

    if not uid:
        return base

    return (
        base
        +
        "/viewer?StudyInstanceUIDs="
        +
        urllib.parse.quote(
            uid,
            safe="."
        )
    )


def set_current_exam_from_dicom(
    dicom_path,
    orthanc_instance_id="",
    orthanc_study_id="",
):
    ds = pydicom.dcmread(
        str(dicom_path),
        stop_before_pixels=True,
    )

    birth_date = str(
        getattr(
            ds,
            "PatientBirthDate",
            "",
        )
    )
    study_date = str(
        getattr(
            ds,
            "StudyDate",
            "",
        )
    )

    age = calculate_age(
        birth_date,
        study_date,
    )

    exam = {
        "patient_name": str(
            getattr(
                ds,
                "PatientName",
                "",
            )
        ),
        "patient_id": str(
            getattr(
                ds,
                "PatientID",
                "",
            )
        ),
        "patient_birth_date": birth_date,
        "patient_birth_date_display": format_dicom_date(
            birth_date
        ),
        "patient_age": age,
        "patient_sex": str(
            getattr(
                ds,
                "PatientSex",
                "",
            )
        ),
        "study_description": str(
            getattr(
                ds,
                "StudyDescription",
                "",
            )
        ),
        "study_date": study_date,
        "study_date_display": format_dicom_date(
            study_date
        ),
        "study_time": str(
            getattr(
                ds,
                "StudyTime",
                "",
            )
        ),
        "study_time_display": format_dicom_time(
            getattr(
                ds,
                "StudyTime",
                "",
            )
        ),
        "modality": str(
            getattr(
                ds,
                "Modality",
                "",
            )
        ),
        "accession_number": str(
            getattr(
                ds,
                "AccessionNumber",
                "",
            )
        ),
        "study_id": str(
            getattr(
                ds,
                "StudyID",
                "",
            )
        ),
        "study_instance_uid": str(
            getattr(
                ds,
                "StudyInstanceUID",
                "",
            )
        ),
        "series_instance_uid": str(
            getattr(
                ds,
                "SeriesInstanceUID",
                "",
            )
        ),
        "sop_instance_uid": str(
            getattr(
                ds,
                "SOPInstanceUID",
                "",
            )
        ),
        "orthanc_instance_id": str(
            orthanc_instance_id or ""
        ),
        "orthanc_study_id": str(
            orthanc_study_id or ""
        ),
    }

    state["current_exam"] = exam
    state["record_observation"] = (
        load_observation_for(
            exam[
                "study_instance_uid"
            ]
        )
    )

    return exam


def persist_original_image(
    source_path,
    instance_id,
):
    source = Path(
        source_path
    ).expanduser().resolve()

    if not source.exists():
        return ""

    target = (
        RECORD_IMAGES_DIR
        /
        f"ORIGINAL_{instance_id}.png"
    )

    with Image.open(source) as img:
        img.convert("L").save(
            target,
            format="PNG",
        )

    state["record_original_image"] = str(
        target
    )
    state["record_original_version"] = int(
        time.time_ns()
    )

    return str(target)


def build_report_pdf():
    exam = state.get(
        "current_exam",
        {}
    )

    if not exam:
        raise RuntimeError(
            "No hay un expediente activo."
        )

    patient_id = (
        exam.get(
            "patient_id",
            "SIN_ID"
        )
        or
        "SIN_ID"
    )

    token = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    report_path = (
        REPORTS_DIR
        /
        f"OTTAVA_REPORTE_{safe_record_key(patient_id)}_{token}.pdf"
    )

    doc = SimpleDocTemplate(
        str(report_path),
        pagesize=letter,
        rightMargin=42,
        leftMargin=42,
        topMargin=42,
        bottomMargin=42,
        title="OTTAVA - Reporte de análisis",
        author="OTTAVA Simulator",
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "OTTAVA_Title",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        alignment=TA_CENTER,
        textColor=colors.HexColor(
            "#17324D"
        ),
        spaceAfter=6,
    )

    subtitle_style = ParagraphStyle(
        "OTTAVA_Subtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        alignment=TA_CENTER,
        textColor=colors.HexColor(
            "#667788"
        ),
        spaceAfter=16,
    )

    heading_style = ParagraphStyle(
        "OTTAVA_Heading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=colors.HexColor(
            "#17324D"
        ),
        spaceBefore=10,
        spaceAfter=6,
    )

    body_style = ParagraphStyle(
        "OTTAVA_Body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor(
            "#202A34"
        ),
    )

    note_style = ParagraphStyle(
        "OTTAVA_Note",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor(
            "#6C737A"
        ),
        spaceBefore=12,
    )

    story = []

    story.append(
        Paragraph(
            "OTTAVA - REPORTE DE ANALISIS",
            title_style,
        )
    )
    story.append(
        Paragraph(
            "Sistema asistido por robot - Imagenologia DICOM e Inteligencia Artificial",
            subtitle_style,
        )
    )

    patient_data = [
        [
            "Paciente",
            exam.get(
                "patient_name",
                ""
            ),
            "ID",
            exam.get(
                "patient_id",
                ""
            ),
        ],
        [
            "Nacimiento",
            exam.get(
                "patient_birth_date_display",
                ""
            ),
            "Edad",
            (
                str(
                    exam.get(
                        "patient_age",
                        ""
                    )
                )
                +
                " años"
                if
                exam.get(
                    "patient_age"
                )
                is not None
                else
                ""
            ),
        ],
        [
            "Sexo",
            exam.get(
                "patient_sex",
                ""
            ),
            "Modalidad",
            exam.get(
                "modality",
                ""
            ),
        ],
    ]

    patient_table = Table(
        patient_data,
        colWidths=[
            0.9 * inch,
            2.1 * inch,
            0.8 * inch,
            2.1 * inch,
        ],
    )

    patient_table.setStyle(
        TableStyle([
            (
                "BACKGROUND",
                (0, 0),
                (-1, -1),
                colors.HexColor(
                    "#F4F7FA"
                ),
            ),
            (
                "TEXTCOLOR",
                (0, 0),
                (0, -1),
                colors.HexColor(
                    "#526274"
                ),
            ),
            (
                "TEXTCOLOR",
                (2, 0),
                (2, -1),
                colors.HexColor(
                    "#526274"
                ),
            ),
            (
                "FONTNAME",
                (0, 0),
                (0, -1),
                "Helvetica-Bold",
            ),
            (
                "FONTNAME",
                (2, 0),
                (2, -1),
                "Helvetica-Bold",
            ),
            (
                "FONTNAME",
                (1, 0),
                (1, -1),
                "Helvetica",
            ),
            (
                "FONTNAME",
                (3, 0),
                (3, -1),
                "Helvetica",
            ),
            (
                "FONTSIZE",
                (0, 0),
                (-1, -1),
                8.5,
            ),
            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.35,
                colors.HexColor(
                    "#D8E0E7"
                ),
            ),
            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "MIDDLE",
            ),
            (
                "LEFTPADDING",
                (0, 0),
                (-1, -1),
                7,
            ),
            (
                "RIGHTPADDING",
                (0, 0),
                (-1, -1),
                7,
            ),
            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                6,
            ),
            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                6,
            ),
        ])
    )

    story.append(
        Paragraph(
            "Datos del paciente",
            heading_style,
        )
    )
    story.append(
        patient_table
    )

    study_data = [
        [
            "Estudio",
            exam.get(
                "study_description",
                ""
            ),
        ],
        [
            "Fecha / hora",
            (
                exam.get(
                    "study_date_display",
                    ""
                )
                +
                "  "
                +
                exam.get(
                    "study_time_display",
                    ""
                )
            ).strip(),
        ],
        [
            "Accession Number",
            exam.get(
                "accession_number",
                ""
            ),
        ],
        [
            "Study ID",
            exam.get(
                "study_id",
                ""
            ),
        ],
        [
            "StudyInstanceUID",
            exam.get(
                "study_instance_uid",
                ""
            ),
        ],
    ]

    study_table = Table(
        study_data,
        colWidths=[
            1.3 * inch,
            4.7 * inch,
        ],
    )

    study_table.setStyle(
        TableStyle([
            (
                "BACKGROUND",
                (0, 0),
                (0, -1),
                colors.HexColor(
                    "#EEF4F8"
                ),
            ),
            (
                "FONTNAME",
                (0, 0),
                (0, -1),
                "Helvetica-Bold",
            ),
            (
                "FONTNAME",
                (1, 0),
                (1, -1),
                "Helvetica",
            ),
            (
                "FONTSIZE",
                (0, 0),
                (-1, -1),
                8,
            ),
            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.35,
                colors.HexColor(
                    "#D8E0E7"
                ),
            ),
            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "TOP",
            ),
            (
                "LEFTPADDING",
                (0, 0),
                (-1, -1),
                7,
            ),
            (
                "RIGHTPADDING",
                (0, 0),
                (-1, -1),
                7,
            ),
            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                5,
            ),
            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                5,
            ),
        ])
    )

    story.append(
        Paragraph(
            "Datos del estudio",
            heading_style,
        )
    )
    story.append(
        study_table
    )

    original_path = Path(
        state.get(
            "record_original_image",
            ""
        )
    )
    seg_path = Path(
        state.get(
            "segmentation_image",
            ""
        )
    )

    image_cells = []

    if original_path.exists():
        image_cells.append(
            RLImage(
                str(original_path),
                width=2.75 * inch,
                height=2.75 * inch,
                kind="proportional",
            )
        )
    else:
        image_cells.append(
            Paragraph(
                "RX original no disponible",
                body_style,
            )
        )

    if seg_path.exists():
        image_cells.append(
            RLImage(
                str(seg_path),
                width=2.75 * inch,
                height=2.75 * inch,
                kind="proportional",
            )
        )
    else:
        image_cells.append(
            Paragraph(
                "Segmentación no disponible",
                body_style,
            )
        )

    image_table = Table(
        [
            [
                Paragraph(
                    "<b>RX ORIGINAL</b>",
                    body_style,
                ),
                Paragraph(
                    "<b>SEGMENTACION ANATOMICA</b>",
                    body_style,
                ),
            ],
            image_cells,
        ],
        colWidths=[
            3.0 * inch,
            3.0 * inch,
        ],
    )

    image_table.setStyle(
        TableStyle([
            (
                "ALIGN",
                (0, 0),
                (-1, -1),
                "CENTER",
            ),
            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "MIDDLE",
            ),
            (
                "BOX",
                (0, 0),
                (-1, -1),
                0.4,
                colors.HexColor(
                    "#D8E0E7"
                ),
            ),
            (
                "INNERGRID",
                (0, 0),
                (-1, -1),
                0.3,
                colors.HexColor(
                    "#E2E8ED"
                ),
            ),
            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.HexColor(
                    "#F4F7FA"
                ),
            ),
            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                6,
            ),
            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                6,
            ),
        ])
    )

    story.append(
        Paragraph(
            "Imagenología",
            heading_style,
        )
    )
    story.append(
        image_table
    )

    ai_rows = [
        [
            Paragraph(
                "<b>Hallazgo / patología</b>",
                body_style,
            ),
            Paragraph(
                "<b>Score</b>",
                body_style,
            ),
        ]
    ]

    for item in (
        state.get(
            "ai_results",
            []
        )[:5]
    ):
        ai_rows.append([
            str(
                item.get(
                    "pathology",
                    ""
                )
            ),
            f'{float(item.get("score", 0.0)):.4f}',
        ])

    if len(ai_rows) == 1:
        ai_rows.append([
            "Sin resultados disponibles",
            "-",
        ])

    ai_table = Table(
        ai_rows,
        colWidths=[
            4.7 * inch,
            1.3 * inch,
        ],
    )

    ai_table.setStyle(
        TableStyle([
            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.HexColor(
                    "#EAF3FA"
                ),
            ),
            (
                "FONTNAME",
                (0, 0),
                (-1, 0),
                "Helvetica-Bold",
            ),
            (
                "FONTNAME",
                (0, 1),
                (-1, -1),
                "Helvetica",
            ),
            (
                "FONTSIZE",
                (0, 0),
                (-1, -1),
                8.5,
            ),
            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.35,
                colors.HexColor(
                    "#D8E0E7"
                ),
            ),
            (
                "ALIGN",
                (1, 1),
                (1, -1),
                "RIGHT",
            ),
            (
                "LEFTPADDING",
                (0, 0),
                (-1, -1),
                7,
            ),
            (
                "RIGHTPADDING",
                (0, 0),
                (-1, -1),
                7,
            ),
            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                5,
            ),
            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                5,
            ),
        ])
    )

    story.append(
        Paragraph(
            "Análisis automatizado",
            heading_style,
        )
    )
    story.append(
        Paragraph(
            "Análisis de IA · Top 5 scores",
            body_style,
        )
    )
    story.append(
        Spacer(
            1,
            5,
        )
    )
    story.append(
        ai_table
    )

    obs = state.get(
        "record_observation",
        {}
    )

    obs_text = str(
        obs.get(
            "observations",
            ""
        )
    ).strip()

    story.append(
        Paragraph(
            "Observaciones del profesional",
            heading_style,
        )
    )

    professional_line = (
        "<b>Profesional:</b> "
        +
        (
            str(
                obs.get(
                    "professional_name",
                    ""
                )
            ).strip()
            or
            "No registrado"
        )
        +
        " &nbsp;&nbsp; <b>Rol:</b> "
        +
        (
            str(
                obs.get(
                    "professional_role",
                    ""
                )
            ).strip()
            or
            "No registrado"
        )
    )

    story.append(
        Paragraph(
            professional_line,
            body_style,
        )
    )

    if obs.get(
        "saved_at"
    ):
        story.append(
            Paragraph(
                "<b>Guardado:</b> "
                +
                str(
                    obs.get(
                        "saved_at",
                        ""
                    )
                ),
                body_style,
            )
        )

    story.append(
        Spacer(
            1,
            6,
        )
    )
    story.append(
        Table(
            [[
                Paragraph(
                    (
                        obs_text.replace(
                            "\n",
                            "<br/>",
                        )
                        if obs_text
                        else
                        "Sin observaciones registradas."
                    ),
                    body_style,
                )
            ]],
            colWidths=[
                6.0 * inch
            ],
            style=TableStyle([
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.HexColor(
                        "#C9D4DE"
                    ),
                ),
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, -1),
                    colors.HexColor(
                        "#FAFBFC"
                    ),
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    9,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    9,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    9,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    9,
                ),
            ]),
        )
    )

    story.append(
        Paragraph(
            (
                "<b>Segmentación:</b> Segmentación generada por IA; "
                "puede presentar imprecisiones y no constituye diagnóstico clínico."
            ),
            note_style,
        )
    )

    story.append(
        Paragraph(
            (
                "<b>Análisis de IA:</b> Resultados generados por IA con fines educativos; "
                "pueden presentar imprecisiones y no sustituyen la valoración profesional."
            ),
            note_style,
        )
    )

    story.append(
        Paragraph(
            (
                "Generado por OTTAVA el "
                +
                datetime.now().strftime(
                    "%d/%m/%Y %H:%M:%S"
                )
            ),
            note_style,
        )
    )

    doc.build(
        story
    )

    state["record_last_report"] = str(
        report_path
    )

    return report_path



def clamp(value):
    return max(-1.0, min(1.0, float(value)))


def zero_motion():
    for arm in ARM_IDS:
        state["arms"][arm].update(arm_state())
    state["camera"] = {"x": 0.0, "y": 0.0}
    state["table"] = {"slide": 0.0, "tilt": 0.0}


def camera_watch_active():
    return (time.time() - state["camera_watch_last_seen"]) < 2.0


def udp_payload():
    return {
        "arms": state["arms"],
        "camera": state["camera"],
        "table": state["table"],
        "capture_seq": state["capture_seq"],
        "new_sim_seq": state["new_sim_seq"],
        "capture_auto_frame": state["capture_auto_frame"],
        "home_all_seq": state["home_all_seq"],
        "arm_home_seq": state["arm_home_seq"],
        "table_center_seq": state["table_center_seq"],
        "jaw_seq": state["jaw_seq"],
        "jaw_action": state["jaw_action"],
        "stop_seq": state["stop_seq"],
        "resume_seq": state["resume_seq"],
        "emergency_stop": state["emergency_stop"],
        "camera_watch": camera_watch_active(),
    }


def send_udp_state():
    try:
        payload = json.dumps(
            udp_payload(),
            separators=(",", ":"),
        ).encode("utf-8")
        UDP_SOCKET.sendto(payload, UDP_TARGET)
    except OSError:
        pass


def action_payload():
    return {
        "capture_seq": state["capture_seq"],
        "new_sim_seq": state["new_sim_seq"],
        "capture_auto_frame": state["capture_auto_frame"],
        "home_all_seq": state["home_all_seq"],
        "arm_home_seq": state["arm_home_seq"],
        "table_center_seq": state["table_center_seq"],
        "jaw_seq": state["jaw_seq"],
        "jaw_action": state["jaw_action"],
        "stop_seq": state["stop_seq"],
        "resume_seq": state["resume_seq"],
        "emergency_stop": state["emergency_stop"],
    }


def write_action_snapshot():
    temp_path = ACTION_FILE.with_suffix(".json.tmp")
    try:
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(action_payload(), handle, separators=(",", ":"))
        os.replace(temp_path, ACTION_FILE)
    except OSError:
        pass


def shared_camera_version():
    try:
        return CAMERA_FILE.stat().st_mtime_ns
    except OSError:
        return 0


def shared_rx_info():
    default = {
        "version": 0,
        "filename": "",
        "acquisition_time": "",
    }
    try:
        with RX_META_FILE.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return {
            "version": int(data.get("version", 0)),
            "filename": str(data.get("filename", "")),
            "acquisition_time": str(data.get("acquisition_time", "")),
        }
    except Exception:
        return default




def ai_set_status(status, message="", *, error=""):
    state["ai_status"] = status
    state["ai_message"] = message
    state["ai_error"] = error
    state["ai_updated_at"] = time.time()


def load_ai_runtime():
    """Carga TorchXRayVision una sola vez por sesión de API."""
    global _AI_MODEL
    global _AI_DEVICE
    global _AI_XRV
    global _AI_TORCH
    global _AI_TORCHVISION

    if _AI_MODEL is not None:
        return (
            _AI_MODEL,
            _AI_DEVICE,
            _AI_XRV,
            _AI_TORCH,
            _AI_TORCHVISION,
        )

    ai_set_status(
        "loading",
        "Cargando modelo TorchXRayVision..."
    )

    import numpy as np
    import torch
    import torchvision
    import torchxrayvision as xrv

    if (
        hasattr(torch.backends, "mps")
        and
        torch.backends.mps.is_available()
    ):
        device = torch.device("mps")
    else:
        device = torch.device("cpu")

    model = xrv.models.DenseNet(
        weights=AI_MODEL_NAME
    )
    model = model.to(device)
    model.eval()

    _AI_MODEL = model
    _AI_DEVICE = device
    _AI_XRV = xrv
    _AI_TORCH = torch
    _AI_TORCHVISION = torchvision

    return (
        model,
        device,
        xrv,
        torch,
        torchvision,
    )



def segmentation_set_status(
    status,
    message="",
    *,
    error="",
):
    state["segmentation_status"] = status
    state["segmentation_message"] = message
    state["segmentation_error"] = error


def load_segmentation_runtime(
    xrv,
    torch,
    device,
):
    """Carga PSPNet una sola vez por sesión."""
    global _SEG_MODEL
    global _SEG_DEVICE

    if _SEG_MODEL is not None:
        return _SEG_MODEL, _SEG_DEVICE

    segmentation_set_status(
        "loading",
        "Cargando PSPNet anatómico..."
    )

    model = (
        xrv.baseline_models
        .chestx_det
        .PSPNet()
    )

    # Preferir el mismo dispositivo de DenseNet.
    try:
        model = model.to(device)
        seg_device = device
    except Exception:
        seg_device = torch.device("cpu")
        model = model.to(seg_device)

    model.eval()

    _SEG_MODEL = model
    _SEG_DEVICE = seg_device

    return model, seg_device


def make_segmentation_overlay(
    ds,
    instance_id,
    xrv,
    torch,
    torchvision,
    device,
):
    """Ejecuta PSPNet y genera PNG con máscara anatómica sobre la RX."""
    import numpy as np

    segmentation_set_status(
        "analyzing",
        "Segmentando anatomía torácica..."
    )

    seg_model, seg_device = (
        load_segmentation_runtime(
            xrv,
            torch,
            device,
        )
    )

    raw_image = (
        ds.pixel_array
        .astype(np.float32)
    )

    if raw_image.ndim > 2:
        raw_image = raw_image[0]

    bits_stored = int(
        getattr(ds, "BitsStored", 8)
    )

    max_value = float(
        (2 ** bits_stored) - 1
    )

    normalized = xrv.datasets.normalize(
        raw_image,
        max_value,
    )
    normalized = normalized[None, ...]

    # PSPNet de ChestX-Det trabaja a resolución 512.
    transform = torchvision.transforms.Compose([
        xrv.datasets.XRayCenterCrop(),
        xrv.datasets.XRayResizer(512),
    ])

    seg_input_np = transform(
        normalized
    )

    seg_tensor = (
        torch.from_numpy(seg_input_np)
        .float()
        .unsqueeze(0)
        .to(seg_device)
    )

    def infer(model, tensor):
        with torch.no_grad():
            return model(tensor)

    try:
        output = infer(
            seg_model,
            seg_tensor,
        )
    except Exception:
        # Algunos operadores pueden no estar implementados para MPS.
        # Reintentar segmentación en CPU sin afectar DenseNet.
        if str(seg_device) != "cpu":
            seg_device = torch.device("cpu")
            seg_model = seg_model.to(seg_device)
            seg_tensor = seg_tensor.to(seg_device)

            _SEG_DEVICE = seg_device
            output = infer(
                seg_model,
                seg_tensor,
            )
        else:
            raise

    masks = (
        output[0]
        .detach()
        .cpu()
        .numpy()
    )

    # Compatibilidad con versiones que devuelven logits o probabilidades.
    if (
        masks.min() < 0.0
        or
        masks.max() > 1.0
    ):
        masks = 1.0 / (
            1.0
            +
            np.exp(
                -np.clip(
                    masks,
                    -30.0,
                    30.0,
                )
            )
        )

    # Imagen base ya crop/resized exactamente igual que el input PSPNet.
    base = seg_input_np[0]
    base = np.clip(
        (base + 1024.0)
        /
        2048.0,
        0.0,
        1.0,
    )

    rgb = np.stack(
        [base, base, base],
        axis=-1,
    )

    # Overlay semitransparente por estructura.
    # Threshold 0.50 conserva regiones con respuesta dominante.
    for index in range(
        min(
            masks.shape[0],
            len(SEGMENTATION_COLORS),
        )
    ):
        probability = np.clip(
            masks[index],
            0.0,
            1.0,
        )

        active = probability >= 0.50

        if not np.any(active):
            continue

        color = (
            np.array(
                SEGMENTATION_COLORS[index],
                dtype=np.float32,
            )
            /
            255.0
        )

        # La opacidad varía suavemente según confianza de la máscara.
        alpha = np.where(
            active,
            0.18
            +
            0.32
            *
            probability,
            0.0,
        )[..., None]

        rgb = (
            rgb
            *
            (1.0 - alpha)
            +
            color
            *
            alpha
        )

    rgb8 = (
        np.clip(
            rgb,
            0.0,
            1.0,
        )
        *
        255.0
    ).astype(
        np.uint8
    )

    image_path = (
        AI_RESULTS_DIR
        /
        f"SEG_{instance_id}.png"
    )

    Image.fromarray(
        rgb8,
        mode="RGB",
    ).save(
        image_path,
        format="PNG",
    )

    state["segmentation_image"] = str(
        image_path
    )
    state["segmentation_version"] = int(
        time.time_ns()
    )

    segmentation_set_status(
        "completed",
        "Segmentación anatómica completada"
    )

    return image_path


def download_orthanc_instance(instance_id):
    request = urllib.request.Request(
        f"{ORTHANC_BASE}/instances/{instance_id}/file",
        method="GET",
    )

    with urllib.request.urlopen(
        request,
        timeout=10.0,
    ) as response:
        return response.read()


def analyze_orthanc_instance(instance_id):
    """Analiza la instancia que YA fue almacenada en Orthanc."""
    try:
        ai_set_status(
            "loading",
            "Preparando TorchXRayVision..."
        )

        (
            model,
            device,
            xrv,
            torch,
            torchvision,
        ) = load_ai_runtime()

        import numpy as np
        import pydicom

        ai_set_status(
            "analyzing",
            "Descargando DICOM desde Orthanc..."
        )

        raw = download_orthanc_instance(
            instance_id
        )

        ds = pydicom.dcmread(
            io.BytesIO(raw)
        )

        ai_set_status(
            "analyzing",
            "Analizando radiografía..."
        )

        image = ds.pixel_array.astype(
            np.float32
        )

        if image.ndim > 2:
            image = image[0]

        bits_stored = int(
            getattr(ds, "BitsStored", 8)
        )
        max_value = float(
            (2 ** bits_stored) - 1
        )

        image = xrv.datasets.normalize(
            image,
            max_value
        )

        image = image[None, ...]

        transform = torchvision.transforms.Compose([
            xrv.datasets.XRayCenterCrop(),
            xrv.datasets.XRayResizer(224),
        ])

        image = transform(image)

        tensor = (
            torch.from_numpy(image)
            .float()
            .unsqueeze(0)
            .to(device)
        )

        with torch.no_grad():
            output = (
                model(tensor)[0]
                .detach()
                .cpu()
                .numpy()
            )

        results = [
            {
                "pathology": str(pathology),
                "score": float(score),
            }
            for pathology, score
            in zip(
                model.pathologies,
                output
            )
        ]

        results.sort(
            key=lambda item: item["score"],
            reverse=True
        )

        report = {
            "orthanc_instance_id": instance_id,
            "patient": {
                "name": str(
                    getattr(ds, "PatientName", "")
                ),
                "id": str(
                    getattr(ds, "PatientID", "")
                ),
            },
            "study": {
                "description": str(
                    getattr(ds, "StudyDescription", "")
                ),
                "study_instance_uid": str(
                    getattr(ds, "StudyInstanceUID", "")
                ),
                "series_instance_uid": str(
                    getattr(ds, "SeriesInstanceUID", "")
                ),
                "sop_instance_uid": str(
                    getattr(ds, "SOPInstanceUID", "")
                ),
            },
            "model": AI_MODEL_NAME,
            "device": str(device),
            "results": results,
            "note": (
                "Resultado de investigación/desarrollo. "
                "No constituye diagnóstico clínico."
            ),
        }

        result_file = (
            AI_RESULTS_DIR
            /
            f"AI_{instance_id}.json"
        )

        result_file.write_text(
            json.dumps(
                report,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        state["ai_instance_id"] = instance_id
        state["ai_results"] = results
        state["ai_result_file"] = str(
            result_file
        )

        # Segmentar anatomía sobre la MISMA instancia recuperada de Orthanc.
        state["segmentation_image"] = ""
        state["segmentation_error"] = ""
        segmentation_set_status(
            "queued",
            "Segmentación anatómica en cola"
        )

        try:
            segmentation_path = (
                make_segmentation_overlay(
                    ds,
                    instance_id,
                    xrv,
                    torch,
                    torchvision,
                    device,
                )
            )

            report[
                "segmentation"
            ] = {
                "model": "PSPNet ChestX-Det",
                "targets": SEGMENTATION_TARGETS,
                "overlay_path": str(
                    segmentation_path
                ),
            }

            # Actualizar el JSON con la sección de segmentación.
            result_file.write_text(
                json.dumps(
                    report,
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

        except Exception as seg_error:
            segmentation_set_status(
                "error",
                "Error en segmentación anatómica",
                error=str(seg_error),
            )

            print("")
            print(
                "OTTAVA · ERROR SEGMENTACIÓN:"
            )
            print(
                repr(seg_error)
            )
            traceback.print_exc()

        ai_set_status(
            "completed",
            "Análisis IA completado"
        )

        print("")
        print("=" * 64)
        print("OTTAVA · TORCHXRAYVISION")
        print("=" * 64)
        print("✓ Instancia:", instance_id)
        print("✓ Modelo:", AI_MODEL_NAME)
        print("✓ Dispositivo:", device)
        print("✓ Top 5:")
        for item in results[:5]:
            print(
                f'  {item["pathology"]:<28} '
                f'{item["score"]:.4f}'
            )
        print("✓ Resultado:", result_file)
        print("=" * 64)

    except Exception as error:
        state["ai_results"] = []
        state["ai_result_file"] = ""

        ai_set_status(
            "error",
            "Error en análisis IA",
            error=str(error),
        )

        print("")
        print("=" * 64)
        print("OTTAVA · ERROR TORCHXRAYVISION")
        print("=" * 64)
        print(repr(error))
        traceback.print_exc()
        print("=" * 64)



def normalize_dicom_sex(value):
    value = str(value or "O").upper().strip()
    return value if value in {"M", "F", "O"} else "O"


def create_dicom_from_capture(req: DicomStoreRequest):
    image_path = Path(req.image_path).expanduser().resolve()

    if not image_path.exists():
        raise FileNotFoundError(
            f"No existe la RX: {image_path}"
        )

    output_dir = Path(req.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now()

    study_uid = generate_uid()
    series_uid = generate_uid()
    sop_uid = generate_uid()

    token = now.strftime("%Y%m%d%H%M%S%f")[:-3]

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = DX_SOP_CLASS_UID
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = generate_uid()

    dicom_path = output_dir / f"{image_path.stem}.dcm"

    ds = FileDataset(
        str(dicom_path),
        {},
        file_meta=file_meta,
        preamble=b"\x00" * 128,
    )

    ds.SpecificCharacterSet = "ISO_IR 192"

    ds.SOPClassUID = DX_SOP_CLASS_UID
    ds.SOPInstanceUID = sop_uid

    # Paciente
    ds.PatientName = req.patient_name
    ds.PatientID = req.patient_id
    ds.PatientBirthDate = req.patient_birth_date
    ds.PatientSex = normalize_dicom_sex(req.patient_sex)

    # Estudio
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.StudyID = f"OTV{token}"[:16]
    ds.AccessionNumber = f"OTTAVA{token}"[:16]
    ds.StudyDate = req.study_date
    ds.StudyTime = req.study_time
    ds.StudyDescription = req.study_description

    # Serie / modalidad
    ds.SeriesDescription = "OTTAVA Radiografia Digital Simulada"
    ds.SeriesNumber = 1
    ds.InstanceNumber = 1
    ds.Modality = "DX"
    ds.PresentationIntentType = "FOR PRESENTATION"
    ds.BodyPartExamined = "CHEST"
    ds.ViewPosition = "AP"

    ds.Manufacturer = "OTTAVA"
    ds.ManufacturerModelName = "OTTAVA Simulator"
    ds.SoftwareVersions = "V4.7.2 FINAL"

    ds.SeriesDate = req.study_date
    ds.SeriesTime = req.study_time
    ds.AcquisitionDate = now.strftime("%Y%m%d")
    ds.AcquisitionTime = now.strftime("%H%M%S.%f")[:13]
    ds.ContentDate = now.strftime("%Y%m%d")
    ds.ContentTime = now.strftime("%H%M%S.%f")[:13]
    ds.InstanceCreationDate = now.strftime("%Y%m%d")
    ds.InstanceCreationTime = now.strftime("%H%M%S.%f")[:13]

    # Imagen 8-bit MONOCHROME2
    with Image.open(image_path) as source:
        gray = source.convert("L")

        ds.Rows = gray.height
        ds.Columns = gray.width
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.BitsAllocated = 8
        ds.BitsStored = 8
        ds.HighBit = 7
        ds.PixelRepresentation = 0
        ds.PixelData = gray.tobytes()

    ds.PixelIntensityRelationship = "LIN"
    ds.PixelIntensityRelationshipSign = 1
    ds.PresentationLUTShape = "IDENTITY"
    ds.BurnedInAnnotation = "NO"
    ds.LossyImageCompression = "00"

    ds.save_as(
        str(dicom_path),
        enforce_file_format=True,
    )

    return dicom_path


def upload_dicom_to_orthanc(dicom_path):
    data = Path(dicom_path).read_bytes()

    request = urllib.request.Request(
        ORTHANC_BASE + "/instances",
        data=data,
        headers={
            "Content-Type": "application/dicom",
            "Expect": "",
        },
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=8.0,
    ) as response:
        return json.loads(
            response.read().decode("utf-8")
        )


def orthanc_health():
    try:
        with urllib.request.urlopen(
            ORTHANC_BASE + "/system",
            timeout=1.0,
        ) as response:
            info = json.loads(
                response.read().decode("utf-8")
            )
        return True, info

    except Exception:
        return False, None


def update_orthanc_health():
    """Comprueba Orthanc como máximo cada 2 segundos."""
    now = time.time()

    if (
        now
        -
        state["orthanc_last_check"]
        <
        2.0
    ):
        return

    state["orthanc_last_check"] = now

    ok, info = orthanc_health()

    state["orthanc_connected"] = bool(ok)

    if ok and info:
        state["orthanc_name"] = str(
            info.get(
                "Name",
                "Orthanc"
            )
        )
    else:
        state["orthanc_name"] = ""


@app.on_event("startup")
def initialize_runtime_state():
    # MASTER FINAL · arrancar sin paciente, estudio, RX ni resultados cargados.
    # Sólo se limpia la sesión activa y los archivos temporales compartidos;
    # los estudios ya almacenados en Orthanc permanecen intactos.
    reset_active_simulation_state()

    # Escribir estado inicial ANTES de que Blender escuche acciones.
    # No se incrementa capture_seq ni new_sim_seq, por lo que iniciar la API
    # nunca dispara una captura ni una nueva simulación automáticamente.
    write_action_snapshot()
    update_orthanc_health()


@app.get("/")
def index():
    return FileResponse(INDEX_FILE)


@app.get("/api/actions")
def get_actions():
    # Estado ligero y autoritativo de botones/acciones discretas.
    return action_payload()


@app.get("/api/state")
def get_state():
    update_orthanc_health()

    now = time.time()
    connected = (now - state["blender_last_seen"]) < 2.5
    state["blender_connected"] = connected

    if not connected and state["blender_last_seen"] > 0:
        state["blender_message"] = "Blender sin respuesta"

    rx = shared_rx_info()

    return {
        **state,
        "camera_watch": camera_watch_active(),
        "camera_frame_version": shared_camera_version(),
        "rx_version": rx["version"],
        "rx_time": rx["acquisition_time"],
        "rx_filename": rx["filename"],
        "ohif_url": current_ohif_url(),
    }


@app.post("/api/control")
def control(packet: ControlPacket):
    if state["emergency_stop"]:
        zero_motion()
        send_udp_state()
        return {"ok": True}

    for arm in ARM_IDS:
        incoming = getattr(packet, arm)
        state["arms"][arm] = {
            "x": clamp(incoming.x),
            "y": clamp(incoming.y),
            "depth": clamp(incoming.depth),
            "tool": clamp(incoming.tool),
        }

    state["camera"] = {
        "x": clamp(packet.camera.x),
        "y": clamp(packet.camera.y),
    }
    state["table"] = {
        "slide": clamp(packet.table.slide),
        "tilt": clamp(packet.table.tilt),
    }

    send_udp_state()
    return {"ok": True}



def reset_active_simulation_state():
    """Limpia la sesión activa sin borrar estudios almacenados en Orthanc."""
    zero_motion()
    state["capture_auto_frame"] = False
    state["emergency_stop"] = False
    state["camera_watch_last_seen"] = 0.0

    state["ai_status"] = "idle"
    state["ai_message"] = "Esperando estudio"
    state["ai_instance_id"] = ""
    state["ai_results"] = []
    state["ai_result_file"] = ""
    state["ai_error"] = ""
    state["ai_updated_at"] = 0.0
    state["last_orthanc_instance_id"] = ""

    state["segmentation_status"] = "idle"
    state["segmentation_message"] = "Esperando estudio"
    state["segmentation_image"] = ""
    state["segmentation_version"] = 0
    state["segmentation_error"] = ""

    state["current_exam"] = {}
    state["record_original_image"] = ""
    state["record_original_version"] = 0
    state["record_observation"] = {
        "professional_name": "",
        "professional_role": "Radiólogo",
        "observations": "",
        "saved_at": "",
    }
    state["record_last_report"] = ""

    # Sólo limpia la RX compartida de la sesión; no toca OTTAVA_Capturas,
    # OTTAVA_DICOM ni Orthanc.
    for path in (RX_FILE, RX_META_FILE):
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass


@app.post("/api/action/new-simulation")
def new_simulation():
    reset_active_simulation_state()
    state["new_sim_seq"] += 1
    write_action_snapshot()
    send_udp_state()
    return {
        "ok": True,
        "new_sim_seq": state["new_sim_seq"],
    }


@app.post("/api/action/capture")
def capture(auto_frame: bool = False):
    state["capture_auto_frame"] = bool(auto_frame)
    state["capture_seq"] += 1
    write_action_snapshot()
    send_udp_state()
    return {
        "ok": True,
        "auto_frame": state["capture_auto_frame"],
    }


@app.post("/api/action/home-all")
def home_all():
    state["home_all_seq"] += 1
    zero_motion()
    write_action_snapshot()
    send_udp_state()
    return {"ok": True}


@app.post("/api/action/arm-home/{arm_id}")
def arm_home(arm_id: str):
    if arm_id not in ARM_IDS:
        return {"ok": False, "error": "Brazo inválido"}
    state["arm_home_seq"][arm_id] += 1
    state["arms"][arm_id] = arm_state()
    write_action_snapshot()
    send_udp_state()
    return {"ok": True}


@app.post("/api/action/table-center")
def table_center():
    state["table_center_seq"] += 1
    state["table"] = {"slide": 0.0, "tilt": 0.0}
    write_action_snapshot()
    send_udp_state()
    return {"ok": True}


@app.post("/api/action/jaw/{arm_id}/{action}")
def jaw(arm_id: str, action: str):
    action = action.upper()
    if arm_id not in {"arm1", "arm2"} or action not in {"OPEN", "CLOSE"}:
        return {"ok": False, "error": "Acción inválida"}
    state["jaw_action"][arm_id] = action
    state["jaw_seq"][arm_id] += 1
    write_action_snapshot()
    send_udp_state()
    return {"ok": True}


@app.post("/api/action/stop")
def stop():
    state["emergency_stop"] = True
    state["stop_seq"] += 1
    zero_motion()
    write_action_snapshot()
    send_udp_state()
    return {"ok": True}


@app.post("/api/action/resume")
def resume():
    state["emergency_stop"] = False
    state["resume_seq"] += 1
    write_action_snapshot()
    send_udp_state()
    return {"ok": True}


@app.post("/api/camera/watch")
def camera_watch():
    state["camera_watch_last_seen"] = time.time()
    send_udp_state()
    return {"ok": True}


@app.get("/api/camera/frame")
def get_camera_frame():
    if not CAMERA_FILE.exists():
        return Response(status_code=204)
    return FileResponse(
        CAMERA_FILE,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@app.get("/api/rx/image")
def get_rx_image():
    if not RX_FILE.exists():
        return Response(status_code=204)
    return FileResponse(
        RX_FILE,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )



@app.post("/api/rx/process")
def rx_process(req: RxProcessRequest):
    """Crea la RX final sin alterar el archivo fuente.

    El modo normal recorta a la región observada por Arm_03_Camera.
    Autoencuadre conserva el estudio completo. El resultado siempre se
    guarda como PNG real, aunque la fuente sea JPEG o WEBP.
    """
    try:
        source = Path(req.image_path).expanduser().resolve()
        output = Path(req.output_path).expanduser().resolve()

        if not source.exists():
            return {
                "ok": False,
                "error": f"No existe la imagen fuente: {source}",
            }

        crop = list(req.crop_box or [])
        if len(crop) != 4:
            return {
                "ok": False,
                "error": "crop_box debe contener 4 valores",
            }

        left, top, right, bottom = [
            max(0.0, min(1.0, float(v)))
            for v in crop
        ]

        if right <= left or bottom <= top:
            return {
                "ok": False,
                "error": "Región de encuadre inválida",
            }

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with Image.open(source) as img:
            img.load()
            width, height = img.size

            if req.auto_frame:
                box_px = (0, 0, width, height)
                processed = img.copy()
            else:
                x0 = max(0, min(width - 1, int(round(left * width))))
                y0 = max(0, min(height - 1, int(round(top * height))))
                x1 = max(x0 + 1, min(width, int(round(right * width))))
                y1 = max(y0 + 1, min(height, int(round(bottom * height))))
                box_px = (x0, y0, x1, y1)
                processed = img.crop(box_px)

            # El resto del flujo trabaja establemente con PNG. Mantener
            # información tonal; convertir sólo modos incompatibles.
            if processed.mode not in {"L", "RGB", "RGBA", "I;16", "I"}:
                processed = processed.convert("L")

            processed.save(
                output,
                format="PNG",
            )

        return {
            "ok": True,
            "output_path": str(output),
            "source_size": [width, height],
            "output_size": [
                box_px[2] - box_px[0],
                box_px[3] - box_px[1],
            ],
            "crop_box": [left, top, right, bottom],
            "crop_pixels": list(box_px),
            "auto_frame": bool(req.auto_frame),
        }

    except Exception as error:
        traceback.print_exc()
        return {
            "ok": False,
            "error": str(error),
        }


@app.post("/api/dicom/store")
def dicom_store(
    req: DicomStoreRequest,
    background_tasks: BackgroundTasks,
):
    try:
        dicom_path = create_dicom_from_capture(req)
    except Exception as error:
        print("")
        print("=" * 58)
        print("OTTAVA · ERROR GENERANDO DICOM")
        print("=" * 58)
        print(repr(error))
        traceback.print_exc()
        print("=" * 58)

        return {
            "ok": False,
            "stage": "dicom",
            "error": str(error),
        }

    try:
        result = upload_dicom_to_orthanc(dicom_path)
    except Exception as error:
        print("")
        print("=" * 58)
        print("OTTAVA · DICOM CREADO, PERO ERROR EN ORTHANC")
        print("=" * 58)
        print("DICOM:", dicom_path)
        print(repr(error))
        traceback.print_exc()
        print("=" * 58)

        return {
            "ok": False,
            "stage": "orthanc",
            "error": str(error),
            "dicom_path": str(dicom_path),
        }

    stored_ok = result.get("Status") in {
        "Success",
        "AlreadyStored",
    }

    instance_id = result.get(
        "ID",
        ""
    )

    if stored_ok and instance_id:
        state["last_orthanc_instance_id"] = instance_id
        state["ai_instance_id"] = instance_id

        try:
            set_current_exam_from_dicom(
                dicom_path,
                orthanc_instance_id=instance_id,
                orthanc_study_id=result.get(
                    "ParentStudy",
                    "",
                ),
            )
            persist_original_image(
                req.image_path,
                instance_id,
            )
        except Exception as record_error:
            print(
                "OTTAVA · AVISO EXPEDIENTE:",
                repr(record_error),
            )
        state["ai_results"] = []
        state["ai_result_file"] = ""

        state["segmentation_image"] = ""
        state["segmentation_error"] = ""
        segmentation_set_status(
            "queued",
            "Esperando análisis IA"
        )

        ai_set_status(
            "queued",
            "Estudio en Orthanc · IA en cola"
        )

        # Se ejecuta DESPUÉS de responder a Blender.
        # Blender no espera a TorchXRayVision.
        background_tasks.add_task(
            analyze_orthanc_instance,
            instance_id,
        )

    return {
        "ok": stored_ok,
        "dicom_path": str(dicom_path),
        "orthanc_status": result.get("Status", ""),
        "orthanc_instance_id": instance_id,
        "orthanc_patient_id": result.get("ParentPatient", ""),
        "orthanc_study_id": result.get("ParentStudy", ""),
        "orthanc_series_id": result.get("ParentSeries", ""),
        "orthanc_path": result.get("Path", ""),
        "ai_status": state["ai_status"],
    }


@app.get("/api/record/original")
def record_original():
    path_text = state.get(
        "record_original_image",
        ""
    )

    if not path_text:
        return Response(
            status_code=404
        )

    image_path = Path(
        path_text
    )

    if not image_path.exists():
        return Response(
            status_code=404
        )

    return FileResponse(
        image_path,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
        },
    )


@app.post("/api/record/observations")
def save_record_observations(
    req: ObservationRequest,
):
    exam = state.get(
        "current_exam",
        {}
    )

    study_uid = str(
        exam.get(
            "study_instance_uid",
            ""
        )
    ).strip()

    if not study_uid:
        return {
            "ok": False,
            "error": "No hay un estudio activo.",
        }

    data = {
        "study_instance_uid": study_uid,
        "orthanc_instance_id": exam.get(
            "orthanc_instance_id",
            ""
        ),
        "patient_id": exam.get(
            "patient_id",
            ""
        ),
        "professional_name": req.professional_name.strip(),
        "professional_role": req.professional_role.strip() or "Radiólogo",
        "observations": req.observations.strip(),
        "saved_at": datetime.now().strftime(
            "%d/%m/%Y %H:%M:%S"
        ),
    }

    path = observation_file_for(
        study_uid
    )

    path.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    state[
        "record_observation"
    ] = {
        "professional_name": data[
            "professional_name"
        ],
        "professional_role": data[
            "professional_role"
        ],
        "observations": data[
            "observations"
        ],
        "saved_at": data[
            "saved_at"
        ],
    }

    return {
        "ok": True,
        "saved_at": data[
            "saved_at"
        ],
    }


@app.get("/api/record/report.pdf")
def record_report_pdf():
    try:
        report_path = (
            build_report_pdf()
        )
    except Exception as error:
        print(
            "OTTAVA · ERROR PDF:",
            repr(error),
        )
        traceback.print_exc()

        return Response(
            content=(
                "No fue posible generar "
                "el reporte PDF."
            ),
            status_code=500,
            media_type="text/plain",
        )

    return FileResponse(
        report_path,
        media_type="application/pdf",
        filename=report_path.name,
        headers={
            "Cache-Control": "no-store",
        },
    )


@app.get("/api/ai/segmentation")
def ai_segmentation():
    path_text = state.get(
        "segmentation_image",
        ""
    )

    if not path_text:
        return Response(
            status_code=404
        )

    image_path = Path(
        path_text
    )

    if not image_path.exists():
        return Response(
            status_code=404
        )

    return FileResponse(
        image_path,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
        },
    )


@app.post("/api/ai/reanalyze")
def ai_reanalyze(
    background_tasks: BackgroundTasks,
):
    instance_id = state.get(
        "last_orthanc_instance_id",
        ""
    )

    if not instance_id:
        return {
            "ok": False,
            "error": "No hay una instancia Orthanc disponible.",
        }

    ai_set_status(
        "queued",
        "Reanálisis IA en cola"
    )

    background_tasks.add_task(
        analyze_orthanc_instance,
        instance_id,
    )

    return {
        "ok": True,
        "instance_id": instance_id,
    }


@app.post("/api/blender-status")
def blender_status(status: BlenderStatus):
    state["blender_connected"] = True
    state["blender_last_seen"] = time.time()
    state["blender_message"] = status.message
    return {"ok": True}


def local_ip():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return "127.0.0.1"


def clean_shared_runtime_files():
    # Evita que una nueva sesión muestre la RX o feed de una prueba anterior.
    for path in (CAMERA_FILE, RX_FILE, RX_META_FILE, ACTION_FILE):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


if __name__ == "__main__":
    clean_shared_runtime_files()
    write_action_snapshot()
    ip = local_ip()
    print("")
    print("=" * 58)
    print("OTTAVA CONTROL V4.7.2 FINAL · CASOS RX + AUTOENCUADRE")
    print("=" * 58)
    print("Mac:      http://127.0.0.1:8000")
    print(f"Telefono: http://{ip}:8000")
    print("Control Blender: UDP local no bloqueante · objetivo 50 Hz")
    print("Feed: OpenGL de Monitor 1 · ~4 FPS")
    print("IA: TorchXRayVision automática después de Orthanc")
    print("Recomendado: telefono en horizontal (landscape).")
    print("Mac y telefono deben estar en la misma Wi-Fi.")

    pacs_ok, _pacs_info = orthanc_health()
    if pacs_ok:
        print(f"Orthanc:  OK · {ORTHANC_BASE}")
    else:
        print(f"Orthanc:  NO DISPONIBLE · {ORTHANC_BASE}")

    print("=" * 58)
    uvicorn.run(app, host="0.0.0.0", port=8000)
