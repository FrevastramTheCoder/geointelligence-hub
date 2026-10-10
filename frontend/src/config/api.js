const API_BASE = '/api';

export const API = {
  BASE: API_BASE,
  HEALTH: `${API_BASE}/health`,
  AUTH: {
    LOGIN: `${API_BASE}/login`,
    REGISTER: `${API_BASE}/register`,
    GOOGLE: `${API_BASE}/google-login`,
    GOOGLE_CODE: `${API_BASE}/google-code`,
    ME: `${API_BASE}/session`,
    SETUP: `${API_BASE}/update-setup`,
  },
  GEE: {
    CONNECT: `${API_BASE}/gee-connect`,
    STATUS: `${API_BASE}/gee/status`,
    OAUTH_START: `${API_BASE}/gee/oauth/start`,
  },
  ANALYSE: `${API_BASE}/analyze`,
  PROJECTS: `${API_BASE}/save-project`,
  PROJECTS_API: `${API_BASE}/projects`,
  RESULTS: `${API_BASE}/results`,
  ZONAL: `${API_BASE}/zonal`,
  SPATIAL_STATISTICS: `${API_BASE}/spatial-statistics`,
  DRONE_ANALYSIS: `${API_BASE}/drone-analysis`,
  ADMIN_BOUNDARY: `${API_BASE}/admin-boundary`,
  EXPORT: `${API_BASE}/export`,
  EXPORTS: `${API_BASE}/exports`,
  EXPORT_STATUS: `${API_BASE}/export/status`,
  EXPORT_DOWNLOAD: `${API_BASE}/export/download`,
  LOGOUT: `${API_BASE}/logout`,
  CHAT: `${API_BASE}/chat`,
  CODE: `${API_BASE}/code`,
};

export const TOKEN_KEY = 'geointel_token';
export const USER_KEY = 'geointel_user';
