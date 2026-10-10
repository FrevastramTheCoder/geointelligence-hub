"""Validated point-pattern and interpolation algorithms for GeoIntelligence Hub.

Uses RFC 7946 WGS84 GeoJSON at the API boundary and a local metric projection
for point-pattern distances. Implementations are dependency-light because the
existing backend environment ships only the Earth Engine client; optional GIS
packages are not silently assumed to exist.
"""
from __future__ import annotations

import math
import random
from statistics import mean, median, variance

EARTH_RADIUS_M = 6371008.8


def _finite(value, label):
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric, not a boolean.")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be numeric.")
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite.")
    return result


def read_points(geojson, value_field=None, fields=None, crs="EPSG:4326", max_points=5000):
    if str(crs).upper().replace(" ", "") not in ("EPSG:4326", "OGC:CRS84", "CRS84"):
        raise ValueError("GeoJSON point coordinates must be EPSG:4326 (longitude, latitude). Reproject to WGS84 first.")
    if not isinstance(geojson, dict) or geojson.get("type") != "FeatureCollection":
        raise ValueError("points must be a GeoJSON FeatureCollection of Point features.")
    features = geojson.get("features")
    if not isinstance(features, list) or not 2 <= len(features) <= max_points:
        raise ValueError(f"Provide 2–{max_points} point features.")
    rows = []
    names = [value_field] if value_field else []
    if fields:
        if not isinstance(fields, list) or not fields:
            raise ValueError("fields must be a non-empty list of numeric property names.")
        names.extend(fields)
    for index, feature in enumerate(features):
        geom = feature.get("geometry") if isinstance(feature, dict) else None
        if not geom or geom.get("type") != "Point":
            raise ValueError(f"Feature {index + 1} is not a Point geometry.")
        coords = geom.get("coordinates")
        if not isinstance(coords, (list, tuple)) or len(coords) < 2:
            raise ValueError(f"Feature {index + 1} needs [longitude, latitude] coordinates.")
        lon, lat = _finite(coords[0], "longitude"), _finite(coords[1], "latitude")
        if not -180 <= lon <= 180 or not -90 <= lat <= 90:
            raise ValueError(f"Feature {index + 1} coordinates are outside WGS84 bounds.")
        props = feature.get("properties") or {}
        if not isinstance(props, dict):
            raise ValueError(f"Feature {index + 1} properties must be an object.")
        rows.append({"lon": lon, "lat": lat, "properties": props, "id": feature.get("id", index)})
    if names:
        for name in names:
            values = []
            for index, row in enumerate(rows):
                if name not in row["properties"] or row["properties"][name] is None:
                    raise ValueError(f"Property {name!r} is missing at feature {index + 1}.")
                values.append(_finite(row["properties"][name], f"{name} at feature {index + 1}"))
            if value_field == name:
                for row, value in zip(rows, values):
                    row["value"] = value
            if fields and name in fields:
                for row, value in zip(rows, values):
                    row.setdefault("predictors", {})[name] = value
    # Local metric plane is suitable for regional AOIs; reject spans where
    # equirectangular distortion becomes material for distance-based methods.
    lon0, lat0 = mean(r["lon"] for r in rows), mean(r["lat"] for r in rows)
    if max(r["lon"] for r in rows) - min(r["lon"] for r in rows) > 5 or max(r["lat"] for r in rows) - min(r["lat"] for r in rows) > 5:
        raise ValueError("Point extent exceeds 5 degrees. Split into regional analyses or use a suitable projected CRS workflow.")
    xscale = math.pi / 180 * EARTH_RADIUS_M * max(1e-6, math.cos(math.radians(lat0)))
    yscale = math.pi / 180 * EARTH_RADIUS_M
    for row in rows:
        row["x"] = (row["lon"] - lon0) * xscale
        row["y"] = (row["lat"] - lat0) * yscale
    return rows


