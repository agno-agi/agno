from pathlib import Path

import requests


def download_cert(cert_url: str, filename: str = "cert.pem"):
    """
    Downloads a CA certificate bundle if it doesn't exist locally.

    Returns:
        str: Path to the certificate file
    """
    cert_dir = Path("./certs")
    cert_path = cert_dir / filename

    # Create directory if it doesn't exist
    cert_dir.mkdir(parents=True, exist_ok=True)

    # Download the certificate if it doesn't exist
    if not cert_path.exists():
        response = requests.get(cert_url)
        response.raise_for_status()

        with open(cert_path, "wb") as f:
            f.write(response.content)

    return str(cert_path.absolute())
