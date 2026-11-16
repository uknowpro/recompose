"""Entry point for the self-contained executable."""
import os
import ssl
import sys
from pathlib import Path

# Respect operator trust settings and installed system roots. Minimal machines
# without a CA file can use the build distribution's bundled public roots.
if (getattr(sys, 'frozen', False) and sys.platform != 'win32'
        and not os.environ.get('SSL_CERT_FILE')
        and not os.environ.get('SSL_CERT_DIR') and ssl.get_default_verify_paths().cafile is None):
    os.environ['SSL_CERT_FILE'] = str(Path(sys._MEIPASS) / 'certificates' / 'ca-certificates.crt')

from recompose.cli import main

raise SystemExit(main())
