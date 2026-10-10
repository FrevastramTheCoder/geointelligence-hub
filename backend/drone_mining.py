"""Drone and mine surface calculations for user-supplied, georeferenced grids.

The service intentionally does not claim to generate photogrammetry products.
Surface differencing/volumes use aligned metric elevation grids and an explicit
reference surface, with GeoJSON cells for map/table/CSV export.
"""
from __future__ import annotations

import math
import re
import statistics


def _number(value, name):
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a finite number.")
    if not math.isfinite(n):
        raise ValueError(f"{name} must be a finite number.")
    return n


def _grid(value, name):
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a georeferenced elevation grid object.")
    crs = str(value.get("crs") or "").strip().upper()
    if not re.fullmatch(r"EPSG:\d{4,6}", crs):
        raise ValueError(f"{name}.crs must be an EPSG projected CRS; geographic degree grids are not accepted for volume.")
    if crs == "EPSG:3857":
        raise ValueError(f"{name}.crs EPSG:3857 has latitude-dependent area distortion; use a suitable local metric CRS such as the correct UTM zone for volume calculations.")
    try:
        from pyproj import CRS
        parsed_crs = CRS.from_user_input(crs)
        if not parsed_crs.is_projected or any(abs(axis.unit_conversion_factor - 1) > 1e-9 for axis in parsed_crs.axis_info[:2]):
            raise ValueError(f"{name}.crs must be projected in metres; transform the input grid before volume calculations.")
    except ImportError:
        code = int(crs.split(":", 1)[1])
        if not (32601 <= code <= 32660 or 32701 <= code <= 32760):
            raise ValueError(f"{name}.crs validation for this projected EPSG code requires pyproj. UTM is supported without it.")
    except Exception as exc:
        if isinstance(exc, ValueError): raise
        raise ValueError(f"Could not validate {name}.crs {crs}: {exc}")
    if str(value.get("horizontalUnits") or "").lower() not in ("m", "metre", "metres", "meter", "meters"):
        raise ValueError(f"{name}.horizontalUnits must be metres.")
    if str(value.get("verticalUnits") or "").lower() not in ("m", "metre", "metres", "meter", "meters"):
        raise ValueError(f"{name}.verticalUnits must be metres.")
    transform = value.get("transform")
    if not isinstance(transform, list) or len(transform) != 6:
        raise ValueError(f"{name}.transform must be [x0, pixelX, rowX, y0, pixelY, rowY].")
    transform = [_number(x, f"{name}.transform") for x in transform]
    pixel_area = abs(transform[1] * transform[5] - transform[2] * transform[4])
    if pixel_area <= 0:
        raise ValueError(f"{name}.transform must have non-zero pixel area.")
    values = value.get("values")
    if not isinstance(values, list) or not values or not isinstance(values[0], list):
        raise ValueError(f"{name}.values must be a non-empty rectangular numeric array.")
    cols = len(values[0])
    if cols == 0 or len(values) * cols > 10000 or any(not isinstance(row, list) or len(row) != cols for row in values):
        raise ValueError(f"{name}.values must be rectangular and contain at most 10,000 cells.")
    clean = []
    for row_index, row in enumerate(values):
        clean_row = []
        for col_index, cell in enumerate(row):
            clean_row.append(None if cell is None else _number(cell, f"{name}.values[{row_index}][{col_index}]"))
        clean.append(clean_row)
    if not any(v is not None for row in clean for v in row):
        raise ValueError(f"{name}.values contains no valid elevation cells.")
    return {"crs": crs, "transform": transform, "values": clean, "rows": len(clean), "cols": cols,
            "pixelArea": pixel_area, "verticalAccuracy": value.get("verticalAccuracyM"),
            "verticalDatum": str(value.get("verticalDatum") or "").strip()}


