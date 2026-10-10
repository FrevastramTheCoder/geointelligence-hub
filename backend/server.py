"""
GeoIntelligence Hub — Bridge Server v3 — Per-User GEE
- Email/password or Google login for identity
- Setup wizard guides user to create their own GEE project
- User connects GEE via Google OAuth → token stored per-user
- Analysis runs on USER'S own Earth Engine account
"""
import json, os, re, traceback, time, hashlib, secrets, threading, urllib.request, urllib.parse, mimetypes, math
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlencode, urlsplit

try:
    from dotenv import load_dotenv
    # Load backend/.env (this file's directory) regardless of the current working directory.
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
except ImportError:
    # python-dotenv not installed; fall back to whatever is already in the process environment.
    pass

import ee
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from remote_sensing import (SPECTRAL_INDICES as RS_SPECTRAL_INDICES, sensor_bands,
                            trend_statistics, validate_training_geojson, classification_metrics)
from spatial_analysis import ahp_weights, validate_weights

from storage import (
    connection,
    create_session,
    get_user,
    get_user_by_id,
    hash_password,
    init_db,
    migrate_legacy_users,
    revoke_session,
    seal,
    session_user_id,
    unseal,
    verify_password,
)

PORT = int(os.getenv('PORT', '5001'))
HOST = os.getenv('HOST', '127.0.0.1')
FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:3000').rstrip('/')
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID', '').strip()
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET', '').strip()
GOOGLE_REDIRECT_URI = os.getenv(
    'GOOGLE_REDIRECT_URI', f'http://localhost:{PORT}/api/gee/oauth/callback'
).strip()
ADMIN_KEY = os.getenv('ADMIN_KEY', '').strip()
DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'
SESSION_TTL_SECONDS = int(os.getenv('SESSION_TTL_SECONDS', str(60 * 60 * 24)))
MAX_BODY_BYTES = int(os.getenv('MAX_BODY_BYTES', str(2 * 1024 * 1024)))
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '').strip()
GOOGLE_USERINFO_URL = 'https://www.googleapis.com/oauth2/v3/userinfo'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_TOKENINFO_URL = 'https://oauth2.googleapis.com/tokeninfo'
EE_SCOPES = (
    'https://www.googleapis.com/auth/earthengine',
    'https://www.googleapis.com/auth/cloud-platform',
)
USERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'users.json')

# --- Auth rate limiting (in-memory sliding window, per-IP) ---
# Prevents brute-force on /api/login, /api/register, /api/google-login.
RATE_LIMIT_MAX_ATTEMPTS = int(os.getenv('RATE_LIMIT_MAX_ATTEMPTS', '20'))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv('RATE_LIMIT_WINDOW_SECONDS', '600'))
_RATE_BUCKETS = {}
_RATE_LOCK = threading.Lock()


def _client_ip(handler):
    forwarded = handler.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()[:64]
    try:
        return handler.client_address[0][:64]
    except Exception:
        return 'unknown'


def _hit_rate_limit(key):
    now = time.time()
    with _RATE_LOCK:
        attempts = _RATE_BUCKETS.get(key, [])
        attempts = [t for t in attempts if now - t < RATE_LIMIT_WINDOW_SECONDS]
        attempts.append(now)
        _RATE_BUCKETS[key] = attempts[-RATE_LIMIT_MAX_ATTEMPTS * 2:]
        return len(attempts) > RATE_LIMIT_MAX_ATTEMPTS

FRONTEND_DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend', 'dist')


init_db()
migrate_legacy_users(USERS_FILE)

# Earth Engine is initialized only with the requesting user's credentials.
_ee_ready = False


def _make_session(email):
    user = get_user(email)
    if not user:
        return None
    return create_session(user['id'], SESSION_TTL_SECONDS)


def _verify_session(token):
    user_id = session_user_id(token)
    if not user_id:
        return None
    user = get_user_by_id(user_id)
    return user['email'] if user else None


def _valid_project_id(project_id):
    return bool(re.fullmatch(r'[a-z][a-z0-9-]{4,28}[a-z0-9]', project_id or ''))


def _parse_class_names(value):
    """Custom class labels from the GEOAI planner. Returns None when absent."""
    if value is None:
        return None
    if isinstance(value, str):
        items = [x.strip() for x in re.split(r'[,;|/]|\band\b', value) if x.strip()]
    elif isinstance(value, (list, tuple)):
        items = [str(x).strip() for x in value if str(x).strip()]
    else:
        return None
    items = [x[:40] for x in items]
    if not 3 <= len(items) <= 8:
        return None
    # Title-case for legend display, keep user wording otherwise
    return [' '.join(w[:1].upper() + w[1:] for w in name.split()) if name else name for name in items]


IMPLEMENTED_ANALYSES = [
    'ndvi', 'evi', 'savi', 'ndwi', 'ndbi', 'urban_growth', 'elevation', 'slope',
    'landcover', 'vegetation', 'dynamicworld', 'worldcover_v200', 'modis_lc',
    'modis_cmg', 'copernicus_lc', 'glc_fcs30', 'nlcd', 'corine', 'change',
    'buildings', 'flood', 'flood_mapping', 'lst', 'rainfall', 'erosion',
    'drought', 'timeseries',
    # Phase 2 — full GEE operator catalogue (all real GEE, no mocks)
    'spectral_index', 'imagery', 'aspect', 'hillshade', 'slope_classes',
    'curvature', 'tri', 'tpi', 'twi', 'terrain',
    'lst_change', 'uhi', 'uftvi', 'sprawl', 'lulc_change', 'deforestation',
    'et', 'airquality', 'hydrology', 'landslide', 'salinity', 'moisture', 'water_change',
    'mineral', 'suitability', 'trend', 'waterlogging',
]

SPECTRAL_INDICES = list(RS_SPECTRAL_INDICES)


def _json_number(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_expiry(value):
    """Parse stored expiry into a NAIVE UTC datetime.

    google-auth's utcnow() is naive (tzinfo=None), so an aware expiry
    crashes `credentials.expired` with
    "can't compare offset-naive and offset-aware datetimes".
    Always normalize to naive UTC here.
    """
    if not value:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            if parsed.tzinfo:
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except ValueError:
            return None


def _normalize_expiry(dt):
    if dt is not None and getattr(dt, 'tzinfo', None) is not None:
        try:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            return dt.replace(tzinfo=None)
    return dt


def _verify_google_access_token_audience(access_token):
    """Verify a Google OAuth access_token was issued to OUR client.

    Prevents an attacker passing a token minted for a different app
    (e.g. via their own OAuth client) to impersonate a victim.
    Raises RuntimeError on failure.
    """
    if not GOOGLE_CLIENT_ID:
        raise RuntimeError('Google OAuth is not configured on the backend.')
    try:
        url = f'{GOOGLE_TOKENINFO_URL}?access_token={urllib.parse.quote(access_token, safe="")}'
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as response:
            info = json.loads(response.read())
    except Exception as exc:
        raise RuntimeError(f'Google token verification failed: {exc}')
    if not isinstance(info, dict):
        raise RuntimeError('Google token verification failed.')
    aud = str(info.get('aud', '') or '')
    azp = str(info.get('azp', '') or '')
    # tokeninfo returns aud/azp; accept either matching our client ID.
    if GOOGLE_CLIENT_ID not in (aud, azp):
        raise RuntimeError('Google token was not issued to this application.')
    try:
        if int(info.get('expires_in', '1')) <= 0:
            raise RuntimeError('Google token is expired.')
    except (TypeError, ValueError):
        pass
    return info


def _credentials(access_token, refresh_token=None, expires_at=None):
    if not access_token:
        raise RuntimeError(
            'Stored Earth Engine token is missing or cannot be decrypted '
            '(encryption key rotated?). Re-connect your Google account.'
        )
    return Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri=GOOGLE_TOKEN_URL,
        client_id=GOOGLE_CLIENT_ID or None,
        client_secret=GOOGLE_CLIENT_SECRET or None,
        scopes=list(EE_SCOPES),
        expiry=_normalize_expiry(_parse_expiry(expires_at)),
    )


def _refresh_connection(connection_row, credentials):
    # Defensive: old DB rows may hold aware ISO strings; google-auth
    # compares with naive utcnow(), so normalize first.
    try:
        credentials.expiry = _normalize_expiry(getattr(credentials, 'expiry', None))
        is_expired = credentials.expired
    except TypeError:
        # Mixed naive/aware — treat as expired when refresh is possible,
        # otherwise force re-connect message below.
        is_expired = bool(credentials.refresh_token)
        credentials.expiry = _normalize_expiry(getattr(credentials, 'expiry', None))
    if not is_expired:
        return credentials
    if not credentials.refresh_token:
        raise RuntimeError('Earth Engine token expired. Re-connect your Google account.')
    credentials.refresh(Request())
    try:
        credentials.expiry = _normalize_expiry(getattr(credentials, 'expiry', None))
    except Exception:
        pass
    expiry = credentials.expiry.isoformat() if credentials.expiry else None
    with connection() as conn:
        conn.execute(
            'UPDATE ee_connections SET ee_access_token = ?, token_expires_at = ?, updated_at = ? WHERE id = ?',
            (seal(credentials.token), expiry, time.time(), connection_row['id']),
        )
    return credentials


def _probe_earth_engine(credentials, project_id):
    """Initialize EE and execute a small public-dataset request."""
    ee.Initialize(credentials=credentials, project=project_id)
    probe_geometry = ee.Geometry.Point([39.2230, -6.7736]).buffer(250)
    probe = (
        ee.Image('USGS/SRTMGL1_003')
        .select('elevation')
        .reduceRegion(
            reducer=ee.Reducer.mean(), geometry=probe_geometry, scale=1000,
            maxPixels=10000, bestEffort=True,
        )
        .getInfo()
    )
    if not isinstance(probe, dict):
        raise RuntimeError('Earth Engine returned no dataset response')
    return {'connected': True, 'earth_engine': 'available', 'probe': probe}


def _connection_for_user(email):
    user = get_user(email)
    if not user:
        return None
    with connection() as conn:
        row = conn.execute(
            'SELECT * FROM ee_connections WHERE user_id = ? ORDER BY updated_at DESC, created_at DESC LIMIT 1',
            (user['id'],),
        ).fetchone()
        return dict(row) if row else None


def _connection_status(email, verify=False):
    user = get_user(email)
    row = _connection_for_user(email)
    base = {
        'oauthConnected': bool(row and row.get('oauth_connected')),
        'eeAuthenticated': bool(row and row.get('ee_authenticated')),
        'earthEngineAvailable': bool(row and row.get('ee_available')),
        'analysisAvailable': bool(row and row.get('analysis_available')),
        'geeConnected': bool(row and row.get('is_active') and row.get('analysis_available')),
        'projectId': row.get('google_project_id') if row else (user or {}).get('cloud_project_id'),
        'error': row.get('last_error') if row else None,
    }
    if not row or not verify:
        return base
    try:
        token = unseal(row.get('ee_access_token'))
        refresh = unseal(row.get('ee_refresh_token'))
        creds = _refresh_connection(row, _credentials(token, refresh, row.get('token_expires_at')))
        _probe_earth_engine(creds, row['google_project_id'])
        with connection() as conn:
            conn.execute(
                'UPDATE ee_connections SET is_active = 1, ee_authenticated = 1, ee_available = 1, '
                'analysis_available = 1, last_error = NULL, verified_at = ?, updated_at = ? WHERE id = ?',
                (time.time(), time.time(), row['id']),
            )
        base.update({
            'eeAuthenticated': True, 'earthEngineAvailable': True,
            'analysisAvailable': True, 'geeConnected': True, 'error': None,
        })
    except Exception as exc:
        message = _gee_error_message(exc)
        with connection() as conn:
            conn.execute(
                'UPDATE ee_connections SET is_active = 0, ee_authenticated = 0, ee_available = 0, '
                'analysis_available = 0, last_error = ?, updated_at = ? WHERE id = ?',
                (message, time.time(), row['id']),
            )
        base.update({
            'eeAuthenticated': False, 'earthEngineAvailable': False,
            'analysisAvailable': False, 'geeConnected': False, 'error': message,
        })
    return base


def _gee_error_message(exc):
    message = str(exc).strip()
    lower = message.lower()
    if not message:
        return 'Earth Engine verification failed.'
    # Token is not a Google OAuth token at all (user pasted wrong value).
    if 'not a google oauth access token' in lower:
        return message
    # Expired / revoked token.
    if 'expired' in lower and ('token' in lower or 'credential' in lower):
        return ('Your Google access token is expired or revoked. '
                'Click "Connect Google Earth Engine" again, or paste a fresh '
                'ya29.* token (Playground tokens expire after ~1 hour).')
    # Wrong scopes — most common when token came from Playground without EE scope.
    if 'insufficient' in lower and ('scope' in lower or 'permission' in lower):
        return ('Token is valid but missing the Earth Engine scope. '
                'In OAuth Playground select scopes '
                '"https://www.googleapis.com/auth/earthengine" + '
                '"https://www.googleapis.com/auth/cloud-platform" and authorize again. '
                'Prefer the blue "Connect Google Earth Engine" button.')
    if 'invalid_grant' in lower or 'invalid credentials' in lower or 'invalid authentication' in lower:
        return ('Google rejected the token (invalid/expired). Paste a fresh access token '
                'starting with "ya29." — the 40-char hex value is not a Google token.')
    # EE API disabled on the Cloud project.
    if 'has not been used' in lower or 'earth engine api' in lower and 'disabled' in lower:
        return ('Earth Engine API is disabled on this Cloud project. '
                'Go to console.cloud.google.com → APIs → enable "Earth Engine API", '
                'then retry.')
    # Project never registered for EE / user never signed up.
    if 'not registered' in lower or 'signup' in lower or 'register' in lower:
        return ('This Cloud project (or Google account) is not registered for Earth Engine. '
                'Complete https://signup.earthengine.google.com/ with the same Google account, '
                'link the project, then retry.')
    if 'permission denied' in lower or 'forbidden' in lower or '403' in lower:
        return ('Permission denied for this project. The Google account you connected '
                'must have access to the Cloud Project ID you entered in Step 4, '
                'and the project must be EE-enabled.')
    if 'project' in lower and ('permission' in lower or 'not found' in lower or 'invalid' in lower):
        return ('Earth Engine is authenticated, but the Project ID is wrong or not accessible. '
                'Re-check Step 4: lowercase, 6-30 chars, must exist in console.cloud.google.com '
                'and have Earth Engine API enabled.')
    if 'token' in lower or 'credential' in lower or 'unauthorized' in lower or '401' in lower:
        return 'Google account connected, but Earth Engine authentication failed. Paste a fresh "ya29." access token with earthengine scope, or use the blue OAuth button (recommended).'
    # Fall back to raw message (truncated) so real EE errors are not hidden.
    return message[:500]

# =========== Export file builders (stdlib only; QGIS-compatible) ===========

def _approx_area_ha(geom):
    """Equirectangular polygon area (lon/lat) for attribute tables. Approximate."""
    try:
        import math
        polys = []
        if geom.get('type') == 'Polygon':
            polys = [geom.get('coordinates', [])]
        elif geom.get('type') == 'MultiPolygon':
            polys = geom.get('coordinates', [])
        total = 0.0
        for poly in polys:
            if not poly:
                continue
            ring = poly[0]
            if len(ring) < 4:
                continue
            lat0 = sum(p[1] for p in ring) / len(ring)
            kx = 111320.0 * math.cos(math.radians(lat0))
            ky = 110540.0
            pts = [(p[0] * kx, p[1] * ky) for p in ring]
            a = abs(sum(pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1] for i in range(len(pts) - 1)) / 2)
            total += a
            for hole in poly[1:]:
                pts = [(p[0] * kx, p[1] * ky) for p in hole]
                if len(pts) > 2:
                    total -= abs(sum(pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1] for i in range(len(pts) - 1)) / 2)
        return max(0.0, total / 10000.0)
    except Exception:
        return 0.0


def _kml_coords(rings):
    out = []
    for ring in rings:
        out.append(' '.join(f'{p[0]},{p[1]},0' for p in ring))
    return out


def _features_to_kml(features, name):
    import xml.sax.saxutils as sax
    placemarks = []
    for f in features:
        props = f.get('properties') or {}
        geom = f.get('geometry') or {}
        data = ''.join(f'<Data name="{sax.quoteattr(str(k))}"><value>{sax.escape(str(v))}</value></Data>'
                       for k, v in props.items())
        gtype = geom.get('type')
        if gtype == 'Point':
            c = geom.get('coordinates', [0, 0])
            geo = f'<Point><coordinates>{c[0]},{c[1]},0</coordinates></Point>'
        elif gtype in ('Polygon', 'MultiPolygon'):
            polys = [geom.get('coordinates', [])] if gtype == 'Polygon' else geom.get('coordinates', [])
            rings = ''.join(
                f'<Polygon><outerBoundaryIs><LinearRing><coordinates>{coords}</coordinates></LinearRing></outerBoundaryIs></Polygon>'
                for poly in polys for coords in _kml_coords([poly[0]]) if poly and poly[0])
            geo = f'<MultiGeometry>{rings}</MultiGeometry>' if gtype == 'MultiPolygon' else rings
        else:
            continue
        placemarks.append(f'<Placemark><name>{sax.escape(str(props.get("class_name", props.get("name", "feature"))))}</name>'
                          f'<ExtendedData>{data}</ExtendedData>{geo}</Placemark>')
    return ('<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2">'
            f'<Document><name>{sax.escape(name)}</name>{"".join(placemarks)}</Document></kml>')


