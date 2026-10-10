"""Sensor mappings and scalar reference implementations for optical indices.

All reflectance inputs to compute_index are surface reflectance in unitless
0–1 units. These scalar functions provide executable formula regression tests;
Earth Engine raster execution is implemented in server.py.
"""
from __future__ import annotations

import math

SENSOR_BANDS = {
    "sentinel2": {"BLUE": "B2", "GREEN": "B3", "RED": "B4", "RE": "B5", "RE2": "B6", "RE3": "B7", "NIR": "B8", "NIR_NARROW": "B8A", "SWIR1": "B11", "SWIR2": "B12", "THERMAL": None},
    "landsat8": {"BLUE": "SR_B2", "GREEN": "SR_B3", "RED": "SR_B4", "RE": None, "RE2": None, "RE3": None, "NIR": "SR_B5", "NIR_NARROW": None, "SWIR1": "SR_B6", "SWIR2": "SR_B7", "THERMAL": "ST_B10"},
    "landsat9": {"BLUE": "SR_B2", "GREEN": "SR_B3", "RED": "SR_B4", "RE": None, "RE2": None, "RE3": None, "NIR": "SR_B5", "NIR_NARROW": None, "SWIR1": "SR_B6", "SWIR2": "SR_B7", "THERMAL": "ST_B10"},
    "landsat7": {"BLUE": "SR_B1", "GREEN": "SR_B2", "RED": "SR_B3", "RE": None, "RE2": None, "RE3": None, "NIR": "SR_B4", "NIR_NARROW": None, "SWIR1": "SR_B5", "SWIR2": "SR_B7", "THERMAL": "ST_B6"},
}

SPECTRAL_INDICES = (
    "NDVI", "NDWI", "MNDWI", "SAVI", "EVI", "EVI2", "MSAVI", "NDRE",
    "GNDVI", "DVI", "RVI", "ARVI", "BSI", "NDBI", "NDMI", "NBR",
    "DNBR", "NDSI", "UI", "IBI", "EBBI", "AWEI",
)

def sensor_bands(source: str) -> dict[str, str | None]:
    try:
        return dict(SENSOR_BANDS[source.lower()])
    except (AttributeError, KeyError):
        raise ValueError(f"Unsupported optical sensor '{source}'. Use Sentinel-2, Landsat 7, Landsat 8 or Landsat 9.")

def _nd(a: float, b: float) -> float:
    den = a + b
    if abs(den) < 1e-12:
        raise ValueError("Index denominator is zero for the supplied reflectance values.")
    return (a - b) / den

def compute_index(index: str, bands: dict[str, float]) -> float:
    """Compute one optical index from named, unitless surface-reflectance bands."""
    name = index.upper()
    if name == "DNBR":
        if "NBR_PRE" not in bands or "NBR_POST" not in bands:
            raise ValueError("dNBR requires NBR_PRE and NBR_POST.")
        return float(bands["NBR_PRE"]) - float(bands["NBR_POST"])
    needed = {
        "NDVI": ("NIR", "RED"), "NDWI": ("GREEN", "NIR"), "MNDWI": ("GREEN", "SWIR1"),
        "NDMI": ("NIR", "SWIR1"), "NBR": ("NIR", "SWIR2"), "NDSI": ("GREEN", "SWIR1"),
        "NDBI": ("SWIR1", "NIR"), "GNDVI": ("NIR", "GREEN"), "NDRE": ("NIR", "RE"),
        "SAVI": ("NIR", "RED"), "EVI": ("NIR", "RED", "BLUE"), "EVI2": ("NIR", "RED"),
        "MSAVI": ("NIR", "RED"), "BSI": ("SWIR1", "RED", "NIR", "BLUE"),
        "DVI": ("NIR", "RED"), "RVI": ("NIR", "RED"),
    }
    if name not in needed:
        raise ValueError(f"No scalar formula is defined for {name}.")
    missing = [band for band in needed[name] if band not in bands or bands[band] is None]
    if missing:
        raise ValueError(f"{name} requires bands: {', '.join(missing)}.")
    b = {key: float(value) for key, value in bands.items() if value is not None}
    if name in ("NDVI", "NDWI", "MNDWI", "NDMI", "NBR", "NDSI", "NDBI", "GNDVI", "NDRE"):
        left, right = needed[name]
        return _nd(b[left], b[right])
    if name == "SAVI":
        return 1.5 * (b["NIR"] - b["RED"]) / (b["NIR"] + b["RED"] + 0.5)
    if name == "EVI":
        return 2.5 * (b["NIR"] - b["RED"]) / (b["NIR"] + 6*b["RED"] - 7.5*b["BLUE"] + 1)
    if name == "EVI2":
        return 2.5 * (b["NIR"] - b["RED"]) / (b["NIR"] + 2.4*b["RED"] + 1)
    if name == "MSAVI":
        radicand = (2*b["NIR"] + 1)**2 - 8*(b["NIR"] - b["RED"])
        if radicand < 0:
            raise ValueError("MSAVI square-root argument is negative for the supplied values.")
        return (2*b["NIR"] + 1 - math.sqrt(radicand)) / 2
    if name == "BSI":
        return ((b["SWIR1"] + b["RED"]) - (b["NIR"] + b["BLUE"])) / ((b["SWIR1"] + b["RED"]) + (b["NIR"] + b["BLUE"]))
    if name == "DVI":
        return b["NIR"] - b["RED"]
    if name == "RVI":
        if abs(b["RED"]) < 1e-12:
            raise ValueError("RVI denominator (RED) is zero.")
        return b["NIR"] / b["RED"]
    raise ValueError(f"No scalar formula is defined for {name}.")