def _aligned(a, b, label="grids"):
    if a["crs"] != b["crs"] or (a["rows"], a["cols"]) != (b["rows"], b["cols"]):
        raise ValueError(f"{label} must have identical CRS and dimensions; reproject/resample before analysis.")
    if any(abs(x-y) > max(1e-8, abs(x)*1e-9) for x, y in zip(a["transform"], b["transform"])):
        raise ValueError(f"{label} must have exactly aligned pixel transforms; resample before analysis.")


def _require_vertical_datum(a, b, label):
    if not a.get("verticalDatum") or not b.get("verticalDatum"):
        raise ValueError(f"{label} must declare verticalDatum metadata on both grids before comparing elevations or calculating volume.")
    if a["verticalDatum"].casefold() != b["verticalDatum"].casefold():
        raise ValueError(f"{label} vertical datums differ ({a['verticalDatum']} vs {b['verticalDatum']}); transform elevations to one datum first.")


def _xy(grid, row, col):
    x0, px, rx, y0, ry, py = grid["transform"]
    return x0 + (col + 0.5) * px + (row + 0.5) * rx, y0 + (col + 0.5) * ry + (row + 0.5) * py


def _output_feature(grid, row, col, props, transformer):
    x0, px, rx, y0, ry, py = grid["transform"]
    corners = [(x0+col*px+row*rx, y0+col*ry+row*py),
               (x0+(col+1)*px+row*rx, y0+(col+1)*ry+row*py),
               (x0+(col+1)*px+(row+1)*rx, y0+(col+1)*ry+(row+1)*py),
               (x0+col*px+(row+1)*rx, y0+col*ry+(row+1)*py)]
    ring = []
    for x, y in corners:
        lon, lat = transformer(x, y)
        ring.append([lon, lat])
    ring.append(ring[0])
    return {"type": "Feature", "id": row * grid["cols"] + col,
            "geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": props}


def _transformer(crs):
    try:
        from pyproj import Transformer
        return Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform
    except ImportError:
        code = int(crs.split(":", 1)[1])
        if code == 3857:
            return lambda x, y: (math.degrees(x / 6378137.0), math.degrees(2 * math.atan(math.exp(y / 6378137.0)) - math.pi / 2))
        if 32601 <= code <= 32660 or 32701 <= code <= 32760:
            zone = code % 100
            south = 32701 <= code <= 32760
            return lambda x, y: _utm_to_lonlat(x, y, zone, south)
        raise ValueError(f"Map display for {crs} requires pyproj; install pyproj or transform the grid to UTM/Web Mercator first.")
    except Exception as exc:
        raise ValueError(f"Could not resolve projected CRS {crs}: {exc}")


def _utm_to_lonlat(x, y, zone, south):
    a = 6378137.0
    e2 = 0.0066943799901413165
    ep2 = e2 / (1 - e2)
    k0 = 0.9996
    x -= 500000.0
    if south: y -= 10000000.0
    m = y / k0
    mu = m / (a * (1-e2/4-3*e2**2/64-5*e2**3/256))
    e1 = (1 - math.sqrt(1-e2)) / (1 + math.sqrt(1-e2))
    phi1 = (mu + (3*e1/2-27*e1**3/32)*math.sin(2*mu) + (21*e1**2/16-55*e1**4/32)*math.sin(4*mu)
            + (151*e1**3/96)*math.sin(6*mu) + (1097*e1**4/512)*math.sin(8*mu))
    c1 = ep2 * math.cos(phi1)**2
    t1 = math.tan(phi1)**2
    n1 = a / math.sqrt(1-e2*math.sin(phi1)**2)
    r1 = a*(1-e2) / (1-e2*math.sin(phi1)**2)**1.5
    d = x / (n1*k0)
    lat = phi1 - (n1*math.tan(phi1)/r1) * (d**2/2 - (5+3*t1+10*c1-4*c1**2-9*ep2)*d**4/24
          + (61+90*t1+298*c1+45*t1**2-252*ep2-3*c1**2)*d**6/720)
    lon0 = math.radians((zone-1)*6-180+3)
    lon = lon0 + (d-(1+2*t1+c1)*d**3/6+(5-2*c1+28*t1-3*c1**2+8*ep2+24*t1**2)*d**5/120)/math.cos(phi1)
    return math.degrees(lon), math.degrees(lat)