def read_polygon(feature, crs="EPSG:4326"):
    if str(crs).upper().replace(" ", "") not in ("EPSG:4326", "OGC:CRS84", "CRS84"):
        raise ValueError("Study-area GeoJSON must be EPSG:4326.")
    geom = feature.get("geometry") if isinstance(feature, dict) and feature.get("type") == "Feature" else feature
    if not isinstance(geom, dict) or geom.get("type") not in ("Polygon", "MultiPolygon"):
        raise ValueError("studyArea must be a GeoJSON Polygon or MultiPolygon.")
    polygons = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    if not polygons:
        raise ValueError("studyArea contains no polygon rings.")
    rings = []
    all_xy = []
    for polygon in polygons:
        if not polygon or len(polygon[0]) < 4:
            raise ValueError("Each study-area polygon needs a closed exterior ring with at least four positions.")
        projected_polygon = []
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4:
                raise ValueError("Every exterior or interior ring must contain at least four positions.")
            projected = []
            for coord in ring:
                lon, lat = _finite(coord[0], "longitude"), _finite(coord[1], "latitude")
                if not -180 <= lon <= 180 or not -90 <= lat <= 90:
                    raise ValueError("Study-area coordinates are outside WGS84 bounds.")
                projected.append((lon, lat))
                all_xy.append((lon, lat))
            if projected[0] != projected[-1]:
                raise ValueError("Study-area polygon rings must be closed.")
            if _ring_self_intersects(projected):
                raise ValueError("Study-area polygon rings must not self-intersect.")
            if abs(_ring_area(projected)) <= 1e-12:
                raise ValueError("Study-area polygon rings must have non-zero area.")
            projected_polygon.append(projected)
        for hole in projected_polygon[1:]:
            if not _in_ring(hole[0][0], hole[0][1], projected_polygon[0]):
                raise ValueError("Interior rings must lie inside their polygon exterior ring.")
        rings.append(projected_polygon)
    lon0, lat0 = mean(x for x, _ in all_xy), mean(y for _, y in all_xy)
    if max(x for x, _ in all_xy) - min(x for x, _ in all_xy) > 5 or max(y for _, y in all_xy) - min(y for _, y in all_xy) > 5:
        raise ValueError("Study area exceeds 5 degrees; use a suitable regional projected-CRS workflow.")
    xs = math.pi / 180 * EARTH_RADIUS_M * max(1e-6, math.cos(math.radians(lat0)))
    ys = math.pi / 180 * EARTH_RADIUS_M
    projected_rings = [[[(x - lon0) * xs, (y - lat0) * ys] for x, y in ring] for polygon in rings for ring in polygon]
    polygon_groups = []
    offset = 0
    for polygon in rings:
        count = len(polygon)
        polygon_groups.append(projected_rings[offset:offset + count])
        offset += count
    area = 0.0
    for polygon in polygon_groups:
        area += abs(_ring_area(polygon[0])) - sum(abs(_ring_area(r)) for r in polygon[1:])
    if not math.isfinite(area) or area <= 0:
        raise ValueError("Study area must have positive non-zero area.")
    bbox = (min(p[0] for poly in polygon_groups for p in poly[0]), min(p[1] for poly in polygon_groups for p in poly[0]),
            max(p[0] for poly in polygon_groups for p in poly[0]), max(p[1] for poly in polygon_groups for p in poly[0]))
    return {"polygons": polygon_groups, "area_m2": area, "bbox": bbox, "lon0": lon0, "lat0": lat0, "xscale": xs, "yscale": ys}


def _ring_area(ring):
    return 0.5 * sum(ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1] for i in range(len(ring) - 1))


def _ring_self_intersects(ring):
    def orient(a, b, c): return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    def on(a, b, p): return min(a[0],b[0])-1e-12<=p[0]<=max(a[0],b[0])+1e-12 and min(a[1],b[1])-1e-12<=p[1]<=max(a[1],b[1])+1e-12
    n = len(ring)-1
    for i in range(n):
        a,b=ring[i],ring[i+1]
        for j in range(i+1,n):
            if j==i+1 or (i==0 and j==n-1): continue
            c,d=ring[j],ring[j+1]
            o1,o2,o3,o4=orient(a,b,c),orient(a,b,d),orient(c,d,a),orient(c,d,b)
            if o1*o2<0 and o3*o4<0: return True
            if (abs(o1)<1e-12 and on(a,b,c)) or (abs(o2)<1e-12 and on(a,b,d)) or (abs(o3)<1e-12 and on(c,d,a)) or (abs(o4)<1e-12 and on(c,d,b)): return True
    return False


def _in_ring(x, y, ring):
    inside = False
    j = len(ring) - 1
    for i, (xi, yi) in enumerate(ring):
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-300) + xi:
            inside = not inside
        j = i
    return inside


def contains_xy(x, y, study):
    return any(_in_ring(x, y, poly[0]) and not any(_in_ring(x, y, hole) for hole in poly[1:]) for poly in study["polygons"])


def to_lonlat(x, y, study):
    return [x / study["xscale"] + study["lon0"], y / study["yscale"] + study["lat0"]]


