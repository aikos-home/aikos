"""Translation into German with the local LLM.

Part of the aikos transcriber (split from roomkey tools/transcribe_publish.py at d0d52b9, code unchanged)."""
from __future__ import annotations

import json
import urllib.request


def to_german(text: str, language: str, url: str, model: str) -> str:
    """Translate an utterance into German with the local LLM ("" if it fails)."""
    body = {"model": model, "stream": False, "think": False, "keep_alive": -1, "options": {"temperature": 0},
            "messages": [{"role": "system", "content":
                          f"Übersetze die folgende Äußerung ({language}), gesprochen an einer Haustür-Sprechanlage, ins "
                          "Deutsche. Namen, Firmen und Zahlen unverändert lassen. Antworte nur mit der Übersetzung."},
                         {"role": "user", "content": text}]}
    req = urllib.request.Request(url.rstrip("/") + "/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return " ".join(json.loads(r.read())["message"]["content"].strip().strip('"„“').split())
    except Exception:
        return ""