def _mask(grid, mask):
    if not isinstance(mask, list) or len(mask) != grid["rows"] or any(not isinstance(r, list) or len(r) != grid["cols"] for r in mask):
        raise ValueError("mask must be a same-sized boolean grid identifying the stockpile/excavation footprint.")
    if any(not isinstance(v, bool) for row in mask for v in row):
        raise ValueError("mask cells must be boolean true/false values, not strings or numeric classes.")
    selected = [[v for v in row] for row in mask]
    if not any(v for row in selected for v in row):
        raise ValueError("mask does not select any cells.")
    return selected


def _slope_degrees(grid, row, col):
    if row == 0 or col == 0 or row == grid["rows"]-1 or col == grid["cols"]-1:
        return None
    z = grid["values"]
    neighbors = (z[row][col-1], z[row][col+1], z[row-1][col], z[row+1][col])
    if any(v is None for v in neighbors):
        return None
    dzdc = (neighbors[1]-neighbors[0])/2
    dzdr = (neighbors[3]-neighbors[2])/2
    _, px, rx, _, ry, py = grid["transform"]
    det = px*py-rx*ry
    dzdx = (dzdc*py-dzdr*rx)/det
    dzdy = (px*dzdr-ry*dzdc)/det
    return math.degrees(math.atan(math.hypot(dzdx,dzdy)))