def align_rows_to_study(rows, study):
    for row in rows:
        row["x"] = (row["lon"] - study["lon0"]) * study["xscale"]
        row["y"] = (row["lat"] - study["lat0"]) * study["yscale"]


def _distance(a, b):
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def _distance_xy(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _neighbors(rows, threshold_m=None, k=None, weight_mode="binary", include_self=False):
    n = len(rows)
    if k is not None:
        if not isinstance(k, int) or not 1 <= k < n:
            raise ValueError("k must be an integer from 1 to n−1.")
        directed = [set(j for _, j in sorted((_distance(rows[i], rows[j]), j) for j in range(n) if j != i)[:k]) for i in range(n)]
        edges = [set(v) for v in directed]
        for i in range(n):
            for j in directed[i]:
                edges[j].add(i)
    else:
        threshold_m = _finite(threshold_m, "distanceThreshold")
        if threshold_m <= 0:
            raise ValueError("distanceThreshold must be greater than zero metres.")
        edges = [set() for _ in rows]
        for i in range(n):
            for j in range(i + 1, n):
                if _distance(rows[i], rows[j]) <= threshold_m:
                    edges[i].add(j); edges[j].add(i)
    if weight_mode not in ("binary", "inverse_distance"):
        raise ValueError("weightMode must be 'binary' or 'inverse_distance'.")
    weights = []
    for i, js in enumerate(edges):
        row = {}
        if include_self:
            row[i] = 1.0
        for j in js:
            d = _distance(rows[i], rows[j])
            if d <= 1e-12 and weight_mode == "inverse_distance":
                raise ValueError("Inverse-distance weights cannot use duplicate point coordinates; aggregate or remove coincident observations.")
            row[j] = (1.0 / d) if weight_mode == "inverse_distance" else 1.0
        weights.append(row)
    if not include_self and any(not row for row in weights):
        raise ValueError("Distance weights leave one or more points without neighbours; increase the threshold or use k-nearest neighbours.")
    return weights


def _moran_i(values, weights):
    n = len(values); avg = mean(values); z = [v - avg for v in values]
    denom = sum(v * v for v in z)
    if denom <= 0:
        raise ValueError("Moran's I requires a non-constant numeric field.")
    s0 = sum(sum(row.values()) for row in weights)
    if s0 <= 0:
        raise ValueError("Spatial weights have no links.")
    numerator = sum(w * z[i] * z[j] for i, row in enumerate(weights) for j, w in row.items() if i != j)
    return n / s0 * numerator / denom


def _bh(p_values):
    n = len(p_values); order = sorted(range(n), key=lambda i: p_values[i]); q = [1.0] * n; running = 1.0
    for rank_index in range(n - 1, -1, -1):
        i = order[rank_index]; rank = rank_index + 1
        running = min(running, p_values[i] * n / rank); q[i] = min(1.0, running)
    return q


def _normal_p(z):
    return max(0.0, min(1.0, math.erfc(abs(z) / math.sqrt(2))))


def _feature(row, properties):
    return {"type": "Feature", "id": row.get("id"), "geometry": {"type": "Point", "coordinates": [row["lon"], row["lat"]]}, "properties": properties}


def _fc(features):
    return {"type": "FeatureCollection", "features": features}


def _grid(study, cell_size_m, max_cells=2500):
    cell_size_m = _finite(cell_size_m, "cellSize")
    if cell_size_m <= 0:
        raise ValueError("cellSize must be positive metres.")
    minx, miny, maxx, maxy = study["bbox"]
    nx, ny = max(1, math.ceil((maxx - minx) / cell_size_m)), max(1, math.ceil((maxy - miny) / cell_size_m))
    if nx * ny > max_cells:
        raise ValueError(f"Grid would have {nx * ny} cells; increase cellSize (limit {max_cells}).")
    pts = []
    for iy in range(ny):
        y = miny + (iy + 0.5) * cell_size_m
        for ix in range(nx):
            x = minx + (ix + 0.5) * cell_size_m
            if contains_xy(x, y, study):
                pts.append((x, y))
    if not pts:
        raise ValueError("No grid centres fall inside studyArea; decrease cellSize.")
    return pts


def run_spatial_statistics(body):
    method = str(body.get("method") or "").strip().lower().replace("-", "_").replace(" ", "_")
    seed = int(body.get("seed", 42))
    if not 0 <= seed <= 2**31 - 1:
        raise ValueError("seed must be between 0 and 2^31−1.")
    if method == "spatial_sampling":
        study = read_polygon(body.get("studyArea"), body.get("crs", "EPSG:4326"))
        count = int(body.get("sampleSize", 100))
        if not 1 <= count <= 5000:
            raise ValueError("sampleSize must be between 1 and 5000.")
        rng = random.Random(seed); minx, miny, maxx, maxy = study["bbox"]
        result = []; attempts = 0
        while len(result) < count and attempts < count * 10000:
            attempts += 1; x = rng.uniform(minx, maxx); y = rng.uniform(miny, maxy)
            if contains_xy(x, y, study):
                lon, lat = to_lonlat(x, y, study)
                result.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                               "properties": {"sample_id": len(result) + 1, "seed": seed, "method": "uniform random"}})
        if len(result) != count:
            raise ValueError("Could not place all samples inside the polygon; check geometry validity and shape.")
        return {"type": "SpatialStatistics", "label": f"Uniform Random Sample ({count})", "stats": {"Samples": count, "Seed": seed, "AOI area": f"{study['area_m2']/1e6:.3f} km²", "CRS": "EPSG:4326 output; metric local plane for sampling"},
                "interpretation": "Uniform random point sample inside the AOI using rejection sampling. Spatial independence is assumed; no stratification is applied.", "geometry": _fc(result), "chartData": None}

    value_field = str(body.get("valueField") or "").strip()
    field_list = body.get("predictors") if method == "spatial_regression" else None
    point_limits={"global_moran":1000,"local_moran":500,"getis_ord_gi_star":2000,"nearest_neighbor":2000,"point_pattern":2000,
                  "idw":200,"kriging":100,"spatial_regression":500,"kde":5000}
    rows = read_points(body.get("points"), value_field or None, field_list, body.get("crs", "EPSG:4326"), point_limits.get(method,5000))
    if method not in ("kde", "nearest_neighbor", "point_pattern") and not value_field:
        raise ValueError(f"{method} requires a numeric valueField property.")
    values = [r["value"] for r in rows] if value_field else []
    weight_mode = str(body.get("weightMode", "binary"))
    threshold = body.get("distanceThreshold")
    k = body.get("k")
    weights = None
    if method in ("global_moran", "local_moran", "getis_ord_gi_star"):
        weights = _neighbors(rows, threshold, int(k) if k is not None else None, weight_mode,
                             include_self=(method == "getis_ord_gi_star"))
    stats, features, chart = {}, [], []

    if method == "global_moran":
        if len(rows) < 4:
            raise ValueError("Global Moran's I needs at least four points.")
        observed = _moran_i(values, weights); expected = -1 / (len(values) - 1)
        permutations = int(body.get("permutations", 199))
        if not 99 <= permutations <= 999:
            raise ValueError("permutations must be between 99 and 999.")
        if permutations*sum(map(len,weights))>20_000_000:
            raise ValueError("Global Moran permutation workload exceeds 20 million weighted links; reduce points/permutations or use sparse k-nearest weights.")
        rng = random.Random(seed); extreme = 0
        for _ in range(permutations):
            permuted = values[:]; rng.shuffle(permuted)
            if abs(_moran_i(permuted, weights) - expected) >= abs(observed - expected):
                extreme += 1
        p = (extreme + 1) / (permutations + 1)
        stats = {"Moran's I": observed, "Expected I under randomization": expected,
                 "Permutation p-value (two-sided)": p, "Permutations": permutations,
                 "P-value resolution": f"≥ {1/(permutations+1):.4f}", "Points": len(rows),
                 "Weight matrix": f"{weight_mode}; {'k='+str(k) if k else 'threshold='+str(threshold)+' m'}",
                 "Significance": "Significant at α=0.05" if p <= 0.05 else "Not significant at α=0.05"}
        for row, val in zip(rows, values):
            features.append(_feature(row, {"value": val}))
        interpretation = "Global spatial autocorrelation tested by randomization; significance is based on the reported two-sided permutation p-value. Inference assumes exchangeability under the null; weights and study design matter."

    elif method == "local_moran":
        if len(rows) < 5:
            raise ValueError("Local Moran's I needs at least five points.")
        permutations = int(body.get("permutations", 199))
        if not 99 <= permutations <= 999 or len(rows) * permutations * max(1, max(map(len, weights))) > 20_000_000:
            raise ValueError("Local Moran permutations must be 99–999 and total point-neighbour tests ≤20 million; reduce sample size or permutations.")
        avg = mean(values); s2 = sum((v - avg) ** 2 for v in values) / len(values)
        if s2 <= 0:
            raise ValueError("Local Moran's I requires a non-constant numeric field.")
        z = [(v - avg) / math.sqrt(s2) for v in values]; rng = random.Random(seed); pvals = []; local = []
        for i, row_w in enumerate(weights):
            neigh = list(row_w.items()); obs = z[i] * sum(w * z[j] for j, w in neigh)
            pool = [z[j] for j in range(len(z)) if j != i]; extreme = 0
            for _ in range(permutations):
                sample = rng.sample(pool, min(len(neigh), len(pool)))
                simulated = z[i] * sum(neigh[t][1] * sample[t] for t in range(len(sample)))
                if abs(simulated) >= abs(obs): extreme += 1
            local.append(obs); pvals.append((extreme + 1) / (permutations + 1))
        qvals = _bh(pvals)
        for i, row in enumerate(rows):
            cluster = "High-High" if z[i] > 0 and local[i] > 0 else "Low-Low" if z[i] < 0 and local[i] > 0 else "High-Low" if z[i] > 0 else "Low-High"
            props = {"value": values[i], "local_moran_i": local[i], "p_value": pvals[i], "q_value_bh": qvals[i],
                     "cluster": cluster if qvals[i] <= 0.05 else "Not significant"}
            features.append(_feature(row, props)); chart.append({"name": str(row["id"]), "value": local[i]})
        stats = {"Points": len(rows), "Permutations per point": permutations, "Significant after BH q≤0.05": sum(q <= 0.05 for q in qvals),
                 "Multiple testing": f"Benjamini–Hochberg FDR across {len(rows)} local tests; spatial dependence can affect FDR control.",
                 "Weight matrix": f"{weight_mode}; {'k='+str(k) if k else 'threshold='+str(threshold)+' m'}"}
        interpretation = "Local Moran's I cluster/outlier labels are assigned only where permutation p-values survive Benjamini–Hochberg false-discovery-rate correction at q≤0.05. Raw p-values and adjusted q-values are included per point."

    elif method == "getis_ord_gi_star":
        if len(rows) < 5:
            raise ValueError("Getis-Ord Gi* needs at least five points.")
        avg = mean(values); std = math.sqrt(sum((x - avg) ** 2 for x in values) / len(values))
        if std <= 0:
            raise ValueError("Getis-Ord Gi* requires a non-constant field.")
        zs = []; pvals = []
        for i, row_w in enumerate(weights):
            sw, sw2 = sum(row_w.values()), sum(w*w for w in row_w.values())
            denominator = std * math.sqrt(max(0, (len(values)*sw2 - sw*sw)/(len(values)-1)))
            zscore = (sum(w*values[j] for j,w in row_w.items()) - avg*sw)/denominator if denominator else 0.0
            zs.append(zscore); pvals.append(_normal_p(zscore))
        qvals = _bh(pvals)
        for i,row in enumerate(rows):
            features.append(_feature(row,{"value":values[i],"gi_star_z":zs[i],"p_value_normal":pvals[i],"q_value_bh":qvals[i],
                "hotspot": "Hot spot" if zs[i] > 0 and qvals[i] <= 0.05 else "Cold spot" if zs[i] < 0 and qvals[i] <= 0.05 else "Not significant"}))
            chart.append({"name":str(row["id"]),"value":zs[i]})
        stats={"Points":len(rows),"Significant after BH q≤0.05":sum(q<=0.05 for q in qvals),"Reference distribution":"Normal approximation; randomization variance, not permutation p-values",
               "Multiple testing":f"Benjamini–Hochberg FDR across {len(rows)} tests; spatial dependence can affect FDR control."}
        interpretation="Getis-Ord Gi* uses self-inclusive spatial weights. Z scores and normal-approximation p-values are reported per point; hot/cold labels require q≤0.05 after BH correction."

    elif method in ("nearest_neighbor", "point_pattern"):
        if len(rows) < 3:
            raise ValueError("Nearest-neighbour and point-pattern analysis need at least three points.")
        nearest=[]
        for i,row in enumerate(rows):
            nearest.append(min(_distance(row,other) for j,other in enumerate(rows) if i != j))
        if method == "nearest_neighbor":
            study=read_polygon(body.get("studyArea"),body.get("crs","EPSG:4326")); n=len(rows); density=n/study["area_m2"]
            observed=mean(nearest); expected=0.5/math.sqrt(density); ratio=observed/expected
            se=0.26136/math.sqrt(n*density); z=(observed-expected)/se if se else 0; p=_normal_p(z)
            stats={"Points":n,"Observed mean nearest distance":f"{observed:.3f} m","CSR expected distance":f"{expected:.3f} m","Clark–Evans R":ratio,"z-score":z,"p-value (normal approximation)":p,
                   "Significance":"Significant at α=0.05" if p<=0.05 else "Not significant at α=0.05","AOI area":f"{study['area_m2']/1e6:.3f} km²","Edge correction":"None; CSR approximation assumes homogeneous Poisson process in the supplied polygon."}
            interpretation="Clark–Evans nearest-neighbour ratio compared with complete spatial randomness (CSR). Edge effects are not corrected; interpret the normal-approximation p-value cautiously, especially for irregular AOIs or inhomogeneous intensity."
        else:
            study=read_polygon(body.get("studyArea"),body.get("crs","EPSG:4326")); radii=body.get("distances") or [median(nearest)*i for i in (1,2,3)]
            radii=[_finite(r,"distance") for r in radii]
            if not 1<=len(radii)<=12 or any(r<=0 for r in radii): raise ValueError("distances must contain 1–12 positive metre radii.")
            n=len(rows); stats={"Points":n,"Mean nearest-neighbour distance (m)":mean(nearest),"AOI area (km²)":study["area_m2"]/1e6,"Ripley K edge correction":"None"}; chart=[]
            dmat=[[_distance(a,b) for b in rows] for a in rows]
            for radius in radii:
                pairs=sum(1 for i in range(n) for j in range(n) if i!=j and dmat[i][j]<=radius)
                kval=study["area_m2"]*pairs/(n*n); lval=math.sqrt(kval/math.pi)-radius
                stats[f"K({radius:.2f}m)"]=kval; stats[f"L(r)-r at {radius:.2f}m"]=lval; chart.append({"name":f"{radius:.1f}m","value":lval})
            interpretation="Ripley's K/L descriptive point-pattern statistics with no edge correction or Monte-Carlo CSR envelope. Positive L(r)-r suggests clustering descriptively; no significance claim is made."
        for row,d in zip(rows,nearest): features.append(_feature(row,{"nearest_distance_m":d}))

    elif method == "kde":
        if len(rows)<2: raise ValueError("KDE needs at least two point locations.")
        study=read_polygon(body.get("studyArea"),body.get("crs","EPSG:4326")); align_rows_to_study(rows,study)
        bandwidth=_finite(body.get("bandwidth"),"bandwidth")
        if bandwidth<=0: raise ValueError("KDE bandwidth must be positive metres.")
        targets=_grid(study,body.get("cellSize",bandwidth),max_cells=2500)
        density_scale=1/(2*math.pi*bandwidth*bandwidth*len(rows))
        for tx,ty in targets:
            mass=sum(math.exp(-0.5*((tx-r['x'])**2+(ty-r['y'])**2)/(bandwidth**2)) for r in rows)
            density=mass*density_scale; lonlat=to_lonlat(tx,ty,study)
            features.append({"type":"Feature","geometry":{"type":"Point","coordinates":lonlat},"properties":{"density_points_per_m2":density,"method":"Gaussian KDE","bandwidth_m":bandwidth}})
            chart.append({"name":str(len(chart)+1),"value":density})
        density_values=[f['properties']['density_points_per_m2'] for f in features]
        stats={"Input points":len(rows),"Grid cells":len(features),"Bandwidth":f"{bandwidth:g} m","Cell size":f"{body.get('cellSize',bandwidth)} m","Kernel":"Gaussian; planar; no edge correction","Density range (points/m²)":f"{min(density_values):.8g}–{max(density_values):.8g}"}
        interpretation="Gaussian kernel density estimate on a regular grid. Bandwidth controls smoothing; output is an intensity surface, not a probability. No edge correction is applied."

    elif method in ("idw", "kriging"):
        if len(rows)<3: raise ValueError(f"{method.upper()} requires at least three valued point samples.")
        if len({(round(r['x'],5),round(r['y'],5)) for r in rows}) < len(rows):
            raise ValueError(f"{method.upper()} requires distinct sample coordinates; aggregate duplicate locations first.")
        study=read_polygon(body.get("studyArea"),body.get("crs","EPSG:4326")); align_rows_to_study(rows,study); targets=_grid(study,body.get("cellSize",1000),max_cells=100 if method=="kriging" else 2500)
        power=_finite(body.get("power",2),"power")
        if not 0.5<=power<=5: raise ValueError("IDW power must be from 0.5 to 5.")
        if method=="kriging":
            if len(rows)<8 or len(rows)>100: raise ValueError("Ordinary kriging requires 8–100 samples for this implementation.")
            if body.get("sill") is None or body.get("range") is None or body.get("nugget") is None:
                raise ValueError("Specify variogram sill, range (metres), and nugget explicitly. Fit and validate the variogram before interpreting kriging output.")
            sill=_finite(body.get("sill"),"sill"); range_m=_finite(body.get("range"),"range"); nugget=_finite(body.get("nugget"),"nugget")
            if sill<=0 or range_m<=0 or nugget<0: raise ValueError("Kriging sill/range must be positive and nugget non-negative.")
            if len({(round(r['x'],5),round(r['y'],5)) for r in rows})<len(rows): raise ValueError("Kriging cannot use duplicate sample coordinates.")
            gamma=lambda d: nugget+sill*(1.5*(d/range_m)-0.5*(d/range_m)**3) if d<range_m else nugget+sill
            matrix=[[0.0 if i==j else gamma(_distance(a,b)) for j,b in enumerate(rows)]+[1.0] for i,a in enumerate(rows)]+[[1.0]*len(rows)+[0.0]]
            lu=_lu_factor(matrix)
        output=[]
        for tx,ty in targets:
            ds=[_distance_xy((tx,ty),(r['x'],r['y'])) for r in rows]
            if method=="idw":
                exact=[i for i,d in enumerate(ds) if d<1e-8]
                estimate=values[exact[0]] if exact else sum(values[i]/(ds[i]**power) for i in range(len(rows)))/sum(1/(d**power) for d in ds)
                props={"predicted":estimate,"method":"IDW","power":power}
            else:
                sol=_lu_solve(lu,[gamma(d) for d in ds]+[1.0]); estimate=sum(sol[i]*values[i] for i in range(len(rows))); kv=sum(sol[i]*gamma(ds[i]) for i in range(len(rows)))+sol[-1]
                props={"predicted":estimate,"kriging_variance":max(0.0,kv),"method":"ordinary kriging spherical variogram"}
            lonlat=to_lonlat(tx,ty,study); output.append({"type":"Feature","geometry":{"type":"Point","coordinates":lonlat},"properties":props}); chart.append({"name":str(len(chart)+1),"value":estimate})
        stats={"Input samples":len(rows),"Grid cells":len(output),"Cell size":f"{body.get('cellSize',1000)} m","Value field":value_field,
               "Algorithm":"Inverse-distance weighted interpolation" if method=="idw" else "Ordinary kriging; spherical semivariogram",
               "Assumptions":"IDW is deterministic and provides no inferential uncertainty." if method=="idw" else f"Second-order stationarity, isotropy and spherical semivariogram assumed; sill={sill:g}, range={range_m:g}m, nugget={nugget:g}. Validate variogram and residuals."}
        interpretation="Interpolation is modelled from supplied point samples, not observed raster data. Predictions outside the sample support are not extrapolation-validated." if method=="idw" else "Ordinary kriging predictions and model variance under the stated stationary isotropic spherical variogram; variance is not a prediction interval without distributional assumptions."
        features=output

    elif method == "spatial_regression":
        if len(rows)<8: raise ValueError("Geographically weighted regression requires at least eight point observations.")
        predictors=body.get("predictors") or []
        if not 1<=len(predictors)<=8: raise ValueError("Provide 1–8 numeric predictor property names.")
        bandwidth=_finite(body.get("bandwidth"),"bandwidth")
        if bandwidth<=0: raise ValueError("GWR bandwidth must be a positive distance in metres.")
        x=[[1.0]+[r["predictors"][p] for p in predictors] for r in rows]; y=values; predictions=[]; local_betas=[]
        for center in rows:
            wi=[math.exp(-0.5*(_distance(center,row)/bandwidth)**2) for row in rows]
            effective=sum(w>0.05 for w in wi)
            if effective < len(predictors)+3:
                raise ValueError("GWR bandwidth leaves too few effective neighbours; increase bandwidth or reduce predictors.")
            xtx=[[sum(w*row[i]*row[j] for w,row in zip(wi,x)) for j in range(len(x[0]))] for i in range(len(x[0]))]
            xty=[sum(w*row[i]*value for w,row,value in zip(wi,x,y)) for i in range(len(x[0]))]
            beta=_solve(xtx,xty); local_betas.append(beta); predictions.append(sum(a*b for a,b in zip(x[len(predictions)],beta)))
        resid=[obs-fit for obs,fit in zip(y,predictions)]; ybar=mean(y); sst=sum((v-ybar)**2 for v in y); sse=sum(v*v for v in resid)
        if sst<=0: raise ValueError("Regression dependent variable must vary.")
        r2=1-sse/sst
        residual_moran=None
        if len(rows)>=4 and max(resid)-min(resid)>1e-10:
            residual_weights=_neighbors(rows,k=min(4,len(rows)-1)); observed=_moran_i(resid,residual_weights); expected=-1/(len(rows)-1)
            permutations=int(body.get("permutations",199))
            if not 99<=permutations<=999 or permutations*sum(map(len,residual_weights))>20_000_000:
                raise ValueError("Residual Moran permutations must be 99–999 and total weighted links ≤20 million.")
            rng=random.Random(seed); extreme=0
            for _ in range(permutations):
                perm=resid[:];rng.shuffle(perm)
                if abs(_moran_i(perm,residual_weights)-expected)>=abs(observed-expected): extreme+=1
            residual_moran={"I":observed,"permutation_p":(extreme+1)/(permutations+1),"permutations":permutations}
        stats={"Observations":len(y),"Dependent variable":value_field,"R² (local fitted)":r2,"GWR bandwidth":f"{bandwidth:g} m","Model":"Gaussian-kernel geographically weighted regression","Predictors":", ".join(predictors),
               "Coefficient inference":"Local coefficient p-values are not reported; spatial multiple-testing and local covariance assumptions require dedicated diagnostics.",
               "Residual spatial autocorrelation (Moran)":residual_moran or "Not computed (constant residuals or invalid permutation count)"}
        for i,(row,fitted,error,beta) in enumerate(zip(rows,predictions,resid,local_betas)):
            props={"observed":row['value'],"fitted":fitted,"residual":error,"local_intercept":beta[0]}
            props.update({f"local_coef_{name}":coef for name,coef in zip(predictors,beta[1:])})
            features.append(_feature(row,props))
        chart=[{"name":str(row['id']),"value":error} for row,error in zip(rows,resid)]
        interpretation="Gaussian-kernel geographically weighted regression with user-specified bandwidth. Local coefficients are descriptive; local coefficient p-values are omitted because spatial dependence and multiple testing require additional inference procedures. Residual Moran's I is reported separately as a permutation diagnostic when calculable."
    else:
        raise ValueError("Unknown spatial method. Use global_moran, local_moran, getis_ord_gi_star, kde, nearest_neighbor, point_pattern, idw, kriging, spatial_sampling or spatial_regression.")

    return {"type":"SpatialStatistics","label":method.replace('_',' ').title(),"stats":stats,
            "interpretation":interpretation,"geometry":_fc(features),"chartData":chart or None}


