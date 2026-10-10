"""Generate strong SESSION_SECRET + TOKEN_ENCRYPTION_KEY for backend/.env.

Usage:
    python generate_keys.py
    python generate_keys.py --write   # append missing keys to .env (never overwrites existing)

Rotating TOKEN_ENCRYPTION_KEY invalidates previously sealed EE tokens;
users will need to re-connect GEE after rotation.
"""
import os
import secrets
import sys
from pathlib import Path

try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet = None


def main():
    write = '--write' in sys.argv
    session_secret = secrets.token_urlsafe(48)
    fernet_key = Fernet.generate_key().decode() if Fernet else secrets.token_urlsafe(48)
    print(f'SESSION_SECRET={session_secret}')
    print(f'TOKEN_ENCRYPTION_KEY={fernet_key}')
    if write:
        env_path = Path(__file__).resolve().parent / '.env'
        existing = env_path.read_text(encoding='utf-8') if env_path.exists() else ''
        lines = []
        if 'SESSION_SECRET' not in existing:
            lines.append(f'SESSION_SECRET={session_secret}')
        if 'TOKEN_ENCRYPTION_KEY' not in existing:
            lines.append(f'TOKEN_ENCRYPTION_KEY={fernet_key}')
        if lines:
            with open(env_path, 'a', encoding='utf-8') as f:
                if existing and not existing.endswith('\n'):
                    f.write('\n')
                f.write('\n'.join(lines) + '\n')
            print(f'\nAppended {len(lines)} key(s) to {env_path} (existing values left untouched).')
        else:
            print('\n.env already contains both keys; nothing written.')
        print('WARNING: rotating TOKEN_ENCRYPTION_KEY requires users to re-connect GEE.')


if __name__ == '__main__':
    main()