def run_drone_analysis(body):
    method = str(body.get("method") or "").strip().lower().replace("-", "_").replace(" ", "_")
    if method in ("point_cloud_inspection", "point_cloud"):
        return _point_cloud(body)
    if method in ("orthomosaic_analysis", "orthomosaic_ndvi"):
        return _orthomosaic_ndvi(body)
    if method not in ("surface_metrics", "dsm_dtm", "dem_difference", "terrain_change", "cut_fill", "stockpile_volume", "excavation_volume"):
        raise ValueError("Unknown drone method. Supported workflows: surface_metrics, dsm_dtm, dem_difference, terrain_change, cut_fill, stockpile_volume, excavation_volume, orthomosaic_ndvi, point_cloud_inspection.")

    current = _grid(body.get("surface") or body.get("dsm") or body.get("after"), "surface")
    reference_arg = body.get("reference") or body.get("dtm") or body.get("before")
    reference = _grid(reference_arg, "reference") if isinstance(reference_arg, dict) else None
    if reference is not None:
        _aligned(current, reference, "surface and reference")
        if method in ("dem_difference", "terrain_change", "cut_fill", "dsm_dtm", "stockpile_volume", "excavation_volume"):
            _require_vertical_datum(current, reference, "surface and reference")
    if method in ("dem_difference", "terrain_change", "cut_fill", "dsm_dtm") and reference is None:
        raise ValueError("Provide aligned surface and reference grids (for example DSM and DTM, or before and after DEMs).")
    if method in ("stockpile_volume", "excavation_volume") and reference is None and not isinstance(body.get("basePlane"), dict):
        raise ValueError("Volume requires an aligned reference grid or an explicit basePlane; no reference surface is inferred.")
    if method in ("stockpile_volume", "excavation_volume") and reference is None:
        plane_datum = str((body.get("basePlane") or {}).get("verticalDatum") or "").strip()
        if not current.get("verticalDatum") or not plane_datum or plane_datum.casefold() != current["verticalDatum"].casefold():
            raise ValueError("Surface and explicit basePlane must declare the same verticalDatum before calculating volume.")
    if method in ("stockpile_volume", "excavation_volume") and not isinstance(body.get("mask"), list):
        raise ValueError("Volume requires a same-sized boolean mask delineating the stockpile/excavation footprint.")

    transformer = _transformer(current["crs"])
    selected = _mask(current, body.get("mask")) if method in ("stockpile_volume", "excavation_volume") else None
    plane = body.get("basePlane") if reference is None else None
    if plane is not None:
        if plane.get("type") == "horizontal":
            plane_z = _number(plane.get("elevationM"), "basePlane.elevationM")
            reference_at = lambda r, c: plane_z
        elif plane.get("type") == "plane":
            a, b, c = (_number(plane.get(k), f"basePlane.{k}") for k in ("a", "b", "c"))
            reference_at = lambda r, col: (lambda xy: a*xy[0] + b*xy[1] + c)(_xy(current, r, col))
        else:
            raise ValueError("basePlane.type must be 'horizontal' or 'plane'; provide elevationM or coefficients a,b,c for z=a*x+b*y+c.")
    else:
        reference_at = lambda r, c: reference["values"][r][c]

    features = []; deltas = []; cut = fill = 0.0; valid = 0; volume_cells = 0
    for r in range(current["rows"]):
        for c in range(current["cols"]):
            z = current["values"][r][c]
            ref = reference_at(r, c) if reference is not None or plane is not None else None
            if z is None or (reference is not None and ref is None):
                continue
            diff = z-ref if ref is not None else None
            if selected is not None and not selected[r][c]:
                continue
            valid += 1
            props = {"surface_elevation_m": z}
            slope = _slope_degrees(current, r, c) if method in ("surface_metrics", "dsm_dtm") else None
            if method in ("surface_metrics", "dsm_dtm"):
                props["slope_degrees"] = slope
            if diff is not None:
                props.update({"reference_elevation_m": ref, "elevation_change_m": diff})
                deltas.append(diff)
                if diff > 0:
                    fill += diff*current["pixelArea"]
                elif diff < 0:
                    cut += -diff*current["pixelArea"]
                if selected is not None:
                    volume_cells += 1
                    props.update({"fill_volume_m3": max(diff,0)*current["pixelArea"], "cut_volume_m3": max(-diff,0)*current["pixelArea"]})
            features.append(_output_feature(current, r, c, props, transformer))
    if not features:
        raise ValueError("No valid overlapping cells remain after NoData and mask checks.")
    elevations = [current["values"][r][c] for r in range(current["rows"]) for c in range(current["cols"])
                  if current["values"][r][c] is not None
                  and (reference is None or reference["values"][r][c] is not None)
                  and (selected is None or selected[r][c])]
    t = current["transform"]
    res_x, res_y = math.hypot(t[1], t[4]), math.hypot(t[2], t[5])
    stats = {"Valid cells": valid, "Cell area": f"{current['pixelArea']:g} m²", "CRS": current["crs"], "Horizontal/vertical units": "metres", "Grid resolution": f"{res_x:g} × {res_y:g} m", "Surface elevation min/max": f"{min(elevations):g} / {max(elevations):g} m"}
    if deltas:
        stats.update({"Mean elevation difference": f"{statistics.mean(deltas):g} m", "Elevation change min/max": f"{min(deltas):g} / {max(deltas):g} m", "Cut volume": f"{cut:g} m³", "Fill volume": f"{fill:g} m³", "Net volume (fill − cut)": f"{fill-cut:g} m³"})
    if method in ("surface_metrics", "dsm_dtm"):
        stats["Mean elevation"] = f"{statistics.mean(elevations):g} m"
        slopes = [f["properties"]["slope_degrees"] for f in features if f["properties"].get("slope_degrees") is not None]
        stats["Slope summary"] = f"mean {statistics.mean(slopes):g}°, range {min(slopes):g}–{max(slopes):g}°; central finite differences, edge cells omitted" if slopes else "Not calculated; need at least a 3×3 valid neighbourhood."
    uncertainty = body.get("verticalAccuracyM")
    if uncertainty is not None and selected is not None:
        sigma = _number(uncertainty, "verticalAccuracyM")
        if sigma < 0: raise ValueError("verticalAccuracyM cannot be negative.")
        stats["Conservative absolute volume uncertainty bound"] = f"±{volume_cells * current['pixelArea'] * sigma:g} m³ (assuming supplied per-cell vertical bound; correlation not modelled)"
    elif selected is not None:
        stats["Volume uncertainty"] = "Not quantified; provide verticalAccuracyM. Registration, surface interpolation and footprint uncertainty are not included."
    if method in ("stockpile_volume", "excavation_volume"):
        stats["Method"] = "Prismatic cell integration (height difference × affine cell area)"
        if method == "stockpile_volume":
            stats["Stockpile volume"] = f"{fill:g} m³ (cells above reference)"
            stats["Below-reference volume"] = f"{cut:g} m³ (reported separately, not included in stockpile volume)"
        else:
            stats["Excavation volume"] = f"{cut:g} m³ (cells below reference)"
        stats["Reference"] = f"Aligned surface {reference['crs']}" if reference else f"User-specified {plane['type']} base plane"
        stats["Footprint"] = "Explicit user-supplied boolean cell mask"
    label = {"surface_metrics": "Drone surface metrics", "dsm_dtm": "DSM–DTM difference", "dem_difference": "DEM difference", "terrain_change": "Terrain change", "cut_fill": "Cut and fill", "stockpile_volume": "Stockpile volume", "excavation_volume": "Excavation volume"}[method]
    return {"success": True, "type": "DroneMining", "label": label, "stats": stats, "statistics": stats,
            "interpretation": "Computed from the supplied elevation grid(s). Output cells are transformed to EPSG:4326 for map display; native grid CRS and metre units are retained in metadata. " + ("Cut/fill signs follow surface minus reference; volume uncertainty is only bounded when verticalAccuracyM is supplied." if deltas else "No photogrammetric reconstruction or terrain filtering was performed."),
            "geometry": {"type": "FeatureCollection", "features": features}, "tableData": [{"cell_id": f["id"], **f["properties"]} for f in features],
            "chartData": [{"name": "Cut", "value": cut}, {"name": "Fill", "value": fill}] if deltas else None,
            "styleBy": "elevation_change_m" if deltas else "surface_elevation_m", "metadata": {"crs": current["crs"], "resolutionM": [res_x, res_y], "pixelAreaM2": current["pixelArea"], "units": "m"}}


