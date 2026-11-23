"""Opening web addresses safely, with certificates checked the way Windows checks them.

Python's own check only trusts the certificates Windows already has saved, and Windows saves some only when a
browser first needs them, so a site with a newer certificate (Codeberg, for gallery-dl) could fail with
"certificate verify failed: certificate has expired" even though it's fine in a browser. So:
1. Windows itself checks the certificate (truststore), fetching anything it's missing, like a browser.
2. If that isn't possible, or fails, the check uses Mozilla's certificate list shipped with the app (certifi).
3. Then Python's usual check. Certificates are always checked; nothing here turns checking off."""
import ssl
import urllib.request

_contexts = None


def contexts():
    """The ways to check certificates, best first."""
    global _contexts
    if _contexts is None:
        found = []
        try:
            import truststore
            found.append(("Windows", truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)))
        except Exception:
            pass
        try:
            import certifi
            found.append(("certifi", ssl.create_default_context(cafile=certifi.where())))
        except Exception:
            pass
        found.append(("Python", ssl.create_default_context()))
        _contexts = found
    return _contexts


def _is_cert_error(exc):
    reason = getattr(exc, "reason", exc)
    return isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(exc)


def urlopen(request, timeout=30):
    """urllib.request.urlopen, trying the next way of checking certificates when one rejects the site."""
    last = None
    for _name, ctx in contexts():
        try:
            return urllib.request.urlopen(request, timeout=timeout, context=ctx)
        except Exception as exc:
            if not _is_cert_error(exc):
                raise
            last = exc
    raise last