def _solve(matrix, vector):
    n=len(vector); a=[list(map(float,row))+[float(vector[i])] for i,row in enumerate(matrix)]
    for c in range(n):
        pivot=max(range(c,n),key=lambda r:abs(a[r][c]))
        if abs(a[pivot][c])<1e-12: raise ValueError("Model matrix is singular; check collinearity, duplicate points, or variogram settings.")
        a[c],a[pivot]=a[pivot],a[c]; div=a[c][c]; a[c]=[v/div for v in a[c]]
        for r in range(n):
            if r==c: continue
            factor=a[r][c]
            if factor: a[r]=[a[r][j]-factor*a[c][j] for j in range(n+1)]
    return [a[i][n] for i in range(n)]


def _lu_factor(matrix):
    n=len(matrix); a=[list(map(float,row)) for row in matrix]; piv=list(range(n))
    for c in range(n):
        p=max(range(c,n),key=lambda r:abs(a[r][c]))
        if abs(a[p][c])<1e-12: raise ValueError("Kriging variogram system is singular; revise range/nugget or remove collinear/duplicate points.")
        a[c],a[p]=a[p],a[c];piv[c],piv[p]=piv[p],piv[c]
        for r in range(c+1,n):
            a[r][c]/=a[c][c]
            for j in range(c+1,n):a[r][j]-=a[r][c]*a[c][j]
    return a,piv


def _lu_solve(factor, vector):
    lu,piv=factor;n=len(piv);b=[float(vector[piv[i]]) for i in range(n)]
    for i in range(n):b[i]-=sum(lu[i][j]*b[j] for j in range(i))
    for i in range(n-1,-1,-1):b[i]=(b[i]-sum(lu[i][j]*b[j] for j in range(i+1,n)))/lu[i][i]
    return b
