"""Аналіз: датчики + фото -> висновок.

Зараз це прості правила + аналіз кольору фото (частка "вогняних" пікселів).
Далі (з фінансуванням): навчена модель (наприклад YOLO) на датасеті фото пожеж.
"""
import io
from dataclasses import dataclass
from typing import List, Optional

import config
from module_client import ModuleReading

FIRE = "ЛІСОВА ПОЖЕЖА"
FIELD = "СПАЛЮВАННЯ ПОЛЯ / СТЕРНІ"
FALSE = "ХИБНА ТРИВОГА"


@dataclass
class Verdict:
    label: str
    confidence: float  # 0..1
    reasons: List[str]
    fire_pixel_share: Optional[float] = None
    reasons_en: List[str] = None


def fire_pixel_share(jpeg: bytes) -> Optional[float]:
    """Частка пікселів кольору полум'я (яскраві, червоно-помаранчеві)."""
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return None
    img = np.asarray(Image.open(io.BytesIO(jpeg)).convert("RGB").resize((160, 120)), dtype=np.int16)
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    mask = (r > 180) & (r > g + 30) & (g > b) & (r - b > 80)
    return float(mask.mean())


def forest_share(lat: float, lon: float) -> Optional[float]:
    """Місце для карти землекористування (ліс/поле). Поки невідомо -> None."""
    return None


def classify(m: ModuleReading, landcover_forest: Optional[float] = None) -> Verdict:
    reasons, en, factors = [], [], 0
    if m.co_detected:
        factors += 1
        reasons.append("MQ-7: є чадний газ (горіння)")
        en.append("MQ-7: carbon monoxide detected (combustion)")
    if m.temp_rise_c >= 8:
        factors += 1
        reasons.append(f"температура повітря зросла на {m.temp_rise_c:.1f} °C")
        en.append(f"air temperature rose by {m.temp_rise_c:.1f} °C")
    hot = None
    if m.thermal_max_c is not None:
        mean = m.thermal_mean_c if m.thermal_mean_c is not None else 15
        hot = m.thermal_max_c
        if hot >= 100 or hot - mean >= 45:
            factors += 1
            reasons.append(f"тепловізор: гаряча точка {hot:.0f} °C (фон {mean:.0f} °C)")
            en.append(f"thermal camera: hot spot {hot:.0f} °C (background {mean:.0f} °C)")

    share = fire_pixel_share(m.photo_jpeg) if m.photo_jpeg else None
    if share is not None and share > 0.02:
        factors += 1
        reasons.append(f"фото: {share * 100:.1f}% пікселів кольору полум'я")
        en.append(f"photo: {share * 100:.1f}% flame-coloured pixels")

    if factors < config.MIN_FACTORS:
        reasons.append(f"збіглося ознак: {factors} з потрібних {config.MIN_FACTORS}")
        en.append(f"signs matched: {factors} of {config.MIN_FACTORS} required")
        return Verdict(FALSE, 0.7, reasons, share, en)

    # Пожежа чи поле: дуже гаряче й сильне горіння -> ліс; слабше -> поле.
    # Коли буде карта землекористування, вона вирішує першою.
    if landcover_forest is not None:
        label = FIRE if landcover_forest >= 0.5 else FIELD
        reasons.append(f"карта: ліс займає {landcover_forest * 100:.0f}% навколо")
        en.append(f"map: forest covers {landcover_forest * 100:.0f}% around")
    else:
        label = FIRE if (hot or 0) >= 160 and m.temp_rise_c >= 8 else FIELD
    conf = min(0.95, 0.5 + 0.15 * factors)
    return Verdict(label, conf, reasons, share, en)
