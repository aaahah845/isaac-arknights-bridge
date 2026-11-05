"""Texture IDs restart with Isaac; isolate their files by client session."""
import hashlib


def texture_namespace(client):
    return hashlib.sha256(str(client).encode('utf-8')).hexdigest()[:16]