def _features_to_shapefile(features):
    """Minimal Polygon/MultiPolygon/Point shapefile (shp+shx+dbf). Returns tuple or None."""
    import struct
    def _valid(g):
        try:
            if g.get('type') == 'Point':
                return len(g.get('coordinates', [])) >= 2
            polys = [g.get('coordinates', [])] if g.get('type') == 'Polygon' else g.get('coordinates', [])
            return any(len(ring) >= 4 for poly in polys for ring in (poly or []))
        except Exception:
            return False
    geoms = []
    for f in features:
        g = f.get('geometry') or {}
        if g.get('type') in ('Polygon', 'MultiPolygon', 'Point') and _valid(g):
            geoms.append((f.get('properties') or {}, g))
    if not geoms:
        return None
    kinds = {g['type'] for _, g in geoms}
    if kinds == {'Point'}:
        stype = 1
    elif kinds <= {'Polygon', 'MultiPolygon'}:
        stype = 5
    else:
        return None  # mixed kinds need no blind conversion
    # Field schema from properties (C up to 25 chars, N numeric). Keep
    # sanitized->original mapping so values are actually found.
    fields = []
    for props, _ in geoms:
        for k, v in props.items():
            name = re.sub(r'[^A-Za-z0-9_]', '_', str(k))[:10] or 'FIELD'
            if name not in [f[0] for f in fields]:
                fields.append((name, str(k), 'N' if isinstance(v, (int, float)) and not isinstance(v, bool) else 'C'))
    fields = fields[:32]
    recs = []
    xs, ys = [], []
    for props, g in geoms:
        if stype == 1:
            x, y = g['coordinates'][0], g['coordinates'][1]
            content = struct.pack('<dd', x, y)
            xs += [x]
            ys += [y]
        else:
            polys = [g['coordinates']] if g['type'] == 'Polygon' else g['coordinates']
            parts, points, n = [], [], 0
            for poly in polys:
                for ring in poly:
                    parts.append(n)
                    for p in ring:
                        points.append((p[0], p[1]))
                        xs.append(p[0])
                        ys.append(p[1])
                    n += len(ring)
            content = struct.pack('<i', len(parts)) + struct.pack('<' + 'i' * len(parts), *parts) + \
                struct.pack('<' + 'd' * (2 * len(points)), *[c for p in points for c in p])
        recs.append((props, struct.pack('<i', stype) + content))
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    # .shp
    shp = [struct.pack('>7i', 9994, 0, 0, 0, 0, 0, 0)]
    shp_len = [50]
    shx = [struct.pack('>7i', 9994, 0, 0, 0, 0, 0, 50)]
    offset = 50
    for i, (_, content) in enumerate(recs):
        shp.append(struct.pack('>2i', i + 1, len(content) // 2))
        shp.append(content)
        shx.append(struct.pack('>2i', offset, len(content) // 2))
        offset += 4 + len(content) // 2
    flen = 50 * 2 + sum(4 + len(c) // 2 for _, c in recs)
    shp[0] = struct.pack('>6i', 9994, 0, 0, 0, 0, 0) + struct.pack('>i', flen) + \
        struct.pack('<i', 1000) + struct.pack('<i', stype) + struct.pack('<8d', xmin, ymin, xmax, ymax, 0, 0, 0, 0)
    shx_bytes = struct.pack('>6i', 9994, 0, 0, 0, 0, 0) + struct.pack('>i', 50 + 4 * len(recs)) + \
        struct.pack('<i', 1000) + struct.pack('<i', stype) + struct.pack('<8d', xmin, ymin, xmax, ymax, 0, 0, 0, 0) + \
        b''.join(shx[1:])
    shp_bytes = b''.join(shp)
    # .dbf (dBase III): header + field descriptors + records.
    nrec = len(recs)
    dbf = [struct.pack('<BBBBIHHHBBBB14s', 3, 26, 9, 28, nrec, 32 + 32 * len(fields) + 1,
                       0, 0, 0, 0, 0, 0, b'\x00' * 14)]
    for fname, _, ftype in fields:
        dbf.append(struct.pack('<11s', fname.encode('ascii', 'replace')) + bytes([ord(ftype)]) +
                   struct.pack('<I', 0) + bytes([25 if ftype == 'C' else 18, 6 if ftype == 'N' else 0]) + bytes(14))
    dbf.append(b'\x0d')
    for props, _ in recs:
        row = [b' ']
        for _, orig, ftype in fields:
            v = props.get(orig, '')
            if ftype == 'N':
                try:
                    row.append(('%18.6f' % float(v)).encode('ascii')[:18])
                except (TypeError, ValueError):
                    row.append(b' ' * 18)
            else:
                row.append(str(v).encode('utf-8', 'replace')[:25].ljust(25))
        dbf.append(b''.join(row))
    return shp_bytes, shx_bytes, b''.join(dbf) + b'\x1a'


# =========== Server ===========

class GEEHandler(BaseHTTPRequestHandler):
    server_version = 'GeoIntelligenceHub/3.0'
    protocol_version = 'HTTP/1.1'

    def _cors(self):
        configured = [x.strip() for x in os.getenv(
            'CORS_ORIGINS', f'{FRONTEND_URL},http://localhost:5173'
        ).split(',') if x.strip()]
        origin = self.headers.get('Origin')
        if origin in configured:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        self.send_header('Access-Control-Allow-Methods','GET,POST,PUT,DELETE,OPTIONS')
        self.send_header('Access-Control-Allow-Headers','Content-Type,Authorization,X-Admin-Key')
        self.send_header('Access-Control-Allow-Credentials', 'true')

    def _security(self, api=True):
        # Tokens are Bearer in localStorage today; these headers reduce
        # XSS/clickjacking fallout. CSP is intentionally not strict here
        # because Leaflet/EE tiles + Google fonts require external img/connect.
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'SAMEORIGIN')
        self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
        self.send_header('Permissions-Policy', 'camera=(), microphone=(), geolocation=(self)')
        if api:
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Pragma', 'no-cache')

    def _serve_static(self, path):
        if not os.path.isdir(FRONTEND_DIST):
            self._json({'error':'Frontend not built. Run: cd frontend && npm run build'}, 503)
            return
        if path == '/' or path == '':
            path = '/index.html'
        # Strip query/fragment, block path traversal (e.g. /../backend/.env).
        clean = urlsplit(path).path
        filepath = os.path.realpath(os.path.join(FRONTEND_DIST, clean.lstrip('/')))
        dist_real = os.path.realpath(FRONTEND_DIST)
        if filepath != dist_real and not filepath.startswith(dist_real + os.sep):
            self._json({'error': 'Forbidden'}, 403)
            return
        if not os.path.isfile(filepath):
            filepath = os.path.join(dist_real, 'index.html')
        try:
            with open(filepath, 'rb') as f:
                content = f.read()
            mime, _ = mimetypes.guess_type(filepath)
            self.send_response(200)
            self._cors()
            self._security(api=False)
            self.send_header('Content-Type', mime or 'application/octet-stream')
            self.send_header('Content-Length', str(len(content)))
            # Immutable cache for hashed Vite assets, no-cache for index.html.
            if filepath.endswith('index.html'):
                self.send_header('Cache-Control', 'no-cache')
            else:
                self.send_header('Cache-Control', 'public, max-age=31536000, immutable')
            self.end_headers()
            self.wfile.write(content)
        except Exception:
            self._json({'error':'File not found'}, 404)

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=True).encode()
        self.send_response(status); self._cors()
        self._security(api=True)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def _respond(self, result, default_status=200):
        if isinstance(result, tuple):
            data, status = result
        else:
            data, status = result, default_status
        self._json(data, status)

    def _redirect(self, location):
        self.send_response(302)
        self._cors()
        self._security(api=True)
        self.send_header('Location', location)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self._security(api=True); self.end_headers()

    def _check_auth_rate_limit(self):
        ip = _client_ip(self)
        if _hit_rate_limit(f'auth:{ip}'):
            self._json({'error': 'Too many attempts. Try again in a few minutes.'}, 429)
            return True
        return False

    def _token(self):
        a = self.headers.get('Authorization','')
        return a[7:] if a.startswith('Bearer ') else None

    def _path(self):
        return urlsplit(self.path).path

    def _body(self):
        length = int(self.headers.get('Content-Length', '0') or 0)
        if length > MAX_BODY_BYTES:
            raise ValueError('Request body is too large')
        raw = self.rfile.read(length) if length else b'{}'
        body = json.loads(raw or b'{}')
        if not isinstance(body, dict):
            raise ValueError('JSON object required')
        return body

    def do_GET(self):
        # Serve static frontend files in production mode
        path = self._path()
        if path == '/api/gee/oauth/callback':
            self._oauth_callback(parse_qs(urlsplit(self.path).query))
            return
        if not path.startswith('/api') and not path.startswith('/health'):
            self._serve_static(self.path)
            return

        if path == '/health' or path == '/api/health':
            self._json({
                'status': 'ok', 'service': 'geointelligence-hub-bridge',
                'ee_ready': _ee_ready, 'oauth_configured': bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
            })
        elif path == '/api/session':
            email = _verify_session(self._token())
            if email:
                user = get_user(email)
                status = _connection_status(email, verify=False)
                gee_error = status.pop('error', None)
                self._json({
                    'valid': True, 'email': email, 'name': user.get('full_name', ''),
                    'setupStep': user.get('setup_step', 0) or 0,
                    'verified': bool(user.get('cloud_project_id')), 'geeError': gee_error,
                    **status,
                })
            else:
                self._json({'valid':False})
        elif path == '/api/gee/status':
            email = _verify_session(self._token())
            if not email:
                self._json({'error': 'Login required'}, 401)
            else:
                self._json(_connection_status(email, verify=True))
        elif path == '/api/projects' or path == '/api/projects/':
            email = _verify_session(self._token())
            if not email:
                self._json({'error': 'Login required'}, 401)
            else:
                self._json(self._list_projects(email))
        elif path.startswith('/api/projects/'):
            email = _verify_session(self._token())
            if not email:
                self._json({'error': 'Login required'}, 401)
            else:
                self._respond(self._get_project(path.rsplit('/', 1)[-1], email))
        elif path == '/api/results':
            email = _verify_session(self._token())
            if not email:
                self._json({'error': 'Login required'}, 401)
            else:
                self._json(self._list_results(email))
        elif path == '/api/admin/users':
            admin_key = self.headers.get('X-Admin-Key','')
            if not ADMIN_KEY or admin_key != ADMIN_KEY:
                self._json({'error':'Invalid admin key'},403)
            else:
                self._json(self._admin_users())
        elif path == '/api/exports':
            email = _verify_session(self._token())
            if not email:
                self._json({'error': 'Login required'}, 401)
            else:
                self._json(self._list_exports(email))
        elif path == '/api/export/status':
            email = _verify_session(self._token())
            if not email:
                self._json({'error': 'Login required'}, 401)
            else:
                q = parse_qs(urlsplit(self.path).query)
                self._respond(self._export_status((q.get('task', [''])[0]), email))
        elif path == '/api/export/download':
            q = parse_qs(urlsplit(self.path).query)
            token = self._token() or (q.get('token', [''])[0])
            email = _verify_session(token)
            if not email:
                self._json({'error': 'Login required'}, 401)
            else:
                self._download_export((q.get('id', [''])[0]), email)
        else:
            self._json({'error':'Not found'},404)

    def do_POST(self):
        try:
            path = self._path()
            if path in ('/api/register', '/api/login', '/api/google-login', '/api/google-code'):
                if self._check_auth_rate_limit():
                    return
            body = self._body()
            session = self._token()
            email = _verify_session(session)

            # Auth endpoints (no session needed)
            if path == '/api/register':
                self._respond(self._register(body))
            elif path == '/api/login':
                self._respond(self._login(body))
            elif path == '/api/google-login':
                self._respond(self._google_login(body))
            elif path == '/api/google-code':
                self._respond(self._google_code_login(body))

            # Analysis endpoints
            elif path == '/api/analyze':
                self._respond(self._run_analysis_fallback(body, email))
            elif path == '/api/tile':
                self._respond(self._get_tile_url_fallback(body, email))
            elif path == '/api/zonal':
                self._respond(self._zonal_stats(body, email))
            elif path == '/api/spatial-statistics':
                if not email:
                    self._json({'error': 'Login required'}, 401)
                    return
                from spatial_statistics import run_spatial_statistics
                result = run_spatial_statistics(body)
                result['success'] = True
                result['analysis'] = {'id': 'spatial_statistics', 'name': result.get('label', 'Spatial statistics')}
                result['statistics'] = result.get('stats', {})
                result['tableData'] = [
                    {'id': feature.get('id', index), **(feature.get('properties') or {})}
                    for index, feature in enumerate((result.get('geometry') or {}).get('features') or [])
                ]
                result['styleBy'] = {
                    'local_moran': 'cluster', 'getis_ord_gi_star': 'gi_star_z', 'kde': 'density_points_per_m2',
                    'nearest_neighbor': 'nearest_distance_m', 'point_pattern': 'nearest_distance_m',
                    'idw': 'predicted', 'kriging': 'predicted', 'spatial_regression': 'residual',
                    'spatial_sampling': 'sample_id',
                }.get(str(body.get('method') or ''), 'value')
                self._respond(result)
            elif path == '/api/drone-analysis':
                if not email:
                    self._json({'error': 'Login required'}, 401)
                    return
                from drone_mining import run_drone_analysis
                self._respond(run_drone_analysis(body))
            elif path == '/api/admin-boundary':
                self._respond(self._admin_boundary(body, email))
            elif path == '/api/export':
                self._respond(self._export_result(body, email))
            elif path == '/api/export-boundary':
                self._respond(self._export_boundary(body, email))

            # Session-required endpoints
            elif not email:
                self._json({'error':'Login required'},401)

            elif path == '/api/chat':
                self._respond(self._chat(body))
            elif path == '/api/update-setup':
                self._respond(self._update_setup(body, email))
            elif path == '/api/gee-verify':
                self._respond(self._verify_gee(email))
            elif path == '/api/logout':
                revoke_session(session)
                self._respond(self._logout(email))
            elif path == '/api/gee/oauth/start':
                self._respond(self._start_gee_oauth(body, email))
            elif path == '/api/gee-connect':
                self._respond(self._connect_gee(body, email))
            elif path == '/api/save-project':
                self._respond(self._save_project(body, email))
            elif path == '/api/projects' or path == '/api/projects/':
                self._respond(self._create_project(body, email))
            elif path == '/api/code':
                self._respond(self._execute_code(body, email))
            elif path == '/api/admin/delete-user':
                self._respond(self._admin_delete_user(body))
            else:
                self._json({'error':f'Unknown: {path}'},404)
        except ValueError as e:
            self._json({'error': str(e)}, 400)
        except Exception as e:
            payload = {'error': str(e) or 'Internal server error'}
            if DEBUG:
                payload['trace'] = traceback.format_exc()
            self._json(payload,500)

    def do_PUT(self):
        try:
            path = self._path()
            email = _verify_session(self._token())
            if not email:
                self._json({'error': 'Login required'}, 401)
                return
            if path.startswith('/api/projects/'):
                self._respond(self._update_project(path.rsplit('/', 1)[-1], self._body(), email))
            else:
                self._json({'error': 'Not found'}, 404)
        except ValueError as exc:
            self._json({'error': str(exc)}, 400)
        except Exception as exc:
            self._json({'error': str(exc)}, 500)

    def do_DELETE(self):
        try:
            path = self._path()
            email = _verify_session(self._token())
            if not email:
                self._json({'error': 'Login required'}, 401)
                return
            if path.startswith('/api/projects/'):
                self._respond(self._delete_project(path.rsplit('/', 1)[-1], email))
            else:
                self._json({'error': 'Not found'}, 404)
        except Exception as exc:
            self._json({'error': str(exc)}, 500)

    # ===== RESEARCH PROJECTS AND RESULTS =====
    def _project_payload(self, row):
        payload = dict(row)
        return payload

    def _list_projects(self, email):
        user = get_user(email)
        with connection() as conn:
            rows = conn.execute(
                'SELECT * FROM projects WHERE user_id = ? ORDER BY updated_at DESC, created_at DESC',
                (user['id'],),
            ).fetchall()
        return {'projects': [self._project_payload(row) for row in rows]}

    def _get_project(self, project_id, email):
        user = get_user(email)
        with connection() as conn:
            row = conn.execute(
                'SELECT * FROM projects WHERE id = ? AND user_id = ?', (project_id, user['id'])
            ).fetchone()
            if not row:
                return {'error': 'Project not found'}, 404
            results = conn.execute(
                'SELECT r.result_json, r.id AS result_id, r.created_at, j.analysis_type, j.status '
                'FROM analysis_results r JOIN analysis_jobs j ON j.id = r.job_id '
                'WHERE r.user_id = ? AND j.project_id = ? ORDER BY r.created_at DESC',
                (user['id'], project_id),
            ).fetchall()
        payload = self._project_payload(row)
        payload['results'] = []
        for result in results:
            try:
                item = json.loads(result['result_json'])
            except (TypeError, ValueError):
                item = {}
            item.update({
                'resultId': result['result_id'], 'analysisType': result['analysis_type'],
                'status': result['status'], 'createdAt': result['created_at'],
            })
            payload['results'].append(item)
        return payload

    def _create_project(self, body, email):
        name = (body.get('name') or '').strip()
        description = (body.get('description') or '').strip()
        if not name or len(name) > 255:
            return {'error': 'Project name is required'}, 400
        user = get_user(email)
        project_id = secrets.token_hex(16)
        now = time.time()
        with connection() as conn:
            conn.execute(
                'INSERT INTO projects (id, user_id, name, description, status, created_at, updated_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (project_id, user['id'], name, description, 'draft', now, now),
            )
        return {'id': project_id, 'name': name, 'description': description, 'status': 'draft'}, 201

    def _update_project(self, project_id, body, email):
        user = get_user(email)
        name = (body.get('name') or '').strip()
        description = (body.get('description') or '').strip()
        if not name or len(name) > 255:
            return {'error': 'Project name is required'}, 400
        with connection() as conn:
            result = conn.execute(
                'UPDATE projects SET name = ?, description = ?, updated_at = ? WHERE id = ? AND user_id = ?',
                (name, description, time.time(), project_id, user['id']),
            )
            if not result.rowcount:
                return {'error': 'Project not found'}, 404
        return self._get_project(project_id, email)

    def _delete_project(self, project_id, email):
        user = get_user(email)
        with connection() as conn:
            result = conn.execute('DELETE FROM projects WHERE id = ? AND user_id = ?', (project_id, user['id']))
            if not result.rowcount:
                return {'error': 'Project not found'}, 404
        return {'status': 'deleted', 'id': project_id}

    def _ensure_project(self, email, project_id=None):
        user = get_user(email)
        with connection() as conn:
            if project_id:
                row = conn.execute(
                    'SELECT * FROM projects WHERE id = ? AND user_id = ?', (project_id, user['id'])
                ).fetchone()
                if not row:
                    raise RuntimeError('Project not found or not owned by this user')
                return dict(row)
            row = conn.execute(
                'SELECT * FROM projects WHERE user_id = ? ORDER BY updated_at DESC, created_at DESC LIMIT 1',
                (user['id'],),
            ).fetchone()
            if row:
                return dict(row)
            now = time.time()
            generated = secrets.token_hex(16)
            conn.execute(
                'INSERT INTO projects (id, user_id, name, description, status, created_at, updated_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (generated, user['id'], 'Default Project', 'Created for the first analysis', 'draft', now, now),
            )
            return dict(conn.execute('SELECT * FROM projects WHERE id = ?', (generated,)).fetchone())

    def _list_results(self, email):
        user = get_user(email)
        with connection() as conn:
            rows = conn.execute(
                'SELECT r.result_json, r.id AS result_id, r.created_at, p.id AS project_id, p.name AS project_name, '
                'j.analysis_type, j.status FROM analysis_results r '
                'JOIN analysis_jobs j ON j.id = r.job_id JOIN projects p ON p.id = j.project_id '
                'WHERE r.user_id = ? ORDER BY r.created_at DESC',
                (user['id'],),
            ).fetchall()
        result = []
        for row in rows:
            try:
                item = json.loads(row['result_json'])
            except (TypeError, ValueError):
                item = {}
            item.update({
                'resultId': row['result_id'], 'projectId': row['project_id'],
                'projectName': row['project_name'], 'analysisType': row['analysis_type'],
                'status': row['status'], 'createdAt': row['created_at'],
            })
            result.append(item)
        return {'results': result}

    def _admin_users(self):
        with connection() as conn:
            rows = conn.execute('SELECT * FROM users ORDER BY created_at DESC').fetchall()
        users = {}
        for row in rows:
            status = _connection_status(row['email'], verify=False)
            users[row['email']] = {
                'name': row['full_name'], 'setupStep': row['setup_step'] or 0,
                'verified': bool(row['cloud_project_id']), 'geeConnected': status['geeConnected'],
                'oauthConnected': status['oauthConnected'],
            }
        return {'users': users, 'count': len(users)}

    # ===== USER MGMT =====
    def _auth_response(self, user):
        token = _make_session(user['email'])
        status = _connection_status(user['email'], verify=False)
        gee_error = status.pop('error', None)
        return {
            'token': token,
            'email': user['email'],
            'name': user.get('full_name', ''),
            'setupStep': user.get('setup_step', 0) or 0,
            'verified': bool(user.get('cloud_project_id')), 'geeError': gee_error,
            **status,
        }

    def _register(self, body):
        email = (body.get('email') or '').strip().lower()
        pw = body.get('password', '')
        name = (body.get('name') or '').strip()
        if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email) or len(pw) < 8:
            return {'error': 'A valid email and password of at least 8 characters are required'}, 400
        if get_user(email):
            return {'error': 'Email already registered'}, 409
        now = time.time()
        with connection() as conn:
            conn.execute(
                'INSERT INTO users (id, email, full_name, password_hash, role, is_active, setup_step, created_at, updated_at) '
                'VALUES (?, ?, ?, ?, ?, 1, 0, ?, ?)',
                (secrets.token_hex(16), email, name, hash_password(pw), 'researcher', now, now),
            )
        return self._auth_response(get_user(email)), 201

    def _login(self, body):
        email = (body.get('email') or '').strip().lower()
        pw = body.get('password', '')
        user = get_user(email)
        if user and not user.get('password_hash') and not user.get('legacy_password_hash'):
            # Google-created account: no password exists, so password login can
            # never succeed — say so instead of a generic "Invalid credentials".
            return {'error': 'This account uses Google sign-in (no password set). Use "Continue with Google" above.',
                    'code': 'google_only'}, 401
        if not user or not verify_password(pw, user.get('password_hash'), user.get('legacy_password_hash')):
            return {'error': 'Invalid credentials'}, 401
        now = time.time()
        with connection() as conn:
            if user.get('legacy_password_hash') and not user.get('password_hash'):
                conn.execute(
                    'UPDATE users SET password_hash = ?, legacy_password_hash = NULL, last_login = ?, updated_at = ? WHERE id = ?',
                    (hash_password(pw), now, now, user['id']),
                )
            else:
                conn.execute('UPDATE users SET last_login = ?, updated_at = ? WHERE id = ?', (now, now, user['id']))
        return self._auth_response(get_user(email))

    def _google_login(self, body):
        access_token = (body.get('access_token') or '').strip()
        if not access_token:
            return {'error': 'Google access token required'}, 400
        try:
            # Critical: verify the token was issued to OUR OAuth client,
            # otherwise any Google token for any app could be replayed here.
            _verify_google_access_token_audience(access_token)
            profile = self._google_userinfo(access_token)
        except Exception as exc:
            msg = str(exc)
            if 'not issued to this application' in msg:
                return {'error': 'Google token was not issued to this application.'}, 401
            return {'error': 'Google authorization failed.'}, 401
        try:
            return self._auth_response(self._upsert_google_user(profile)), 200
        except RuntimeError:
            return {'error': 'Google authorization failed.'}, 401

    def _upsert_google_user(self, profile):
        """Create-or-login by Google identity. Existing email accounts are
        linked (google_id attached), never duplicated."""
        email = (profile.get('email') or '').strip().lower()
        google_id = profile.get('sub')
        if not email or not google_id or profile.get('email_verified') is False:
            raise RuntimeError('Google authorization failed.')
        user = get_user(email)
        now = time.time()
        with connection() as conn:
            if user:
                conn.execute(
                    'UPDATE users SET google_id = ?, full_name = ?, avatar_url = ?, last_login = ?, updated_at = ? WHERE id = ?',
                    (google_id, profile.get('name', ''), profile.get('picture'), now, now, user['id']),
                )
            else:
                conn.execute(
                    'INSERT INTO users (id, email, full_name, google_id, avatar_url, role, is_active, setup_step, created_at, updated_at, last_login) '
                    'VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?)',
                    (secrets.token_hex(16), email, profile.get('name', ''), google_id, profile.get('picture'), 'researcher', now, now, now),
                )
        return get_user(email)

    def _google_code_login(self, body):
        """Authorization-code login: exchange ?code= for tokens server-side
        (client_secret never leaves the backend), verify audience, same
        upsert + session as the legacy token login."""
        code = (body.get('code') or '').strip()
        redirect_uri = (body.get('redirect_uri') or '').strip()
        if not code:
            return {'error': 'Google authorization code required'}, 400
        # Whitelist: only our own frontend origin or the GEE callback may be
        # used as redirect_uri — never an arbitrary third-party URL.
        allowed = {
            f'{FRONTEND_URL}/', GOOGLE_REDIRECT_URI,
            # Local dev variants (localhost vs 127.0.0.1, vite vs backend-static).
            'http://localhost:3000/', 'http://127.0.0.1:3000/',
            f'http://localhost:{PORT}/', f'http://127.0.0.1:{PORT}/',
        }
        if redirect_uri not in allowed:
            return {'error': f'Invalid redirect URI "{redirect_uri}". Register "{redirect_uri}" in Google Cloud Console > Credentials > Authorized redirect URIs.'}, 400
        if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
            return {'error': 'Google OAuth is not configured on the backend (missing GOOGLE_CLIENT_SECRET). Add it to backend/.env then restart the backend.'}, 503
        try:
            token_body = urlencode({
                'code': code, 'client_id': GOOGLE_CLIENT_ID,
                'client_secret': GOOGLE_CLIENT_SECRET, 'redirect_uri': redirect_uri,
                'grant_type': 'authorization_code',
            }).encode()
            token_request = urllib.request.Request(
                GOOGLE_TOKEN_URL, data=token_body,
                headers={'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'},
            )
            with urllib.request.urlopen(token_request, timeout=20) as response:
                token_data = json.loads(response.read())
            access_token = token_data.get('access_token')
            if not access_token:
                raise RuntimeError(token_data.get('error_description') or 'Google did not return an access token')
            _verify_google_access_token_audience(access_token)
            profile = self._google_userinfo(access_token)
            return self._auth_response(self._upsert_google_user(profile)), 200
        except Exception as exc:
            msg = str(exc)
            if 'not issued to this application' in msg:
                return {'error': 'Google token was not issued to this application.'}, 401
            if DEBUG:
                print(f'[Google login] code exchange failed: {msg}')
            return {'error': 'Google authorization failed. Please click "Continue with Google" again.'}, 401

    def _google_userinfo(self, access_token):
        request = urllib.request.Request(
            GOOGLE_USERINFO_URL,
            headers={'Authorization': f'Bearer {access_token}', 'Accept': 'application/json'},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            profile = json.loads(response.read())
        if not isinstance(profile, dict):
            raise RuntimeError('Invalid Google profile')
        return profile

    def _update_setup(self, body, email):
        try:
            step = int(body.get('step', 0))
        except (TypeError, ValueError):
            return {'error': 'Invalid setup step'}, 400
        if step < 0 or step > 5:
            return {'error': 'Invalid setup step'}, 400
        user = get_user(email)
        new_step = max(user.get('setup_step', 0) or 0, step)
        with connection() as conn:
            conn.execute('UPDATE users SET setup_step = ?, updated_at = ? WHERE id = ?', (new_step, time.time(), user['id']))
        return {'setupStep': new_step, 'verified': bool(user.get('cloud_project_id'))}

    def _verify_gee(self, email):
        status = _connection_status(email, verify=True)
        user = get_user(email)
        return {
            **status,
            'verified': bool(user and user.get('cloud_project_id')),
            'needsProject': not bool(user and user.get('cloud_project_id')),
        }

    def _logout(self, email):
        # Logging out revokes the application session but does not disconnect EE.
        return {'status': 'ok'}

    def _save_project(self, body, email):
        project_id = (body.get('projectId') or '').strip()
        if not _valid_project_id(project_id):
            return {'error': 'Invalid Google Cloud Project ID'}, 400
        user = get_user(email)
        with connection() as conn:
            conn.execute(
                'UPDATE users SET cloud_project_id = ?, setup_step = MAX(COALESCE(setup_step, 0), 4), updated_at = ? WHERE id = ?',
                (project_id, time.time(), user['id']),
            )
        print(f'[PROJECT] {email} -> {project_id}')
        return {'verified': True, 'projectId': project_id, 'setupStep': 4, 'message': 'Project saved.'}

    def _connect_gee(self, body, email):
        access_token = (body.get('access_token') or body.get('geeAccessToken') or '').strip()
        if not access_token:
            return {'error': 'GEE access token required. Paste the ya29.* value or use the OAuth button.'}, 400
        # Fast fail: a real Google OAuth access token always starts with ya29.
        # The 40-char hex string users sometimes paste is NOT a Google token.
        if not (access_token.startswith('ya29.') and len(access_token) > 30):
            return {'error': (
                'That is not a Google OAuth access token. A valid token starts with "ya29." '
                'and is ~200 characters. You pasted a %d-char value. '
                'Use the blue "Connect Google Earth Engine" button (recommended), or in '
                'OAuth 2.0 Playground authorize scopes earthengine + cloud-platform and '
                'copy the Access token (not the auth code, not a session id).'
            ) % len(access_token)}, 400
        user = get_user(email)
        project_id = (body.get('project_id') or body.get('googleProjectId') or user.get('cloud_project_id') or '').strip()
        if not _valid_project_id(project_id):
            return {'error': 'Project ID required. Complete step 4 in wizard first.'}, 400
        try:
            # Manual tokens carry no expiry metadata; assume ~1h lifetime so the
            # UI can warn before it dies instead of failing mid-analysis.
            # Pre-check scope before burning an EE quota call: manual tokens
            # from Playground often lack the earthengine scope.
            try:
                url = f'{GOOGLE_TOKENINFO_URL}?access_token={urllib.parse.quote(access_token, safe="")}'
                req = urllib.request.Request(url, headers={'Accept': 'application/json'})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    info = json.loads(resp.read() or b'{}')
                scope = str(info.get('scope', '') or '')
                if scope and 'earthengine' not in scope:
                    return {'error': (
                        'Token is valid but missing the Earth Engine scope (scopes: %s). '
                        'In Playground check BOTH earthengine and cloud-platform, authorize, '
                        'and copy the new access token. Or use the OAuth button.'
                    ) % (scope[:200] or 'none')}, 400
            except Exception:
                pass  # fall through to EE probe for the authoritative error
            creds = _credentials(access_token)
            probe = _probe_earth_engine(creds, project_id)
            if not creds.expiry:
                # Naive UTC to match google-auth utcnow() (see _parse_expiry).
                creds.expiry = datetime.fromtimestamp(time.time() + 3600, tz=timezone.utc).replace(tzinfo=None)
            self._store_connection(user, project_id, creds, oauth_connected=False)
        except Exception as exc:
            return {'error': _gee_error_message(exc)}, 502
        print(f'[GEE] {email} -> {project_id}')
        return {
            'verified': True, 'geeConnected': True, 'oauthConnected': False,
            'eeAuthenticated': True, 'earthEngineAvailable': True,
            'analysisAvailable': True, 'earth_engine': probe['earth_engine'],
            'message': 'Earth Engine connected.',
        }

    def _store_connection(self, user, project_id, credentials, oauth_connected, google_subject=None, google_email=None):
        now = time.time()
        # Normalize to naive UTC before persisting (see _parse_expiry).
        try:
            credentials.expiry = _normalize_expiry(getattr(credentials, 'expiry', None))
        except Exception:
            pass
        expires = credentials.expiry.isoformat() if credentials.expiry else None
        with connection() as conn:
            existing = conn.execute(
                'SELECT id, ee_refresh_token FROM ee_connections WHERE user_id = ? AND google_project_id = ?',
                (user['id'], project_id),
            ).fetchone()
            refresh_token = credentials.refresh_token
            if not refresh_token and existing:
                refresh_token = unseal(existing['ee_refresh_token'])
            values = (
                seal(credentials.token), seal(refresh_token), expires, int(bool(oauth_connected)),
                google_subject, google_email, now,
            )
            if existing:
                conn.execute(
                    'UPDATE ee_connections SET ee_access_token = ?, ee_refresh_token = ?, token_expires_at = ?, '
                    'is_active = 1, oauth_connected = ?, ee_authenticated = 1, ee_available = 1, '
                    'analysis_available = 1, google_subject = COALESCE(?, google_subject), '
                    'google_email = COALESCE(?, google_email), last_error = NULL, verified_at = ?, updated_at = ? WHERE id = ?',
                    (*values[:6], now, now, existing['id']),
                )
            else:
                conn.execute(
                    'INSERT INTO ee_connections (id, user_id, google_project_id, ee_access_token, ee_refresh_token, '
                    'token_expires_at, is_active, oauth_connected, ee_authenticated, ee_available, analysis_available, '
                    'google_subject, google_email, verified_at, created_at, updated_at) '
                    'VALUES (?, ?, ?, ?, ?, ?, 1, ?, 1, 1, 1, ?, ?, ?, ?, ?)',
                    (secrets.token_hex(16), user['id'], project_id, values[0], values[1], values[2], values[3],
                     values[4], values[5], now, now, now),
                )
            conn.execute(
                'UPDATE users SET cloud_project_id = ?, setup_step = MAX(COALESCE(setup_step, 0), 5), updated_at = ? WHERE id = ?',
                (project_id, now, user['id']),
            )

    def _start_gee_oauth(self, body, email):
        if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
            return {'error': 'Google OAuth is not configured on the backend (missing GOOGLE_CLIENT_SECRET). Add it to backend/.env then restart the backend.'}, 503
        user = get_user(email)
        project_id = (body.get('project_id') or user.get('cloud_project_id') or '').strip()
        if not _valid_project_id(project_id):
            return {'error': 'Complete Step 4 with a valid Google Cloud Project ID first.'}, 400
        state = secrets.token_urlsafe(32)
        now = time.time()
        with connection() as conn:
            conn.execute(
                'INSERT INTO oauth_states (state_hash, user_id, project_id, expires_at, created_at) VALUES (?, ?, ?, ?, ?)',
                (hashlib.sha256(state.encode()).hexdigest(), user['id'], project_id, now + 600, now),
            )
        query = urlencode({
            'client_id': GOOGLE_CLIENT_ID,
            'redirect_uri': GOOGLE_REDIRECT_URI,
            'response_type': 'code',
            'scope': ' '.join((*EE_SCOPES, 'openid', 'email', 'profile')),
            'access_type': 'offline',
            'prompt': 'consent',
            'include_granted_scopes': 'true',
            'state': state,
        })
        return {'authorization_url': f'https://accounts.google.com/o/oauth2/v2/auth?{query}'}

    def _oauth_callback(self, query):
        error = query.get('error', [None])[0]
        state = query.get('state', [None])[0]
        if error:
            self._redirect(f'{FRONTEND_URL}/?gee_oauth=error&reason=authorization')
            return
        if not state or not query.get('code', [None])[0]:
            self._redirect(f'{FRONTEND_URL}/?gee_oauth=error&reason=authorization')
            return
        with connection() as conn:
            state_row = conn.execute(
                'SELECT * FROM oauth_states WHERE state_hash = ? AND expires_at > ?',
                (hashlib.sha256(state.encode()).hexdigest(), time.time()),
            ).fetchone()
            conn.execute('DELETE FROM oauth_states WHERE state_hash = ?', (hashlib.sha256(state.encode()).hexdigest(),))
        if not state_row:
            self._redirect(f'{FRONTEND_URL}/?gee_oauth=error&reason=authorization')
            return
        try:
            if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
                raise RuntimeError('Google OAuth is not configured on the backend.')
            token_body = urlencode({
                'code': query['code'][0], 'client_id': GOOGLE_CLIENT_ID,
                'client_secret': GOOGLE_CLIENT_SECRET, 'redirect_uri': GOOGLE_REDIRECT_URI,
                'grant_type': 'authorization_code',
            }).encode()
            token_request = urllib.request.Request(
                GOOGLE_TOKEN_URL, data=token_body,
                headers={'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'},
            )
            with urllib.request.urlopen(token_request, timeout=20) as response:
                token_data = json.loads(response.read())
            access_token = token_data.get('access_token')
            if not access_token:
                raise RuntimeError('Google did not return an access token')
            scope = token_data.get('scope', '')
            if 'earthengine' not in scope:
                raise RuntimeError('Earth Engine scope was not granted')
            profile = self._google_userinfo(access_token)
            if not profile.get('email') or profile.get('email_verified') is False:
                raise RuntimeError('Google authorization failed')
            credentials = _credentials(
                access_token, token_data.get('refresh_token'),
                time.time() + int(token_data.get('expires_in', 3600)),
            )
            user = get_user_by_id(state_row['user_id'])
            _probe_earth_engine(credentials, state_row['project_id'])
            self._store_connection(
                user, state_row['project_id'], credentials, oauth_connected=True,
                google_subject=profile.get('sub'), google_email=profile.get('email'),
            )
        except Exception as exc:
            print(f'[GEE OAuth] callback failed: {exc}')
            self._redirect(f'{FRONTEND_URL}/?gee_oauth=error&reason=verification')
            return
        self._redirect(f'{FRONTEND_URL}/?gee_oauth=success')

    # ===== ANALYSIS (per-user EE only — no fallback) =====
    def _ee_session(self, email):
        """Shared per-user EE auth: returns (user, credentials, project, row).
        Raises RuntimeError with a user-facing message on failure."""
        user = get_user(email)
        row = _connection_for_user(email)
        project = row.get('google_project_id') if row else (user.get('cloud_project_id') if user else None)
        if not project:
            raise RuntimeError('GEE Project ID missing. Complete wizard Step 4: Enter your Google Cloud Project ID.')
        if not row or not row.get('ee_access_token'):
            raise RuntimeError('Google Earth Engine is not connected. Connect your Google account to continue.')
        try:
            token = unseal(row.get('ee_access_token'))
            refresh_token = unseal(row.get('ee_refresh_token'))
            credentials = _refresh_connection(row, _credentials(token, refresh_token, row.get('token_expires_at')))
            _probe_earth_engine(credentials, project)
        except Exception as exc:
            message = _gee_error_message(exc)
            with connection() as conn:
                conn.execute(
                    'UPDATE ee_connections SET is_active = 0, ee_authenticated = 0, ee_available = 0, '
                    'analysis_available = 0, last_error = ?, updated_at = ? WHERE id = ?',
                    (message, time.time(), row['id']),
                )
            raise RuntimeError(message)
        return user, credentials, project, row

    def _run_analysis_fallback(self, body, email=None):
        if not email:
            return {'error': 'Login required. Please register and login first.',
                    'code': 'AUTH_REQUIRED', 'status': 'auth_required'}, 401
        try:
            return self._run_analysis_impl_safe(body, email)
        except ValueError as exc:
            return {'error': str(exc), 'code': 'INVALID_PARAMETERS'}, 400

    def _run_analysis_impl_safe(self, body, email):
        """Shared analysis validation + execution (raises ValueError on bad input)."""
        analysis = (body.get('analysis') or '').strip().lower()
        geometry = body.get('geometry')
        # Safe structured log: request shape only, never tokens/credentials.
        try:
            geom_kind = (geometry or {}).get('type') if isinstance(geometry, dict) else type(geometry).__name__
        except Exception:
            geom_kind = 'unknown'
        print(f"[ANALYSIS] request analysis={analysis or '?'} year={body.get('year', 2024)} "
              f"source={body.get('source', 'sentinel2')} roi={geom_kind} user={email}")
        try:
            year = int(body.get('year', 2024))
            year2 = int(body.get('year2', 2020))
            num_classes = int(body.get('numClasses', 5))
            max_cloud = float(body.get('maxCloud', 30))
            comparison_years = body.get('comparisonYears')
            if comparison_years is not None:
                comparison_years = sorted({int(y) for y in comparison_years})
                if not 2 <= len(comparison_years) <= 8:
                    raise ValueError()
                year2, year = comparison_years[0], comparison_years[-1]
        except (TypeError, ValueError):
            raise ValueError('Invalid analysis parameters; comparisonYears must contain 2–8 distinct years.')
        source = (body.get('source') or 'sentinel2').strip().lower()
        # GEOAI planner parameters (optional; validated below)
        class_names = _parse_class_names(body.get('classNames') or body.get('classes'))
        algorithm = (body.get('algorithm') or 'random_forest').strip().lower().replace('-', '_')
        class_property = str(body.get('classProperty') or 'class').strip()
        training_samples = body.get('trainingSamples')
        validation_samples = body.get('validationSamples')
        balance_classes = bool(body.get('balanceClasses', False))
        feature_selection = body.get('featureSelection')
        if feature_selection is not None:
            if not isinstance(feature_selection, list) or not feature_selection or len(feature_selection) > 32:
                raise ValueError('featureSelection must be a non-empty list of up to 32 feature names.')
            feature_selection = [str(x).strip().lower() for x in feature_selection]
            if any(not re.fullmatch(r'[a-z][a-z0-9_]{0,15}', x) for x in feature_selection) or len(set(feature_selection)) != len(feature_selection):
                raise ValueError('featureSelection contains invalid or duplicate names.')
        try:
            model_config = body.get('modelConfig') or {}
            if not isinstance(model_config, dict):
                raise ValueError()
            model_config = {
                'trees': int(model_config.get('trees', 150)),
                'minLeafPopulation': int(model_config.get('minLeafPopulation', 1)),
                'variablesPerSplit': int(model_config.get('variablesPerSplit', 0)),
                'bagFraction': float(model_config.get('bagFraction', 0.5)),
                'svmKernel': str(model_config.get('svmKernel', 'RBF')).upper(),
                'svmCost': float(model_config.get('svmCost', 1.0)),
                'svmGamma': float(model_config.get('svmGamma', 0.5)),
            }
            if not 10 <= model_config['trees'] <= 1000 or not 1 <= model_config['minLeafPopulation'] <= 1000 or not 0 <= model_config['variablesPerSplit'] <= 32 or not 0.1 <= model_config['bagFraction'] <= 1 or model_config['svmKernel'] not in ('LINEAR', 'RBF', 'POLY', 'SIGMOID') or model_config['svmCost'] <= 0 or model_config['svmGamma'] <= 0:
                raise ValueError()
        except (TypeError, ValueError):
            raise ValueError('Invalid modelConfig. RF/CART/SVM settings must be within documented ranges.')
        method = (body.get('method') or body.get('index') or '').strip().lower() or None
        variable = (body.get('variable') or '').strip().lower() or None
        dataset = (body.get('dataset') or '').strip().lower() or None
        if dataset and dataset in ('sentinel-2', 'sentinel 2', 's2'):
            source = 'sentinel2'
        elif dataset and dataset in ('landsat 8', 'l8'):
            source = 'landsat8'
        elif dataset and dataset in ('landsat 9', 'l9'):
            source = 'landsat9'

        if not geometry:
            raise ValueError('Draw AOI on map first')
        if year < 1984 or year > 2030 or year2 < 1984 or year2 > 2030:
            raise ValueError('Analysis years must be between 1984 and 2030')
        if analysis in ('change', 'urban_growth', 'sprawl', 'lulc_change', 'deforestation', 'water_change') and year == year2:
            raise ValueError('Change analysis requires two distinct years.')
        if analysis == 'spectral_index' and str(body.get('index') or '').upper() == 'DNBR' and year == year2:
            raise ValueError('dNBR requires distinct pre-fire and post-fire years.')
        if num_classes < (2 if training_samples is not None else 3) or num_classes > 8:
            raise ValueError('Number of classes must be between 2 and 8 with imported samples, or 3 and 8 with the built-in WorldCover schema.')
        if class_names is not None and len(class_names) != num_classes:
            raise ValueError(f'classNames has {len(class_names)} names but numClasses is {num_classes}')
        if algorithm not in ('random_forest', 'rf', 'cart', 'svm', 'gtb', 'kmeans', 'k_means', 'k-means',
                             'minimum_distance', 'minimum-distance', 'mindist'):
            raise ValueError('Unknown algorithm. Use Random Forest, CART, SVM, Minimum Distance, Gradient Tree Boosting or K-Means.')
        normalized_training, training_class_map = (None, None)
        if training_samples is not None:
            normalized_training, training_class_map = validate_training_geojson(training_samples, class_property)
            if len(training_class_map) > num_classes:
                raise ValueError(f'Training samples contain {len(training_class_map)} classes but numClasses is {num_classes}.')
            if len(training_class_map) != num_classes:
                raise ValueError(f'numClasses={num_classes} but training samples contain {len(training_class_map)} classes.')
            if class_names is None:
                class_names = [training_class_map[i] for i in range(num_classes)]
        normalized_validation = None
        if validation_samples is not None:
            if normalized_training is None:
                raise ValueError('Independent validationSamples require trainingSamples so class codes can be matched.')
            normalized_validation, _ = validate_training_geojson(validation_samples, class_property,
                                                                   class_mapping=training_class_map)
        # Extended GEOAI parameters (each validated where used)
        index = (body.get('index') or '').strip().upper() or None
        if index and index not in SPECTRAL_INDICES:
            raise ValueError(f'Unknown index {index}. Available: {", ".join(SPECTRAL_INDICES)}.')
        mode = (body.get('mode') or '').strip().lower() or None
        thresholds = body.get('thresholds')
        if thresholds is not None:
            try:
                thresholds = sorted({float(x) for x in thresholds})
                min_thresholds = 1 if analysis == 'hydrology' else 3
                if len(thresholds) < min_thresholds or len(thresholds) > 9 or any(not math.isfinite(x) for x in thresholds):
                    raise ValueError()
            except (TypeError, ValueError):
                return {'error': 'thresholds must contain ' + ('1–9 positive upstream-area values in km².' if analysis == 'hydrology' else '3–9 ascending finite numbers (e.g. [0,5,15,30,45]).')}, 400
        period = (body.get('period') or 'annual').strip().lower()
        if period not in ('annual', 'monthly', 'seasonal'):
            return {'error': 'period must be annual, monthly or seasonal'}, 400
        if source not in ('sentinel2', 'landsat7', 'landsat8', 'landsat9'):
            return {'error': 'source must be sentinel2, landsat7, landsat8 or landsat9'}, 400
        try:
            month = int(body.get('month')) if body.get('month') is not None else None
            if month is not None and not 1 <= month <= 12:
                raise ValueError()
        except (TypeError, ValueError):
            return {'error': 'month must be 1–12'}, 400
        season = (body.get('season') or '').strip().lower() or None
        months = body.get('months')
        if months is not None:
            try:
                months = sorted({int(m) for m in months})
                if not months or any(m < 1 or m > 12 for m in months):
                    raise ValueError()
            except (TypeError, ValueError):
                return {'error': 'months must be integers 1–12'}, 400
        indicator = (body.get('indicator') or '').strip().lower() or None
        pollutant = (body.get('pollutant') or '').strip().lower() or None
        if pollutant and pollutant not in ('no2', 'so2', 'co', 'o3', 'aod', 'pm25'):
            return {'error': 'Unknown pollutant. Use NO2, SO2, CO, O3, AOD (PM2.5 has no configured dataset).'}, 400
        ratio = body.get('ratio')
        ratio_num = ratio_den = None
        if ratio is not None:
            try:
                ratio_num = str(ratio.get('num')).upper()
                ratio_den = str(ratio.get('den')).upper()
                if not (re.fullmatch(r'B\d{1,2}[A-Z]?', ratio_num) and re.fullmatch(r'B\d{1,2}[A-Z]?', ratio_den)):
                    raise ValueError()
            except (AttributeError, TypeError, ValueError):
                return {'error': 'ratio must be {num: "B7", den: "B2"} sensor band codes'}, 400
        preset = (body.get('preset') or '').strip().lower() or None
        use = (body.get('use') or 'residential').strip().lower()
        weights = body.get('weights')
        pairwise_matrix = body.get('pairwiseMatrix')
        criteria = body.get('criteria')
        constraints = body.get('constraints')
        suitability_method = (body.get('suitabilityMethod') or 'wlc').strip().lower()
        if suitability_method not in ('wlc', 'ahp'):
            return {'error': "suitabilityMethod must be 'wlc' or 'ahp'."}, 400
        if weights is not None:
            try:
                weights = validate_weights(weights)
            except (TypeError, ValueError, AttributeError) as exc:
                return {'error': str(exc)}, 400
        if analysis == 'suitability':
            suitability_criteria = {'slope', 'landcover', 'flood', 'ndvi', 'rainfall', 'elevation'}
            if suitability_method == 'ahp':
                if not isinstance(criteria, list):
                    return {'error': 'AHP requires criteria in the same order as pairwiseMatrix rows and columns.'}, 400
                try:
                    weights, consistency_ratio, _ = ahp_weights(pairwise_matrix, criteria)
                except ValueError as exc:
                    return {'error': str(exc)}, 400
                if consistency_ratio > 0.10:
                    return {'error': f'AHP consistency ratio is {consistency_ratio:.3f} (>0.10). Revise the pairwise judgments.'}, 400
            elif weights is None:
                return {'error': 'Provide explicit weights (for example slope:40, rainfall:30, landcover:30) or choose AHP with a pairwise matrix. No default scientific weights are assumed.'}, 400
            try:
                weights = validate_weights(weights, suitability_criteria)
            except ValueError as exc:
                return {'error': str(exc)}, 400
            if constraints is not None and not isinstance(constraints, dict):
                return {'error': 'constraints must be an object, for example {excludeWater:true,maxSlope:25}.'}, 400
            if constraints:
                if set(constraints) - {'excludeWater', 'maxSlope'} or ('excludeWater' in constraints and not isinstance(constraints['excludeWater'], bool)):
                    return {'error': 'Use supported constraints only: excludeWater (boolean) and maxSlope (degrees).'}, 400
                try:
                    max_slope = float(constraints.get('maxSlope', 30))
                except (TypeError, ValueError):
                    return {'error': 'constraints.maxSlope must be degrees from 0 to 90.'}, 400
                if not math.isfinite(max_slope) or not 0 <= max_slope <= 90:
                    return {'error': 'constraints.maxSlope must be degrees from 0 to 90.'}, 400
            scenarios = body.get('scenarios')
            if scenarios is not None:
                if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= 6:
                    return {'error': 'scenarios must be a list of 1–6 named weight objects.'}, 400
                try:
                    for item in scenarios:
                        if not isinstance(item, dict) or not isinstance(item.get('weights'), dict):
                            raise ValueError('Each scenario requires {name, weights:{criterion:weight}}.')
                        validate_weights(item['weights'], suitability_criteria)
                except ValueError as exc:
                    return {'error': str(exc)}, 400
            sensitivity = body.get('sensitivity')
            if sensitivity:
                if not isinstance(sensitivity, (bool, dict)):
                    return {'error': 'sensitivity must be true or an object with perturbation (default 0.1).'}, 400
                try:
                    perturbation = float(sensitivity.get('perturbation', 0.1)) if isinstance(sensitivity, dict) else 0.1
                except (TypeError, ValueError):
                    return {'error': 'sensitivity.perturbation must be in (0, 0.5].'}, 400
                if not math.isfinite(perturbation) or not 0 < perturbation <= 0.5:
                    return {'error': 'sensitivity.perturbation must be in (0, 0.5].'}, 400
        test = (body.get('test') or 'both').strip().lower()
        tune = bool(body.get('tune', False))
        stats_op = (body.get('statsOp') or '').strip().lower() or None
        if max_cloud < 0 or max_cloud > 100:
            return {'error': 'Cloud cover must be between 0 and 100'}, 400

        try:
            user, credentials, project, row = self._ee_session(email)
        except RuntimeError as exc:
            msg = str(exc)
            # Structured auth errors: frontend distinguishes expired /
            # missing / project problems instead of one generic message.
            if msg.startswith('GEE Project ID missing'):
                err_code, status, http = 'GEE_PROJECT_MISSING', 'invalid_roi', 400
            elif 'expired' in msg.lower() and 're-connect' in msg.lower():
                err_code, status, http = 'GEE_AUTH_EXPIRED', 'auth_expired', 401
            elif msg.startswith('Google Earth Engine is not connected'):
                err_code, status, http = 'GEE_AUTH_REQUIRED', 'auth_required', 401
            else:
                err_code, status, http = 'GEE_AUTH_INVALID', 'auth_invalid', 502
            print(f'[ANALYSIS] blocked analysis={analysis or "?"} reason={err_code} user={email}')
            return {'error': msg, 'code': err_code, 'status': status}, http

        try:
            project_row = self._ensure_project(email, body.get('projectId'))
            geom = self._geom_any(geometry)
        except Exception as exc:
            return {'error': str(exc)}, 400

        job_id = secrets.token_hex(16)
        started = time.time()
        params = {
            'year': year, 'year2': year2, 'numClasses': num_classes,
            'comparisonYears': comparison_years,
            'source': source, 'maxCloud': max_cloud,
            'classNames': class_names, 'algorithm': algorithm,
            'classProperty': class_property, 'trainingSamples': normalized_training,
            'validationSamples': normalized_validation, 'featureSelection': feature_selection,
            'modelConfig': model_config, 'balanceClasses': balance_classes,
            'method': method, 'variable': variable, 'dataset': dataset,
            'index': index, 'mode': mode, 'thresholds': thresholds,
            'period': period, 'month': month, 'season': season, 'months': months,
            'indicator': indicator, 'pollutant': pollutant,
            'ratio': {'num': ratio_num, 'den': ratio_den} if ratio_num else None,
            'preset': preset, 'use': use, 'weights': weights,
            'suitabilityMethod': suitability_method, 'criteria': criteria,
            'pairwiseMatrix': pairwise_matrix, 'constraints': constraints,
            'sensitivity': body.get('sensitivity'), 'scenarios': body.get('scenarios'),
            'test': test, 'tune': tune, 'statsOp': stats_op,
            # Stored for reproducibility + export rebuild (traceability §42).
            'geometry': geometry,
        }
        with connection() as conn:
            conn.execute(
                'INSERT INTO analysis_jobs (id, project_id, user_id, analysis_type, parameters, status, started_at, created_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (job_id, project_row['id'], user['id'], analysis, json.dumps(params), 'running', started, started),
            )
        try:
            print(f'[ANALYSIS] {email} -> {analysis} ({year})')
            result = self._run_analysis_impl(
                analysis, geom, year, year2, num_classes, source, max_cloud,
                class_names=class_names, algorithm=algorithm, method=method, variable=variable,
                comparison_years=comparison_years,
                training_samples=normalized_training, validation_samples=normalized_validation,
                class_property=class_property, feature_selection=feature_selection, model_config=model_config,
                balance_classes=balance_classes,
                index=index, mode=mode, thresholds=thresholds, period=period, month=month,
                season=season, months=months, indicator=indicator, pollutant=pollutant,
                ratio_num=ratio_num, ratio_den=ratio_den, preset=preset, use=use,
                weights=weights, test=test, tune=tune, stats_op=stats_op,
                suitability_method=suitability_method, constraints=constraints,
                sensitivity=body.get('sensitivity'), scenarios=body.get('scenarios'))
            if result.get('error'):
                raise RuntimeError(result['error'])
            result = self._std_result(result, analysis, source, year, year2, params)
            result['jobId'] = job_id
            result['projectId'] = project_row['id']
            result_id = secrets.token_hex(16)
            completed = time.time()
            with connection() as conn:
                conn.execute(
                    'UPDATE analysis_jobs SET status = ?, completed_at = ? WHERE id = ?',
                    ('completed', completed, job_id),
                )
                conn.execute(
                    'INSERT INTO analysis_results (id, job_id, user_id, stats, tile_url, interpretation, result_json, created_at) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                    (result_id, job_id, user['id'], json.dumps(result.get('stats', {})), result.get('tileUrl'),
                     result.get('interpretation'), json.dumps(result), completed),
                )
            result['resultId'] = result_id
            return result
        except Exception as exc:
            message = str(exc) or 'Analysis execution failed'
            with connection() as conn:
                conn.execute(
                    'UPDATE analysis_jobs SET status = ?, error_message = ?, completed_at = ? WHERE id = ?',
                    ('failed', message, time.time(), job_id),
                )
            return {'error': message}, 502

    def _supervised_classifier(self, algorithm, training, class_prop, bands, config=None):
        """Real EE classifiers. Returns (classifier, actual_name). Never fakes."""
        algo = (algorithm or 'random_forest').lower().replace('-', '_')
        config = config or {}
        if algo == 'rf':
            algo = 'random_forest'
        if algo == 'cart':
            clf = ee.Classifier.smileCart(None, config.get('minLeafPopulation', 1))
            return clf.train(training, class_prop, bands), 'CART'
        if algo == 'svm':
            clf = ee.Classifier.libsvm(svmType='C_SVC', kernelType=config.get('svmKernel', 'RBF'),
                                       gamma=config.get('svmGamma', 0.5), cost=config.get('svmCost', 1.0))
            return clf.train(training, class_prop, bands), f'SVM ({config.get("svmKernel", "RBF")})'
        if algo in ('minimum_distance', 'mindist'):
            return ee.Classifier.minimumDistance().train(training, class_prop, bands), 'Minimum Distance'
        if algo in ('gtb', 'gradient_tree_boosting', 'boosting'):
            return ee.Classifier.smileGradientTreeBoost(30).train(training, class_prop, bands), 'Gradient Tree Boosting'
        if algo in ('random_forest',):
            clf = ee.Classifier.smileRandomForest(config.get('trees', 150),
                config.get('variablesPerSplit', 0) or None, config.get('minLeafPopulation', 1),
                config.get('bagFraction', 0.5), None, 42)
            return clf.train(training, class_prop, bands), f'Random Forest ({config.get("trees", 150)} trees)'
        raise ValueError(f'Unsupported supervised classifier: {algorithm}.')

    def _std_result(self, legacy, analysis, source, year, year2, params):
        """Standard envelope (map + legend + statistics + explanation) that keeps
        every legacy key (type/label/stats/tileUrl/interpretation) intact."""
        names = {
            'ndvi': ('NDVI', 'vegetation', 'NDVI'), 'evi': ('EVI', 'vegetation', 'EVI'),
            'savi': ('SAVI', 'vegetation', 'SAVI'), 'ndwi': ('NDWI', 'water', 'NDWI'),
            'ndbi': ('NDBI', 'urban', 'NDBI'), 'urban_growth': ('Urban Growth', 'urban', 'NDBI difference'),
            'water_change': ('Water Extent Change', 'change', 'NDWI threshold comparison'),
            'elevation': ('Elevation', 'terrain', 'SRTM DEM'), 'slope': ('Slope', 'terrain', 'SRTM DEM'),
            'landcover': ('Land Cover Classification', 'landcover', params.get('algorithm', 'random_forest')),
            'vegetation': ('Vegetation Classification', 'vegetation', 'NDVI thresholds'),
            'dynamicworld': ('Dynamic World', 'landcover', 'Dynamic World V1'),
            'worldcover_v200': ('ESA WorldCover', 'landcover', 'WorldCover v200'),
            'modis_lc': ('MODIS Land Cover', 'landcover', 'MCD12Q1'),
            'modis_cmg': ('MODIS CMG', 'landcover', 'MCD12C1'),
            'copernicus_lc': ('Copernicus Land Cover', 'landcover', 'Proba-V C3'),
            'glc_fcs30': ('GLC_FCS30D', 'landcover', 'GLC_FCS30D'),
            'nlcd': ('NLCD', 'landcover', 'NLCD 2021'), 'corine': ('CORINE', 'landcover', 'CORINE 2018'),
            'change': ('Change Detection', 'change', 'NDVI difference'),
            'buildings': ('Building Density', 'urban', 'Open Buildings'),
            'flood': ('Flood Susceptibility', 'flood', 'SRTM terrain proxy'),
            'flood_mapping': ('Flood Mapping', 'flood', 'Sentinel-1 SAR'),
            'lst': ('Land Surface Temperature', 'climate', 'MODIS MOD11A1'),
            'rainfall': ('Rainfall', 'climate', 'CHIRPS'),
            'erosion': ('Soil Erosion (RUSLE-lite)', 'soil', 'RUSLE proxy'),
            'drought': ('Drought (NDVI anomaly)', 'climate', 'NDVI + CHIRPS anomaly'),
            'timeseries': ('Time Series', 'timeseries', params.get('variable', 'ndvi')),
            'spectral_index': (params.get('index', 'Index'), 'indices', params.get('index', '')),
            'imagery': ('Satellite Imagery', 'imagery', params.get('mode', 'composite')),
            'aspect': ('Aspect', 'terrain', 'SRTM DEM'), 'hillshade': ('Hillshade', 'terrain', 'SRTM DEM'),
            'slope_classes': ('Slope Classification', 'terrain', 'SRTM DEM'),
            'curvature': ('Terrain Curvature', 'terrain', 'SRTM 3×3 Laplacian'),
            'tri': ('Terrain Ruggedness Index', 'terrain', 'SRTM 8-neighbour RMS'),
            'tpi': ('Topographic Position Index', 'terrain', 'SRTM neighbourhood mean'),
            'twi': ('Topographic Wetness Index', 'terrain', 'MERIT Hydro + SRTM'),
            'terrain': ('Terrain Derivative', 'terrain', params.get('variable', 'slope')),
            'lst_change': ('LST Change', 'climate', 'MODIS MOD11A1'),
            'uhi': ('Urban Heat Island', 'climate', 'MODIS + WorldCover/NDBI'),
            'uftvi': ('UTFVI', 'climate', 'MODIS UTFVI'),
            'sprawl': ('Urban Sprawl', 'urban', 'NDBI multi-temporal'),
            'lulc_change': ('LULC Change + Transition Matrix', 'change', params.get('algorithm', 'random_forest')),
            'deforestation': ('Deforestation (Hansen)', 'change', 'Hansen GFC'),
            'et': ('Evapotranspiration', 'climate', 'MODIS MOD16A2'),
            'airquality': ('Air Quality', 'airquality', params.get('pollutant', '')),
            'hydrology': ('Hydrology', 'hydrology', 'MERIT Hydro'),
            'landslide': ('Landslide Susceptibility', 'hazard', 'weighted overlay'),
            'salinity': ('Soil Salinity Indicator', 'soil', 'spectral SI'),
            'moisture': ('Soil Moisture (NDMI)', 'soil', 'NDMI'),
            'mineral': ('Mineral Indicator', 'geology', 'band ratios'),
            'suitability': ('Suitability', 'suitability', 'weighted overlay'),
            'trend': ('Trend Analysis', 'timeseries', 'regression + Mann-Kendall'),
            'waterlogging': ('Waterlogging', 'water', 'MNDWI + terrain'),
        }
        title, category, method = names.get(analysis, (legacy.get('type', analysis), 'analysis', 'GEE'))
        dataset = {'sentinel2': 'Sentinel-2', 'landsat8': 'Landsat 8', 'landsat9': 'Landsat 9',
                   'landsat7': 'Landsat 7', 'modis': 'MODIS'}.get(source, source)
        out = dict(legacy)
        out.update({
            'success': True,
            'analysis': {'id': analysis, 'name': title, 'category': category, 'method': method},
            'layer': {'name': legacy.get('label', title), 'tile_url': legacy.get('tileUrl'),
                      'vis_params': legacy.get('visParams', {})},
            'legend': legacy.get('legend', []),
            'statistics': legacy.get('stats', {}),
            'parameters': params,
            'metadata': {'dataset': dataset, 'date': str(year), 'year2': year2,
                         'scale': legacy.get('scale', 10), 'aoi': 'current'},
            'message': legacy.get('interpretation', ''),
        })
        return out

    def _run_analysis_impl(self, analysis, geom, year, year2, num_classes, source, max_cloud=30,
                           class_names=None, algorithm='random_forest', method=None, variable=None,
                           index=None, mode=None, thresholds=None, period='annual', month=None,
                           season=None, months=None, indicator=None, pollutant=None,
                           ratio_num=None, ratio_den=None, preset=None, use='residential',
                           weights=None, test='both', tune=False, stats_op=None,
                           training_samples=None, validation_samples=None, class_property='class',
                           feature_selection=None, model_config=None, balance_classes=False,
                           comparison_years=None, suitability_method='wlc',
                           constraints=None, sensitivity=None, scenarios=None):
        """Unified per-user analysis engine (real GEE only — no mocks)."""
        start, end = f'{year}-01-01', f'{year}-12-31'
        months_filter = None
        optical_composites = ('spectral_index', 'imagery', 'ndvi', 'evi', 'savi', 'ndwi', 'ndbi')
        if analysis in optical_composites:
            if period == 'monthly':
                if not month:
                    return {'error': 'Choose a month for a monthly optical composite.'}
                start = f'{year}-{month:02d}-01'
                end = f'{year + (1 if month == 12 else 0)}-{(month % 12) + 1:02d}-01'
            elif period == 'seasonal':
                if not months:
                    return {'error': 'Choose seasonal months for a seasonal optical composite.'}
                months_filter = sorted({int(m) for m in months})
                if not months_filter or any(m < 1 or m > 12 for m in months_filter):
                    return {'error': 'Season months must be integers from 1 to 12.'}
                crosses_year = 12 in months_filter and 1 in months_filter
                first_month = min((m for m in months_filter if m > 6), default=min(months_filter)) if crosses_year else min(months_filter)
                last_month = max((m for m in months_filter if m <= 6), default=max(months_filter)) if crosses_year else max(months_filter)
                start_year = year - 1 if crosses_year else year
                end_year = year if crosses_year else year
                start = f'{start_year}-{first_month:02d}-01'
                end = f'{end_year + (1 if last_month == 12 else 0)}-{(last_month % 12) + 1:02d}-01'
        no_optical = ('elevation', 'slope', 'aspect', 'hillshade', 'slope_classes', 'buildings',
                      'lst', 'lst_change', 'uhi', 'uftvi', 'rainfall', 'et', 'flood_mapping',
                      'erosion', 'drought', 'timeseries', 'trend', 'dynamicworld', 'worldcover_v200',
                      'modis_lc', 'modis_cmg', 'copernicus_lc', 'glc_fcs30', 'nlcd', 'corine',
                      'deforestation', 'airquality', 'hydrology', 'landslide', 'salinity',
                      'moisture', 'mineral', 'suitability', 'curvature', 'tri', 'tpi', 'twi', 'terrain',
                      'lulc_change', 'sprawl', 'waterlogging')
        observation_count = None
        if analysis in optical_composites:
            col, observation_count = self._collection(geom, start, end, source, max_cloud,
                                                       months=months_filter, return_count=True)
        elif analysis in no_optical:
            col = None
        else:
            col, observation_count = self._collection(geom, start, end, source, max_cloud, return_count=True)

        if analysis == 'ndvi':
            B = self._bands(source)
            b = (B['NIR'], B['RED'])
            img = col.normalizedDifference(b).rename('NDVI')
            tile = self._tile(img,{'min':-0.2,'max':0.8,'palette':['red','yellow','green']})
            q = self._stats4(img, geom, 10, 'NDVI')
            m = q.get('Mean', 0) or 0
            stats = {'Mean NDVI': m, 'Scenes after metadata filters': observation_count}
            if q.get('Min') is not None:
                stats.update({'Min NDVI': q['Min'], 'Max NDVI': q['Max'], 'Std NDVI': q['Std']})
            return {'type':'NDVI','label':f'NDVI ({year})','stats':stats,'tileUrl':tile,'interpretation':m>0.6 and 'Dense vegetation' or m>0.3 and 'Moderate' or 'Sparse',
                    'legend': {'type':'continuous','min':-0.2,'max':0.8,'unit':'NDVI'}, 'scale': 10}

        elif analysis in ('evi',):
            B = self._bands(source)
            nir, red, blue = B['NIR'], B['RED'], B['BLUE']
            img = col.expression('2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
                                 {'NIR': col.select(nir), 'RED': col.select(red), 'BLUE': col.select(blue)}).rename('EVI')
            tile = self._tile(img,{'min':0,'max':1,'palette':['#d73027','#fee08b','#1a9850']})
            s = self._reduce(img,geom)
            m = s.get('EVI',0)
            return {'type':'EVI','label':f'EVI ({year})','stats':{'Mean EVI':round(m,4), 'Scenes after metadata filters': observation_count},'tileUrl':tile,
                    'interpretation':m>0.5 and 'Dense healthy vegetation' or m>0.3 and 'Moderate' or 'Sparse/stressed',
                    'legend': {'type':'continuous','min':0,'max':1,'unit':'EVI'}, 'scale': 10}

        elif analysis in ('savi',):
            B = self._bands(source)
            nir, red = B['NIR'], B['RED']
            img = col.expression('((NIR - RED) / (NIR + RED + 0.5)) * 1.5',
                                 {'NIR': col.select(nir), 'RED': col.select(red)}).rename('SAVI')
            tile = self._tile(img,{'min':0,'max':1,'palette':['#d73027','#fee08b','#1a9850']})
            s = self._reduce(img,geom)
            m = s.get('SAVI',0)
            return {'type':'SAVI','label':f'SAVI ({year})','stats':{'Mean SAVI':round(m,4), 'Scenes after metadata filters': observation_count},'tileUrl':tile,
                    'interpretation':m>0.5 and 'Dense vegetation (soil-adjusted)' or m>0.25 and 'Moderate' or 'Sparse/bare soil influence',
                    'legend': {'type':'continuous','min':0,'max':1,'unit':'SAVI'}, 'scale': 10}

        elif analysis == 'ndwi':
            B = self._bands(source)
            b = (B['GREEN'], B['NIR'])
            img = col.normalizedDifference(b).rename('NDWI')
            # Documented screening rule: NDWI > 0 => water. Thresholds vary by
            # season, turbidity and sensor; use local reference data to tune.
            water = img.gt(0).rename('water')
            tile = self._tile(water,{'min':0,'max':1,'palette':['#8B4513','#0000CD']})
            s = self._reduce(img,geom)
            m = s.get('NDWI',0)
            wa = self._class_areas(water, geom, 10, {0: 'Non-water', 1: 'Water'})
            return {'type':'NDWI','label':f'NDWI water extent ({year})','stats':{'Mean NDWI':round(m,4), 'Water threshold': 'NDWI > 0 (fixed screening threshold)', 'Scenes after metadata filters': observation_count, **wa},'tileUrl':tile,'interpretation':'Water extent screened with NDWI > 0 (McFeeters-style fixed threshold). Threshold is not universal; validate locally against reference water data and season.',
                    'legend': [{'value': 0, 'label': 'Non-water', 'color': '#8B4513'}, {'value': 1, 'label': 'Water', 'color': '#0000CD'}], 'scale': 10}

        elif analysis == 'ndbi':
            B = self._bands(source)
            b = (B['SWIR1'], B['NIR'])
            img = col.normalizedDifference(b).rename('NDBI')
            tile = self._tile(img,{'min':-0.3,'max':0.3,'palette':['#00FF00','#FFFF00','#FF0000']})
            s = self._reduce(img,geom)
            m = s.get('NDBI',0)
            ba = self._class_areas(img.gt(0.1).rename('b'), geom, 10, {0: 'Non built-up', 1: 'Built-up'})
            return {'type':'NDBI','label':f'NDBI ({year})','stats':{'Mean NDBI':round(m,4), 'Scenes after metadata filters': observation_count, **ba},'tileUrl':tile,'interpretation':m>0.1 and 'Urban area' or 'Non-urban',
                    'legend': [{'value': 0, 'label': 'Non built-up', 'color': '#00FF00'}, {'value': 1, 'label': 'Built-up', 'color': '#FF0000'}], 'scale': 10}

        elif analysis == 'urban_growth':
            y1, y2 = year2, year
            c1, count1 = self._collection(geom,f'{y1}-01-01',f'{y1}-12-31',source,max_cloud,return_count=True)
            c2, count2 = self._collection(geom,f'{y2}-01-01',f'{y2}-12-31',source,max_cloud,return_count=True)
            B = self._bands(source)
            b = (B['SWIR1'], B['NIR'])
            ndbi_pre, ndbi_post = c1.normalizedDifference(b), c2.normalizedDifference(b)
            growth = ndbi_post.subtract(ndbi_pre).rename('growth')
            pre_built, post_built = ndbi_pre.gt(0.1), ndbi_post.gt(0.1)
            transition_img = pre_built.toInt().multiply(2).add(post_built.toInt()).rename('built_transition').clip(geom)
            legend = [{'value': 0, 'label': 'Persistent non-built', 'color': '#d9d9d9'},
                      {'value': 1, 'label': 'Urban expansion', 'color': '#fdae61'},
                      {'value': 2, 'label': 'Built-up loss', 'color': '#4575b4'},
                      {'value': 3, 'label': 'Persistent built-up', 'color': '#d7191c'}]
            tile = self._tile(transition_img, {'min': 0, 'max': 3, 'palette': [x['color'] for x in legend]})
            m = self._reduce(growth, geom, 10).get('growth', 0) or 0
            pre_m2, post_m2 = self._class_area_m2(pre_built, geom), self._class_area_m2(post_built, geom)
            expansion_m2 = self._class_area_m2(post_built.And(pre_built.Not()), geom)
            loss_m2 = self._class_area_m2(pre_built.And(post_built.Not()), geom)
            years_elapsed = max(1, y2-y1)
            pct = 100 * (post_m2-pre_m2)/pre_m2 if pre_m2 else None
            return {'type':'UrbanGrowth','label':f'Urban Expansion ({y1} → {y2})',
                    'stats':{'Mean NDBI change':round(float(m),4), 'Pre-period scenes':count1, 'Post-period scenes':count2,
                             'Pre built-up (NDBI > 0.1)':f'{pre_m2/1e4:.2f} ha / {pre_m2/1e6:.4f} km²',
                             'Post built-up (NDBI > 0.1)':f'{post_m2/1e4:.2f} ha / {post_m2/1e6:.4f} km²',
                             'Expansion':f'{expansion_m2/1e4:.2f} ha / {expansion_m2/1e6:.4f} km²',
                             'Built-up loss':f'{loss_m2/1e4:.2f} ha / {loss_m2/1e6:.4f} km²',
                             'Annualized net area change':f'{(post_m2-pre_m2)/1e4/years_elapsed:+.2f} ha/yr',
                             'Percentage change':f'{pct:+.2f}%' if pct is not None else 'Undefined (no pre-period built-up area)'},
                    'tileUrl':tile,'interpretation':'NDBI > 0.1 binary built-up screening comparison; thresholds are not universal and this is not a cadastral building map.',
                    'legend': legend, 'scale': 10}

        elif analysis == 'elevation':
            dem = ee.Image('USGS/SRTMGL1_003').clip(geom)
            tile = self._tile(dem,{'min':0,'max':300,'palette':['#006400','#32CD32','#FFD700','#8B4513','#FFFFFF']})
            s = self._reduce(dem,geom,30)
            m = s.get('elevation',0)
            return {'type':'Elevation','label':'Elevation','stats':{'Mean':f'{m:.1f}m'},'tileUrl':tile,'interpretation':f'Mean elevation: {m:.0f}m (SRTM 30m)',
                    'legend': {'type':'continuous','min':0,'max':300,'unit':'m'}, 'scale': 30}

        elif analysis == 'slope':
            dem = ee.Image('USGS/SRTMGL1_003').clip(geom)
            slope_img = ee.Terrain.slope(dem).rename('slope')
            tile = self._tile(slope_img,{'min':0,'max':45,'palette':['green','yellow','orange','red']})
            s = self._reduce(slope_img,geom,30)
            m = s.get('slope',0)
            steep = self._class_areas(slope_img.gt(15).rename('s'), geom, 30, {0: 'Gentle (≤15°)', 1: 'Steep (>15°)'})
            return {'type':'Slope','label':'Slope','stats':{'Mean':f'{m:.1f}°', **steep},'tileUrl':tile,
                    'interpretation':(m>15 and 'Steep' or m>5 and 'Moderate' or 'Flat') + f' (mean {m:.1f}°)',
                    'legend': [{'value': 0, 'label': 'Gentle (≤15°)', 'color': 'green'}, {'value': 1, 'label': 'Steep (>15°)', 'color': 'red'}], 'scale': 30}

        elif analysis == 'change':
            y1, y2 = year2, year
            c1, count1 = self._collection(geom,f'{y1}-01-01',f'{y1}-12-31',source,max_cloud,return_count=True)
            c2, count2 = self._collection(geom,f'{y2}-01-01',f'{y2}-12-31',source,max_cloud,return_count=True)
            b = ('SR_B5','SR_B4') if 'landsat' in source else ('B8','B4')
            diff = c2.normalizedDifference(b).subtract(c1.normalizedDifference(b)).rename('change')
            tile = self._tile(diff,{'min':-0.5,'max':0.5,'palette':['red','orange','yellow','white','lightgreen','green']})
            s = self._reduce(diff,geom)
            m = s.get('change',0)
            gain_m2 = self._class_area_m2(diff.gt(0.05), geom, 10)
            loss_m2 = self._class_area_m2(diff.lt(-0.05), geom, 10)
            aoi_m2 = geom.area(1).getInfo() or 1
            interval = max(1, abs(y2 - y1))
            return {'type':'ChangeDetection','label':f'NDVI Change ({y1} → {y2})',
                    'stats':{'Mean NDVI change':round(m,4), 'Pre-period scenes':count1, 'Post-period scenes':count2,
                             'Gain area (>+0.05)':f'{gain_m2/1e4:.2f} ha / {gain_m2/1e6:.4f} km²',
                             'Loss area (<−0.05)':f'{loss_m2/1e4:.2f} ha / {loss_m2/1e6:.4f} km²',
                             'Gain percent of AOI':f'{100*gain_m2/aoi_m2:.2f}%',
                             'Loss percent of AOI':f'{100*loss_m2/aoi_m2:.2f}%',
                             'Annualized gain':f'{gain_m2/1e4/interval:.2f} ha/yr',
                             'Annualized loss':f'{loss_m2/1e4/interval:.2f} ha/yr'},'tileUrl':tile,
                    'interpretation':f'NDVI difference = {y2} − {y1}; gain/loss masks use ±0.05 screening threshold and are not causal attribution.',
                    'legend': {'type':'continuous','min':-0.5,'max':0.5,'unit':'NDVI change'}, 'scale': 10}

        elif analysis == 'water_change':
            y1, y2 = sorted((year, year2))
            B = self._bands(source)
            c1, count1 = self._collection(geom, f'{y1}-01-01', f'{y1}-12-31', source, max_cloud, return_count=True)
            c2, count2 = self._collection(geom, f'{y2}-01-01', f'{y2}-12-31', source, max_cloud, return_count=True)
            water1 = c1.normalizedDifference([B['GREEN'], B['NIR']]).gt(0).rename('water')
            water2 = c2.normalizedDifference([B['GREEN'], B['NIR']]).gt(0).rename('water')
            # Transition codes: 0 land→land, 1 land→water, 2 water→land, 3 water→water.
            transition_img = water1.toInt().multiply(2).add(water2.toInt()).rename('water_transition').clip(geom)
            labels = {0: 'Persistent non-water', 1: 'Water gain', 2: 'Water loss', 3: 'Persistent water'}
            legend = [{'value': 0, 'label': labels[0], 'color': '#d9d9d9'},
                      {'value': 1, 'label': labels[1], 'color': '#2c7bb6'},
                      {'value': 2, 'label': labels[2], 'color': '#d7191c'},
                      {'value': 3, 'label': labels[3], 'color': '#00a6ca'}]
            tile = self._tile(transition_img, {'min': 0, 'max': 3, 'palette': [x['color'] for x in legend]})
            area_transition = self._class_areas(transition_img, geom, 10, labels)
            pre_m2 = self._class_area_m2(water1, geom, 10)
            post_m2 = self._class_area_m2(water2, geom, 10)
            gain_m2 = self._class_area_m2(water2.And(water1.Not()), geom, 10)
            loss_m2 = self._class_area_m2(water1.And(water2.Not()), geom, 10)
            delta_m2 = post_m2 - pre_m2
            elapsed = max(1, y2 - y1)
            pct = (100 * delta_m2 / pre_m2) if pre_m2 else None
            return {'type': 'WaterExtentChange', 'label': f'Water Extent Change ({y1} → {y2})',
                    'stats': {'Pre-period scenes': count1, 'Post-period scenes': count2,
                              'Pre water extent': f'{pre_m2/1e4:.2f} ha / {pre_m2/1e6:.4f} km²',
                              'Post water extent': f'{post_m2/1e4:.2f} ha / {post_m2/1e6:.4f} km²',
                              'Water gain': f'{gain_m2/1e4:.2f} ha / {gain_m2/1e6:.4f} km²',
                              'Water loss': f'{loss_m2/1e4:.2f} ha / {loss_m2/1e6:.4f} km²',
                              'Net change': f'{delta_m2/1e4:+.2f} ha ({pct:+.2f}%)' if pct is not None else f'{delta_m2/1e4:+.2f} ha (percent undefined: zero pre water area)',
                              'Annualized net change': f'{delta_m2/1e4/elapsed:+.2f} ha/yr',
                              'Threshold': 'NDWI > 0, fixed screening method', **area_transition},
                    'transition': area_transition, 'tileUrl': tile,
                    'interpretation': 'Matched annual surface-reflectance composites; NDWI > 0 masks. Threshold is season/sensor dependent and requires local reference validation.',
                    'legend': legend, 'scale': 10}

        elif analysis == 'dynamicworld':
            dw = ee.ImageCollection('GOOGLE/DYNAMICWORLD/V1').filterBounds(geom).filterDate(start,end).select('label').mode().clip(geom)
            tile = self._tile(dw,{'min':0,'max':8,'palette':['#419BDF','#397D49','#88B053','#7A87C6','#E49635','#DFC35A','#C4281B','#A59B8F','#B39FE1']})
            names = {0:'Water',1:'Trees',2:'Grass',3:'Flooded Veg',4:'Crops',5:'Shrub/Scrub',6:'Built-up',7:'Bare',8:'Snow/Ice'}
            areas = self._class_areas(dw, geom, 10, names)
            palette_dw = ['#419BDF','#397D49','#88B053','#7A87C6','#E49635','#DFC35A','#C4281B','#A59B8F','#B39FE1']
            legend = [{'value': i, 'label': names[i], 'color': palette_dw[i]} for i in range(9)]
            return {'type':'DynamicWorld','label':f'Dynamic World ({year})','stats':areas,'tileUrl':tile,'interpretation':f'Land cover for {year}',
                    'legend': legend, 'scale': 10}

        elif analysis == 'landcover':
            # Classes are first-class: default 5-class schema, custom names honored.
            # Use supervised reference classes (or imported samples); K-Means has no accuracy score.
            n = min(8, max(2 if training_samples is not None else 3, num_classes))
            defaults = {3: ['Bareland', 'Vegetation', 'Built-up'],
                        4: ['Built-up', 'Vegetation', 'Bare', 'Water'],
                        5: ['Bareland', 'Built-up', 'Vegetation', 'Cropland', 'Rangeland'],
                        6: ['Bareland', 'Built-up', 'Forest', 'Cropland', 'Rangeland', 'Water']}
            names_list = list(class_names) if class_names and len(class_names) == n else list(defaults.get(n, defaults[5]))
            while len(names_list) < n:
                names_list.append(f'Class {len(names_list) + 1}')
            names_list = names_list[:n]
            B = self._bands(source)
            aliases = {'blue': 'BLUE', 'green': 'GREEN', 'red': 'RED', 'rededge1': 'RE',
                       'rededge2': 'RE2', 'rededge3': 'RE3', 'nir': 'NIR', 'nir_narrow': 'NIR_NARROW',
                       'swir1': 'SWIR1', 'swir2': 'SWIR2'}
            available_indices = {'ndvi','ndwi','mndwi','savi','evi','evi2','msavi','gndvi',
                                 'ndmi','nbr','ndsi','ndbi','bsi','dvi','rvi','arvi','awei','ndre'}
            feature_names = feature_selection or [f for f, role in aliases.items() if B.get(role)] + ['ndvi','ndbi','mndwi']
            invalid_features = set(feature_names) - set(aliases) - available_indices
            if invalid_features:
                raise ValueError(f'Unsupported classification feature(s): {", ".join(sorted(invalid_features))}.')
            missing_features = [f for f in feature_names if f in aliases and not B.get(aliases[f])]
            if missing_features:
                raise ValueError(f'Features unavailable for {source}: {", ".join(missing_features)}.')
            derived = []
            output_bands = []
            for feature in feature_names:
                if feature in aliases:
                    out_band = B[aliases[feature]]
                    derived.append(col.select(out_band).rename(feature.upper()))
                else:
                    image, _, _ = self._spectral(col, B, feature.upper())
                    derived.append(image.rename(feature.upper()))
                output_bands.append(feature.upper())
            full = col
            for feature_image in derived:
                full = full.addBands(feature_image)
            bands = output_bands
            algo = (algorithm or 'random_forest').lower().replace('-', '_')
            palette_all = ['#d73027', '#FF0000', '#1a9850', '#FFD700', '#91cf60', '#0000FF', '#FF8C00', '#B39FE1']
            if algo in ('kmeans', 'k_means') or (n >= 7 and training_samples is None):
                clusterer = ee.Clusterer.wekaKMeans(n, 42).train(full.select(bands).sample(geom, 10, 2000, seed=42))
                classified = full.select(bands).cluster(clusterer).rename('lc').clip(geom)
                actual = 'K-Means (unsupervised — labels assigned low→high, not field-validated)'
                accuracy_info = {'Validation': 'Not applicable to unsupervised cluster IDs; supply labeled samples for supervised accuracy assessment.'}
            else:
                remaps = {
                    3: ([10,20,30,40,50,60,70,80,90,95,100],[1,1,1,1,2,0,0,0,1,1,1]),
                    4: ([10,20,30,40,50,60,70,80,90,95,100],[1,1,1,1,0,2,2,3,1,1,1]),
                    5: ([10,20,30,40,50,60,70,80,90,95,100],[2,4,4,3,1,0,0,0,4,2,0]),
                    6: ([10,20,30,40,50,60,70,80,90,95,100],[4,4,4,3,1,0,0,5,4,2,0]),
                }
                if training_samples is not None:
                    sample_features = ee.FeatureCollection(training_samples)
                    train = full.select(bands).sampleRegions(sample_features, [class_property], 10, geometries=True)
                    train = train.filter(ee.Filter.notNull(bands + [class_property]))
                else:
                    src_vals, dst_vals = remaps[n]
                    wc = ee.Image('ESA/WorldCover/v200/2021').select('Map').clip(geom)
                    lc = wc.remap(src_vals, dst_vals, 0).rename('lc')
                    pts = lc.stratifiedSample(80, 'lc', geom, 10, seed=42, geometries=True)
                    train = full.select(bands).sampleRegions(pts, ['lc'], 10, geometries=True)
                if balance_classes:
                    label_field = class_property if training_samples is not None else 'lc'
                    histogram = train.aggregate_histogram(label_field).getInfo() or {}
                    class_counts = {str(k): int(v) for k, v in histogram.items() if int(v) > 0}
                    if len(class_counts) < 2:
                        raise ValueError('Class balancing needs at least two populated classes in training samples.')
                    target_count = min(class_counts.values())
                    balanced = ee.FeatureCollection([])
                    for class_code in class_counts:
                        part = (train.filter(ee.Filter.eq(label_field, int(class_code)))
                                .randomColumn('balance_seed', 42).sort('balance_seed').limit(target_count))
                        balanced = balanced.merge(part)
                    train = balanced
                train_label = class_property if training_samples is not None else 'lc'
                if training_samples is not None:
                    train_set, test_set = train, ee.FeatureCollection([])
                else:
                    def assign_spatial_fold(feature):
                        xy = feature.geometry().centroid(1).coordinates()
                        gx = ee.Number(xy.get(0)).multiply(20).floor()
                        gy = ee.Number(xy.get(1)).multiply(20).floor()
                        fold = gx.add(gy.multiply(1000003)).abs().mod(5)
                        return feature.set('_spatial_fold', fold)
                    sample = train.map(assign_spatial_fold)
                    train_set = sample.filter(ee.Filter.neq('_spatial_fold', 0))
                    test_set = sample.filter(ee.Filter.eq('_spatial_fold', 0))
                clf, actual = self._supervised_classifier(algo, train_set, train_label, bands, model_config)
                # Imported validation features are held apart before fitting; otherwise
                # use a disjoint 30% WorldCover-labeled sample split and label it as such.
                accuracy_info = {}
                try:
                    if validation_samples is not None:
                        independent = full.select(bands).sampleRegions(
                            ee.FeatureCollection(validation_samples).filter(ee.Filter.disjoint(
                                leftField='.geo', rightValue=ee.FeatureCollection(training_samples).geometry().buffer(30))),
                            [class_property], 10, geometries=True)
                        independent = independent.filter(ee.Filter.notNull(bands + [class_property]))
                        validated = independent.classify(clf)
                        validation_kind = 'Independent imported reference samples'
                    else:
                        validated = test_set.classify(clf)
                        validation_kind = 'Disjoint WorldCover-derived holdout; not field-independent'
                    cm = validated.errorMatrix(train_label, 'classification')
                    matrix_info = cm.getInfo()
                    matrix = matrix_info.get('array') if isinstance(matrix_info, dict) else matrix_info
                    computed_metrics = classification_metrics(matrix)
                    per_class = {}
                    order = matrix_info.get('order', list(range(len(computed_metrics['classes'])))) if isinstance(matrix_info, dict) else list(range(len(computed_metrics['classes'])))
                    for i, metric in enumerate(computed_metrics['classes']):
                        code = int(order[i]) if i < len(order) else i
                        class_label = names_list[code] if 0 <= code < len(names_list) else str(code)
                        per_class[class_label] = {
                            "Producer's accuracy": round(metric['producer_accuracy'], 4) if metric['producer_accuracy'] is not None else None,
                            "User's accuracy": round(metric['user_accuracy'], 4) if metric['user_accuracy'] is not None else None,
                            'F1-score': round(metric['f1'], 4) if metric['f1'] is not None else None,
                            'Reference samples': metric['reference_n'],
                        }
                    accuracy_info = {
                        'Validation source': validation_kind + ('; ≥30 m from training geometries' if validation_samples is not None else ''),
                        'Overall accuracy': round(computed_metrics['overall_accuracy'], 4),
                        'Kappa': round(computed_metrics['kappa'], 4) if computed_metrics['kappa'] is not None else None,
                        "Producer's and user's accuracy + F1": per_class,
                        'Confusion matrix': matrix,
                    }
                except Exception:
                    accuracy_info = {'Validation': 'No valid independent reference sample matrix could be computed; accuracy not reported.'}
                if tune and algo in ('random_forest', 'rf'):
                    # Honest tuning: compare tree counts on the same holdout.
                    tried = {}
                    for trees in (50, 150, 300):
                        try:
                            c = ee.Classifier.smileRandomForest(trees).train(train_set, train_label, bands)
                            a = float(test_set.classify(c).errorMatrix(train_label, 'classification').accuracy().getInfo() or 0)
                            tried[trees] = round(a, 4)
                        except Exception:
                            continue
                    if tried:
                        best_trees = max(tried, key=tried.get)
                        accuracy_info['Tuning (trees→accuracy)'] = tried
                        accuracy_info['Best trees'] = best_trees
                        if best_trees != 150:
                            clf = ee.Classifier.smileRandomForest(best_trees).train(train_set, train_label, bands)
                            actual = f'Random Forest (tuned: {best_trees} trees)'
                classified = full.select(bands).classify(clf).rename('lc').clip(geom)
            tile = self._tile(classified, {'min': 0, 'max': n - 1, 'palette': palette_all[:n]})
            code_to_name = {i: names_list[i] for i in range(n)}
            areas = self._class_areas(classified, geom, 10, code_to_name)
            legend = [{'value': i, 'label': names_list[i], 'color': palette_all[i]} for i in range(n)]
            interp = f'{n}-class {actual} on {source} ({year}). Classes: {", ".join(names_list)}.'
            if n == 5 and not class_names:
                interp += ' Default schema (Bareland, Built-up, Vegetation, Cropland, Rangeland).'
            if algo in ('kmeans', 'k_means') or (n >= 7 and training_samples is None):
                interp += ' Unsupervised cluster IDs have no fixed land-cover meaning; no classification accuracy is reported.'
            else:
                interp += (' Imported training samples used.' if training_samples is not None else
                           ' Supervised labels and spatial holdout derive from ESA WorldCover 2021; this is not field-independent validation.')
            if accuracy_info.get('Overall accuracy') is not None:
                kappa_text = f'κ={accuracy_info["Kappa"]:.2f}' if isinstance(accuracy_info.get('Kappa'), (int, float)) else 'κ unavailable'
                interp += f' Validation accuracy {accuracy_info["Overall accuracy"]:.2%} ({kappa_text}).'
            stats_out = dict(areas)
            if accuracy_info.get('Overall accuracy') is not None:
                stats_out['Overall accuracy'] = accuracy_info['Overall accuracy']
                stats_out['Kappa'] = accuracy_info['Kappa']
                stats_out['Validation source'] = accuracy_info['Validation source']
                stats_out['Confusion matrix (rows=reference, columns=predicted)'] = json.dumps(accuracy_info['Confusion matrix'])
                for class_label, metrics in accuracy_info.get("Producer's and user's accuracy + F1", {}).items():
                    stats_out[f"{class_label} producer accuracy"] = metrics["Producer's accuracy"]
                    stats_out[f"{class_label} user accuracy"] = metrics["User's accuracy"]
                    stats_out[f'{class_label} F1-score'] = metrics['F1-score']
            uncertainty_tile = None
            if algo in ('random_forest', 'rf'):
                try:
                    probabilities = full.select(bands).classify(clf.setOutputMode('MULTIPROBABILITY'))
                    confidence = probabilities.arrayReduce(ee.Reducer.max(), [0]).arrayGet([0]).rename('confidence')
                    uncertainty = ee.Image(1).subtract(confidence).rename('uncertainty').clip(geom)
                    uncertainty_stats = self._reduce(uncertainty, geom, 10).get('uncertainty')
                    if uncertainty_stats is not None:
                        stats_out['Mean RF classification uncertainty (1 - max class probability)'] = round(float(uncertainty_stats), 4)
                    uncertainty_tile = self._tile(uncertainty, {'min': 0, 'max': 1, 'palette': ['#1a9850', '#ffffbf', '#d7191c']})
                    self._export_image = classified
                    self._export_vis = {'min': 0, 'max': n - 1, 'palette': palette_all[:n]}
                except Exception:
                    uncertainty_tile = None
                stats_out['Uncertainty'] = ('RF probability proxy: per-pixel uncertainty = 1 − maximum class probability; not calibrated.'
                                            if uncertainty_tile else 'RF probability uncertainty unavailable for this response.')
            elif algo not in ('kmeans', 'k_means'):
                stats_out['Uncertainty'] = f'Not calculated for {actual}; model has no calibrated per-class probability output in this workflow.'
            return {'type': 'LandCover', 'label': f'Land Cover {n}-class ({year})', 'stats': stats_out,
                    'tileUrl': tile, 'interpretation': interp, 'legend': legend, 'scale': 10,
                    'accuracy': accuracy_info, 'featureBands': bands,
                    'uncertaintyTileUrl': uncertainty_tile,
                    'modelConfig': model_config or {'trees': 150},
                    'class balancing': 'Random undersampling of training rows only' if balance_classes else 'No extra balancing; default WorldCover samples are stratified',
                    'visParams': {'min': 0, 'max': n - 1, 'palette': palette_all[:n]}}

        elif analysis == 'vegetation':
            ndvi_img = col.normalizedDifference(['SR_B5','SR_B4'] if 'landsat' in source else ['B8','B4']).rename('NDVI')
            palette = ['#d73027','#fc8d59','#fee08b','#91cf60','#1a9850','#006837']
            levels = [0, 0.1, 0.2, 0.3, 0.5, 0.7]
            n = min(num_classes, len(levels) - 1)  # NDVI thresholds support up to 5 bins honestly
            veg = ee.Image(0)
            for i in range(n):
                veg = veg.where(ndvi_img.gte(levels[i]).And(ndvi_img.lt(levels[i+1] if i+1<len(levels) else 1)), i+1)
            veg = veg.clip(geom)
            tile = self._tile(veg,{'min':0,'max':n,'palette':palette[:n+1]})
            s = self._reduce(ndvi_img,geom)
            m = s.get('NDVI',0)
            if class_names and len(class_names) == num_classes:
                bin_labels = ['Bare'] + list(class_names[:n])
            elif class_names and len(class_names) == n:
                bin_labels = ['Bare'] + list(class_names)
            else:
                bin_labels = (['Bare','Very Low','Low','Moderate','High','Dense'])[:n+1]
            legend = [{'value': i, 'label': bin_labels[i] if i < len(bin_labels) else f'Class {i}',
                       'color': palette[i] if i < len(palette) else '#888888'} for i in range(n+1)]
            note = '' if n == num_classes else f' Note: {num_classes} classes requested but NDVI thresholds support {n} bins.'
            return {'type':'Vegetation','label':f'Vegetation ({year})','stats':{'Mean NDVI':round(m,4),'Classes':n},
                    'tileUrl':tile,
                    'interpretation':(m>0.5 and 'Predominantly dense vegetation' or m>0.3 and 'Mixed vegetation' or 'Sparse vegetation') + '.' + note,
                    'legend': legend, 'scale': 10}

        elif analysis == 'buildings':
            bld = ee.FeatureCollection('GOOGLE/Research/open-buildings/v3/polygons').filterBounds(geom).filter(ee.Filter.gte('confidence',0.6))
            count = bld.size().getInfo()
            pt = bld.map(lambda f: f.centroid())
            bi = ee.Image().float().paint(pt,1).clip(geom)
            tile = self._tile(bi,{'min':0,'max':1,'palette':['transparent','#FF0000']})
            return {'type':'Buildings','label':'Building Density','stats':{'Count':str(count)},'tileUrl':tile,'interpretation':f'{count} buildings detected (Open Buildings, confidence ≥ 0.6)',
                    'legend': [{'value': 1, 'label': 'Building presence', 'color': '#FF0000'}], 'scale': 10}

        elif analysis == 'worldcover_v200':
            wc = ee.Image('ESA/WorldCover/v200/2021').select(0).rename('lc').clip(geom)
            tile = self._tile(wc, {'min': 10, 'max': 100, 'palette': [
                '#006400', '#b2dfa3', '#ffbb22', '#ffff4c', '#f096ff', '#fa0000',
                '#b4b4b4', '#f0f0f0', '#0064c8', '#0096a0', '#00cf75', '#fae6a0']})
            stats = self._class_areas(wc, geom, 10, {
                10: 'Trees', 20: 'Shrub', 30: 'Grass', 40: 'Cropland', 50: 'Built-up',
                60: 'Bare', 70: 'Snow', 80: 'Water', 90: 'Wetlands', 95: 'Mangroves', 100: 'Moss'})
            top = max(stats, key=lambda k: float(str(stats[k]).split()[0]) if str(stats[k]).split() else -1) if stats else '—'
            wc_names = {10: 'Trees', 20: 'Shrub', 30: 'Grass', 40: 'Cropland', 50: 'Built-up',
                        60: 'Bare', 70: 'Snow', 80: 'Water', 90: 'Wetlands', 95: 'Mangroves', 100: 'Moss'}
            wc_pal = ['#006400', '#b2dfa3', '#ffbb22', '#ffff4c', '#f096ff', '#fa0000',
                      '#b4b4b4', '#f0f0f0', '#0064c8', '#0096a0', '#00cf75', '#fae6a0']
            return {'type': 'WorldCover', 'label': 'ESA WorldCover v200 (10m, 2021)',
                    'stats': stats or {'Note': 'No data in AOI'},
                    'tileUrl': tile, 'interpretation': f'Dominant: {top}',
                    'legend': [{'value': c, 'label': wc_names[c], 'color': wc_pal[i]} for i, c in enumerate(wc_names)],
                    'scale': 10}

        elif analysis == 'modis_lc':
            y = min(max(year, 2001), 2023)
            coll = ee.ImageCollection('MODIS/061/MCD12Q1').filter(
                ee.Filter.calendarRange(y, y, 'year')).select(0)
            img = coll.mode().rename('lc').clip(geom)
            tile = self._tile(img, {'min': 1, 'max': 17, 'palette': [
                '#1c6917', '#2d9b2a', '#7ec87e', '#a9c490', '#d6e8be', '#e8d39a',
                '#d8b56a', '#c49a52', '#a67c3a', '#8c6230', '#b5b5b5', '#dcdcdc',
                '#ff0000', '#0000ff', '#ffffff', '#00ffff', '#808080']})
            stats = self._class_areas(img, geom, 500, {
                1: 'Evergreen Needle', 2: 'Evergreen Broad', 3: 'Deciduous Needle',
                4: 'Deciduous Broad', 5: 'Mixed Forest', 6: 'Closed Shrub',
                7: 'Open Shrub', 8: 'Woody Savanna', 9: 'Savanna', 10: 'Grass',
                11: 'Wetlands', 12: 'Cropland', 13: 'Urban', 14: 'Crop Mosaic',
                15: 'Snow/Ice', 16: 'Barren', 17: 'Water'})
            igbp = {1: 'Evergreen Needle', 2: 'Evergreen Broad', 3: 'Deciduous Needle',
                    4: 'Deciduous Broad', 5: 'Mixed Forest', 6: 'Closed Shrub', 7: 'Open Shrub',
                    8: 'Woody Savanna', 9: 'Savanna', 10: 'Grass', 11: 'Wetlands', 12: 'Cropland',
                    13: 'Urban', 14: 'Crop Mosaic', 15: 'Snow/Ice', 16: 'Barren', 17: 'Water'}
            igbp_pal = ['#1c6917', '#2d9b2a', '#7ec87e', '#a9c490', '#d6e8be', '#e8d39a', '#d8b56a',
                        '#c49a52', '#a67c3a', '#8c6230', '#b5b5b5', '#dcdcdc', '#ff0000', '#0000ff',
                        '#ffffff', '#00ffff', '#808080']
            return {'type': 'MODIS_LC', 'label': f'MODIS MCD12Q1 ({y}, 500m)',
                    'stats': stats or {'Note': 'No data in AOI'},
                    'tileUrl': tile, 'interpretation': f'IGBP classes for {y}',
                    'legend': [{'value': c, 'label': igbp[c], 'color': igbp_pal[i]} for i, c in enumerate(igbp)],
                    'scale': 500}

        elif analysis == 'modis_cmg':
            y = min(max(year, 2001), 2023)
            coll = ee.ImageCollection('MODIS/061/MCD12C1').filter(
                ee.Filter.calendarRange(y, y, 'year')).select(0)
            img = coll.mode().rename('lc').clip(geom)
            tile = self._tile(img, {'min': 0, 'max': 17, 'palette': [
                '#000000', '#1c6917', '#2d9b2a', '#7ec87e', '#a9c490', '#d6e8be',
                '#e8d39a', '#d8b56a', '#c49a52', '#a67c3a', '#8c6230', '#b5b5b5',
                '#dcdcdc', '#ff0000', '#0000ff', '#ffffff', '#00ffff', '#808080']})
            stats = self._class_areas(img, geom, 5600, None)
            cmg_names = {0: 'Water', 1: 'Evergreen Needle', 2: 'Evergreen Broad', 3: 'Deciduous Needle',
                         4: 'Deciduous Broad', 5: 'Mixed Forest', 6: 'Closed Shrub', 7: 'Open Shrub',
                         8: 'Woody Savanna', 9: 'Savanna', 10: 'Grass', 11: 'Wetlands', 12: 'Cropland',
                         13: 'Urban', 14: 'Crop Mosaic', 15: 'Snow/Ice', 16: 'Barren', 17: 'Water'}
            cmg_pal = ['#000000', '#1c6917', '#2d9b2a', '#7ec87e', '#a9c490', '#d6e8be', '#e8d39a',
                       '#d8b56a', '#c49a52', '#a67c3a', '#8c6230', '#b5b5b5', '#dcdcdc', '#ff0000',
                       '#0000ff', '#ffffff', '#00ffff', '#808080']
            cmg_legend = [{'value': c, 'label': cmg_names[c], 'color': cmg_pal[i]} for i, c in enumerate(cmg_names)]
            return {'type': 'MODIS_CMG', 'label': f'MODIS MCD12C1 CMG ({y})',
                    'stats': stats or {'Note': 'No data in AOI'},
                    'tileUrl': tile, 'interpretation': f'Climate-Modeling-Grid classes for {y}',
                    'legend': cmg_legend, 'scale': 5600}

        elif analysis == 'copernicus_lc':
            y = min(max(year, 2015), 2019)
            coll = ee.ImageCollection('COPERNICUS/Landcover/100m/Proba-V-C3/Global').filter(
                ee.Filter.calendarRange(y, y, 'year')).select('discrete_classification')
            img = coll.mode().rename('lc').clip(geom)
            tile = self._tile(img, {'min': 0, 'max': 200, 'palette': [
                '#000000', '#ff0000', '#ffff00', '#00ff00', '#0000ff', '#ff00ff', '#00ffff']})
            stats = self._class_areas(img, geom, 100, {
                0: 'Unknown', 20: 'Shrubs', 30: 'Herbaceous', 40: 'Cultivated',
                50: 'Urban', 60: 'Bare', 70: 'Snow', 80: 'Water', 90: 'Wetlands',
                100: 'Moss/Lichen', 111: 'Closed Forest', 112: 'Open Forest'})
            cop_names = {0: 'Unknown', 20: 'Shrubs', 30: 'Herbaceous', 40: 'Cultivated', 50: 'Urban',
                         60: 'Bare', 70: 'Snow', 80: 'Water', 90: 'Wetlands', 100: 'Moss/Lichen',
                         111: 'Closed Forest', 112: 'Open Forest'}
            cop_pal = ['#282828', '#ffbb22', '#ffff4c', '#f096ff', '#fa0000', '#b4b4b4', '#f0f0f0',
                       '#0032c8', '#009900', '#00cf75', '#006400', '#397D49']
            return {'type': 'Copernicus_LC', 'label': f'Copernicus GLCS ({y}, 100m)',
                    'stats': stats or {'Note': 'No data in AOI'},
                    'tileUrl': tile, 'interpretation': f'Global land cover {y}',
                    'legend': [{'value': c, 'label': cop_names[c], 'color': cop_pal[i % len(cop_pal)]} for i, c in enumerate(cop_names)],
                    'scale': 100}

        elif analysis == 'glc_fcs30':
            y = min(max(year, 1985), 2022)
            # Annual 30m product; select first band defensively (band names vary by version).
            coll = ee.ImageCollection('CAS/IGSNRR/GLC_FCS30D/annual').filter(
                ee.Filter.calendarRange(y, y, 'year')).select(0)
            img = coll.mode().rename('lc').clip(geom)
            tile = self._tile(img, {'min': 10, 'max': 250, 'palette': [
                '#1c6917', '#d8b56a', '#e8d39a', '#ff0000', '#0000ff', '#b5b5b5', '#ffffff']})
            stats = self._class_areas(img, geom, 30, {
                10: 'Rainfed Cropland', 11: 'Herbaceous Cover', 12: 'Tree/Shrub Cover',
                20: 'Irrigated Cropland', 51: 'Open Evergreen', 52: 'Closed Evergreen',
                61: 'Open Deciduous', 62: 'Closed Deciduous', 81: 'Open Mixed',
                82: 'Closed Mixed', 120: 'Shrubland', 130: 'Grassland',
                140: 'Lichens/Mosses', 150: 'Sparse Veg', 190: 'Built-up',
                200: 'Bare', 210: 'Water', 220: 'Snow/Ice', 250: 'Filled'})
            glc_codes = [10, 11, 12, 20, 51, 52, 61, 62, 81, 82, 120, 130, 140, 150, 190, 200, 210, 220, 250]
            glc_labels = ['Rainfed Cropland', 'Herbaceous Cover', 'Tree/Shrub Cover', 'Irrigated Cropland',
                          'Open Evergreen', 'Closed Evergreen', 'Open Deciduous', 'Closed Deciduous', 'Open Mixed',
                          'Closed Mixed', 'Shrubland', 'Grassland', 'Lichens/Mosses', 'Sparse Veg', 'Built-up',
                          'Bare', 'Water', 'Snow/Ice', 'Filled']
            glc_pal = ['#ffff00', '#ffbb22', '#006400', '#f096ff', '#1c6917', '#004d00', '#7ec87e', '#2d9b2a',
                       '#a9c490', '#397D49', '#d8b56a', '#dade48', '#00cf75', '#b5b5b5', '#ff0000', '#dcdcdc',
                       '#0000ff', '#ffffff', '#282828']
            return {'type': 'GLC_FCS30D', 'label': f'GLC_FCS30D ({y}, 30m)',
                    'stats': stats or {'Note': 'No data in AOI'},
                    'tileUrl': tile, 'interpretation': f'35-class land cover {y}',
                    'legend': [{'value': glc_codes[i], 'label': glc_labels[i], 'color': glc_pal[i]} for i in range(len(glc_codes))],
                    'scale': 30}

        elif analysis == 'nlcd':
            img = ee.Image('USGS/NLCD_RELEASES/2021_REL/NLCD').select('landcover').rename('lc').clip(geom)
            tile = self._tile(img, {'min': 11, 'max': 95, 'palette': [
                '#5475a8', '#d1def8', '#dec5c5', '#d99282', '#eb0000', '#ab0000',
                '#b3ac9f', '#68ab5f', '#1c5f2c', '#b5c58f', '#ccb879', '#dfdfc2',
                '#dcd939', '#ab6c28', '#b8d9eb', '#6c9fb8']})
            stats = self._class_areas(img, geom, 30, {
                11: 'Open Water', 12: 'Perennial Ice', 21: 'Developed Open',
                22: 'Developed Low', 23: 'Developed Med', 24: 'Developed High',
                31: 'Barren', 41: 'Deciduous Forest', 42: 'Evergreen Forest',
                43: 'Mixed Forest', 52: 'Shrub', 71: 'Grassland', 81: 'Pasture',
                82: 'Crops', 90: 'Woody Wetlands', 95: 'Herbaceous Wetlands'})
            nlcd_codes = [11, 12, 21, 22, 23, 24, 31, 41, 42, 43, 52, 71, 81, 82, 90, 95]
            nlcd_labels = ['Open Water', 'Perennial Ice', 'Developed Open', 'Developed Low', 'Developed Med',
                           'Developed High', 'Barren', 'Deciduous Forest', 'Evergreen Forest', 'Mixed Forest',
                           'Shrub', 'Grassland', 'Pasture', 'Crops', 'Woody Wetlands', 'Herbaceous Wetlands']
            nlcd_pal = ['#5475a8', '#d1def8', '#dec5c5', '#d99282', '#eb0000', '#ab0000', '#b3ac9f', '#68ab5f',
                        '#1c5f2c', '#b5c58f', '#ccb879', '#dfdfc2', '#dcd939', '#ab6c28', '#b8d9eb', '#6c9fb8']
            nlcd_legend = [{'value': nlcd_codes[i], 'label': nlcd_labels[i], 'color': nlcd_pal[i]} for i in range(len(nlcd_codes))]
            if not stats:
                return {'type': 'NLCD', 'label': 'NLCD 2021 (USA, 30m)',
                        'stats': {'Note': 'No NLCD coverage — USA (CONUS) only'},
                        'tileUrl': tile, 'interpretation': 'AOI outside NLCD coverage',
                        'legend': nlcd_legend, 'scale': 30}
            return {'type': 'NLCD', 'label': 'NLCD 2021 (USA, 30m)',
                    'stats': stats, 'tileUrl': tile, 'interpretation': 'NLCD land cover 2021',
                    'legend': nlcd_legend, 'scale': 30}

        elif analysis == 'corine':
            img = ee.Image('COPERNICUS/CORINE/V20/100m/2018').select('landcover').rename('lc').clip(geom)
            tile = self._tile(img, {'min': 111, 'max': 523, 'palette': [
                '#e6004d', '#ff0000', '#cc4df2', '#cc0000', '#e6cccc', '#e6cce6',
                '#a600cc', '#a64d00', '#ff4dff', '#ffe6ff', '#ffffa8', '#ffff00',
                '#e6e64d', '#e68000', '#f2cca8', '#e6a600', '#a6a600', '#a6ff00',
                '#4dff00', '#ccf24d', '#a6e64d', '#00cc4d', '#4da600', '#ccffcc',
                '#66a600', '#a800e6', '#4d0073', '#0073e6', '#e6e6e6']})
            stats = self._class_areas(img, geom, 100, None)
            corine_legend = [{'value': 111, 'label': 'Urban fabric', 'color': '#e6004d'},
                             {'value': 121, 'label': 'Industrial', 'color': '#ff0000'},
                             {'value': 311, 'label': 'Forest', 'color': '#80ff00'},
                             {'value': 211, 'label': 'Agriculture', 'color': '#ffff00'},
                             {'value': 411, 'label': 'Wetland', 'color': '#ccffcc'},
                             {'value': 512, 'label': 'Water', 'color': '#000080'}]
            if not stats:
                return {'type': 'CORINE', 'label': 'CORINE 2018 (EU, 100m)',
                        'stats': {'Note': 'No CORINE coverage — Europe only'},
                        'tileUrl': tile, 'interpretation': 'AOI outside CORINE coverage',
                        'legend': corine_legend, 'scale': 100}
            return {'type': 'CORINE', 'label': 'CORINE 2018 (EU, 100m)',
                    'stats': stats, 'tileUrl': tile, 'interpretation': 'CORINE land cover 2018 (detailed codes in statistics)',
                    'legend': corine_legend, 'scale': 100}

        elif analysis == 'flood':
            dem = ee.Image('USGS/SRTMGL1_003').clip(geom)
            slope_img = ee.Terrain.slope(dem)
            y = min(max(year, 1981), 2026)
            rain = (ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterBounds(geom)
                    .filter(ee.Filter.calendarRange(y, y, 'year')).select('precipitation').sum().rename('rain_mm'))
            upa = ee.Image('MERIT/Hydro/v1_0_1').select('upa').rename('upa_km2')
            # Transparent exploratory equal-weight index: low elevation, flat
            # slope, higher annual rainfall and larger upstream contributing
            # area. These are screening transforms, not calibrated probabilities.
            factor_low_elev = ee.Image(1).subtract(dem.divide(100).clamp(0, 1))
            factor_flat = ee.Image(1).subtract(slope_img.divide(30).clamp(0, 1))
            factor_rain = rain.divide(2000).clamp(0, 1)
            factor_drain = upa.add(1).log().divide(math.log(1001)).clamp(0, 1)
            risk_score = (factor_low_elev.add(factor_flat).add(factor_rain).add(factor_drain)
                          .divide(4).rename('susceptibility').clip(geom))
            risk = ee.Image(1).where(risk_score.gte(0.25), 2).where(risk_score.gte(0.5), 3).where(risk_score.gte(0.75), 4).rename('risk').clip(geom)
            tile = self._tile(risk, {'min': 1, 'max': 4, 'palette': ['#1a9850', '#ffff00', '#ff9800', '#ff0000']})
            stats = self._class_areas(risk, geom, 90, {
                1: 'Low', 2: 'Moderate', 3: 'High', 4: 'Very high'})
            rain_mean = self._stats4(rain, geom, 5000, 'rain_mm').get('Mean')
            upa_mean = self._stats4(upa, geom, 90, 'upa_km2').get('Mean')
            high = stats.get('Very high', '0 ha')
            return {'type': 'Flood', 'label': f'Flood Susceptibility Screening ({y})',
                    'stats': {**stats, 'Mean annual CHIRPS rainfall': f'{rain_mean} mm',
                              'Mean MERIT upstream area': f'{upa_mean} km²',
                              'Rainfall period': 'Year-to-date (current calendar year incomplete)' if y == datetime.now().year else 'Calendar-year accumulation',
                              'Model': 'Exploratory equal-weight index; SRTM + CHIRPS + MERIT Hydro'},
                    'tileUrl': tile,
                    'interpretation': (f'Flood susceptibility screening using elevation, slope, CHIRPS annual rainfall ({y}) and MERIT upstream area. Very-high class area: {high}. '
                                       'Equal weights and monotonic 0–1 transforms are exploratory, not locally calibrated probabilities or flood risk. '
                                       'This is not an observed flood extent or hydraulic flood-depth model — '
                                       'see Flood Mapping (Sentinel-1) for observed water extent.'),
                    'legend': [{'value': 1, 'label': 'Low', 'color': '#1a9850'},
                               {'value': 2, 'label': 'Moderate', 'color': '#ffff00'},
                               {'value': 3, 'label': 'High', 'color': '#ff9800'},
                               {'value': 4, 'label': 'Very high', 'color': '#ff0000'}], 'scale': 90}

        elif analysis == 'flood_mapping':
            # Sentinel-1 VH open-water screening; a second year enables an
            # observed before/after water-change map (not a flood-depth model).
            def _s1_water(yr):
                collection = (ee.ImageCollection('COPERNICUS/S1_GRD')
                    .filterBounds(geom).filterDate(f'{yr}-01-01', f'{yr}-12-31')
                    .filter(ee.Filter.eq('instrumentMode', 'IW'))
                    .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VH'))
                    .select('VH'))
                count = collection.size().getInfo()
                if not count:
                    raise ValueError(f'No Sentinel-1 IW/VH scenes overlap the AOI in {yr}.')
                return collection.median().clip(geom).lt(-18).rename('water'), count
            after, count_after = _s1_water(year)
            if year2 != year and (mode or '').lower() in ('compare', 'change', 'before_after'):
                before, count_before = _s1_water(year2)
                transition = before.toInt().multiply(2).add(after.toInt()).rename('water_change')
                legend = [{'value': 0, 'label': 'Persistent dry', 'color': '#dedede'},
                          {'value': 1, 'label': 'New water (possible flood/inundation)', 'color': '#2674d9'},
                          {'value': 2, 'label': 'Water receded', 'color': '#f4a340'},
                          {'value': 3, 'label': 'Persistent water', 'color': '#08306b'}]
                tile = self._tile(transition, {'min': 0, 'max': 3, 'palette': [x['color'] for x in legend]})
                stats = self._class_areas(transition, geom, 10, {0: 'Persistent dry', 1: 'New water', 2: 'Water receded', 3: 'Persistent water'})
                affected = self._class_area_m2(after.And(before.Not()), geom, 10)
                stats.update({'Before scenes': count_before, 'After scenes': count_after,
                              'New water area': f'{affected / 1e4:.2f} ha / {affected / 1e6:.4f} km²'})
                return {'type': 'FloodMapping', 'label': f'Sentinel-1 Water Change ({year2} → {year})',
                    'stats': stats, 'tileUrl': tile,
                    'interpretation': (f'Observed open-water screening difference using Sentinel-1 VH < −18 dB; '
                        f'new-water area {affected / 1e4:.2f} ha. New water can reflect flooding or seasonal/permanent-water change; '
                        'before/after scenes are annual medians. SAR may miss water under canopy or urban structures.'),
                    'legend': legend, 'scale': 10}
            tile = self._tile(after.selfMask(), {'min': 0, 'max': 1, 'palette': ['#0000CD']})
            stats = self._class_areas(after, geom, 10, {0: 'Non-water', 1: 'Water'})
            stats['Sentinel-1 scenes'] = count_after
            flooded = stats.get('Water', '0 ha')
            return {'type': 'FloodMapping', 'label': f'Sentinel-1 Water Extent ({year})',
                    'stats': stats or {'Note': 'No water detected'}, 'tileUrl': tile,
                    'interpretation': (f'Observed open-water extent from Sentinel-1 VH (< −18 dB) for {year}: {flooded}. '
                        'This threshold is a screening method and can include permanent water; SAR may miss water under canopy/buildings.'),
                    'legend': [{'value': 0, 'label': 'Non-water', 'color': '#e0e0e0'},
                               {'value': 1, 'label': 'Water', 'color': '#0000CD'}], 'scale': 10}

        elif analysis == 'lst':
            y = min(max(year, 2000), 2026)
            lst = (ee.ImageCollection('MODIS/061/MOD11A1').filterBounds(geom)
                   .filter(ee.Filter.calendarRange(y, y, 'year'))
                   .select('LST_Day_1km').median().multiply(0.02).subtract(273.15).rename('lst').clip(geom))
            tile = self._tile(lst, {'min': 15, 'max': 45, 'palette': ['#0000ff', '#00ffff', '#ffff00', '#ff9800', '#ff0000']})
            r = lst.reduceRegion(reducer=ee.Reducer.mean().combine(ee.Reducer.minMax(), '', True),
                                 geometry=geom, scale=1000, maxPixels=int(1e9), bestEffort=True).getInfo()
            mean = r.get('lst_mean', 0) or 0
            hot = self._class_areas(lst.gt(35).rename('h'), geom, 1000, {0: 'Normal (≤35°C)', 1: 'Hotspot (>35°C)'})
            return {'type': 'LST', 'label': f'Land Surface Temperature ({y})',
                    'stats': {'Mean': f'{mean:.1f}°C',
                              'Min': f'{(r.get("lst_min", 0) or 0):.1f}°C',
                              'Max': f'{(r.get("lst_max", 0) or 0):.1f}°C', **hot},
                    'tileUrl': tile,
                    'interpretation': f'Mean daytime LST {mean:.1f}°C (MODIS 1km, {y}). Hotspot = >35°C.',
                    'legend': {'type': 'continuous', 'min': 15, 'max': 45, 'unit': '°C'}, 'scale': 1000}

        elif analysis == 'rainfall':
            # 1985–2026 supported; CHIRPS latency noted when clamped.
            y = min(max(year, 1981), 2026)
            note = '' if y == year else f' (year clamped to CHIRPS range, used {y})'
            chirps = (ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterBounds(geom)
                      .filter(ee.Filter.calendarRange(y, y, 'year')).select('precipitation'))
            if (period or 'annual') == 'monthly' and month:
                rain = chirps.filter(ee.Filter.calendarRange(month, month, 'month')).sum().rename('rain')
                label, unit = f'Rainfall {y}-{month:02d} (monthly)', 'mm/month'
            elif (period or 'annual') == 'monthly':
                # Monthly climatology: 12 values, one EE aggregation -> chart + annual map.
                seq = ee.List([ee.Dictionary({'month': m, 'value': chirps.filter(
                    ee.Filter.calendarRange(m, m, 'month')).sum().reduceRegion(
                        ee.Reducer.mean(), geom, 5000, maxPixels=int(1e9), bestEffort=True).get('precipitation')})
                    for m in range(1, 13)])
                raw_m = seq.getInfo()
                chart, mstats = [], {}
                for item in raw_m:
                    try:
                        v = float(item.get('value')) if item.get('value') is not None else None
                    except (TypeError, ValueError):
                        v = None
                    if v is not None:
                        chart.append({'year': f'{y}-{int(item.get("month")):02d}', 'value': round(v, 1)})
                        mstats[f'M{int(item.get("month")):02d}'] = f'{v:.0f} mm'
                rain = chirps.sum().rename('rain')
                label, unit = f'Rainfall ({y}, monthly climatology + annual map)', 'mm'
                rain = rain.clip(geom)
                tile = self._tile(rain, {'min': 0, 'max': 2000, 'palette': ['#ffffff', '#00ffff', '#0000ff', '#ff00ff']})
                return {'type': 'Rainfall', 'label': label, 'stats': mstats,
                        'chartData': chart, 'tileUrl': tile,
                        'interpretation': f'CHIRPS {y}: monthly means + annual-total map.',
                        'legend': {'type': 'continuous', 'min': 0, 'max': 2000, 'unit': 'mm/yr'}, 'scale': 5000}
            elif (period or 'annual') == 'seasonal' and months:
                ms = sorted(months)
                rain = ee.ImageCollection([chirps.filter(ee.Filter.calendarRange(m, m, 'month')).sum() for m in ms]).sum().rename('rain')
                label, unit = f'Rainfall {y} season {season or ms} (months {ms})', 'mm/season'
            else:
                rain = chirps.sum().rename('rain')
                label, unit = f'Rainfall ({y}, annual)', 'mm/yr'
            rain = rain.clip(geom)
            tile = self._tile(rain, {'min': 0, 'max': 2000 if 'annual' in label else 500,
                                     'palette': ['#ffffff', '#00ffff', '#0000ff', '#ff00ff']})
            r = rain.reduceRegion(reducer=ee.Reducer.mean().combine(ee.Reducer.minMax(), '', True),
                                  geometry=geom, scale=5000, maxPixels=int(1e9), bestEffort=True).getInfo()
            mean = r.get('rain_mean', 0) or 0
            return {'type': 'Rainfall', 'label': label,
                    'stats': {'Mean': f'{mean:.0f} mm',
                              'Min': f'{(r.get("rain_min", 0) or 0):.0f} mm',
                              'Max': f'{(r.get("rain_max", 0) or 0):.0f} mm'},
                    'tileUrl': tile,
                    'interpretation': f'CHIRPS {label}: mean {mean:.0f} mm over AOI.{note}',
                    'legend': {'type': 'continuous', 'min': 0, 'max': 2000, 'unit': unit}, 'scale': 5000}

        elif analysis == 'erosion':
            # RUSLE-lite proxy: A = R * K * LS * C * P. Factors exposed, honest proxy.
            y = min(max(year, 1981), 2025)
            rain = (ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterBounds(geom)
                    .filter(ee.Filter.calendarRange(y, y, 'year'))
                    .select('precipitation').sum().rename('rain').clip(geom))
            dem = ee.Image('USGS/SRTMGL1_003').clip(geom)
            slope_img = ee.Terrain.slope(dem)
            ndvi_img = col.normalizedDifference(['SR_B5', 'SR_B4'] if 'landsat' in source else ['B8', 'B4']).rename('NDVI')
            R = rain.multiply(0.5).rename('R')
            K = ee.Image.constant(0.03).rename('K')
            LS = slope_img.divide(9).pow(1.4).add(0.4).rename('LS')
            C = ee.Image(1).subtract(ndvi_img.clamp(-1, 1)).multiply(0.5).clamp(0.05, 1).rename('C')
            soil_loss = R.multiply(K).multiply(LS).multiply(C).rename('loss')
            cls = ee.Image(0).where(soil_loss.gte(5).And(soil_loss.lt(15)), 1).where(soil_loss.gte(15), 2).rename('cls').clip(geom)
            tile = self._tile(cls, {'min': 0, 'max': 2, 'palette': ['#1a9850', '#FFD700', '#FF0000']})
            stats = self._class_areas(cls, geom, 30, {0: 'Slight (<5)', 1: 'Moderate (5-15)', 2: 'Severe (>15)'})
            m = self._reduce(soil_loss, geom, 30).get('loss', 0)
            return {'type': 'Erosion', 'label': f'Soil Loss RUSLE-lite ({y})',
                    'stats': {**stats, 'Mean loss': f'{m:.1f} t/ha/yr'},
                    'tileUrl': tile,
                    'interpretation': (f'RUSLE-lite proxy A=R·K·LS·C·P: R=0.5×CHIRPS annual, K=0.03 constant, '
                                       f'LS from SRTM slope, C from NDVI, P=1. Mean {m:.1f} t/ha/yr. '
                                       'Screening proxy only — calibrate K/C/P locally before decisions.'),
                    'legend': [{'value': 0, 'label': 'Slight (<5 t/ha/yr)', 'color': '#1a9850'},
                               {'value': 1, 'label': 'Moderate (5-15)', 'color': '#FFD700'},
                               {'value': 2, 'label': 'Severe (>15)', 'color': '#FF0000'}],
                    'scale': 30}

        elif analysis == 'drought':
            # NDVI anomaly vs 5-yr baseline + CHIRPS anomaly context (2 EE requests total).
            base_years = list(range(max(2000, year - 5), year))
            if not base_years:
                base_years = [max(2000, year - 1)]
            def _ndvi_of(yr):
                s, e = f'{yr}-01-01', f'{yr}-12-31'
                c = self._collection(geom, s, e, source, max_cloud)
                return c.normalizedDifference(['SR_B5', 'SR_B4'] if 'landsat' in source else ['B8', 'B4']).rename('NDVI')
            cur = _ndvi_of(year)
            base = _ndvi_of(base_years[0])
            for by in base_years[1:]:
                base = base.addBands(_ndvi_of(by))
            baseline = base.reduce(ee.Reducer.median()).rename('NDVI')
            ind = (indicator or 'anomaly').lower()
            if ind == 'vci':
                bmin = base.reduce(ee.Reducer.min()).rename('mn')
                bmax = base.reduce(ee.Reducer.max()).rename('mx')
                vci = cur.subtract(bmin).divide(bmax.subtract(bmin).add(0.001)).multiply(100).rename('vci').clip(geom)
                tile = self._tile(vci, {'min': 0, 'max': 100, 'palette': ['#FF0000', '#FFFF00', '#1a9850']})
                stats = self._class_areas(
                    ee.Image(0).where(vci.gte(0).And(vci.lt(20)), 0).where(vci.gte(20).And(vci.lt(35)), 1)
                    .where(vci.gte(35).And(vci.lt(50)), 2).where(vci.gte(50).And(vci.lt(65)), 3)
                    .where(vci.gte(65), 4).rename('v').clip(geom), geom, 10,
                    {0: 'Extreme (<20)', 1: 'Severe (20-35)', 2: 'Moderate (35-50)', 3: 'Mild (50-65)', 4: 'Normal (>65)'})
                m = self._reduce(vci, geom).get('vci', 0)
                return {'type': 'VCI', 'label': f'Vegetation Condition Index ({year})',
                        'stats': {**stats, 'Mean VCI': round(m, 1)},
                        'tileUrl': tile,
                        'interpretation': f'VCI=(NDVI−NDVImin)/(NDVImax−NDVImin)×100 vs {base_years[0]}–{year - 1}. Mean {m:.0f}. <35 = drought stress.',
                        'legend': [{'value': i, 'label': l, 'color': c} for i, (l, c) in enumerate(
                            [('Extreme (<20)', '#FF0000'), ('Severe (20-35)', '#FF9800'), ('Moderate (35-50)', '#FFFF00'),
                             ('Mild (50-65)', '#91cf60'), ('Normal (>65)', '#1a9850')])],
                        'scale': 10}
            if ind in ('tci', 'vhi'):
                def _lst_of(yr):
                    return (ee.ImageCollection('MODIS/061/MOD11A1').filterBounds(geom)
                            .filter(ee.Filter.calendarRange(yr, yr, 'year'))
                            .select('LST_Day_1km').median().multiply(0.02).subtract(273.15))
                lcur, lbase = _lst_of(year), _lst_of(base_years[0])
                for by in base_years[1:]:
                    lbase = lbase.addBands(_lst_of(by))
                lmin = lbase.reduce(ee.Reducer.min()).rename('mn')
                lmax = lbase.reduce(ee.Reducer.max()).rename('mx')
                tci = lmax.subtract(lcur).divide(lmax.subtract(lmin).add(0.001)).multiply(100).rename('tci').clip(geom)
                if ind == 'vhi':
                    bmin = base.reduce(ee.Reducer.min()).rename('mn')
                    bmax = base.reduce(ee.Reducer.max()).rename('mx')
                    vci = cur.subtract(bmin).divide(bmax.subtract(bmin).add(0.001)).multiply(100)
                    img, name = tci.addBands(vci).reduce(ee.Reducer.mean()).rename('vhi').clip(geom), 'VHI'
                else:
                    img, name = tci, 'TCI'
                tile = self._tile(img, {'min': 0, 'max': 100, 'palette': ['#FF0000', '#FFFF00', '#1a9850']})
                stats = self._class_areas(
                    ee.Image(0).where(img.lt(20), 0).where(img.gte(20).And(img.lt(35)), 1)
                    .where(img.gte(35).And(img.lt(50)), 2).where(img.gte(50), 3).rename('v').clip(geom), geom, 1000,
                    {0: 'Extreme (<20)', 1: 'Severe (20-35)', 2: 'Moderate (35-50)', 3: 'Normal (>50)'})
                m = self._reduce(img, geom, 1000).get(name.lower(), 0)
                extra = ' VHI=0.5·VCI+0.5·TCI.' if ind == 'vhi' else ' TCI=(LSTmax−LST)/(LSTmax−LSTmin)×100 (MODIS).'
                return {'type': name, 'label': f'{name} ({year})', 'stats': {**stats, f'Mean {name}': round(m, 1)},
                        'tileUrl': tile, 'interpretation': f'{name} vs {base_years[0]}–{year - 1}. Mean {m:.0f}.{extra}',
                        'legend': [{'value': 0, 'label': 'Extreme (<20)', 'color': '#FF0000'},
                                   {'value': 1, 'label': 'Severe (20-35)', 'color': '#FF9800'},
                                   {'value': 2, 'label': 'Moderate (35-50)', 'color': '#FFFF00'},
                                   {'value': 3, 'label': 'Normal (>50)', 'color': '#1a9850'}],
                        'scale': 1000}
            if ind == 'spi':
                def _rain(yr):
                    return (ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterBounds(geom)
                            .filter(ee.Filter.calendarRange(yr, yr, 'year')).select('precipitation').sum())
                pcur, pbase = _rain(year), _rain(base_years[0])
                for by in base_years[1:]:
                    pbase = pbase.addBands(_rain(by))
                pmean = pbase.reduce(ee.Reducer.mean()).rename('m')
                pstd = pbase.reduce(ee.Reducer.stdDev()).rename('s')
                spi = pcur.subtract(pmean).divide(pstd.add(1)).rename('spi').clip(geom)
                tile = self._tile(spi, {'min': -2, 'max': 2, 'palette': ['#FF0000', '#FFFF00', '#FFFFFF', '#91cf60', '#0000CD']})
                stats = self._class_areas(
                    ee.Image(3).where(spi.lte(-2), 0).where(spi.gt(-2).And(spi.lte(-1.5)), 1)
                    .where(spi.gt(-1.5).And(spi.lte(-1)), 2).where(spi.gt(-1).And(spi.lte(1)), 3)
                    .where(spi.gt(1), 4).rename('s').clip(geom), geom, 5000,
                    {0: 'Extreme (≤-2)', 1: 'Severe (-2..-1.5)', 2: 'Moderate (-1.5..-1)', 3: 'Normal', 4: 'Wet (>1)'})
                m = self._reduce(spi, geom, 5000).get('spi', 0)
                return {'type': 'SPI', 'label': f'Standardized Precipitation Index ({year})',
                        'stats': {**stats, 'Mean SPI': round(m, 2)},
                        'tileUrl': tile,
                        'interpretation': f'SPI=(P−Pmean)/Pstd vs {base_years[0]}–{year - 1} (CHIRPS). Mean {m:+.2f}. ≤−1 = drought.',
                        'legend': [{'value': 0, 'label': 'Extreme (≤-2)', 'color': '#7f0000'},
                                   {'value': 1, 'label': 'Severe', 'color': '#FF0000'},
                                   {'value': 2, 'label': 'Moderate', 'color': '#FFFF00'},
                                   {'value': 3, 'label': 'Normal', 'color': '#FFFFFF'},
                                   {'value': 4, 'label': 'Wet (>1)', 'color': '#0000CD'}],
                        'scale': 5000}
            if ind == 'aridity':
                pann = (ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterBounds(geom)
                        .filter(ee.Filter.calendarRange(year, year, 'year')).select('precipitation').sum())
                pet = (ee.ImageCollection('MODIS/061/MOD16A2').filterBounds(geom)
                       .filter(ee.Filter.calendarRange(year, year, 'year')).select('ET').sum().multiply(0.1))
                ai = pann.divide(pet.add(1)).rename('ai').clip(geom)
                tile = self._tile(ai, {'min': 0, 'max': 1, 'palette': ['#7f0000', '#FF0000', '#FFD700', '#91cf60', '#1a9850']})
                stats = self._class_areas(
                    ee.Image(4).where(ai.lt(0.05), 0).where(ai.gte(0.05).And(ai.lt(0.2)), 1)
                    .where(ai.gte(0.2).And(ai.lt(0.5)), 2).where(ai.gte(0.5).And(ai.lt(0.65)), 3)
                    .rename('a').clip(geom), geom, 500,
                    {0: 'Hyper-arid (<0.05)', 1: 'Arid', 2: 'Semi-arid', 3: 'Dry sub-humid', 4: 'Humid'})
                m = self._reduce(ai, geom, 500).get('ai', 0)
                return {'type': 'Aridity', 'label': f'Aridity Index ({year})',
                        'stats': {**stats, 'Mean AI': round(m, 3)},
                        'tileUrl': tile,
                        'interpretation': f'Satellite aridity AI=P/PET (CHIRPS/MOD16) {year}: {m:.2f}. <0.65 = drylands (UNEP classes).',
                        'legend': [{'value': 0, 'label': 'Hyper-arid', 'color': '#7f0000'},
                                   {'value': 1, 'label': 'Arid', 'color': '#FF0000'},
                                   {'value': 2, 'label': 'Semi-arid', 'color': '#FFD700'},
                                   {'value': 3, 'label': 'Dry sub-humid', 'color': '#91cf60'},
                                   {'value': 4, 'label': 'Humid', 'color': '#1a9850'}],
                        'scale': 500}
            anom = cur.subtract(baseline).rename('anom')
            tile = self._tile(anom, {'min': -0.3, 'max': 0.3, 'palette': ['#FF0000', '#FFFF00', '#FFFFFF', '#91cf60', '#1a9850']})
            stats = self._class_areas(
                ee.Image(0).where(anom.lt(-0.05).And(anom.gte(-0.1)), 1).where(anom.lt(-0.1), 2).rename('d').clip(geom),
                geom, 10, {0: 'Normal', 1: 'Moderate (<-0.05)', 2: 'Severe (<-0.1)'})
            m = self._reduce(anom, geom).get('anom', 0)
            rain_now = (ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterBounds(geom)
                        .filter(ee.Filter.calendarRange(year, year, 'year'))
                        .select('precipitation').sum())
            rain_base = (ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterBounds(geom)
                         .filter(ee.Filter.calendarRange(base_years[0], year - 1, 'year'))
                         .select('precipitation').sum().divide(max(1, len(base_years))))
            rn = self._reduce(rain_now, geom, 5000).get('precipitation', 0)
            rb = self._reduce(rain_base, geom, 5000).get('precipitation', 0)
            rain_note = ''
            try:
                pct = ((float(rn or 0) - float(rb or 0)) / float(rb or 1)) * 100
                rain_note = f' Rainfall {year}: {float(rn or 0):.0f} mm vs baseline {float(rb or 0):.0f} mm ({pct:+.0f}%).'
            except (TypeError, ValueError, ZeroDivisionError):
                pass
            sev = stats.get('Severe (<-0.1)', '0 ha')
            return {'type': 'Drought', 'label': f'Drought NDVI anomaly ({year})',
                    'stats': {**stats, 'Mean anomaly': round(m, 4)},
                    'tileUrl': tile,
                    'interpretation': (f'NDVI anomaly {year} vs {base_years[0]}–{year - 1} median: {m:+.3f}. '
                                       f'Severe: {sev}.{rain_note} Negative anomaly + below-normal rain = drought signal.'),
                    'legend': [{'value': 0, 'label': 'Normal', 'color': '#1a9850'},
                               {'value': 1, 'label': 'Moderate (<-0.05)', 'color': '#FFFF00'},
                               {'value': 2, 'label': 'Severe (<-0.1)', 'color': '#FF0000'}],
                    'scale': 10}

        elif analysis == 'timeseries':
            # One EE request: yearly means mapped server-side, returned as chartData.
            var = (variable or 'ndvi').lower()
            y1 = min(year, year2) if year2 else min(year, 2024)
            y2c = max(year, year2) if year2 else 2024
            y1, y2c = max(1984, y1), min(2030, y2c)
            if y2c - y1 > 10:
                y1 = y2c - 10
            years_list = list(range(y1, y2c + 1))
            if var == 'rainfall':
                def _v(yr):
                    img = (ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterBounds(geom)
                           .filter(ee.Filter.calendarRange(yr, yr, 'year'))
                           .select('precipitation').sum())
                    return img.reduceRegion(ee.Reducer.mean(), geom, 5000, maxPixels=int(1e9), bestEffort=True).get('precipitation')
                unit, label = 'mm', f'Rainfall trend ({y1}–{y2c})'
            elif var in ('lst', 'temperature'):
                def _v(yr):
                    img = (ee.ImageCollection('MODIS/061/MOD11A1').filterBounds(geom)
                           .filter(ee.Filter.calendarRange(yr, yr, 'year'))
                           .select('LST_Day_1km').median().multiply(0.02).subtract(273.15))
                    return img.reduceRegion(ee.Reducer.mean(), geom, 1000, maxPixels=int(1e9), bestEffort=True).get('LST_Day_1km')
                unit, label = '°C', f'LST trend ({y1}–{y2c})'
            elif var.upper() in SPECTRAL_INDICES and var.upper() != 'DNBR':
                idx = var.upper()
                B = self._bands(source)
                def _v(yr):
                    c = self._collection(geom, f'{yr}-01-01', f'{yr}-12-31', source, max_cloud)
                    img, _, _ = self._spectral(c, B, idx)
                    return img.reduceRegion(ee.Reducer.mean(), geom, 10, maxPixels=int(1e9), bestEffort=True).get(idx)
                var = idx.lower()
                unit, label = 'index', f'{idx} annual time series ({y1}–{y2c})'
            else:
                var = 'ndvi'
                B = self._bands(source)
                def _v(yr):
                    c = self._collection(geom, f'{yr}-01-01', f'{yr}-12-31', source, max_cloud)
                    img, _, _ = self._spectral(c, B, 'NDVI')
                    return img.reduceRegion(ee.Reducer.mean(), geom, 10, maxPixels=int(1e9), bestEffort=True).get('NDVI')
                unit, label = 'index', f'NDVI annual time series ({y1}–{y2c})'
            seq = ee.List([ee.Dictionary({'year': yr, 'value': _v(yr)}) for yr in years_list])
            raw_series = seq.getInfo()
            chart, vals = [], []
            for item in raw_series:
                try:
                    v = float(item.get('value')) if item.get('value') is not None else None
                except (TypeError, ValueError):
                    v = None
                chart.append({'year': str(item.get('year')), 'value': round(v, 4) if v is not None else None})
                if v is not None:
                    vals.append(v)
            trend = ''
            trend_stats = {}
            valid = [(int(item['year']), float(item['value'])) for item in chart if item['value'] is not None]
            if len(valid) >= 3:
                ts = trend_statistics([item[0] for item in valid], [item[1] for item in valid])
                direction = 'increasing' if ts['sen_slope'] > 0 else ('decreasing' if ts['sen_slope'] < 0 else 'flat')
                trend_stats = {'Sen slope': f"{ts['sen_slope']:+.5f} {unit}/yr", 'MK S': ts['mk_s'],
                               'MK Z': round(ts['mk_z'], 3), 'MK p': round(ts['mk_p'], 5),
                               'MK verdict': f"{direction}, {'significant' if ts['mk_p'] < 0.05 else 'not significant'} at α=0.05"}
                trend = f"Sen slope {ts['sen_slope']:+.4f} {unit}/yr; Mann–Kendall p={ts['mk_p']:.4f}."
            elif len(valid) >= 2:
                trend = 'At least three annual observations are required for Sen/Mann–Kendall inference.'
            last_img = self._collection(geom, f'{y2c}-01-01', f'{y2c}-12-31', source, max_cloud)
            if var in {item.lower() for item in SPECTRAL_INDICES if item != 'DNBR'}:
                last_index, _, _ = self._spectral(last_img, self._bands(source), var.upper())
            else:
                last_index, _, _ = self._spectral(last_img, self._bands(source), 'NDVI')
            tile = self._tile(last_index, {'min': -0.5 if var in ('nbr','ndmi','ndsi') else -0.2,
                                           'max': 1, 'palette': ['#8c510a', '#f6e8c3', '#01665e']})
            return {'type': 'TimeSeries', 'label': label,
                    'stats': {**{str(c['year']): c['value'] for c in chart if c['value'] is not None}, **trend_stats},
                    'chartData': chart, 'tileUrl': tile,
                    'interpretation': f'Annual {var} {y1}–{y2c}. {trend} Mann–Kendall uses a normal approximation without autocorrelation correction.',
                    'legend': {'type': 'continuous', 'min': y1, 'max': y2c, 'unit': 'year'}, 'scale': 10}

        elif analysis == 'spectral_index':
            idx = (index or method or 'NDVI').upper()
            if idx not in SPECTRAL_INDICES:
                return {'error': f'Unknown index {idx}. Available: {", ".join(SPECTRAL_INDICES)}.'}
            B = self._bands(source)
            try:
                if idx == 'DNBR':
                    pre_year, post_year = sorted((year, year2))
                    pre, pre_count = self._collection(geom, f'{pre_year}-01-01', f'{pre_year}-12-31',
                                                       source, max_cloud, return_count=True)
                    post, post_count = self._collection(geom, f'{post_year}-01-01', f'{post_year}-12-31',
                                                        source, max_cloud, return_count=True)
                    pre_nbr, _, _ = self._spectral(pre, B, 'NBR')
                    post_nbr, _, _ = self._spectral(post, B, 'NBR')
                    img = pre_nbr.subtract(post_nbr).rename('DNBR')
                    unit, thermal_note = 'index', False
                    observation_count = {'pre': pre_count, 'post': post_count}
                else:
                    img, unit, thermal_note = self._spectral(col, B, idx)
            except Exception as exc:
                return {'error': str(exc)}
            ranges = {'RVI': (0, 5), 'DVI': (-1, 1), 'EBBI': None}
            q = self._stats4(img, geom, 10, idx)
            vmin, vmax = ranges.get(idx, (-1, 1))
            if vmin is None:  # EBBI: dynamic range from actual stats
                lo, hi = q.get('Min'), q.get('Max')
                if lo is None or hi is None or hi <= lo:
                    lo, hi = -0.01, 0.01
                vmin, vmax = lo, hi
            pal = ['#8B4513', '#FFD700', '#00BFFF', '#0000CD'] if idx in ('MNDWI', 'AWEI', 'NDWI') else \
                  ['#00FF00', '#FFFF00', '#FF0000'] if idx in ('NDBI', 'UI', 'IBI', 'EBBI', 'BSI') else \
                  ['red', 'yellow', 'green']
            severity = None
            if idx == 'DNBR':
                severity = (ee.Image(0).where(img.gte(0.1).And(img.lt(0.27)), 1)
                            .where(img.gte(0.27).And(img.lt(0.44)), 2)
                            .where(img.gte(0.44).And(img.lt(0.66)), 3)
                            .where(img.gte(0.66), 4).where(img.lt(-0.1), 5).rename('severity'))
                vmin, vmax = 0, 5
                pal = ['#f7f7f7', '#fee08b', '#fdae61', '#f46d43', '#d73027', '#2166ac']
            tile = self._tile(severity if severity is not None else img, {'min': vmin, 'max': vmax, 'palette': pal})
            stats = {f'Mean {idx}': q.get('Mean'), f'Min {idx}': q.get('Min'),
                     f'Max {idx}': q.get('Max'), f'Std {idx}': q.get('Std')}
            # FIX: define interp BEFORE any augmented assignment.
            interp = f'{idx} from {source} ({year}).'
            if idx in ('MNDWI', 'AWEI', 'NDWI'):
                threshold = 0.0
                stats['Water threshold'] = f'{idx} > {threshold:g} (fixed screening threshold)'
                stats.update(self._class_areas(img.gt(threshold).rename('w'), geom, 10, {0: 'Non-water', 1: 'Water'}))
                if idx in ('MNDWI', 'NDWI'):
                    interp += ' Water area is a fixed index > 0 screening classification; threshold requires local seasonal/reference validation.'
            if idx in ('NDBI', 'UI', 'IBI', 'BSI'):
                stats.update(self._class_areas(img.gt(0.1 if idx != 'BSI' else 0).rename('b'), geom, 10,
                                               {0: 'Other', 1: idx}))
            if idx == 'DNBR':
                # Common dNBR severity breaks; intended as screening classes, not field-validated burn severity.
                stats.update(self._class_areas(severity, geom, 30, {0:'Unburned/low change', 1:'Low', 2:'Moderate-low', 3:'Moderate-high', 4:'High', 5:'Enhanced regrowth'}))
                stats.update({'Pre-fire year': pre_year, 'Post-fire year': post_year,
                              'Pre-fire scenes': observation_count['pre'], 'Post-fire scenes': observation_count['post']})
                interp = (f'dNBR = NBR {pre_year} − NBR {post_year}; unitless. Severity classes use common screening breaks '
                          '(<−0.1 regrowth; 0.1/0.27/0.44/0.66). Verify thresholds and burn date with local reference data.')
            else:
                stats['Scenes after metadata filters'] = observation_count
            if thermal_note:
                interp += ' EBBI uses Landsat thermal (Kelvin); thresholds are relative.'
            return {'type': idx, 'label': f'{idx} ({year})', 'stats': stats, 'tileUrl': tile,
                    'interpretation': interp,
                    'legend': ([{'value': 0, 'label': 'Unburned/low change', 'color': '#f7f7f7'},
                                {'value': 1, 'label': 'Low severity', 'color': '#fee08b'},
                                {'value': 2, 'label': 'Moderate-low', 'color': '#fdae61'},
                                {'value': 3, 'label': 'Moderate-high', 'color': '#f46d43'},
                                {'value': 4, 'label': 'High severity', 'color': '#d73027'},
                                {'value': 5, 'label': 'Enhanced regrowth', 'color': '#2166ac'}] if idx == 'DNBR'
                               else {'type': 'continuous', 'min': round(vmin, 4), 'max': round(vmax, 4), 'unit': unit}),
                    'scale': 30 if idx == 'DNBR' else 10}

        elif analysis == 'imagery':
            m = (mode or 'composite').lower()
            B = self._bands(source)
            if m in ('truecolor', 'true', 'true_colour', 'rgb'):
                vis = {'min': 0, 'max': 0.3, 'bands': [B['RED'], B['GREEN'], B['BLUE']], 'gamma': 1.4}
                label = f'True Colour ({year})'
            elif m in ('falsecolor', 'false', 'nir'):
                vis = {'min': 0, 'max': 0.35, 'bands': [B['NIR'], B['RED'], B['GREEN']], 'gamma': 1.4}
                label = f'False Colour NIR ({year})'
            else:
                vis = {'min': 0, 'max': 0.3, 'bands': [B['RED'], B['GREEN'], B['BLUE']], 'gamma': 1.4}
                label = f'Cloud-free Composite ({year})'
            tile = self._tile(col, vis)
            return {'type': 'Imagery', 'label': label,
                    'stats': {'Source': source, 'Cloud filter': f'≤{max_cloud}%', 'Composite': f'{period} median',
                              'Scenes after metadata filters': observation_count, 'QA': 'cloud + cloud shadow masked'},
                    'tileUrl': tile,
                    'interpretation': f'{label} from {source}: {period} cloud/shadow-masked median composite clipped to AOI.',
                    'legend': {'type': 'continuous', 'min': 0, 'max': 1, 'unit': 'reflectance'}, 'scale': 10}

        elif analysis == 'aspect':
            dem = ee.Image('USGS/SRTMGL1_003').clip(geom)
            asp = ee.Terrain.aspect(dem).rename('aspect')
            tile = self._tile(asp, {'min': 0, 'max': 360, 'palette': ['#0000ff', '#00ffff', '#00ff00', '#ffff00', '#ff0000', '#0000ff']})
            stats = self._class_areas(
                asp.expression('(b >= 315 || b < 45) ? 0 : (b < 135) ? 1 : (b < 225) ? 2 : 3', {'b': asp}).rename('a'),
                geom, 30, {0: 'North', 1: 'East', 2: 'South', 3: 'West'})
            return {'type': 'Aspect', 'label': 'Aspect', 'stats': stats, 'tileUrl': tile,
                    'interpretation': 'Slope direction from SRTM (N/E/S/W quadrants). Flat areas report -1 and are excluded.',
                    'legend': [{'value': 0, 'label': 'North', 'color': '#0000ff'}, {'value': 1, 'label': 'East', 'color': '#00ff00'},
                               {'value': 2, 'label': 'South', 'color': '#ff0000'}, {'value': 3, 'label': 'West', 'color': '#ffff00'}],
                    'scale': 30}

        elif analysis == 'hillshade':
            dem = ee.Image('USGS/SRTMGL1_003').clip(geom)
            hs = ee.Terrain.hillshade(dem).rename('hillshade')
            tile = self._tile(hs, {'min': 0, 'max': 255, 'palette': ['#000000', '#ffffff']})
            q = self._stats4(hs, geom, 30, 'hillshade')
            return {'type': 'Hillshade', 'label': 'Hillshade',
                    'stats': {'Mean': q.get('Mean'), 'Min': q.get('Min'), 'Max': q.get('Max')},
                    'tileUrl': tile, 'interpretation': 'Shaded relief from SRTM (azimuth 315°, altitude 45° default).',
                    'legend': {'type': 'continuous', 'min': 0, 'max': 255, 'unit': 'brightness'}, 'scale': 30}

        elif analysis in ('curvature', 'tri', 'tpi', 'twi', 'terrain'):
            # SRTM is a geographic WGS84 elevation model in metres, about 30 m
            # near the equator, with coverage roughly 60°N–56°S.
            dem = ee.Image('USGS/SRTMGL1_003').select('elevation').clip(geom)
            terrain = ee.Terrain.products(dem)
            if analysis == 'terrain':
                variable = (variable or 'slope').lower()
                if variable not in ('elevation', 'slope', 'aspect', 'hillshade', 'curvature', 'tri', 'tpi', 'twi'):
                    return {'error': 'terrain variable must be elevation, slope, aspect, hillshade, curvature, tri, tpi or twi.'}
                analysis = variable
            if analysis == 'curvature':
                # 3x3 discrete Laplacian; elevation change in m per pixel².
                kernel = ee.Kernel.fixed(3, 3, [[-1, -1, -1], [-1, 8, -1], [-1, -1, -1]], 1, 1, False)
                img = dem.convolve(kernel).rename('curvature')
                vis, unit, label = {'min': -30, 'max': 30, 'palette': ['#2166ac', '#f7f7f7', '#b2182b']}, 'm/pixel²', 'Discrete curvature (3×3 Laplacian)'
            elif analysis == 'tri':
                # Riley-style 8-neighbour root-mean-square elevation difference.
                squares = None
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        if dx == 0 and dy == 0:
                            continue
                        delta = dem.subtract(dem.translate(dx, dy, 'pixels')).pow(2)
                        squares = delta if squares is None else squares.add(delta)
                img = squares.divide(8).sqrt().rename('tri')
                vis, unit, label = {'min': 0, 'max': 100, 'palette': ['#1a9850', '#fee08b', '#d73027']}, 'm', 'Terrain Ruggedness Index (8-neighbour RMS)'
            elif analysis == 'tpi':
                neighborhood = dem.focalMean(radius=3, kernelType='circle', units='pixels')
                img = dem.subtract(neighborhood).rename('tpi')
                vis, unit, label = {'min': -30, 'max': 30, 'palette': ['#2166ac', '#f7f7f7', '#b2182b']}, 'm', 'Topographic Position Index (3-pixel radius)'
            elif analysis == 'twi':
                # MERIT upstream area (km²) converted to specific catchment
                # area using nominal 90m cell width; slope comes from SRTM.
                upa = ee.Image('MERIT/Hydro/v1_0_1').select('upa')
                slope_rad = terrain.select('slope').multiply(math.pi / 180)
                tan_slope = slope_rad.tan().max(0.001)
                img = upa.multiply(1e6 / 90).divide(tan_slope).log().rename('twi').clip(geom)
                vis, unit, label = {'min': 2, 'max': 18, 'palette': ['#d73027', '#fee08b', '#1a9850', '#2166ac']}, 'index', 'Topographic Wetness Index (MERIT upstream area / 90m width)'
            else:
                key = {'slope': 'slope', 'aspect': 'aspect', 'hillshade': 'hillshade', 'elevation': 'elevation'}[analysis]
                img = terrain.select(key).rename(key) if key != 'elevation' else dem
                vis = {'slope': {'min': 0, 'max': 45, 'palette': ['#1a9850', '#fee08b', '#d73027']},
                       'aspect': {'min': 0, 'max': 360, 'palette': ['#0000ff', '#00ffff', '#00ff00', '#ffff00', '#ff0000', '#0000ff']},
                       'hillshade': {'min': 0, 'max': 255, 'palette': ['#000000', '#ffffff']},
                       'elevation': {'min': 0, 'max': 3000, 'palette': ['#006400', '#32CD32', '#FFD700', '#8B4513', '#ffffff']}}[analysis]
                unit, label = {'elevation': ('m', 'Elevation'), 'slope': ('degrees', 'Slope'), 'aspect': ('degrees clockwise from north', 'Aspect'), 'hillshade': ('0–255', 'Hillshade') }[analysis]
            scale = 90 if analysis == 'twi' else 30
            tile = self._tile(img, vis)
            q = self._stats4(img, geom, scale, img.bandNames().get(0).getInfo())
            return {'type': 'Terrain', 'label': label, 'stats': {**q, 'Units': unit,
                'DEM': 'USGS SRTMGL1 v003 (metres; approx. 30m; 60°N–56°S)'},
                'tileUrl': tile, 'interpretation': f'{label} computed from SRTM elevation. Units: {unit}. '
                    + ('TWI uses MERIT Hydro upstream contributing area and a nominal 90m contour width; it is a topographic index, not measured soil moisture.' if analysis == 'twi' else ''),
                'legend': {'type': 'continuous', **{k: v for k, v in vis.items() if k in ('min', 'max', 'palette')}, 'unit': unit}, 'scale': scale}

        elif analysis == 'slope_classes':
            dem = ee.Image('USGS/SRTMGL1_003').clip(geom)
            slope_img = ee.Terrain.slope(dem)
            if thresholds and len(thresholds) >= 3:
                brk = list(thresholds)
            else:
                ncls = min(8, max(3, num_classes))
                brk = [round(45 * i / (ncls - 1), 1) for i in range(ncls)]
                if brk[0] != 0:
                    brk = [0] + brk
            cls = ee.Image(0)
            for i in range(len(brk) - 1):
                lo, hi = brk[i], brk[i + 1]
                last = i == len(brk) - 2
                cond = slope_img.gte(lo).And(slope_img.lt(hi)) if not last else slope_img.gte(lo)
                cls = cls.where(cond, i + 1)
            cls = cls.rename('slope_class').clip(geom)
            ncls = len(brk) - 1
            pal = ['#1a9850', '#91cf60', '#fee08b', '#fc8d59', '#d73027', '#7f0000', '#4d004b', '#000000'][:ncls + 1]
            tile = self._tile(cls, {'min': 0, 'max': ncls, 'palette': pal})
            labels = {i + 1: f'{brk[i]:g}–{brk[i + 1]:g}°' + ('+' if i == ncls - 1 else '') for i in range(ncls)}
            labels[0] = 'Flat (0°)'
            stats = self._class_areas(cls, geom, 30, labels)
            legend = [{'value': i, 'label': labels.get(i, str(i)), 'color': pal[i] if i < len(pal) else '#888888'} for i in range(ncls + 1)]
            custom = 'custom thresholds' if thresholds else f'{ncls} equal-interval classes'
            return {'type': 'SlopeClasses', 'label': f'Slope Classes ({custom})', 'stats': stats, 'tileUrl': tile,
                    'interpretation': f'Slope binned from SRTM using {custom} (breaks {brk}°).',
                    'legend': legend, 'scale': 30}

        elif analysis == 'lst_change':
            y1, y2 = min(year, year2), max(year, year2)
            y1, y2 = max(2000, y1), min(2026, y2)
            note = '' if (y1, y2) == (min(year, year2), max(year, year2)) else ' (clamped to MODIS 2000–2026)'

            def _lst(yr):
                return (ee.ImageCollection('MODIS/061/MOD11A1').filterBounds(geom)
                        .filter(ee.Filter.calendarRange(yr, yr, 'year'))
                        .select('LST_Day_1km').median().multiply(0.02).subtract(273.15))
            diff = _lst(y2).subtract(_lst(y1)).rename('dlst').clip(geom)
            tile = self._tile(diff, {'min': -5, 'max': 5, 'palette': ['#0000ff', '#ffffff', '#ff0000']})
            m = self._reduce(diff, geom, 1000).get('dlst', 0)
            return {'type': 'LSTChange', 'label': f'LST Change ({y1} → {y2})',
                    'stats': {'Mean change': f'{m:+.2f}°C'},
                    'tileUrl': tile,
                    'interpretation': f'Daytime LST difference {y1} → {y2} (MODIS 1km): {m:+.2f}°C mean.{note}',
                    'legend': {'type': 'continuous', 'min': -5, 'max': 5, 'unit': '°C change'}, 'scale': 1000}

        elif analysis == 'uhi':
            y = min(max(year, 2000), 2026)
            lst = (ee.ImageCollection('MODIS/061/MOD11A1').filterBounds(geom)
                   .filter(ee.Filter.calendarRange(y, y, 'year'))
                   .select('LST_Day_1km').median().multiply(0.02).subtract(273.15))
            s2y = self._collection(geom, f'{y}-01-01', f'{y}-12-31', 'sentinel2', max_cloud)
            veg_ref = s2y.normalizedDifference(['B8', 'B4'])
            urban_mask = veg_ref.lt(0.2)
            rural_mask = veg_ref.gt(0.4)
            urban_img = lst.updateMask(urban_mask)
            rural_img = lst.updateMask(rural_mask)
            um = urban_img.reduceRegion(ee.Reducer.mean(), geom, 1000, maxPixels=int(1e9), bestEffort=True).getInfo()
            rm = rural_img.reduceRegion(ee.Reducer.mean(), geom, 1000, maxPixels=int(1e9), bestEffort=True).getInfo()
            ut = float(um.get('LST_Day_1km', 0) or 0)
            rt = float(rm.get('LST_Day_1km', 0) or 0)
            intensity = ut - rt
            rel = lst.subtract(ee.Image.constant(rt)).rename('uhi').clip(geom)
            tile = self._tile(rel, {'min': -2, 'max': 6, 'palette': ['#0000ff', '#00ffff', '#ffff00', '#ff0000']})
            hot = self._class_areas(rel.gt(2).rename('h'), geom, 1000, {0: 'Non-UHI', 1: 'UHI (>+2°C)'})
            return {'type': 'UHI', 'label': f'Urban Heat Island ({y})',
                    'stats': {'Urban mean': f'{ut:.1f}°C', 'Rural mean': f'{rt:.1f}°C',
                              'UHI intensity': f'{intensity:+.1f}°C', **hot},
                    'tileUrl': tile,
                    'interpretation': (f'LST-based UHI {y} (MODIS 1km): urban mask = Sentinel-2 NDVI<0.2, '
                                       f'rural = NDVI>0.4. Intensity {intensity:+.1f}°C. Masks are proxies, not land-use maps.'),
                    'legend': {'type': 'continuous', 'min': -2, 'max': 6, 'unit': '°C vs rural'}, 'scale': 1000}

        elif analysis == 'uftvi':
            # Urban Thermal Field Variance Index (Liu & Zhang): UTFVI = (Ts - Tmean) / Tmean (Kelvin).
            y = min(max(year, 2000), 2026)
            lstk = (ee.ImageCollection('MODIS/061/MOD11A1').filterBounds(geom)
                    .filter(ee.Filter.calendarRange(y, y, 'year'))
                    .select('LST_Day_1km').median().multiply(0.02))
            tmean = lstk.reduceRegion(ee.Reducer.mean(), geom, 1000, maxPixels=int(1e9), bestEffort=True).getInfo().get('LST_Day_1km', 0) or 0
            uftvi = lstk.subtract(ee.Image.constant(float(tmean))).divide(ee.Image.constant(float(tmean) or 1)).rename('uftvi').clip(geom)
            tile = self._tile(uftvi, {'min': -0.05, 'max': 0.15, 'palette': ['#0000ff', '#00ff00', '#ffff00', '#ff0000']})
            stats = self._class_areas(
                ee.Image(0).where(uftvi.gte(0).And(uftvi.lt(0.005)), 1).where(uftvi.gte(0.005).And(uftvi.lt(0.01)), 2)
                .where(uftvi.gte(0.01).And(uftvi.lt(0.015)), 3).where(uftvi.gte(0.015).And(uftvi.lt(0.02)), 4)
                .where(uftvi.gte(0.02), 5).rename('u').clip(geom),
                geom, 1000, {0: 'None (<0)', 1: 'Weak', 2: 'Middle', 3: 'Strong', 4: 'Stronger', 5: 'Strongest'})
            return {'type': 'UTFVI', 'label': f'UTFVI ({y})',
                    'stats': stats, 'tileUrl': tile,
                    'interpretation': f'UTFVI=(Ts−Tmean)/Tmean from MODIS LST {y} (Tmean={float(tmean):.1f}K). Classes per Liu & Zhang thresholds.',
                    'legend': [{'value': 0, 'label': 'None (<0)', 'color': '#0000ff'}, {'value': 1, 'label': 'Weak', 'color': '#00ffff'},
                               {'value': 2, 'label': 'Middle', 'color': '#00ff00'}, {'value': 3, 'label': 'Strong', 'color': '#ffff00'},
                               {'value': 4, 'label': 'Stronger', 'color': '#ff9800'}, {'value': 5, 'label': 'Strongest', 'color': '#ff0000'}],
                    'scale': 1000}

        elif analysis == 'sprawl':
            y1, y2 = min(year, year2), max(year, year2)
            c1 = self._collection(geom, f'{y1}-01-01', f'{y1}-12-31', source, max_cloud)
            c2 = self._collection(geom, f'{y2}-01-01', f'{y2}-12-31', source)
            b = ('SR_B6', 'SR_B5') if 'landsat' in source else ('B11', 'B8')
            bu1 = c1.normalizedDifference(b).gt(0.1).rename('b')
            bu2 = c2.normalizedDifference(b).gt(0.1).rename('b')
            expansion = bu2.And(bu1.Not()).rename('exp')
            # Infill/edge (within 100m of old built-up) vs leapfrog (isolated).
            near_old = bu1.focalMax(100, 'circle', 'meters')
            infill = expansion.And(near_old).rename('i')
            leap = expansion.And(near_old.Not()).rename('l')
            tile = self._tile(
                ee.Image(0).where(bu1, 1).where(expansion.And(near_old), 2).where(expansion.And(near_old.Not()), 3).rename('s').clip(geom),
                {'min': 0, 'max': 3, 'palette': ['#e0e0e0', '#ff0000', '#ff9800', '#ffff00']})
            e = self._class_areas(expansion, geom, 10, {0: 'Other', 1: 'New built-up'})
            ii = self._class_areas(infill, geom, 10, {0: 'Other', 1: 'Infill/Edge'})
            ll = self._class_areas(leap, geom, 10, {0: 'Other', 1: 'Leapfrog'})
            yrs = max(1, y2 - y1)
            try:
                exp_ha = float(str(e.get('New built-up', '0 ha')).split()[0])
            except (TypeError, ValueError, IndexError):
                exp_ha = 0
            return {'type': 'Sprawl', 'label': f'Urban Sprawl ({y1} → {y2})',
                    'stats': {'New built-up': e.get('New built-up', '0 ha'),
                              'Growth rate': f'{exp_ha / yrs:.1f} ha/yr',
                              'Infill/Edge': ii.get('Infill/Edge', '0 ha'),
                              'Leapfrog': ll.get('Leapfrog', '0 ha')},
                    'tileUrl': tile,
                    'interpretation': (f'Built-up (NDBI>0.1) {y1} → {y2}: +{exp_ha:.1f} ha ({exp_ha / yrs:.1f} ha/yr). '
                                       'Red=pre-existing, orange=infill/edge (<100m of old), yellow=leapfrog/isolated. NDBI proxy, not cadastral data.'),
                    'legend': [{'value': 0, 'label': 'Non built-up', 'color': '#e0e0e0'},
                               {'value': 1, 'label': 'Pre-existing built-up', 'color': '#ff0000'},
                               {'value': 2, 'label': 'Infill/Edge growth', 'color': '#ff9800'},
                               {'value': 3, 'label': 'Leapfrog growth', 'color': '#ffff00'}],
                    'scale': 10}

        elif analysis == 'lulc_change':
            y1, y2 = min(year, year2), max(year, year2)
            if algorithm.lower().replace('-', '_') in ('kmeans', 'k_means'):
                raise ValueError('LULC transition matrices need supervised class codes; unsupervised cluster labels are not stable across dates.')
            n = min(8, max(2 if training_samples is not None else 3, num_classes))
            defaults = {3: ['Bareland', 'Vegetation', 'Built-up'],
                        4: ['Built-up', 'Vegetation', 'Bare', 'Water'],
                        5: ['Bareland', 'Built-up', 'Vegetation', 'Cropland', 'Rangeland'],
                        6: ['Bareland', 'Built-up', 'Forest', 'Cropland', 'Rangeland', 'Water']}
            names_list = list(class_names) if class_names and len(class_names) == n else list(defaults.get(n, defaults[5]))
            remaps = {3: ([10,20,30,40,50,60,70,80,90,95,100],[1,1,1,1,2,0,0,0,1,1,1]),
                      4: ([10,20,30,40,50,60,70,80,90,95,100],[1,1,1,1,0,2,2,3,1,1,1]),
                      5: ([10,20,30,40,50,60,70,80,90,95,100],[2,4,4,3,1,0,0,0,4,2,0]),
                      6: ([10,20,30,40,50,60,70,80,90,95,100],[4,4,4,3,1,0,0,5,4,2,0])}
            if n not in remaps and training_samples is None:
                raise ValueError('Seven/eight-class LULC comparison requires imported labeled samples; ESA WorldCover schema is available only for 3–6 classes.')
            src_vals, dst_vals = remaps.get(n, (None, None))
            bands = (['SR_B2','SR_B3','SR_B4','SR_B5','SR_B6','SR_B7','NDVI','NDBI','MNDWI'] if 'landsat' in source else
                     ['B2','B3','B4','B5','B6','B7','B8','B8A','B11','B12','NDVI','NDBI','MNDWI'])
            scene_counts = {}

            def _features(yr):
                s, e = f'{yr}-01-01', f'{yr}-12-31'
                c, scene_counts[str(yr)] = self._collection(geom, s, e, source, max_cloud, return_count=True)
                ndvi = c.normalizedDifference(['SR_B5','SR_B4'] if 'landsat' in source else ['B8','B4']).rename('NDVI')
                ndbi = c.normalizedDifference(['SR_B6','SR_B5'] if 'landsat' in source else ['B11','B8']).rename('NDBI')
                mndwi = c.normalizedDifference(['SR_B3','SR_B6'] if 'landsat' in source else ['B3','B11']).rename('MNDWI')
                full = c.addBands(ndvi).addBands(ndbi).addBands(mndwi)
                return full.select(bands)

            # Train ONE model from the reference-year composite so both dates
            # share identical feature definitions, class codes and classifier.
            reference_features = _features(2021)
            if training_samples is not None:
                reference_train = reference_features.sampleRegions(
                    ee.FeatureCollection(training_samples), [class_property], 10)
                label_field = class_property
            else:
                wc = ee.Image('ESA/WorldCover/v200/2021').select('Map').clip(geom)
                ref = wc.remap(src_vals, dst_vals, 0).rename('lc')
                pts = ref.stratifiedSample(80, 'lc', geom, 10, seed=42, geometries=True)
                reference_train = reference_features.sampleRegions(pts, ['lc'], 10, geometries=True)
                label_field = 'lc'
            train = reference_train.filter(ee.Filter.notNull(bands + [label_field]))
            train = train.randomColumn('r', 42).filter(ee.Filter.lt('r', 0.7))
            clf, actual = self._supervised_classifier(algorithm, train, label_field, bands, model_config)
            change_accuracy = {}
            if validation_samples is not None:
                validation_fc = reference_features.sampleRegions(
                    ee.FeatureCollection(validation_samples).filter(ee.Filter.disjoint(
                        leftField='.geo', rightValue=ee.FeatureCollection(training_samples).geometry().buffer(30))),
                    [class_property], 10)
                validation_fc = validation_fc.filter(ee.Filter.notNull(bands + [class_property]))
                validation_matrix_info = validation_fc.classify(clf).errorMatrix(label_field, 'classification').getInfo()
                validation_matrix = validation_matrix_info.get('array') if isinstance(validation_matrix_info, dict) else validation_matrix_info
                validation_metric = classification_metrics(validation_matrix)
                change_accuracy = {'Validation source': 'Imported reference samples ≥30 m from training; evaluated on 2021 reference composite only',
                                   'Overall accuracy': round(validation_metric['overall_accuracy'], 4),
                                   'Kappa': round(validation_metric['kappa'], 4) if validation_metric['kappa'] is not None else None,
                                   'Confusion matrix (rows=reference, columns=predicted)': validation_metric['matrix']}

            def _classify(yr):
                return _features(yr).classify(clf).rename('lc').clip(geom)

            year_sequence = sorted(set(comparison_years or [y1, y2]))
            if not 2 <= len(year_sequence) <= 8:
                raise ValueError('LULC comparison supports 2–8 distinct dates.')
            year_maps = {yr: _classify(yr) for yr in year_sequence}
            transition_by_period = {}
            period_stats = []
            final_change_code = None
            final_changed_m2 = 0.0
            for from_year, to_year in zip(year_sequence[:-1], year_sequence[1:]):
                from_map, to_map = year_maps[from_year], year_maps[to_year]
                code_image = from_map.multiply(n).add(to_map).rename('chg').clip(geom)
                raw = (ee.Image.pixelArea().addBands(code_image)
                       .reduceRegion(reducer=ee.Reducer.sum().group(1, 'code'),
                                     geometry=geom, scale=10, maxPixels=int(1e9), bestEffort=True).getInfo())
                groups = raw.get('groups', []) or []
                total_m2 = sum(float(g.get('sum', 0) or 0) for g in groups)
                matrix_rows = {}
                for group in groups:
                    try:
                        value = int(group.get('code'))
                        from_class, to_class = value // n, value % n
                        m2 = float(group.get('sum', 0))
                    except (TypeError, ValueError):
                        continue
                    pct = 100 * m2 / total_m2 if total_m2 else 0
                    matrix_rows[f'{names_list[from_class]} → {names_list[to_class]}'] = {
                        'hectares': round(m2 / 1e4, 2), 'square_kilometres': round(m2 / 1e6, 4),
                        'percent_of_AOI': round(pct, 2)}
                change_mask = from_map.neq(to_map)
                changed_m2 = self._class_area_m2(change_mask, geom, 10)
                elapsed = max(1, to_year-from_year)
                key = f'{from_year}→{to_year}'
                transition_by_period[key] = matrix_rows
                period_stats.append({'period': key, 'year': key, 'value': round(changed_m2 / 1e4, 2),
                                     'changed_hectares': round(changed_m2 / 1e4, 2),
                                     'changed_square_kilometres': round(changed_m2 / 1e6, 4),
                                     'annualized_hectares': round(changed_m2 / 1e4 / elapsed, 2)})
                final_change_code, final_changed_m2 = code_image, changed_m2
            map1, map2 = year_maps[year_sequence[-2]], year_maps[year_sequence[-1]]
            change_code = final_change_code
            transition_palette = [
                '#313695','#4575b4','#74add1','#abd9e9','#e0f3f8','#ffffbf','#fee090','#fdae61',
                '#f46d43','#d73027','#a50026','#006837','#1a9850','#66bd63','#a6d96a','#d9ef8b']
            tile = self._tile(change_code, {'min': 0, 'max': n * n - 1, 'palette': transition_palette})
            transition = transition_by_period[f'{year_sequence[-2]}→{year_sequence[-1]}']
            a1 = self._class_areas(map1, geom, 10, {i: names_list[i] for i in range(n)})
            a2 = self._class_areas(map2, geom, 10, {i: names_list[i] for i in range(n)})
            chg_stats = self._class_areas(map1.neq(map2).rename('c'), geom, 10, {0: 'Stable', 1: 'Changed'})
            changed_m2 = final_changed_m2
            interval = max(1, y2 - y1)
            change_legend = [{'value': f * 100 + t, 'label': f'{names_list[f]} → {names_list[t]}',
                              'color': transition_palette[(f * n + t) % 16]}
                             for f in range(n) for t in range(n)]
            out = {'type': 'LULCChange', 'label': f'LULC Change ({y1} → {y2})',
                   'stats': {**{f'{y1} ' + k: v for k, v in list(a1.items())[:n]},
                             **{f'{y2} ' + k: v for k, v in list(a2.items())[:n]},
                             'Changed area': f'{changed_m2 / 1e4:.2f} ha / {changed_m2 / 1e6:.4f} km²',
                             'Annualized changed area': f'{changed_m2 / 1e4 / interval:.2f} ha/yr',
                             'Percent AOI changed': f'{100 * changed_m2 / (geom.area(1).getInfo() or 1):.2f}%',
                             'Model': actual,
                             'Scenes by year': json.dumps(scene_counts),
                             **(change_accuracy or {'Accuracy': 'No scores: independent reference samples not supplied.'})},
                   'tileUrl': tile,
                   'interpretation': (f'{n}-class supervised change {y1} → {y2} ({algorithm}). '
                                      f'Changed: {chg_stats.get("Changed", "0 ha")}. One {actual} model trained on 2021 reference inputs was reused across both dates. See full transition matrix.'),
                   'legend': change_legend,
                   'transition': transition, 'transitionByPeriod': transition_by_period,
                   'accuracy': change_accuracy,
                   'chartData': period_stats, f'stats_{year_sequence[-1]}': a2, 'scale': 10}
            return out

        elif analysis == 'deforestation':
            y1, y2 = min(year, year2), max(year, year2)
            y1c, y2c = max(2001, y1), min(2023, y2)
            if y1c > y2c:
                raise ValueError('Hansen annual forest-loss data cover 2001–2023; choose a year range overlapping that period.')
            note = '' if (y1c, y2c) == (y1, y2) else ' (loss years clamped to Hansen 2000–2023)'
            gfc = ee.Image('UMD/hansen/global_forest_change_2023_v1_11').clip(geom)
            loss = gfc.select('lossyear')
            loss_period = loss.gte(y1c - 2000 + 1).And(loss.lte(y2c - 2000 + 1)).And(loss.neq(0)).rename('loss')
            gain_2000_2012 = gfc.select('gain').eq(1).rename('gain')
            event_map = ee.Image(0).where(loss_period, 1).where(gain_2000_2012, 2)
            event_map = event_map.where(loss_period.And(gain_2000_2012), 3).rename('forest_change').clip(geom)
            forest_legend = [{'value': 0, 'label': 'No mapped loss/gain event', 'color': '#d9d9d9'},
                             {'value': 1, 'label': f'Forest loss {y1c}–{y2c}', 'color': '#d7191c'},
                             {'value': 2, 'label': 'Forest gain (Hansen 2000–2012)', 'color': '#1a9641'},
                             {'value': 3, 'label': 'Gain and interval loss', 'color': '#fdae61'}]
            tile = self._tile(event_map, {'min': 0, 'max': 3, 'palette': [x['color'] for x in forest_legend]})
            stats = self._class_areas(event_map, geom, 30, {x['value']: x['label'] for x in forest_legend})
            loss_m2 = self._class_area_m2(loss_period, geom, 30)
            gain_m2 = self._class_area_m2(gain_2000_2012, geom, 30)
            aoi_m2 = geom.area(1).getInfo() or 1
            total_change_years = max(1, y2c-y1c+1)
            cover = gfc.select('treecover2000')
            cm = self._reduce(cover, geom, 30).get('treecover2000', 0)
            return {'type': 'Deforestation', 'label': f'Forest Loss ({y1c}–{y2c})',
                    'stats': {**stats,
                              f'Forest loss {y1c}–{y2c}': f'{loss_m2/1e4:.2f} ha / {loss_m2/1e6:.4f} km²',
                              'Annualized loss': f'{loss_m2/1e4/total_change_years:.2f} ha/yr',
                              'Loss percent of AOI': f'{100*loss_m2/aoi_m2:.2f}%',
                              'Hansen forest gain (2000–2012)': f'{gain_m2/1e4:.2f} ha / {gain_m2/1e6:.4f} km²',
                              'Gain percent of AOI': f'{100*gain_m2/aoi_m2:.2f}%',
                              'Mean 2000 tree cover': f'{cm:.1f}%'},
                    'tileUrl': tile,
                    'interpretation': (f'Hansen Global Forest Change v1.11 (30m): loss {y1c}–{y2c} = '
                                       f'{loss_m2/1e4:.1f} ha; gain uses the Hansen fixed 2000–2012 gain layer (not annual). 2000 tree cover mean {cm:.0f}%.{note}'),
                    'legend': forest_legend,
                    'scale': 30}

        elif analysis == 'et':
            y = min(max(year, 2001), 2026)
            mod16 = (ee.ImageCollection('MODIS/061/MOD16A2').filterBounds(geom)
                     .filter(ee.Filter.calendarRange(y, y, 'year')).select('ET'))
            if (period or 'annual') == 'monthly' and month:
                et = mod16.filter(ee.Filter.calendarRange(month, month, 'month')).sum().multiply(0.1).rename('et')
                label, unit = f'ET {y}-{month:02d} (monthly)', 'mm/month'
            elif (period or 'annual') == 'seasonal' and months:
                ms = sorted(months)
                et = ee.ImageCollection([mod16.filter(ee.Filter.calendarRange(m, m, 'month')).sum() for m in ms]).sum().multiply(0.1).rename('et')
                label, unit = f'ET {y} season (months {ms})', 'mm/season'
            else:
                et = mod16.sum().multiply(0.1).rename('et')
                label, unit = f'ET ({y}, annual)', 'mm/yr'
            et = et.clip(geom)
            tile = self._tile(et, {'min': 0, 'max': 1500, 'palette': ['#ffffff', '#91cf60', '#1a9850', '#004d00']})
            m = self._reduce(et, geom, 500).get('et', 0)
            return {'type': 'ET', 'label': label, 'stats': {'Mean ET': f'{m:.0f} mm'},
                    'tileUrl': tile,
                    'interpretation': f'MODIS MOD16A2 {label}: mean {m:.0f} mm over AOI (mm/8-day sums).',
                    'legend': {'type': 'continuous', 'min': 0, 'max': 1500, 'unit': unit}, 'scale': 500}

        elif analysis == 'airquality':
            pol = (pollutant or 'no2').lower()
            y = min(max(year, 2018), 2026)
            note = '' if y == year else f' (clamped to Sentinel-5P 2018–2026, used {y})'
            if pol == 'pm25':
                return {'error': ('PM2.5 has no valid configured GEE dataset (it needs ground-calibrated models). '
                                  'Available: NO2, SO2, CO, O3 (Sentinel-5P) and AOD (MODIS). Try "show NO2".')}
            conf = {
                'no2': ('COPERNICUS/S5P/OFFL/L3_NO2', 'tropospheric_NO2_column_number_density', 1e6, 'µmol/m²', 'NO₂ tropospheric column'),
                'so2': ('COPERNICUS/S5P/OFFL/L3_SO2', 'SO2_column_number_density', 1e6, 'µmol/m²', 'SO₂ column'),
                'co': ('COPERNICUS/S5P/OFFL/L3_CO', 'CO_column_number_density', 1e3, 'mmol/m²', 'CO column'),
                'o3': ('COPERNICUS/S5P/OFFL/L3_O3', 'ozone_total_vertical_column', 1e3, 'mmol/m²', 'O₃ total column'),
                'aod': ('MODIS/061/MCD19A2_GRANULES', 'Optical_Depth_055', 1, 'unitless', 'Aerosol optical depth 550nm'),
            }.get(pol)
            if not conf:
                return {'error': 'Unknown pollutant. Use NO2, SO2, CO, O3 or AOD.'}
            ds, band, scale_f, unit, desc = conf
            conc = (ee.ImageCollection(ds).filterBounds(geom)
                    .filter(ee.Filter.calendarRange(y, y, 'year'))
                    .select(band).median().multiply(scale_f).rename('aq').clip(geom))
            tile = self._tile(conc, {'min': 0, 'max': 200, 'palette': ['#00ff00', '#ffff00', '#ff9800', '#ff0000']})
            q = self._stats4(conc, geom, 7000 if pol != 'aod' else 1000, 'aq')
            conv_note = ' Concentration (column density), not emissions — totals need flux modelling.' if 'emission' in (method or '') else ''
            return {'type': 'AirQuality', 'label': f'{pol.upper()} ({y})',
                    'stats': {f'Mean {pol.upper()}': f"{q.get('Mean', 0)} {unit}",
                              f'Max {pol.upper()}': f"{q.get('Max', 0)} {unit}"},
                    'tileUrl': tile,
                    'interpretation': f'{desc} {y} ({ds}): mean {q.get("Mean", 0)} {unit}.{conv_note}{note}',
                    'legend': {'type': 'continuous', 'min': 0, 'max': 200, 'unit': unit},
                    'scale': 7000 if pol != 'aod' else 1000}

        elif analysis == 'hydrology':
            # MERIT Hydro is a hydro-conditioned global flow-direction and
            # upstream-area product (~90m); this does not run a new D8 solver.
            hydro = ee.Image('MERIT/Hydro/v1_0_1')
            mode_h = (variable or 'drainage').lower().replace('-', '_').replace(' ', '_')
            upa = hydro.select('upa').rename('upa').clip(geom)  # km²
            if mode_h in ('flow_direction', 'direction', 'dir'):
                result_img, vis_h, unit_h = hydro.select('dir').rename('flow_direction').clip(geom), {'min': 1, 'max': 128, 'palette': ['#2166ac', '#67a9cf', '#d1e5f0', '#fddbc7', '#ef8a62', '#b2182b']}, 'MERIT D8 direction code'
                label_h = 'MERIT Hydro Flow Direction'
            elif mode_h in ('flow_accumulation', 'accumulation', 'upa'):
                result_img, vis_h, unit_h = upa, {'min': 0, 'max': 10000, 'palette': ['#f7fbff', '#6baed6', '#2171b5', '#08306b']}, 'upstream km²'
                label_h = 'Flow Accumulation (Upstream Area)'
            elif mode_h in ('catchment', 'catchment_statistics', 'statistics'):
                q = self._stats4(upa, geom, 90, 'upa')
                area = self._class_area_m2(ee.Image(1), geom, 90)
                return {'type': 'Hydrology', 'label': 'Catchment Indicators (AOI summary)',
                    'stats': {**q, 'AOI area': f'{area / 1e6:.3f} km²', 'Units': 'MERIT upstream area is km²'},
                    'tileUrl': self._tile(upa, {'min': 0, 'max': 10000, 'palette': ['#f7fbff', '#6baed6', '#2171b5', '#08306b']}),
                    'interpretation': 'Statistics summarize MERIT Hydro upstream contributing area within the drawn AOI. This is not a pour-point watershed boundary. For true watershed delineation, supply a snapped outlet and a validated flow-routing solver.',
                    'legend': {'type': 'continuous', 'min': 0, 'max': 10000, 'unit': 'km² upstream area'}, 'scale': 90}
            elif mode_h in ('stream_order', 'order', 'strahler'):
                return {'error': 'MERIT Hydro supplies flow direction and upstream area, but not Strahler order. A verified directed-network graph or local D8 routing engine is required; no stream order is inferred from area thresholds.'}
            elif mode_h in ('watershed', 'delineate_watershed', 'basin'):
                return {'error': 'Watershed delineation requires a pour-point coordinate snapped to the conditioned flow network. Drawn AOI alone is not an outlet; provide a pour point and routing workflow.'}
            else:
                # Network extraction by an explicit contributing-area threshold.
                threshold_km2 = 10.0
                if thresholds and len(thresholds) == 1:
                    threshold_km2 = float(thresholds[0])
                if not math.isfinite(threshold_km2) or threshold_km2 <= 0:
                    return {'error': 'Drainage threshold must be a positive upstream area in km².'}
                result_img = upa.gte(threshold_km2).rename('drainage')
                vis_h, unit_h = {'min': 0, 'max': 1, 'palette': ['#ffffff', '#0050c8']}, f'upa ≥ {threshold_km2:g} km²'
                label_h = f'Drainage Extraction (upa ≥ {threshold_km2:g} km²)'
            tile = self._tile(result_img, vis_h)
            if mode_h in ('flow_direction', 'direction', 'dir'):
                stats = self._stats4(result_img, geom, 90, 'flow_direction')
            elif mode_h in ('flow_accumulation', 'accumulation', 'upa'):
                stats = self._stats4(result_img, geom, 90, 'upa')
            else:
                stats = self._class_areas(result_img, geom, 90, {0: 'Below threshold', 1: 'Drainage'} if mode_h not in ('flow_direction', 'direction', 'dir') else None)
            return {'type': 'Hydrology', 'label': label_h, 'stats': {**(stats or {}), 'Units': unit_h,
                'Source': 'MERIT Hydro v1.0.1, ~90m, hydro-conditioned; DIR and UPA bands'},
                'tileUrl': tile,
                'interpretation': f'{label_h}. MERIT Hydro provides conditioned flow direction and accumulated upstream area; extraction uses the documented threshold. This output does not calculate stream order or delineate a pour-point watershed.',
                'legend': {'type': 'continuous', **{k: v for k, v in vis_h.items() if k in ('min', 'max', 'palette')}, 'unit': unit_h}, 'scale': 90}

        elif analysis == 'landslide':
            # Weighted overlay — defaults documented, user weights honored.
            w = dict(weights) if weights else {}
            w = {'slope': w.get('slope', 0.35), 'rainfall': w.get('rainfall', 0.25),
                 'landcover': w.get('landcover', 0.15), 'ndvi': w.get('ndvi', 0.15),
                 'elevation': w.get('elevation', 0.10)}
            tot = sum(w.values()) or 1
            w = {k: v / tot for k, v in w.items()}
            y = min(max(year, 1981), 2026)
            dem = ee.Image('USGS/SRTMGL1_003').clip(geom)
            slope_img = ee.Terrain.slope(dem)
            f_slope = slope_img.divide(45).clamp(0, 1)
            rain = (ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterBounds(geom)
                    .filter(ee.Filter.calendarRange(y, y, 'year')).select('precipitation').sum())
            f_rain = rain.divide(2000).clamp(0, 1)
            wc = ee.Image('ESA/WorldCover/v200/2021').select(0).clip(geom)
            f_lc = wc.remap([10,20,30,40,50,60,70,80,90,95,100],[0.2,0.6,0.5,0.4,0.1,0.7,0.1,0.0,0.5,0.2,0.3],0.5)
            s2y = self._collection(geom, f'{y}-01-01', f'{y}-12-31', 'sentinel2', max_cloud)
            f_ndvi = ee.Image(1).subtract(s2y.normalizedDifference(['B8','B4']).clamp(-1, 1)).multiply(0.5)
            f_elev = dem.divide(3000).clamp(0, 1)
            sus = (f_slope.multiply(w['slope']).add(f_rain.multiply(w['rainfall'])).add(f_lc.multiply(w['landcover']))
                   .add(f_ndvi.multiply(w['ndvi'])).add(f_elev.multiply(w['elevation']))).rename('sus').clip(geom)
            cls = ee.Image(0).where(sus.gte(0.33).And(sus.lt(0.5)), 1).where(sus.gte(0.5).And(sus.lt(0.66)), 2).where(sus.gte(0.66), 3).rename('c').clip(geom)
            tile = self._tile(cls, {'min': 0, 'max': 3, 'palette': ['#1a9850', '#FFFF00', '#FF9800', '#FF0000']})
            stats = self._class_areas(cls, geom, 30, {0: 'Low', 1: 'Moderate', 2: 'High', 3: 'Very high'})
            wtxt = ', '.join(f'{k}={v:.2f}' for k, v in w.items())
            return {'type': 'Landslide', 'label': 'Landslide Susceptibility',
                    'stats': stats, 'tileUrl': tile,
                    'interpretation': (f'Weighted overlay (weights {wtxt}): slope, CHIRPS rain {y}, WorldCover, '
                                       '(1−NDVI), elevation — all normalized 0–1. Screening model, not geotechnical mapping.'),
                    'legend': [{'value': 0, 'label': 'Low', 'color': '#1a9850'},
                               {'value': 1, 'label': 'Moderate', 'color': '#FFFF00'},
                               {'value': 2, 'label': 'High', 'color': '#FF9800'},
                               {'value': 3, 'label': 'Very high', 'color': '#FF0000'}],
                    'scale': 30}

        elif analysis == 'salinity':
            # Salinity indicator (spectral) — labeled indicator, not lab measurement.
            B = self._bands(source)
            red, nir = col.select(B['RED']), col.select(B['NIR'])
            green = col.select(B['GREEN'])
            si_img = red.multiply(green).sqrt().rename('si')
            nssi = col.expression('(RED - NIR) / (RED + NIR)', {'RED': red, 'NIR': nir}).rename('nssi')
            sal = si_img.addBands(nssi).reduce(ee.Reducer.mean()).rename('sal').clip(geom)
            tile = self._tile(sal, {'min': 0, 'max': 1, 'palette': ['#1a9850', '#FFFF00', '#FF0000']})
            stats = self._class_areas(
                ee.Image(0).where(sal.gte(0.3).And(sal.lt(0.5)), 1).where(sal.gte(0.5), 2).rename('c').clip(geom),
                geom, 10, {0: 'Non-saline', 1: 'Moderate', 2: 'High'})
            q = self._stats4(sal, geom, 10, 'sal')
            return {'type': 'Salinity', 'label': f'Soil Salinity Indicator ({year})',
                    'stats': {**stats, 'Mean SI': q.get('Mean')},
                    'tileUrl': tile,
                    'interpretation': ('Spectral salinity indicator SI=√(Red×Green) + NDSI mean. INDICATOR ONLY — '
                                       'not lab-measured EC; confirm with soil sampling.'),
                    'legend': [{'value': 0, 'label': 'Non-saline', 'color': '#1a9850'},
                               {'value': 1, 'label': 'Moderate', 'color': '#FFFF00'},
                               {'value': 2, 'label': 'High', 'color': '#FF0000'}],
                    'scale': 10}

        elif analysis == 'moisture':
            ndmi = col.normalizedDifference(
                [self._bands(source)['NIR'], self._bands(source)['SWIR1']]).rename('ndmi')
            tile = self._tile(ndmi, {'min': -0.5, 'max': 0.8, 'palette': ['#8B4513', '#FFFF00', '#0000CD']})
            q = self._stats4(ndmi, geom, 10, 'ndmi')
            wet = self._class_areas(ndmi.gt(0.2).rename('w'), geom, 10, {0: 'Dry', 1: 'Moist (>0.2)'})
            return {'type': 'Moisture', 'label': f'Soil Moisture NDMI ({year})',
                    'stats': {'Mean NDMI': q.get('Mean'), 'Min NDMI': q.get('Min'), 'Max NDMI': q.get('Max'), **wet},
                    'tileUrl': tile, 'interpretation': 'NDMI=(NIR−SWIR1)/(NIR+SWIR1): vegetation/soil moisture proxy.',
                    'legend': {'type': 'continuous', 'min': -0.5, 'max': 0.8, 'unit': 'NDMI'}, 'scale': 10}

        elif analysis == 'mineral':
            B = self._bands(source)
            presets = {'clay': ('SWIR1', 'SWIR2'), 'ferrous': ('SWIR1', 'NIR'),
                       'alteration': ('SWIR1', 'BLUE'), 'silica': ('BLUE', 'SWIR1')}
            if ratio_num and ratio_den:
                num_b = self._band_code(B, ratio_num, source)
                den_b = self._band_code(B, ratio_den, source)
                label = f'{ratio_num}/{ratio_den}'
            else:
                pre = (preset or 'clay').lower()
                pair = presets.get(pre, presets['clay'])
                num_b, den_b = B[pair[0]], B[pair[1]]
                label = f'{pre} ({pair[0]}/{pair[1]})'
            ratio_img = col.select(num_b).divide(col.select(den_b).add(0.001)).rename('ratio').clip(geom)
            q = self._stats4(ratio_img, geom, 10, 'ratio')
            lo, hi = q.get('Min'), q.get('Max')
            if lo is None or hi is None or hi <= lo:
                lo, hi = 0, 2
            tile = self._tile(ratio_img, {'min': lo, 'max': hi, 'palette': ['#000000', '#FFD700', '#FF0000']})
            anom = self._class_areas(ratio_img.gt(lo + (hi - lo) * 0.75).rename('a'), geom, 10,
                                     {0: 'Background', 1: 'Anomalous (top quartile)'})
            return {'type': 'Mineral', 'label': f'Mineral Indicator {label} ({year})',
                    'stats': {'Mean ratio': q.get('Mean'), **anom},
                    'tileUrl': tile,
                    'interpretation': (f'Spectral {label} ratio on {source} ({year}). ANOMALY INDICATOR ONLY — '
                                       'not a confirmed deposit; needs field/geochemical validation.'),
                    'legend': [{'value': 0, 'label': 'Background', 'color': '#000000'},
                               {'value': 1, 'label': 'Anomalous', 'color': '#FF0000'}],
                    'scale': 10}

        elif analysis == 'suitability':
            u = (use or 'residential').lower()
            if u not in ('residential', 'agricultural', 'urban'):
                return {'error': 'Configured suitability screening currently supports agricultural, residential and urban use. Solar needs an irradiance layer; infrastructure and conservation need explicit distance/ecological criteria not present in this catalogue.'}
            available = {'slope', 'landcover', 'flood', 'ndvi', 'rainfall', 'elevation'}
            try:
                w = validate_weights(weights, available)
            except ValueError as exc:
                return {'error': str(exc)}
            if set(w) - available:
                return {'error': 'One or more weighted criteria have no configured data layer.'}
            y = year
            dem = ee.Image('USGS/SRTMGL1_003').clip(geom)
            target_projection = dem.projection()
            slope_img = ee.Terrain.slope(dem)
            fns = {
                'slope': ee.Image(1).subtract(slope_img.divide(30).clamp(0, 1)),
                'landcover': ee.Image('ESA/WorldCover/v200/2021').select(0).clip(geom)
                    .remap([10,20,30,40,50,60,70,80,90,95,100],[0.6,0.7,0.8,0.9,0.2,0.3,0.2,0.0,0.7,0.6,0.5],0.5),
                'flood': ee.Image(1).subtract(
                    dem.lt(10).And(slope_img.lt(5)).selfMask().unmask(0).multiply(1)).clamp(0, 1),
                'ndvi': self._collection(geom, f'{y}-01-01', f'{y}-12-31', 'sentinel2', max_cloud)
                    .normalizedDifference(['B8', 'B4']).clamp(-1, 1).multiply(0.5).add(0.5),
                'rainfall': (ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterBounds(geom)
                             .filter(ee.Filter.calendarRange(y, y, 'year')).select('precipitation')
                             .sum().divide(2000).clamp(0, 1)),
                'elevation': ee.Image(1).subtract(dem.divide(3000).clamp(0, 1)),
            }
            # Factor directions and scales are explicit, documented screening
            # transforms. Categorical WorldCover uses nearest-neighbour; the
            # continuous layers are aligned on the SRTM grid. CHIRPS remains
            # the limiting native resolution when rainfall is selected.
            fns['landcover'] = fns['landcover'].reproject(crs=target_projection)
            score = None
            for k, wt in w.items():
                f = fns.get(k)
                if f is None:
                    return {'error': f'Unknown suitability factor "{k}". Available: {", ".join(sorted(fns))}.'}
                if k != 'landcover':
                    f = f.resample('bilinear').reproject(crs=target_projection)
                score = f.multiply(wt) if score is None else score.add(f.multiply(wt))
            score = score.rename('suitability').clip(geom)
            constraints = constraints or {}
            if set(constraints) - {'excludeWater', 'maxSlope'}:
                return {'error': 'Supported constraints are excludeWater (boolean) and maxSlope (degrees).'}
            exclude_water = constraints.get('excludeWater', False)
            max_slope = constraints.get('maxSlope', 90)
            if not isinstance(exclude_water, bool):
                return {'error': 'constraints.excludeWater must be true or false.'}
            try:
                max_slope = float(max_slope)
            except (TypeError, ValueError):
                return {'error': 'constraints.maxSlope must be degrees from 0 to 90.'}
            if not math.isfinite(max_slope) or not 0 <= max_slope <= 90:
                return {'error': 'constraints.maxSlope must be degrees from 0 to 90.'}
            wc = ee.Image('ESA/WorldCover/v200/2021').select(0).clip(geom)
            constrained = score.updateMask(wc.neq(80)) if exclude_water else score
            constrained = constrained.updateMask(slope_img.lte(max_slope))
            cls = ee.Image(1).where(constrained.gte(0.25).And(constrained.lt(0.5)), 2).where(constrained.gte(0.5).And(constrained.lt(0.75)), 3).where(constrained.gte(0.75), 4).rename('suitability_class').clip(geom)
            # Export the continuous weighted score; the displayed map is the
            # classified result. Both rasters are actual Earth Engine images.
            tile = self._tile(cls, {'min': 1, 'max': 4, 'palette': ['#FF0000', '#FFFF00', '#91cf60', '#1a9850']})
            stats = self._class_areas(cls, geom, 30, {1: 'Very low (0–0.25)', 2: 'Low (0.25–0.50)', 3: 'Moderate (0.50–0.75)', 4: 'High (0.75–1.00)'})
            mean_score = self._stats4(constrained, geom, 30, 'suitability').get('Mean')
            wtxt = ', '.join(f'{k}={v:.2f}' for k, v in w.items())
            scenario_rows = []
            if scenarios is not None:
                if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= 6:
                    return {'error': 'scenarios must be a list of 1–6 named weight objects.'}
                for scenario in scenarios:
                    if not isinstance(scenario, dict) or not isinstance(scenario.get('weights'), dict):
                        return {'error': 'Each scenario requires {name, weights:{criterion:weight}}.'}
                    sw = validate_weights(scenario['weights'], available)
                    missing = set(sw) - set(fns)
                    if missing:
                        return {'error': f'Scenario uses unavailable criteria: {", ".join(sorted(missing))}.'}
                    scenario_score = None
                    for k, wt in sw.items():
                        f = fns[k]
                        if k != 'landcover':
                            f = f.resample('bilinear').reproject(crs=target_projection)
                        scenario_score = f.multiply(wt) if scenario_score is None else scenario_score.add(f.multiply(wt))
                    scenario_score = scenario_score.updateMask(wc.neq(80)) if exclude_water else scenario_score
                    scenario_score = scenario_score.updateMask(slope_img.lte(max_slope)).rename('score')
                    sv = self._stats4(scenario_score, geom, 30, 'score').get('Mean')
                    scenario_rows.append({'scenario': str(scenario.get('name') or f'Scenario {len(scenario_rows)+1}'), 'mean_suitability': sv})
            if sensitivity:
                if not isinstance(sensitivity, (bool, dict)):
                    return {'error': 'sensitivity must be true or an object with perturbation (default 0.1).'}
                perturbation = float(sensitivity.get('perturbation', 0.1)) if isinstance(sensitivity, dict) else 0.1
                if not math.isfinite(perturbation) or not 0 < perturbation <= 0.5:
                    return {'error': 'sensitivity.perturbation must be in (0, 0.5].'}
                for criterion in w:
                    for sign, suffix in ((-1, '−'), (1, '+')):
                        changed = dict(w)
                        changed[criterion] = max(0, changed[criterion] * (1 + sign * perturbation))
                        changed = validate_weights(changed, available)
                        changed_score = None
                        for key, weight_value in changed.items():
                            factor = fns[key]
                            if key != 'landcover':
                                factor = factor.resample('bilinear').reproject(crs=target_projection)
                            changed_score = factor.multiply(weight_value) if changed_score is None else changed_score.add(factor.multiply(weight_value))
                        changed_score = changed_score.updateMask(wc.neq(80)) if exclude_water else changed_score
                        changed_score = changed_score.updateMask(slope_img.lte(max_slope)).rename('score')
                        changed_mean = self._stats4(changed_score, geom, 30, 'score').get('Mean')
                        scenario_rows.append({'scenario': f'{criterion} {suffix}{perturbation:.0%}', 'mean_suitability': changed_mean})
            legend = [{'value': 1, 'label': 'Very low (0–0.25)', 'color': '#FF0000'},
                      {'value': 2, 'label': 'Low (0.25–0.50)', 'color': '#FFFF00'},
                      {'value': 3, 'label': 'Moderate (0.50–0.75)', 'color': '#91cf60'},
                      {'value': 4, 'label': 'High (0.75–1.00)', 'color': '#1a9850'}]
            stats.update({'Mean continuous score (0–1)': mean_score, 'Weights': wtxt,
                          'Method': 'AHP weights + WLC' if suitability_method == 'ahp' else 'Weighted Linear Combination',
                          'Normalization': 'Slope: inverse 0–30°; NDVI: −1..1 to 0..1; rainfall: 0–2000 mm/year; elevation: inverse 0–3000m; WorldCover ordinal compatibility values: 10=.6, 20=.7, 30=.8, 40=.9, 50=.2, 60=.3, 70=.2, 80=.0, 90=.7, 95=.6, 100=.5.',
                          'Resolution': '30m SRTM grid; CHIRPS rainfall criterion has coarser native resolution.',
                          'Rainfall period': 'Year-to-date (current calendar year incomplete)' if y == datetime.now().year and 'rainfall' in w else 'Calendar-year accumulation' if 'rainfall' in w else 'Not used'})
            return {'type': 'Suitability', 'label': f'{u.title()} Suitability',
                    'stats': stats, 'tileUrl': tile, 'chartData': scenario_rows or None,
                    'interpretation': f'{"AHP-derived" if suitability_method == "ahp" else "User-entered"} weights ({wtxt}) applied with WLC. Constraints: {"water excluded" if exclude_water else "water allowed"}; slope ≤{max_slope:g}°. Factor transforms are documented screening scales; output is relative suitability, not yield or engineering certification.',
                    'legend': legend, 'scale': 30}

        elif analysis == 'trend':
            var = (variable or 'ndvi').lower()
            trendable_indices = {item.lower() for item in SPECTRAL_INDICES if item != 'DNBR'}
            if var not in ('rainfall', 'lst', 'et', 'no2') and var not in trendable_indices:
                var = 'ndvi'
            y1 = min(year, year2) if year2 else min(year, 2024)
            y2c = max(year, year2) if year2 else 2024
            y1, y2c = max(1985, y1), min(2026, y2c)
            if y2c - y1 > 11:
                y1 = y2c - 11
            years_list = list(range(y1, y2c + 1))
            if var == 'rainfall':
                def _v(yr):
                    img = (ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterBounds(geom)
                           .filter(ee.Filter.calendarRange(yr, yr, 'year')).select('precipitation').sum())
                    return img.reduceRegion(ee.Reducer.mean(), geom, 5000, maxPixels=int(1e9), bestEffort=True).get('precipitation')
                unit = 'mm'
            elif var == 'lst':
                def _v(yr):
                    img = (ee.ImageCollection('MODIS/061/MOD11A1').filterBounds(geom)
                           .filter(ee.Filter.calendarRange(max(2000, yr), max(2000, yr), 'year'))
                           .select('LST_Day_1km').median().multiply(0.02).subtract(273.15))
                    return img.reduceRegion(ee.Reducer.mean(), geom, 1000, maxPixels=int(1e9), bestEffort=True).get('LST_Day_1km')
                unit = '°C'
            elif var == 'et':
                def _v(yr):
                    img = (ee.ImageCollection('MODIS/061/MOD16A2').filterBounds(geom)
                           .filter(ee.Filter.calendarRange(max(2001, yr), max(2001, yr), 'year'))
                           .select('ET').sum().multiply(0.1))
                    return img.reduceRegion(ee.Reducer.mean(), geom, 500, maxPixels=int(1e9), bestEffort=True).get('ET')
                unit = 'mm'
            elif var == 'no2':
                def _v(yr):
                    img = (ee.ImageCollection('COPERNICUS/S5P/OFFL/L3_NO2').filterBounds(geom)
                           .filter(ee.Filter.calendarRange(max(2018, yr), max(2018, yr), 'year'))
                           .select('tropospheric_NO2_column_number_density').median().multiply(1e6))
                    return img.reduceRegion(ee.Reducer.mean(), geom, 7000, maxPixels=int(1e9), bestEffort=True).get('tropospheric_NO2_column_number_density')
                unit = 'µmol/m²'
            else:
                idx = var.upper()
                B = self._bands(source)
                def _v(yr):
                    c = self._collection(geom, f'{yr}-01-01', f'{yr}-12-31', source, max_cloud)
                    img, _, _ = self._spectral(c, B, idx)
                    return img.reduceRegion(ee.Reducer.mean(), geom, 10, maxPixels=int(1e9), bestEffort=True).get(idx)
                unit = 'index'
            seq = ee.List([ee.Dictionary({'year': yr, 'value': _v(yr)}) for yr in years_list])
            raw_series = seq.getInfo()
            pts = []
            for item in raw_series:
                try:
                    v = float(item.get('value')) if item.get('value') is not None else None
                except (TypeError, ValueError):
                    v = None
                if v is not None:
                    pts.append((int(item.get('year')), v))
            if len(pts) < 3:
                return {'error': f'Not enough {var} observations {y1}–{y2c} for a trend (need ≥3 years).'}
            xs = [p[0] for p in pts]
            vs = [p[1] for p in pts]
            npts = len(pts)
            trend = trend_statistics(xs, vs)
            slope, intercept, r2 = trend['ols_slope'], trend['intercept'], trend['r2']
            sen_slope, S, Z, p_val = trend['sen_slope'], trend['mk_s'], trend['mk_z'], trend['mk_p']
            direction = 'increasing' if sen_slope > 0 else ('decreasing' if sen_slope < 0 else 'flat')
            signif = 'significant at α=0.05' if p_val < 0.05 else 'not significant at α=0.05'
            chart = [{'year': str(x), 'value': round(v, 4)} for x, v in pts]
            which = (test or 'both').lower()
            stats = {str(x): round(v, 4) for x, v in pts}
            if which in ('regression', 'both'):
                stats.update({'Slope': f'{slope:+.5f} {unit}/yr', 'Intercept': round(intercept, 4), 'R²': round(r2, 4)})
            if which in ('mannkendall', 'mann-kendall', 'mk', 'both'):
                stats.update({'MK S': S, 'MK Z': round(Z, 3), 'MK p': round(p_val, 4), 'Sen slope': f'{sen_slope:+.5f} {unit}/yr',
                              'MK verdict': f'{direction}, {signif}'})
            return {'type': 'Trend', 'label': f'{var.upper()} Trend ({y1}–{y2c})',
                    'stats': stats, 'chartData': chart, 'tileUrl': None,
                    'interpretation': (f'{var} {y1}–{y2c} ({npts} annual means): OLS slope {slope:+.5f} {unit}/yr (R²={r2:.3f}); '
                                       f'Sen slope {sen_slope:+.5f} {unit}/yr; Mann-Kendall S={S}, Z={Z:.2f}, p={p_val:.4f} ({signif}). '
                                       'Normal approximation; no autocorrelation correction.'),
                    'legend': {'type': 'continuous', 'min': y1, 'max': y2c, 'unit': 'year'}, 'scale': 10}

        elif analysis == 'waterlogging':
            y = year
            s2y = self._collection(geom, f'{y}-01-01', f'{y}-12-31', 'sentinel2', max_cloud)
            mndwi = s2y.normalizedDifference(['B3', 'B11']).rename('m')
            ndvi_img = s2y.normalizedDifference(['B8', 'B4']).rename('v')
            dem = ee.Image('USGS/SRTMGL1_003').clip(geom)
            slope_img = ee.Terrain.slope(dem)
            # Waterlogged ≠ open water: wet soil/sparse veg on flat lowland.
            wl = mndwi.gt(-0.1).And(mndwi.lt(0.3)).And(slope_img.lt(5)).And(ndvi_img.lt(0.4)).rename('wl')
            tile = self._tile(wl.selfMask(), {'min': 0, 'max': 1, 'palette': ['#FF9800']})
            stats = self._class_areas(wl, geom, 10, {0: 'Not waterlogged', 1: 'Waterlogged'})
            return {'type': 'Waterlogging', 'label': f'Waterlogging ({y})',
                    'stats': stats, 'tileUrl': tile,
                    'interpretation': ('Waterlogging proxy: −0.1<MNDWI<0.3 + slope<5° + NDVI<0.4. '
                                       'Distinct from open water bodies (see NDWI/MNDWI). Field-check before drainage decisions.'),
                    'legend': [{'value': 0, 'label': 'Not waterlogged', 'color': '#e0e0e0'},
                               {'value': 1, 'label': 'Waterlogged', 'color': '#FF9800'}],
                    'scale': 10}

        else:
            return {'error': (
                f"Unknown analysis: {analysis}. Available: {', '.join(IMPLEMENTED_ANALYSES)}. "
                "Try 'what can you analyze?' in the assistant.")}

    def _run_simple_analysis(self, analysis, geometry, year, num_classes, source):
        """Simple analysis using bridge's GEE (no user session)."""
        try:
            geom = self._geom(geometry)
            start, end = f'{year}-01-01', f'{year}-12-31'

            def mask_s2(i):
                qa = i.select('QA60')
                return i.updateMask(qa.bitwiseAnd(1<<10).eq(0).And(qa.bitwiseAnd(1<<11).eq(0))).divide(10000)

            s2 = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')\
                .filterBounds(geom).filterDate(start, end)\
                .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 30))\
                .map(mask_s2).median().clip(geom)

            if analysis == 'ndvi':
                img = s2.normalizedDifference(['B8','B4']).rename('NDVI')
                s = img.reduceRegion(reducer=ee.Reducer.mean(),geometry=geom,scale=10,maxPixels=1e9).getInfo()
                m = s.get('NDVI',0)
                tile = img.getMapId({'min':-0.2,'max':0.8,'palette':['red','yellow','green']})
                url = f"https://earthengine.googleapis.com/v1/{tile['mapid']}/tiles/{{z}}/{{x}}/{{y}}?token={tile['token']}"
                return {'type':'NDVI','label':f'NDVI ({year})','stats':{'Mean':round(m,4)},'tileUrl':url,'interpretation':m>0.6 and 'Dense vegetation' or m>0.3 and 'Moderate' or 'Sparse'}

            elif analysis == 'ndwi':
                img = s2.normalizedDifference(['B3','B8']).rename('NDWI')
                s = img.reduceRegion(reducer=ee.Reducer.mean(),geometry=geom,scale=10,maxPixels=1e9).getInfo()
                m = s.get('NDWI',0)
                tile = img.getMapId({'min':-1,'max':1,'palette':['#8B4513','#FFD700','#00BFFF']})
                url = f"https://earthengine.googleapis.com/v1/{tile['mapid']}/tiles/{{z}}/{{x}}/{{y}}?token={tile['token']}"
                return {'type':'NDWI','label':f'NDWI ({year})','stats':{'Mean':round(m,4)},'tileUrl':url,'interpretation':m>0 and 'Water present' or 'Dry'}

            elif analysis == 'ndbi':
                img = s2.normalizedDifference(['B11','B8']).rename('NDBI')
                s = img.reduceRegion(reducer=ee.Reducer.mean(),geometry=geom,scale=10,maxPixels=1e9).getInfo()
                m = s.get('NDBI',0)
                tile = img.getMapId({'min':-0.3,'max':0.3,'palette':['#00FF00','#FFFF00','#FF0000']})
                url = f"https://earthengine.googleapis.com/v1/{tile['mapid']}/tiles/{{z}}/{{x}}/{{y}}?token={tile['token']}"
                return {'type':'NDBI','label':f'NDBI ({year})','stats':{'Mean':round(m,4)},'tileUrl':url,'interpretation':m>0.1 and 'Urban area' or 'Non-urban'}

            elif analysis == 'elevation':
                dem = ee.Image('USGS/SRTMGL1_003').clip(geom)
                s = dem.reduceRegion(reducer=ee.Reducer.mean(),geometry=geom,scale=30,maxPixels=1e9).getInfo()
                m = s.get('elevation',0)
                tile = dem.getMapId({'min':0,'max':300,'palette':['#006400','#32CD32','#FFD700','#8B4513']})
                url = f"https://earthengine.googleapis.com/v1/{tile['mapid']}/tiles/{{z}}/{{x}}/{{y}}?token={tile['token']}"
                return {'type':'Elevation','label':'Elevation','stats':{'Mean':f'{m:.1f}m'},'tileUrl':url,'interpretation':f'Mean elevation: {m:.0f}m'}

            elif analysis == 'slope':
                dem = ee.Image('USGS/SRTMGL1_003').clip(geom)
                slp = ee.Terrain.slope(dem)
                s = slp.reduceRegion(reducer=ee.Reducer.mean(),geometry=geom,scale=30,maxPixels=1e9).getInfo()
                m = s.get('slope',0)
                tile = slp.getMapId({'min':0,'max':45,'palette':['green','yellow','orange','red']})
                url = f"https://earthengine.googleapis.com/v1/{tile['mapid']}/tiles/{{z}}/{{x}}/{{y}}?token={tile['token']}"
                return {'type':'Slope','label':'Slope','stats':{'Mean':f'{m:.1f}°'},'tileUrl':url,'interpretation':m>15 and 'Steep' or m>5 and 'Moderate' or 'Flat'}

            elif analysis == 'buildings':
                bld = ee.FeatureCollection('GOOGLE/Research/open-buildings/v3/polygons').filterBounds(geom).filter(ee.Filter.gte('confidence',0.6))
                count = bld.size().getInfo()
                pt = bld.map(lambda f: f.centroid())
                bi = ee.Image().float().paint(pt,1).clip(geom)
                tile = bi.getMapId({'min':0,'max':1,'palette':['transparent','#FF0000']})
                url = f"https://earthengine.googleapis.com/v1/{tile['mapid']}/tiles/{{z}}/{{x}}/{{y}}?token={tile['token']}"
                return {'type':'Buildings','label':'Building Density','stats':{'Count':str(count)},'tileUrl':url,'interpretation':f'{count} buildings detected'}

            else:
                return {'error':f'Unknown analysis: {analysis}'}

        except Exception as e:
            return {'error': str(e), 'trace': traceback.format_exc()}

    def _ee_auth_or_error(self, email):
        try:
            return (None, self._ee_session(email))
        except RuntimeError as exc:
            msg = str(exc)
            code = 400 if msg.startswith('GEE Project ID missing') or msg.startswith('Google Earth Engine is not connected') else 502
            return ({'error': msg}, code), None

    # ===== EXPORT MANAGER: real GEE downloads for QGIS =====
    def _export_dir(self):
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'exports')
        os.makedirs(d, exist_ok=True)
        return d

    def _save_export_file(self, user_id, job_id, analysis, fmt, filename, params, data, ext, mime):
        export_id = secrets.token_hex(12)
        safe_name = re.sub(r'[^A-Za-z0-9_-]', '_', (filename or analysis)[:48]) or 'export'
        path = os.path.join(self._export_dir(), f'{export_id}_{safe_name}{ext}')
        with open(path, 'wb') as f:
            f.write(data)
        now = time.time()
        with connection() as conn:
            conn.execute(
                'INSERT INTO exports (id, user_id, job_id, analysis_type, format, filename, parameters, status, file_path, created_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (export_id, user_id, job_id, analysis, fmt, safe_name + ext, json.dumps(params), 'completed', path, now),
            )
        return {'exportId': export_id, 'format': fmt, 'filename': safe_name + ext,
                'download': f'/api/export/download?id={export_id}', 'mime': mime}

    def _record_export(self, user_id, job_id, analysis, fmt, filename, params, status='pending',
                       download_url=None, file_path=None, ee_task_id=None, error=None):
        export_id = secrets.token_hex(12)
        with connection() as conn:
            conn.execute(
                'INSERT INTO exports (id, user_id, job_id, analysis_type, format, filename, parameters, status, '
                'download_url, file_path, ee_task_id, error_message, created_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (export_id, user_id, job_id, analysis, fmt, filename, json.dumps(params), status,
                 download_url, file_path, ee_task_id, error, time.time()),
            )
        return export_id

    def _export_result(self, body, email=None):
        if not email:
            return {'error': 'Login required. Please register and login first.'}, 401
        fmt = (body.get('format') or '').strip().lower().lstrip('.')
        aliases = {'tif': 'geotiff', 'tiff': 'geotiff', 'geotiff': 'geotiff', 'cog': 'geotiff',
                   'png': 'png', 'csv': 'csv', 'geojson': 'geojson', 'json': 'geojson',
                   'shp': 'shp', 'shapefile': 'shp', 'kml': 'kml', 'kmz': 'kmz', 'xlsx': 'csv'}
        fmt = aliases.get(fmt, fmt)
        if fmt not in ('geotiff', 'png', 'csv', 'geojson', 'shp', 'kml', 'kmz'):
            return {'error': 'Unsupported format. Use GeoTIFF, PNG, CSV, GeoJSON, Shapefile, KML or KMZ.'}, 400
        filename = re.sub(r'[^A-Za-z0-9_-]', '_', str(body.get('filename') or '')[:48]) or None
        try:
            scale = int(body.get('scale', 0) or 0)
            if scale and not 1 <= scale <= 10000:
                raise ValueError()
        except (TypeError, ValueError):
            return {'error': 'scale must be 1–10000 (meters/pixel).'}, 400
        crs = (body.get('crs') or 'EPSG:4326').strip()[:32]
        # Resolve analysis + params + geometry: live body wins, else stored result.
        analysis, params, geometry, job_id, stored = None, {}, None, None, None
        result_id = (body.get('resultId') or '').strip() or None
        user = get_user(email)
        if result_id:
            with connection() as conn:
                r = conn.execute(
                    'SELECT r.result_json, j.id AS job_id, j.analysis_type, j.parameters FROM analysis_results r '
                    'JOIN analysis_jobs j ON j.id = r.job_id WHERE r.id = ? AND r.user_id = ?',
                    (result_id, user['id'])).fetchone()
            if not r:
                return {'error': 'Result not found.'}, 404
            stored = json.loads(r['result_json'])
            job_params = json.loads(r['parameters'] or '{}')
            analysis = (body.get('analysis') or r['analysis_type']).strip().lower()
            params = dict(job_params)
            geometry = body.get('geometry') or job_params.get('geometry')
            job_id = r['job_id']
        else:
            analysis = (body.get('analysis') or '').strip().lower()
            geometry = body.get('geometry')
            job_id = (body.get('jobId') or '').strip() or None
        if analysis not in IMPLEMENTED_ANALYSES:
            return {'error': f'Unknown analysis: {analysis}.'}, 400
        if not geometry:
            return {'error': 'No geometry for export. Pass geometry or a resultId with stored AOI.'}, 400
        filename = filename or f'{analysis}_{params.get("year", 2024) if isinstance(params, dict) else analysis}'
        err, sess = self._ee_auth_or_error(email)
        if err:
            return err
        # CSV of stored statistics needs no recompute.
        if fmt == 'csv' and stored and not body.get('geometry'):
            stats = stored.get('statistics', stored.get('stats', {}))
            lines = ['key,value']
            for k, v in (stats.items() if isinstance(stats, dict) else []):
                lines.append(f'"{k}","{v}"')
            if stored.get('transition'):
                lines.append('transition_from_to,hectares,square_kilometres,percent_of_AOI')
                for k, v in stored['transition'].items():
                    if isinstance(v, dict):
                        lines.append(f'"{k}",{v.get("hectares", "")},{v.get("square_kilometres", "")},{v.get("percent_of_AOI", "")}')
                    else:
                        lines.append(f'"{k}","{v}",,')
            if stored.get('transitionByPeriod'):
                lines.append('period,transition_from_to,hectares,square_kilometres,percent_of_AOI')
                for period, rows in stored['transitionByPeriod'].items():
                    for label, values in (rows or {}).items():
                        lines.append(f'"{period}","{label}",{values.get("hectares", "")},{values.get("square_kilometres", "")},{values.get("percent_of_AOI", "")}')
            if stored.get('accuracy'):
                lines.append('accuracy_metric,value')
                for k, v in stored['accuracy'].items():
                    if not isinstance(v, (dict, list)):
                        lines.append(f'"{k}","{v}"')
            meta = (f'# analysis: {analysis}\n# label: {stored.get("label", "")}\n'
                    f'# dataset: {(stored.get("metadata") or {}).get("dataset", "")}\n'
                    f'# parameters: {json.dumps({k: v for k, v in params.items() if k != "geometry"})}\n')
            saved = self._save_export_file(user['id'], job_id, analysis, 'csv', filename, params,
                                           (meta + '\n'.join(lines)).encode('utf-8'), '.csv', 'text/csv')
            return {'status': 'completed', 'exportId': saved['exportId'], 'filename': saved['filename'],
                    'download': saved['download'], 'format': 'csv',
                    'message': 'Statistics CSV ready — opens directly in QGIS/Excel.'}
        # Fresh rebuild to capture the REAL raster (never a screenshot).
        try:
            geom = self._geom_any(geometry)
        except Exception as exc:
            return {'error': str(exc)}, 400
        full_body = dict(params)
        full_body.update({k: v for k, v in body.items() if v is not None})
        full_body['analysis'], full_body['geometry'] = analysis, geometry
        try:
            print(f'[EXPORT] {email} -> {analysis} [{fmt}]')
            result = self._run_analysis_impl(
                analysis, geom, int(full_body.get('year', 2024)), int(full_body.get('year2', 2020)),
                int(full_body.get('numClasses', 5)), str(full_body.get('source', 'sentinel2')),
                float(full_body.get('maxCloud', 30)),
                class_names=_parse_class_names(full_body.get('classNames')),
                algorithm=str(full_body.get('algorithm', 'random_forest')),
                method=full_body.get('method'), variable=full_body.get('variable'),
                index=(full_body.get('index') or '').upper() or None, mode=full_body.get('mode'),
                thresholds=full_body.get('thresholds'), period=str(full_body.get('period', 'annual')),
                month=full_body.get('month'), season=full_body.get('season'), months=full_body.get('months'),
                indicator=full_body.get('indicator'), pollutant=full_body.get('pollutant'),
                ratio_num=(full_body.get('ratio') or {}).get('num') if isinstance(full_body.get('ratio'), dict) else None,
                ratio_den=(full_body.get('ratio') or {}).get('den') if isinstance(full_body.get('ratio'), dict) else None,
                preset=full_body.get('preset'), use=str(full_body.get('use', 'residential')),
                weights=full_body.get('weights'), test=str(full_body.get('test', 'both')),
                tune=bool(full_body.get('tune', False)), stats_op=full_body.get('statsOp'),
                suitability_method=str(full_body.get('suitabilityMethod', 'wlc')),
                constraints=full_body.get('constraints'), sensitivity=full_body.get('sensitivity'),
                scenarios=full_body.get('scenarios'),
                training_samples=full_body.get('trainingSamples'),
                validation_samples=full_body.get('validationSamples'),
                class_property=full_body.get('classProperty', 'class'),
                feature_selection=full_body.get('featureSelection'),
                model_config=full_body.get('modelConfig'), balance_classes=bool(full_body.get('balanceClasses', False)),
                comparison_years=full_body.get('comparisonYears'))
            if result.get('error'):
                raise RuntimeError(result['error'])
            img = getattr(self, '_export_image', None)
            if img is None:
                raise RuntimeError('This analysis exposes no raster for export.')
            legend = result.get('legend', [])
            default_scale = result.get('scale', 30) or 30
            use_scale = scale or default_scale
            if fmt == 'geotiff':
                try:
                    url = img.getDownloadURL({'scale': use_scale, 'crs': crs, 'region': geom, 'format': 'GEO_TIFF'})
                except Exception as exc:
                    if any(w in str(exc).lower() for w in ('too large', 'size', 'pixels', 'limit', 'memory')):
                        try:
                            task = ee.batch.Export.image.toDrive({'image': img, 'description': filename[:100],
                                                                  'fileNamePrefix': filename[:100], 'scale': use_scale,
                                                                  'crs': crs, 'region': geom, 'maxPixels': int(1e9)})
                            task.start()
                            export_id = self._record_export(user['id'], job_id, analysis, 'geotiff', filename + '.tif',
                                                            params, status='running', ee_task_id=task.id)
                            return {'status': 'running', 'exportId': export_id, 'eeTaskId': task.id,
                                    'message': 'Region too large for direct download — Drive export task started. Poll status.'}
                        except Exception as exc2:
                            eid = self._record_export(user['id'], job_id, analysis, 'geotiff', filename + '.tif',
                                                      params, status='failed', error=str(exc2)[:500])
                            return {'error': f'Drive export unavailable ({str(exc2)[:200]}). Try a smaller region or coarser scale.'}, 502
                    raise
                export_id = self._record_export(user['id'], job_id, analysis, 'geotiff', filename + '.tif',
                                                params, status='completed', download_url=url)
                return {'status': 'completed', 'exportId': export_id, 'downloadUrl': url,
                        'filename': filename + '.tif', 'format': 'geotiff', 'scale': use_scale, 'crs': crs,
                        'message': 'QGIS-ready GeoTIFF (real georeferenced raster, EPSG as requested). Layer → Add Raster Layer.'}
            if fmt == 'png':
                vis = dict(getattr(self, '_export_vis', {}) or {})
                thumb = img.getThumbURL({'region': geom, 'dimensions': 1024, **{k: v for k, v in vis.items() if k in ('min', 'max', 'palette', 'bands', 'gamma')}})
                export_id = self._record_export(user['id'], job_id, analysis, 'png', filename + '.png',
                                                params, status='completed', download_url=thumb)
                return {'status': 'completed', 'exportId': export_id, 'downloadUrl': thumb,
                        'filename': filename + '.png', 'format': 'png',
                        'message': 'Rendered PNG preview of the actual result (not QGIS data — use GeoTIFF for analysis).'}
            # Vector family: only categorical rasters (never blindly convert continuous).
            if not (isinstance(legend, list) and legend):
                return {'error': f'This result is continuous raster — Shapefile/GeoJSON/KML are not applicable. Use GeoTIFF for QGIS.'}, 400
            try:
                vectors = img.reduceToVectors(geometry=geom, scale=use_scale, geometryType='polygon',
                                              eightConnected=False, labelProperty='class',
                                              maxPixels=int(1e9), bestEffort=True)
                feats = (vectors.limit(2000).getInfo() or {}).get('features', [])
            except Exception as exc:
                return {'error': f'Vectorization failed ({str(exc)[:200]}). Try a coarser scale.'}, 502
            if not feats:
                return {'error': 'Nothing to vectorize in this AOI.'}, 400
            names = {l.get('value'): l.get('label') for l in legend if isinstance(l, dict)}
            for f in feats:
                props = f.setdefault('properties', {})
                code = props.get('class')
                props['class_id'] = code
                props['class_name'] = names.get(code, str(code))
                props['area_ha'] = round(_approx_area_ha(f.get('geometry')), 2)
                props['source'] = f'{analysis}'
            if fmt == 'geojson':
                saved = self._save_export_file(user['id'], job_id, analysis, 'geojson', filename, params,
                                               json.dumps({'type': 'FeatureCollection', 'features': feats}).encode('utf-8'),
                                               '.geojson', 'application/geo+json')
            elif fmt == 'kml':
                saved = self._save_export_file(user['id'], job_id, analysis, 'kml', filename, params,
                                               _features_to_kml(feats, filename).encode('utf-8'), '.kml',
                                               'application/vnd.google-earth.kml+xml')
            elif fmt == 'kmz':
                import zipfile, io
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
                    z.writestr('doc.kml', _features_to_kml(feats, filename))
                saved = self._save_export_file(user['id'], job_id, analysis, 'kmz', filename, params,
                                               buf.getvalue(), '.kmz', 'application/vnd.google-earth.kmz')
            else:  # shp
                import io
                blobs = _features_to_shapefile(feats)
                if blobs is None:
                    return {'error': 'Shapefile writing supports Polygon/MultiPolygon/Point only.'}, 400
                import zipfile
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
                    z.writestr(filename + '.shp', blobs[0])
                    z.writestr(filename + '.shx', blobs[1])
                    z.writestr(filename + '.dbf', blobs[2])
                saved = self._save_export_file(user['id'], job_id, analysis, 'shp', filename, params,
                                               buf.getvalue(), '.zip', 'application/zip')
                saved['filename'] = filename + '.zip (shp+shx+dbf inside)'
            return {'status': 'completed', 'exportId': saved['exportId'], 'filename': saved['filename'],
                    'download': saved['download'], 'format': fmt, 'features': len(feats),
                    'message': f'QGIS-ready vector ({len(feats)} features, class_id/class_name/area_ha). Vector → Add Vector Layer.'}
        except Exception as exc:
            message = _gee_error_message(exc)
            self._record_export(user['id'], job_id, analysis, fmt, (filename or analysis), params,
                                status='failed', error=message[:500])
            return {'error': message}, 502

    def _export_boundary(self, body, email=None):
        if not email:
            return {'error': 'Login required. Please register and login first.'}, 401
        fmt = (body.get('format') or 'geojson').strip().lower().lstrip('.')
        fmt = {'tif': 'geojson', 'shp': 'shp', 'shapefile': 'shp', 'kml': 'kml',
               'kmz': 'kmz', 'csv': 'csv', 'json': 'geojson', 'geojson': 'geojson'}.get(fmt, fmt)
        if fmt not in ('geojson', 'shp', 'kml', 'kmz', 'csv'):
            return {'error': 'Boundary formats: GeoJSON, Shapefile, KML, KMZ, CSV.'}, 400
        feats = []
        fc = body.get('features') or body.get('featureCollection')
        if isinstance(fc, dict) and fc.get('type') == 'FeatureCollection':
            feats = [f for f in (fc.get('features') or []) if isinstance(f, dict)]
        elif isinstance(body.get('geometry'), dict):
            feats = [{'type': 'Feature', 'properties': {}, 'geometry': body.get('geometry')}]
        if not feats:
            return {'error': 'No boundary features provided.'}, 400
        if len(feats) > 2000:
            return {'error': f'Too many features ({len(feats)}). Max 2000 — filter first.'}, 400
        user = get_user(email)
        filename = re.sub(r'[^A-Za-z0-9_-]', '_', str(body.get('filename') or 'boundary')[:48]) or 'boundary'
        params = {'count': len(feats)}
        if fmt == 'geojson':
            saved = self._save_export_file(user['id'], None, 'boundary', 'geojson', filename, params,
                                           json.dumps({'type': 'FeatureCollection', 'features': feats}).encode('utf-8'),
                                           '.geojson', 'application/geo+json')
        elif fmt == 'csv':
            keys = []
            for f in feats:
                for k in (f.get('properties') or {}):
                    if k not in keys:
                        keys.append(str(k))
            keys = keys[:30]
            lines = ['wkt' + (',' + ','.join(f'"{k}"' for k in keys) if keys else '')]
            for f in feats:
                props = f.get('properties') or {}
                lines.append('"' + json.dumps(f.get('geometry')).replace('"', '""') + '"' +
                             ''.join(f',"{props.get(k, "")}"' for k in keys))
            saved = self._save_export_file(user['id'], None, 'boundary', 'csv', filename, params,
                                           '\n'.join(lines).encode('utf-8'), '.csv', 'text/csv')
        elif fmt == 'kml':
            saved = self._save_export_file(user['id'], None, 'boundary', 'kml', filename, params,
                                           _features_to_kml(feats, filename).encode('utf-8'), '.kml',
                                           'application/vnd.google-earth.kml+xml')
        elif fmt == 'kmz':
            import zipfile, io
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
                z.writestr('doc.kml', _features_to_kml(feats, filename))
            saved = self._save_export_file(user['id'], None, 'boundary', 'kmz', filename, params,
                                           buf.getvalue(), '.kmz', 'application/vnd.google-earth.kmz')
        else:
            blobs = _features_to_shapefile(feats)
            if blobs is None:
                return {'error': 'Shapefile supports Polygon/MultiPolygon/Point layers of one kind.'}, 400
            import zipfile, io
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
                z.writestr(filename + '.shp', blobs[0])
                z.writestr(filename + '.shx', blobs[1])
                z.writestr(filename + '.dbf', blobs[2])
                z.writestr(filename + '.prj', 'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["Degree",0.017453292519943295],AUTHORITY["EPSG","4326"]]')
            saved = self._save_export_file(user['id'], None, 'boundary', 'shp', filename, params,
                                           buf.getvalue(), '.zip', 'application/zip')
            saved['filename'] = filename + '.zip (shp+shx+dbf+prj inside — QGIS-ready)'
        return {'status': 'completed', 'exportId': saved['exportId'], 'filename': saved['filename'],
                'download': saved['download'], 'format': fmt, 'features': len(feats),
                'message': 'Boundary exported with CRS metadata. QGIS: Vector → Add Vector Layer.'}

    def _list_exports(self, email):
        user = get_user(email)
        with connection() as conn:
            rows = conn.execute(
                'SELECT id, analysis_type, format, filename, status, download_url, ee_task_id, error_message, created_at '
                'FROM exports WHERE user_id = ? ORDER BY created_at DESC LIMIT 50', (user['id'],)).fetchall()
        return {'exports': [dict(r) for r in rows]}

    def _export_status(self, task_id, email):
        if not task_id:
            return {'error': 'task id required'}, 400
        err, sess = self._ee_auth_or_error(email)
        if err:
            return err
        try:
            info = ee.data.getTaskStatus([task_id])
            state = (info[0].get('state') if info else 'UNKNOWN') if isinstance(info, list) else 'UNKNOWN'
        except Exception as exc:
            return {'error': str(exc)[:300]}, 502
        mapping = {'READY': 'running', 'RUNNING': 'running', 'COMPLETED': 'completed',
                   'FAILED': 'failed', 'CANCELLED': 'cancelled'}
        with connection() as conn:
            conn.execute('UPDATE exports SET status = ? WHERE ee_task_id = ?', (mapping.get(state, state.lower()), task_id))
        return {'eeTaskId': task_id, 'state': state, 'status': mapping.get(state, state.lower())}

    def _download_export(self, export_id, email):
        user = get_user(email)
        with connection() as conn:
            row = conn.execute('SELECT * FROM exports WHERE id = ? AND user_id = ?', (export_id, user['id'])).fetchone()
        if not row:
            return self._json({'error': 'Export not found.'}, 404)
        row = dict(row)
        if row.get('file_path') and os.path.isfile(row['file_path']):
            mimes = {'.csv': 'text/csv', '.geojson': 'application/geo+json', '.kml': 'application/vnd.google-earth.kml+xml',
                     '.kmz': 'application/vnd.google-earth.kmz', '.zip': 'application/zip', '.tif': 'image/tiff'}
            ext = os.path.splitext(row['file_path'])[1].lower()
            with open(row['file_path'], 'rb') as f:
                data = f.read()
            self.send_response(200)
            self._cors()
            self.send_header('Content-Type', mimes.get(ext, 'application/octet-stream'))
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Content-Disposition', f'attachment; filename="{row["filename"]}"')
            self.end_headers()
            self.wfile.write(data)
            return
        if row.get('download_url'):
            return self._json({'downloadUrl': row['download_url']})
        return self._json({'error': row.get('error_message') or 'Export has no file yet.'}, 404)

    def _get_tile_url_fallback(self, body, email=None):
        if not email:
            return {'error': 'Login required'}, 401
        return self._get_tile_url(body, email)

    # ===== BOUNDARY: zonal statistics + admin boundaries =====
    def _zonal_stats(self, body, email=None):
        if not email:
            return {'error': 'Login required. Please register and login first.'}, 401
        analysis = (body.get('analysis') or 'ndvi').strip().lower()
        if analysis not in IMPLEMENTED_ANALYSES:
            return {'error': f'Unknown analysis: {analysis}.'}, 400
        raw_features = body.get('features')
        if isinstance(raw_features, dict) and raw_features.get('type') == 'FeatureCollection':
            feats = [f for f in (raw_features.get('features') or []) if isinstance(f, dict)]
        elif isinstance(body.get('geometry'), dict):
            feats = [{'type': 'Feature', 'properties': {}, 'geometry': body.get('geometry')}]
        else:
            return {'error': 'Provide features (FeatureCollection, max 50) or a geometry.'}, 400
        if not feats:
            return {'error': 'No features provided.'}, 400
        if len(feats) > 50:
            return {'error': f'Too many features ({len(feats)}). Max 50 per request — split the layer.'}, 400
        blob = json.dumps(feats)
        if len(blob) > 1500000:
            return {'error': 'Boundary is too detailed (>1.5MB). Simplify it first (reduce vertices).'}, 400
        # Optional attribute filter: {field, value} substring, case-insensitive.
        filt = body.get('filter') or {}
        if isinstance(filt, dict) and filt.get('field') and filt.get('value') is not None:
            field, want = str(filt['field']), str(filt['value']).lower()
            kept = [f for f in feats if want in str((f.get('properties') or {}).get(field, '')).lower()
                    or want in str((f.get('properties') or {}).get(field.upper(), '')).lower()]
            if not kept:
                return {'error': f'No feature matches {field} = {filt["value"]}. Check the attribute table.'}, 400
            feats = kept
        label_field = (body.get('labelField') or '').strip() or None
        if not label_field:
            probe_props = {}
            for f in feats:
                for k in (f.get('properties') or {}):
                    probe_props[k] = True
            for cand in ('name', 'NAME', 'Name', 'label', 'LABEL', 'WARD_NAME', 'WARD', 'DISTRICT', 'VILLAGE', 'ID', 'id'):
                if cand in probe_props:
                    label_field = cand
                    break

        err, sess = self._ee_auth_or_error(email)
        if err:
            return err
        user, credentials, project, row = sess
        try:
            ee_feats = [self._feature(f) for f in feats]
            fc = ee.FeatureCollection(ee_feats)
            dissolved = fc.geometry()
        except Exception as exc:
            return {'error': str(exc)}, 400
        # Light param read (strict validation lives in /api/analyze).
        def _int(key, default):
            try:
                return int(body.get(key, default))
            except (TypeError, ValueError):
                return default
        year, year2 = _int('year', 2024), _int('year2', 2020)
        try:
            max_cloud = float(body.get('maxCloud', 30))
        except (TypeError, ValueError):
            max_cloud = 30
        source = (body.get('source') or 'sentinel2').strip().lower()
        kw = dict(year=year, year2=year2, num_classes=_int('numClasses', 5), source=source, max_cloud=max_cloud,
                  class_names=_parse_class_names(body.get('classNames')), algorithm=(body.get('algorithm') or 'random_forest'),
                  method=(body.get('method') or body.get('index') or None), variable=body.get('variable'),
                  index=(body.get('index') or '').upper() or None, mode=body.get('mode'), thresholds=body.get('thresholds'),
                  period=(body.get('period') or 'annual'), month=body.get('month'), season=body.get('season'), months=body.get('months'),
                  indicator=body.get('indicator'), pollutant=body.get('pollutant'),
                  ratio_num=(body.get('ratio') or {}).get('num') if isinstance(body.get('ratio'), dict) else None,
                  ratio_den=(body.get('ratio') or {}).get('den') if isinstance(body.get('ratio'), dict) else None,
                  preset=body.get('preset'), use=(body.get('use') or 'residential'), weights=body.get('weights'),
                  test=(body.get('test') or 'both'), tune=bool(body.get('tune', False)), stats_op=body.get('statsOp'))
        try:
            print(f'[ZONAL] {email} -> {analysis} x{len(feats)}')
            result = self._run_analysis_impl(analysis, dissolved, **kw)
            if result.get('error'):
                raise RuntimeError(result['error'])
            img = getattr(self, '_export_image', None)
            if img is None:
                raise RuntimeError('This analysis exposes no raster for zonal statistics.')
            band = img.bandNames().getInfo()
            band = band[0] if band else None
            legend = result.get('legend', [])
            categorical = isinstance(legend, list) and len(legend) > 0
            rows = []
            for i, ef in enumerate(ee_feats):
                props = feats[i].get('properties') or {}
                label = str(props.get(label_field, f'Feature {i + 1}')) if label_field else f'Feature {i + 1}'
                g = ef.geometry()
                if categorical:
                    grouped = (ee.Image.pixelArea().addBands(img.rename('lc'))
                               .reduceRegion(ee.Reducer.sum().group(1, 'class'), geometry=g,
                                             scale=result.get('scale', 10), maxPixels=int(1e9), bestEffort=True).getInfo())
                    groups = grouped.get('groups', []) or []
                    total = sum(float(x.get('sum', 0)) for x in groups) or 0
                    stats = {}
                    names = {l.get('value'): l.get('label') for l in legend if isinstance(l, dict)}
                    for x in groups:
                        code = x.get('class')
                        ha = float(x.get('sum', 0)) / 1e4
                        stats[str(names.get(code, code))] = f'{ha:.1f} ha ({(ha * 1e4 / total * 100) if total else 0:.1f}%)'
                else:
                    r = img.reduceRegion(ee.Reducer.mean().combine(ee.Reducer.minMax(), '', True),
                                         geometry=g, scale=result.get('scale', 10),
                                         maxPixels=int(1e9), bestEffort=True).getInfo()
                    stats = {}
                    for suffix, name in (('mean', 'Mean'), ('min', 'Min'), ('max', 'Max')):
                        v = r.get(f'{band}_{suffix}') if band else None
                        try:
                            stats[name] = round(float(v), 4) if v is not None else None
                        except (TypeError, ValueError):
                            stats[name] = None
                rows.append({'label': label, **stats})
        except Exception as exc:
            return {'error': _gee_error_message(exc)}, 502
        # Persist CSV + enriched GeoJSON for download (real files, QGIS-ready).
        saved = []
        try:
            user_row = get_user(email)
            csv_text = 'label,' + ','.join(list(rows[0].keys())[1:]) + '\n' + '\n'.join(
                ','.join(f'"{v}"' for v in row.values()) for row in rows)
            saved.append(self._save_export_file(user_row['id'], None, analysis, 'csv',
                                                f'{analysis}_zonal', {'labelField': label_field}, csv_text.encode('utf-8'),
                                                '.csv', 'text/csv'))
            enriched = {'type': 'FeatureCollection', 'features': []}
            for i, f in enumerate(feats):
                nf = {'type': 'Feature', 'properties': dict(f.get('properties') or {}), 'geometry': f.get('geometry')}
                nf['properties'].update({f'zonal_{k}': v for k, v in rows[i].items() if k != 'label'})
                nf['properties']['zonal_label'] = rows[i]['label']
                enriched['features'].append(nf)
            saved.append(self._save_export_file(user_row['id'], None, analysis, 'geojson',
                                                f'{analysis}_zonal', {'labelField': label_field},
                                                json.dumps(enriched).encode('utf-8'), '.geojson', 'application/geo+json'))
        except Exception:
            pass
        return {'type': 'ZonalStatistics', 'label': f'{analysis} by feature', 'rows': rows,
                'count': len(rows), 'labelField': label_field, 'legend': legend,
                'downloads': saved,
                'interpretation': f'Zonal statistics of {analysis} for {len(rows)} feature(s). CSV + GeoJSON saved for QGIS.'}

    def _admin_boundary(self, body, email=None):
        if not email:
            return {'error': 'Login required. Please register and login first.'}, 401
        name = (body.get('name') or '').strip()
        if not name:
            return {'error': 'Provide a name, e.g. {"name": "Mbozi"}.'}, 400
        try:
            level = int(body.get('level', 2))
            level = 1 if level == 1 else 2
        except (TypeError, ValueError):
            level = 2
        parent = (body.get('parent') or '').strip() or None
        err, sess = self._ee_auth_or_error(email)
        if err:
            return err
        try:
            asset = f'FAO/GAUL/2015/level{level}'
            name_field = 'ADM2_NAME' if level == 2 else 'ADM1_NAME'
            variants = list({name, name.upper(), name.title()})
            filt = ee.Filter.inList(name_field, variants)
            for alt in variants:
                filt = filt.Or(ee.Filter.stringContains(name_field, alt))
            gaul = ee.FeatureCollection(asset).filter(filt)
            if parent and level == 2:
                gaul = gaul.filter(ee.Filter.Or(*[ee.Filter.stringContains('ADM1_NAME', v)
                                                  for v in {parent, parent.upper(), parent.title()}]))
            matches = gaul.limit(10).getInfo()
            features = (matches.get('features') or []) if isinstance(matches, dict) else []
            if not features:
                return {'error': f'No administrative boundary found for "{name}" (level {level}). Try level 1, or check spelling.'}, 404
            candidates = []
            for f in features:
                props = f.get('properties', {})
                candidates.append({'name': props.get(name_field), 'parent': props.get('ADM1_NAME') if level == 2 else props.get('ADM0_NAME')})
            fc = {'type': 'FeatureCollection', 'features': features}
            return {'type': 'AdminBoundary', 'label': f'{name} (GAUL level {level})',
                    'featureCollection': fc, 'count': len(features), 'candidates': candidates,
                    'dataset': asset,
                    'interpretation': f'Found {len(features)} boundary feature(s) for "{name}". Add to map and use as AOI.'}
        except Exception as exc:
            return {'error': _gee_error_message(exc)}, 502

    def _get_tile_url(self, body, email):
        row = _connection_for_user(email)
        if not row or not row.get('ee_access_token'):
            return {'error': 'Google Earth Engine is not connected. Connect your Google account to continue.'}, 400
        try:
            credentials = _refresh_connection(
                row, _credentials(unseal(row.get('ee_access_token')), unseal(row.get('ee_refresh_token')), row.get('token_expires_at'))
            )
            _probe_earth_engine(credentials, row['google_project_id'])
        except Exception as exc:
            return {'error': _gee_error_message(exc)}, 502
        analysis = body.get('analysis','rgb')
        geom = self._geom(body.get('geometry'))
        if analysis == 'rgb':
            s2 = self._collection(geom,'2024-01-01','2024-12-31','sentinel2', body.get('maxCloud', 30))
            return {'tileUrl':self._tile(s2,{'min':0,'max':0.3,'bands':['B4','B3','B2'],'gamma':1.4})}
        return {'error':'Unknown tile'}, 400

    # ===== HELPERS =====
    def _geom_any(self, g):
        """Accept Geometry, Feature, or FeatureCollection (dissolved to one geometry)."""
        if not isinstance(g, dict):
            raise ValueError('A valid GeoJSON geometry is required')
        t = g.get('type')
        if t == 'FeatureCollection':
            feats = [f for f in (g.get('features') or []) if isinstance(f, dict)]
            if not feats:
                raise ValueError('FeatureCollection has no features')
            fc = ee.FeatureCollection([self._feature(f) for f in feats])
            return fc.geometry()
        return self._geom(g)

    def _feature(self, f):
        if not isinstance(f, dict):
            raise ValueError('Invalid feature')
        if f.get('type') == 'FeatureCollection':
            raise ValueError('Nested FeatureCollections are not supported here')
        geom = self._geom(f.get('geometry') if f.get('type') == 'Feature' else f)
        props = dict(f.get('properties') or {}) if f.get('type') == 'Feature' else {}
        # Keep only JSON-safe scalar props (no secrets ever enter properties).
        safe = {str(k)[:64]: (v if isinstance(v, (str, int, float, bool)) or v is None else str(v)[:256])
                for k, v in props.items()}
        return ee.Feature(geom, safe)

    def _geom(self, g):
        if not isinstance(g, dict):
            raise ValueError('A valid GeoJSON geometry is required')
        if g.get('type') == 'Feature':
            g = g.get('geometry') or {}
        if g.get('type') == 'FeatureCollection':
            return self._geom_any(g)
        t, coordinates = g.get('type'), g.get('coordinates')
        if not coordinates:
            raise ValueError('A valid GeoJSON geometry is required')
        if t == 'Polygon':
            return ee.Geometry.Polygon(coordinates, None, False)
        if t == 'MultiPolygon':
            return ee.Geometry.MultiPolygon(coordinates)
        if t == 'Point':
            return ee.Geometry.Point(coordinates).buffer(500)
        if t == 'LineString':
            return ee.Geometry.LineString(coordinates).buffer(50)
        raise ValueError(f'Unsupported geometry type: {t}')

    def _collection(self, geom, start, end, source, max_cloud=30, months=None, return_count=False):
        """Cloud/shadow-masked surface-reflectance median; optional scene count."""
        max_cloud = max(0, min(100, float(max_cloud)))
        try:
            if isinstance(end, str) and re.fullmatch(r'\d{4}-12-31', end.strip()):
                end = f'{int(end[:4]) + 1}-01-01'
        except (TypeError, ValueError):
            pass
        if source == 'sentinel2':
            collection = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                          .filterBounds(geom).filterDate(start, end)
                          .filter(ee.Filter.lte('CLOUDY_PIXEL_PERCENTAGE', max_cloud)))
            if months:
                month_filters = [ee.Filter.calendarRange(int(m), int(m), 'month') for m in months]
                month_filter = month_filters[0]
                for item in month_filters[1:]:
                    month_filter = ee.Filter.Or(month_filter, item)
                collection = collection.filter(month_filter)

            def mask_s2(image):
                qa = image.select('QA60')
                scl = image.select('SCL')
                qa_clear = qa.bitwiseAnd(1 << 10).eq(0).And(qa.bitwiseAnd(1 << 11).eq(0))
                # SCL 3=cloud shadow; 8/9=cloud; 10=cirrus. Keep class 11 snow
                # so NDSI remains usable. 0/1 are no-data/saturated pixels.
                scl_clear = (scl.neq(0).And(scl.neq(1)).And(scl.neq(3))
                             .And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10)))
                return (image.select(['B2','B3','B4','B5','B6','B7','B8','B8A','B11','B12'])
                        .updateMask(qa_clear).updateMask(scl_clear).divide(10000))

            collection = collection.map(mask_s2)
        else:
            cid = {'landsat7': 'LANDSAT/LE07/C02/T1_L2',
                   'landsat8': 'LANDSAT/LC08/C02/T1_L2',
                   'landsat9': 'LANDSAT/LC09/C02/T1_L2'}[source]
            collection = (ee.ImageCollection(cid).filterBounds(geom).filterDate(start, end)
                          .filter(ee.Filter.lte('CLOUD_COVER', max_cloud)))
            if months:
                month_filters = [ee.Filter.calendarRange(int(m), int(m), 'month') for m in months]
                month_filter = month_filters[0]
                for item in month_filters[1:]:
                    month_filter = ee.Filter.Or(month_filter, item)
                collection = collection.filter(month_filter)

            def mask_landsat(image):
                qa = image.select('QA_PIXEL')
                # Mask fill, dilated cloud, cirrus (where present), cloud and shadow.
                clear = (qa.bitwiseAnd(1 << 0).eq(0).And(qa.bitwiseAnd(1 << 1).eq(0))
                         .And(qa.bitwiseAnd(1 << 2).eq(0)).And(qa.bitwiseAnd(1 << 3).eq(0))
                         .And(qa.bitwiseAnd(1 << 4).eq(0)))
                band_names = (['SR_B1','SR_B2','SR_B3','SR_B4','SR_B5','SR_B7'] if source == 'landsat7'
                              else ['SR_B2','SR_B3','SR_B4','SR_B5','SR_B6','SR_B7'])
                reflectance = image.select(band_names).updateMask(clear).multiply(0.0000275).add(-0.2)
                thermal_name = 'ST_B6' if source == 'landsat7' else 'ST_B10'
                return reflectance.addBands(image.select(thermal_name).updateMask(clear))

            collection = collection.map(mask_landsat)
        count = collection.size().getInfo() if return_count else None
        if count == 0:
            raise ValueError(f'No {source} scenes match this AOI, date window and cloud filter ({max_cloud}%). Change the period, sensor or cloud limit.')
        composite = collection.median().clip(geom)
        return (composite, int(count)) if return_count else composite

    def _reduce(self, img, geom, scale=10):
        return img.reduceRegion(reducer=ee.Reducer.mean(), geometry=geom, scale=scale, maxPixels=1000000000, bestEffort=True).getInfo()

    def _stats4(self, img, geom, scale, band):
        """Mean/min/max/std in ONE EE request (concurrency-safe)."""
        try:
            r = img.reduceRegion(
                reducer=ee.Reducer.mean().combine(ee.Reducer.minMax(), '', True).combine(
                    ee.Reducer.stdDev(), '', True),
                geometry=geom, scale=scale, maxPixels=int(1e9), bestEffort=True).getInfo()
        except Exception:
            return {}
        out = {}
        for suffix, label in (('mean', 'Mean'), ('min', 'Min'), ('max', 'Max'), ('stdDev', 'Std')):
            try:
                v = r.get(f'{band}_{suffix}')
                out[label] = round(float(v), 4) if v is not None else None
            except (TypeError, ValueError):
                out[label] = None
        return out

    def _bands(self, source):
        """Surface-reflectance band names for the selected sensor product."""
        return sensor_bands(source)

    def _spectral(self, col, B, index):
        """Generic spectral-index engine (register new indices here only).
        B: band dict from _bands(). Returns (image, unit, needs_thermal_note)."""
        idx = (index or '').upper()
        S = lambda k: col.select(B[k])
        E = lambda expr, args: col.expression(expr, {k: S(v) for k, v in args.items()})
        if idx == 'NDVI':
            return col.normalizedDifference([B['NIR'], B['RED']]).rename('NDVI'), 'index', False
        if idx == 'NDWI':
            return col.normalizedDifference([B['GREEN'], B['NIR']]).rename('NDWI'), 'index', False
        if idx == 'MNDWI':
            return col.normalizedDifference([B['GREEN'], B['SWIR1']]).rename('MNDWI'), 'index', False
        if idx == 'SAVI':
            return E('((NIR - RED) / (NIR + RED + 0.5)) * 1.5', {'NIR': 'NIR', 'RED': 'RED'}).rename('SAVI'), 'index', False
        if idx == 'EVI2':
            return E('2.5 * (NIR - RED) / (NIR + 2.4 * RED + 1)', {'NIR': 'NIR', 'RED': 'RED'}).rename('EVI2'), 'index', False
        if idx == 'NDMI':
            return col.normalizedDifference([B['NIR'], B['SWIR1']]).rename('NDMI'), 'index', False
        if idx == 'NBR':
            return col.normalizedDifference([B['NIR'], B['SWIR2']]).rename('NBR'), 'index', False
        if idx == 'NDSI':
            return col.normalizedDifference([B['GREEN'], B['SWIR1']]).rename('NDSI'), 'index', False
        if idx == 'EVI':
            return E('2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
                     {'NIR': 'NIR', 'RED': 'RED', 'BLUE': 'BLUE'}).rename('EVI'), 'index', False
        if idx == 'MSAVI':
            return E('(2 * NIR + 1 - sqrt(pow(2 * NIR + 1, 2) - 8 * (NIR - RED))) / 2',
                     {'NIR': 'NIR', 'RED': 'RED'}).rename('MSAVI'), 'index', False
        if idx == 'NDRE':
            if not B['RE']:
                raise RuntimeError('NDRE needs a red-edge band: re-run with Sentinel-2 (dataset Sentinel-2).')
            return E('(NIR - RE) / (NIR + RE)', {'NIR': 'NIR', 'RE': 'RE'}).rename('NDRE'), 'index', False
        if idx == 'GNDVI':
            return E('(NIR - GREEN) / (NIR + GREEN)', {'NIR': 'NIR', 'GREEN': 'GREEN'}).rename('GNDVI'), 'index', False
        if idx == 'DVI':
            return E('NIR - RED', {'NIR': 'NIR', 'RED': 'RED'}).rename('DVI'), 'reflectance', False
        if idx == 'RVI':
            return E('NIR / max(RED, 0.001)', {'NIR': 'NIR', 'RED': 'RED'}).rename('RVI'), 'ratio', False
        if idx == 'ARVI':
            return E('(NIR - (2 * RED - BLUE)) / (NIR + (2 * RED - BLUE))',
                     {'NIR': 'NIR', 'RED': 'RED', 'BLUE': 'BLUE'}).rename('ARVI'), 'index', False
        if idx == 'BSI':
            return E('((SWIR1 + RED) - (NIR + BLUE)) / ((SWIR1 + RED) + (NIR + BLUE))',
                     {'SWIR1': 'SWIR1', 'RED': 'RED', 'NIR': 'NIR', 'BLUE': 'BLUE'}).rename('BSI'), 'index', False
        if idx == 'NDBI':
            return col.normalizedDifference([B['SWIR1'], B['NIR']]).rename('NDBI'), 'index', False
        if idx == 'UI':
            return E('(SWIR2 - NIR) / (SWIR2 + NIR)', {'SWIR2': 'SWIR2', 'NIR': 'NIR'}).rename('UI'), 'index', False
        if idx == 'IBI':
            ndbi = E('(SWIR1 - NIR) / (SWIR1 + NIR)', {'SWIR1': 'SWIR1', 'NIR': 'NIR'})
            savi = E('((NIR - RED) / (NIR + RED + 0.5)) * 1.5', {'NIR': 'NIR', 'RED': 'RED'})
            mndwi = E('(GREEN - SWIR1) / (GREEN + SWIR1)', {'GREEN': 'GREEN', 'SWIR1': 'SWIR1'})
            ibi = col.expression('(A - (B + C) / 2) / (A + (B + C) / 2)', {'A': ndbi, 'B': savi, 'C': mndwi}).rename('IBI')
            return ibi, 'index', False
        if idx == 'EBBI':
            if not B['THERMAL']:
                raise RuntimeError('EBBI needs a thermal band: re-run with Landsat 8/9.')
            tir = S('THERMAL').multiply(0.00341802).add(149.0)
            ebbi = col.expression('(SWIR1 - NIR) / (10 * sqrt(SWIR1 + TIR))',
                                  {'SWIR1': S('SWIR1'), 'NIR': S('NIR'), 'TIR': tir}).rename('EBBI')
            return ebbi, 'index', True
        if idx == 'AWEI':
            return E('BLUE + 2.5 * GREEN - 1.5 * (NIR + SWIR1) - 0.25 * SWIR2',
                     {'BLUE': 'BLUE', 'GREEN': 'GREEN', 'NIR': 'NIR', 'SWIR1': 'SWIR1', 'SWIR2': 'SWIR2'}
                     ).rename('AWEIsh'), 'index', False
        raise RuntimeError(f'Unknown index {idx}. Available: {", ".join(SPECTRAL_INDICES)}.')

    def _band_code(self, B, code, source):
        """Map sensor-relative codes (B7/B2) to actual band names."""
        code = (code or '').upper()
        if 'landsat' in source:
            m = re.fullmatch(r'B([1-7])', code)
            if m:
                return f'SR_B{m.group(1)}'
            if code in ('B8', 'B8A'):
                return 'SR_B5'
            raise RuntimeError(f'Band {code} not available on Landsat (use B1–B7).')
        s2 = {'B2': 'B2', 'B3': 'B3', 'B4': 'B4', 'B5': 'B5', 'B6': 'B6', 'B7': 'B7',
              'B8': 'B8', 'B8A': 'B8A', 'B11': 'B11', 'B12': 'B12'}
        if code in s2:
            return s2[code]
        raise RuntimeError(f'Band {code} not available on Sentinel-2.')

    def _class_areas(self, classified_img, geom, scale=10, names=None):
        """Real per-class area + percentage + pixel count. Returns {} when empty."""
        try:
            grouped = (ee.Image.pixelArea().addBands(classified_img.rename('lc'))
                       .reduceRegion(reducer=ee.Reducer.sum().group(1, 'class'),
                                     geometry=geom, scale=scale,
                                     maxPixels=int(1e9), bestEffort=True).getInfo())
        except Exception:
            return {}
        groups = grouped.get('groups', []) or []
        try:
            total = sum(float(g.get('sum', 0)) for g in groups)
        except (TypeError, ValueError):
            total = 0
        out = {}
        for g in groups:
            code = g.get('class')
            try:
                m2 = float(g.get('sum', 0))
            except (TypeError, ValueError):
                continue
            ha = m2 / 1e4
            pct = (m2 / total * 100) if total > 0 else 0
            px = int(round(m2 / max(1, scale * scale)))
            label = (names.get(code, str(code)) if names else str(code)) if code is not None else 'Unknown'
            out[str(label)] = f'{ha:.1f} ha / {ha / 100:.3f} km² ({pct:.1f}%, {px} px)'
        return out

    def _class_area_m2(self, mask, geom, scale=10):
        """Real masked area in square metres for change-rate calculations."""
        try:
            value = ee.Image.pixelArea().updateMask(ee.Image(mask)).reduceRegion(
                reducer=ee.Reducer.sum(), geometry=geom, scale=scale,
                maxPixels=int(1e9), bestEffort=True).getInfo()
            return float(next(iter(value.values()), 0) or 0)
        except Exception:
            return 0.0

    def _tile(self, img, vis):
        # Stash the source EE image + vis on this per-request handler so the
        # export manager can rebuild a real download (never a screenshot).
        try:
            self._export_image = img
            self._export_vis = dict(vis or {})
        except Exception:
            pass
        mapid = img.visualize(**vis).getMapId()
        base = ee.data.getTileUrl(mapid, 0, 0, 0)
        token = mapid.get('token', '')
        if token:
            base += f'?token={token}'
        return base.replace('/0/0/0', '/{z}/{x}/{y}')

    def _chat(self, body):
        msg = body.get('message','')
        if not msg.strip():
            return {'reply':'Type a message. / Andika ujumbe.','type':'empty'}
        if GEMINI_API_KEY:
            try: return self._gemini(msg, GEMINI_API_KEY)
            except: pass
        m = msg.lower()
        sw = any(x in m for x in ['habari','mambo','vipi','sasa','swahili','kiswahili','tafadhali','asante',
                                  'nipe','nionyeshe','onyesha','ainisha','mvua','maji','mmea','mimea','ardhi',
                                  'mafuriko','ukame','mteremko','joto','madini','misitu','mazao','eneo'])
        if any(x in m for x in ['hi','hello','habari','mambo','vipi','hujambo','shikamoo']):
            if sw or any(x in m for x in ['habari','mambo','vipi','hujambo','shikamoo']):
                return {'reply':("Habari! Mimi ni Msaidizi wako wa GIS. Chora poligoni kwenye ramani, "
                                 "kisha niulize chochote: 'onyesha mimea', 'onyesha maji', 'ainisha ardhi'."),'type':'chat'}
            return {'reply':"Hello! I'm your GIS assistant. Draw a polygon and ask me to analyze it.",'type':'chat'}
        if sw:
            return {'reply':("Chora poligoni, kisha sema: 'onyesha mimea', 'onyesha maji', "
                             "'ainisha ardhi katika madarasa 5', 'onyesha mvua'."),'type':'chat'}
        return {'reply':"Draw a polygon, then ask: 'show vegetation', 'water bodies', 'classify land'",'type':'chat'}

    def _gemini(self, msg, key):
        data = json.dumps({'contents':[{'parts':[{'text':f'You are a GIS assistant. Reply in user language. If analysis requested, prepend [ANALYSIS:type]. User: {msg}'}]}],'generationConfig':{'maxOutputTokens':300}}).encode()
        req = urllib.request.Request(f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}',data=data,headers={'Content-Type':'application/json'})
        r = urllib.request.urlopen(req,timeout=20)
        result = json.loads(r.read())
        return {'reply':result['candidates'][0]['content']['parts'][0]['text'],'type':'llm'}

    def _admin_delete_user(self, body):
        admin_key = self.headers.get('X-Admin-Key','')
        if not ADMIN_KEY or admin_key != ADMIN_KEY:
            return {'error': 'Invalid admin key'}, 403
        email = (body.get('email') or '').strip().lower()
        if not email:
            return {'error': 'Email required'}, 400
        user = get_user(email)
        if not user:
            return {'error': 'User not found'}, 404
        with connection() as conn:
            conn.execute('DELETE FROM users WHERE id = ?', (user['id'],))
        return {'deleted': True, 'email': email}

    def _execute_code(self, body, email):
        return {
            'error': 'The server-side code editor is disabled for security. Use a named analysis instead.'
        }, 403

    def log_message(self, fmt, *args):
        print(f'[{self.log_date_time_string()}] {args[0]}')

def _startup_secret_warnings():
    for key in ('SESSION_SECRET', 'TOKEN_ENCRYPTION_KEY'):
        value = os.getenv(key, '').strip()
        if not value:
            print(f'[WARN] {key} is not set. Encrypted EE tokens/sessions will fail. See backend/.env.example')
        elif value.startswith('replace-with-') or len(value) < 16:
            print(f'[WARN] {key} looks like a placeholder or is too short. Generate a strong value.')
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        print('[WARN] GOOGLE_CLIENT_ID/SECRET not set. Google login + GEE OAuth will fail.')
    if not ADMIN_KEY:
        print('[WARN] ADMIN_KEY not set. Admin endpoints are disabled (safe default).')


def main():
    _startup_secret_warnings()
    print(f'\n[GeoIntelligence Hub] http://{HOST}:{PORT}')
    print('[GeoIntelligence Hub] Threaded mode | Per-User EE')
    print('[GeoIntelligence Hub] Each user connects own GEE account\n')
    server = ThreadingHTTPServer((HOST, PORT), GEEHandler)
    server.daemon_threads = True
    server.allow_reuse_address = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == '__main__':
    main()