def trend_statistics(years, values):
    """OLS slope, Sen slope, and tie-corrected Mann-Kendall normal approximation.

    The returned p-value is two-sided and does not correct for autocorrelation.
    """
    pairs = [(float(y), float(v)) for y, v in zip(years, values)
             if y is not None and v is not None and math.isfinite(float(v))]
    if len(pairs) < 3:
        raise ValueError("At least three valid annual observations are required for trend analysis.")
    xs, ys = zip(*pairs)
    n = len(pairs)
    xmean, ymean = sum(xs) / n, sum(ys) / n
    sxx = sum((x - xmean) ** 2 for x in xs)
    sxy = sum((x - xmean) * (y - ymean) for x, y in pairs)
    ols = sxy / sxx if sxx else 0.0
    intercept = ymean - ols * xmean
    sst = sum((y - ymean) ** 2 for y in ys)
    r2 = (sxy * sxy / (sxx * sst)) if sxx and sst else 0.0
    pair_slopes = [(ys[j] - ys[i]) / (xs[j] - xs[i])
                   for i in range(n) for j in range(i + 1, n) if xs[j] != xs[i]]
    sen = sorted(pair_slopes)[len(pair_slopes) // 2] if len(pair_slopes) % 2 else (
        sorted(pair_slopes)[len(pair_slopes) // 2 - 1] + sorted(pair_slopes)[len(pair_slopes) // 2]) / 2
    S = sum(1 if ys[j] > ys[i] else -1 if ys[j] < ys[i] else 0
            for i in range(n) for j in range(i + 1, n))
    from collections import Counter
    tie_sum = sum(t * (t - 1) * (2 * t + 5) for t in Counter(ys).values() if t > 1)
    variance = (n * (n - 1) * (2 * n + 5) - tie_sum) / 18
    if variance <= 0:
        z, pvalue = 0.0, 1.0
    else:
        z = (S - 1) / math.sqrt(variance) if S > 0 else ((S + 1) / math.sqrt(variance) if S < 0 else 0.0)
        pvalue = math.erfc(abs(z) / math.sqrt(2))
    return {"n": n, "ols_slope": ols, "intercept": intercept, "r2": r2,
            "sen_slope": sen, "mk_s": S, "mk_variance": variance, "mk_z": z, "mk_p": pvalue}


def validate_training_geojson(collection, class_property="class", max_features=10000, class_mapping=None):
    """Validate labeled GeoJSON samples and map class labels to stable integer codes.

    Returns normalized FeatureCollection and {code: original label}; no sample
    values or accuracy results are generated by this function.
    """
    if not isinstance(collection, dict) or collection.get("type") != "FeatureCollection":
        raise ValueError("Training/validation samples must be a GeoJSON FeatureCollection.")
    features = collection.get("features")
    if not isinstance(features, list) or not features or len(features) > max_features:
        raise ValueError(f"Sample FeatureCollection must contain 1–{max_features} features.")
    labels = []
    for i, feature in enumerate(features):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError(f"Sample feature {i + 1} is not a GeoJSON Feature.")
        geometry = feature.get("geometry") or {}
        if geometry.get("type") not in ("Point", "MultiPoint", "Polygon", "MultiPolygon"):
            raise ValueError(f"Sample feature {i + 1} must be Point, MultiPoint, Polygon or MultiPolygon.")
        coord_pairs = []
        def collect_coords(node):
            if isinstance(node, (list, tuple)) and len(node) >= 2 and all(isinstance(v, (int, float)) for v in node[:2]):
                coord_pairs.append((float(node[0]), float(node[1])))
            elif isinstance(node, (list, tuple)):
                for child in node:
                    collect_coords(child)
        collect_coords(geometry.get("coordinates"))
        if not coord_pairs or any(not math.isfinite(x) or not math.isfinite(y) or abs(x) > 180 or abs(y) > 90 for x, y in coord_pairs):
            raise ValueError(f"Sample feature {i + 1} coordinates must be finite WGS84 longitude/latitude.")
        props = feature.get("properties") or {}
        if class_property not in props or props[class_property] is None:
            raise ValueError(f"Sample feature {i + 1} is missing class property '{class_property}'.")
        label = str(props[class_property]).strip()
        if not label:
            raise ValueError(f"Sample feature {i + 1} has an empty class label.")
        labels.append(label)
    unique = sorted(set(labels))
    if class_mapping is None and len(unique) < 2:
        raise ValueError("At least two distinct classes are required in samples.")
    class_to_code = {str(label): int(code) for code, label in class_mapping.items()} if class_mapping else {label: i for i, label in enumerate(unique)}
    unknown = sorted(set(unique) - set(class_to_code))
    if unknown:
        raise ValueError(f"Sample labels not present in training data: {', '.join(unknown)}.")
    normalized = {"type": "FeatureCollection", "features": []}
    for feature, label in zip(features, labels):
        item = dict(feature)
        item["properties"] = dict(feature.get("properties") or {})
        item["properties"][class_property] = class_to_code[label]
        normalized["features"].append(item)
    return normalized, {code: label for label, code in class_to_code.items()}


def classification_metrics(confusion):
    """Calculate class producer/user accuracy and F1 from square confusion counts.

    Matrix convention: rows=reference/actual, columns=predicted.
    """
    if not isinstance(confusion, (list, tuple)) or not confusion:
        raise ValueError("A non-empty confusion matrix is required.")
    matrix = [[int(v) for v in row] for row in confusion]
    n = len(matrix)
    if any(len(row) != n or any(v < 0 for v in row) for row in matrix):
        raise ValueError("Confusion matrix must be square with non-negative counts.")
    total = sum(map(sum, matrix))
    if total <= 0:
        raise ValueError("Confusion matrix contains no validation observations.")
    diagonal = sum(matrix[i][i] for i in range(n))
    row_totals = [sum(row) for row in matrix]
    col_totals = [sum(matrix[i][j] for i in range(n)) for j in range(n)]
    classes = []
    for i in range(n):
        producer = matrix[i][i] / row_totals[i] if row_totals[i] else None
        user = matrix[i][i] / col_totals[i] if col_totals[i] else None
        f1 = (2 * producer * user / (producer + user)) if producer is not None and user is not None and producer + user else None
        classes.append({"producer_accuracy": producer, "user_accuracy": user, "f1": f1,
                        "reference_n": row_totals[i], "predicted_n": col_totals[i]})
    expected = sum(row_totals[i] * col_totals[i] for i in range(n)) / (total * total)
    observed = diagonal / total
    kappa = (observed - expected) / (1 - expected) if expected < 1 else None
    return {"overall_accuracy": observed, "kappa": kappa, "classes": classes,
            "total": total, "matrix": matrix}
