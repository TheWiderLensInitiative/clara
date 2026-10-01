"""Print a QR code in the terminal.  python qr.py [url]   (default: where to get the Clara phone app)"""
import os
import sys

import qrcode

APP_URL = os.environ.get("CLARA_APP_URL", "https://github.com/TheWiderLensInitiative/clara/releases/latest")


def show(url: str = APP_URL) -> None:
    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_L)
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)   # half-block characters: dark modules print as the terminal's background


if __name__ == "__main__":
    show(sys.argv[1] if len(sys.argv) > 1 else APP_URL)
