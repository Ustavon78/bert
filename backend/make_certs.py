# SPDX-License-Identifier: GPL-3.0-or-later
"""Create a local certificate authority (CA) and a server certificate for the HTTPS server.

    python make_certs.py --out certs --ip 192.168.1.10 [--host bert.school.local] [--new-ca]

Layout of the output folder:
    ca/ca.key           private key of the CA   (keep it safe, never mount it into a container)
    public/ca.crt       CA certificate          (import into browsers, public)
    public/ca.b64       the same as one line of base64, for the display console: set ca <line>
    server/server.crt   certificate of the HTTPS server
    server/server.key   private key of the HTTPS server

If a CA already exists it is reused and only the server certificate is created again (for example
after the IP address changed). The displays keep working then, they only know the CA.
Use --new-ca to start over; every display then needs the new CA.

About the validity: the certificates are valid from 2020 to 2060 on purpose. The displays have no
reliable clock (they only know the build date of their firmware), so a certificate that starts
"today" would look not yet valid to them. The CA is only trusted by Bert itself.
"""

import argparse
import base64
import datetime
import ipaddress
import os
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

UTC = datetime.timezone.utc
NOT_BEFORE = datetime.datetime(2020, 1, 1, tzinfo=UTC)
CA_NOT_AFTER = datetime.datetime(2060, 1, 1, tzinfo=UTC)
SERVER_NOT_AFTER = datetime.datetime(2055, 1, 1, tzinfo=UTC)


def write_private(path: Path, key: ec.EllipticCurvePrivateKey) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(data)


def write_public(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o644)


def name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Bert"),
                      x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def create_ca(out: Path) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = name("Bert local CA")
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject).issuer_name(subject).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOT_BEFORE).not_valid_after(CA_NOT_AFTER)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                                     data_encipherment=False, key_agreement=False, key_cert_sign=True,
                                     crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    write_private(out / "ca" / "ca.key", key)
    der = certificate.public_bytes(serialization.Encoding.DER)
    write_public(out / "public" / "ca.crt", certificate.public_bytes(serialization.Encoding.PEM))
    write_public(out / "public" / "ca.b64", base64.b64encode(der))  # one line, no line break
    return key, certificate


def load_ca(out: Path) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    key = serialization.load_pem_private_key((out / "ca" / "ca.key").read_bytes(), password=None)
    certificate = x509.load_pem_x509_certificate((out / "public" / "ca.crt").read_bytes())
    return key, certificate


def create_server_certificate(out: Path, ca_key, ca_certificate, hosts: list[str], ips: list[str],
                              common_name: str) -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    # Every IP address is listed twice: as an IP address (what browsers and OpenSSL check) and as a
    # DNS name with the same text. The displays use mbedTLS 2.x, which does not look at IP address
    # entries at all and compares the address as text with the DNS names.
    names: list[x509.GeneralName] = (
            [x509.DNSName(h) for h in hosts + ips]
            + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    )
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name(common_name)).issuer_name(ca_certificate.subject)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(NOT_BEFORE).not_valid_after(SERVER_NOT_AFTER)
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
                                     data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                     crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    write_private(out / "server" / "server.key", key)
    write_public(out / "server" / "server.crt", certificate.public_bytes(serialization.Encoding.PEM))


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the CA and the server certificate for Bert.")
    parser.add_argument("--out", default="certs", help="output folder (default: certs)")
    parser.add_argument("--host", action="append", default=[], help="DNS name of the server (repeatable)")
    parser.add_argument("--ip", action="append", default=[], help="IP address of the server (repeatable)")
    parser.add_argument("--new-ca", action="store_true", help="create a new CA even if one exists")
    args = parser.parse_args()
    if not args.host and not args.ip:
        parser.error("at least one --ip or --host is required")
    for value in args.ip:
        ipaddress.ip_address(value)  # fails with a clear message for typos

    out = Path(args.out)
    ca_exists = (out / "ca" / "ca.key").exists() and (out / "public" / "ca.crt").exists()
    if ca_exists and not args.new_ca:
        ca_key, ca_certificate = load_ca(out)
        print("Existing CA reused (displays do not need a new certificate).")
    else:
        ca_key, ca_certificate = create_ca(out)
        print("New CA created. Every display needs it: set ca <content of public/ca.b64>")

    # localhost is always included, so that the server can be checked on the machine itself.
    hosts = list(dict.fromkeys(args.host + ["localhost"]))  # without duplicates
    ips = list(dict.fromkeys(args.ip + ["127.0.0.1"]))
    create_server_certificate(out, ca_key, ca_certificate, hosts, ips, (args.host + args.ip)[0])
    fingerprint = ca_certificate.fingerprint(hashes.SHA256()).hex(":")
    print(f"Server certificate created for: {', '.join(hosts + ips)}")
    print(f"CA fingerprint (SHA-256): {fingerprint}")


if __name__ == "__main__":
    main()