def _point_cloud(body):
    crs = str(body.get("crs") or "").upper()
    units = str(body.get("units") or "").lower()
    fc = body.get("pointCloud")
    if not re.fullmatch(r"EPSG:\d{4,6}", crs) or crs in ("EPSG:4326", "EPSG:4269") or units not in ("m", "metre", "meter", "metres", "meters"):
        raise ValueError("Point cloud inspection requires a projected EPSG CRS and metre units.")
    if not isinstance(fc, dict) or fc.get("type") != "FeatureCollection" or not isinstance(fc.get("features"), list) or not 3 <= len(fc["features"]) <= 20000:
        raise ValueError("Provide 3–20,000 GeoJSON Point features with [x,y,z] projected metre coordinates.")
    transform = _transformer(crs)
    xyz=[]
    for i, feat in enumerate(fc["features"]):
        coords=(feat.get("geometry") or {}).get("coordinates")
        if (feat.get("geometry") or {}).get("type") != "Point" or not isinstance(coords, list) or len(coords) < 3:
            raise ValueError(f"Point cloud feature {i+1} needs a Point with [x,y,z].")
        xyz.append(tuple(_number(coords[j], f"point {i+1} coordinate") for j in range(3)))
    zs=[v[2] for v in xyz]; xs=[v[0] for v in xyz]; ys=[v[1] for v in xyz]
    stride=max(1, math.ceil(len(xyz)/5000)); output=[]
    for i in range(0,len(xyz),stride):
        x,y,z=xyz[i]; lon,lat=transform(x,y)
        output.append({"type":"Feature","id":i,"geometry":{"type":"Point","coordinates":[lon,lat]},"properties":{"elevation_m":z}})
    stats={"Input points":len(xyz),"Map points displayed":len(output),"CRS":crs,"Units":"m","X extent":f"{min(xs):g}–{max(xs):g} m","Y extent":f"{min(ys):g}–{max(ys):g} m","Z min/max":f"{min(zs):g} / {max(zs):g} m","Mean Z":f"{statistics.mean(zs):g} m","Point spacing/density":"Not estimated without a defined footprint/voxel size."}
    return {"success":True,"type":"DroneMining","label":"Point cloud inspection","stats":stats,"statistics":stats,"interpretation":"Descriptive inspection of supplied projected XYZ points. Display is evenly sampled for map performance; no classification, denoising, meshing or photogrammetric processing is claimed.","geometry":{"type":"FeatureCollection","features":output},"tableData":[{"point_id":f['id'],**f['properties']} for f in output],"chartData":None,"styleBy":"elevation_m","metadata":{"crs":crs,"units":"m"}}


def _orthomosaic_ndvi(body):
    bands = body.get("bands")
    if not isinstance(bands, dict) or not isinstance(bands.get("red"), dict) or not isinstance(bands.get("nir"), dict):
        raise ValueError("Provide calibrated orthomosaic red and NIR band grids with units='reflectance'.")
    checked = []
    for name in ("red", "nir"):
        band = dict(bands[name])
        if str(band.get("units") or "").lower() not in ("reflectance", "unitless_reflectance"):
            raise ValueError(f"bands.{name}.units must identify calibrated unitless reflectance (not raw DN).")
        band["verticalUnits"] = "m"
        checked.append(_grid(band, f"bands.{name}"))
    red, nir = checked
    _aligned(red, nir, "orthomosaic red/NIR bands")
    transformer = _transformer(red["crs"])
    features=[]; values=[]
    for r in range(red["rows"]):
        for c in range(red["cols"]):
            rv, nv = red["values"][r][c], nir["values"][r][c]
            if rv is None or nv is None: continue
            if not 0 <= rv <= 1.5 or not 0 <= nv <= 1.5:
                raise ValueError("Reflectance values must be between 0 and 1.5; apply the provider scale factor before analysis.")
            denom=nv+rv
            if abs(denom)<1e-12: continue
            ndvi=(nv-rv)/denom; values.append(ndvi)
            features.append(_output_feature(red,r,c,{"NDVI":ndvi,"red_reflectance":rv,"nir_reflectance":nv},transformer))
    if not features: raise ValueError("No valid red/NIR pixel pairs remain after NoData and zero-denominator checks.")
    stats={"Valid pixels":len(values),"Mean NDVI":statistics.mean(values),"NDVI min/max":f"{min(values):.6g} / {max(values):.6g}","Pixel area":f"{red['pixelArea']:g} m²","CRS":red["crs"],"Band units":"Calibrated unitless reflectance","Input":"User-supplied orthomosaic band grids; no orthomosaic generation performed"}
    return {"success":True,"type":"DroneMining","label":"Orthomosaic NDVI","stats":stats,"statistics":stats,"interpretation":"NDVI computed from supplied calibrated red and near-infrared orthomosaic reflectance grids. This does not build an orthomosaic or extract buildings/roads.","geometry":{"type":"FeatureCollection","features":features},"tableData":[{"pixel_id":f['id'],**f['properties']} for f in features],"chartData":[{"name":"Mean NDVI","value":statistics.mean(values)}],"styleBy":"NDVI","metadata":{"crs":red["crs"],"resolution":red["pixelArea"]**0.5,"units":"unitless NDVI"}}
