# IDEA

## Problem

[jebi](https://github.com/jebi-sh/jebi) (macOS Terminal mit eingebauter lokaler AI)
unterstützt nur zwei LLM-Provider:

- `ollama` — prüft Verfügbarkeit/Modelle zwingend über `GET /api/tags`
  (Ollamas natives Format), bevor irgendetwas gesendet wird.
- `llama-server` — startet selbst einen `llama-server`-Subprozess mit einer
  lokalen `.gguf`-Datei.

[Rapid-MLX](https://github.com/raullenchai/Rapid-MLX) (rapidmlx.com) ist ein
schneller lokaler Inferenz-Server für Apple Silicon, aber rein
OpenAI-/Anthropic-kompatibel (`/v1/chat/completions`, `/v1/models`,
`/v1/messages`, ...). Es gibt **keinen** `/api/tags`-Endpoint — also keine
Ollama-API-Emulation. Verifiziert per Code-Review: die Routen unter
`vllm_mlx/routes/` (chat, completions, anthropic, models, ...) haben nichts
Ollama-Kompatibles im Repo.

Konsequenz: `jebi` mit `provider: "ollama"` und `endpointURL` auf einen
laufenden Rapid-MLX-Server zeigen lassen scheitert am Verfügbarkeitscheck
(`/api/tags` → 404), obwohl der eigentliche Chat-Endpoint
(`/v1/chat/completions`) technisch kompatibel wäre.

## Lösung

Ein minimaler lokaler Reverse-Proxy (`proxy.py`, nur Python-Stdlib):

- `GET /api/tags` → wird aus Rapid-MLX' `GET /v1/models` synthetisiert
  (Ollama-Shape: `{"models": [{"name": ..., "model": ..., ...}]}`)
- alle anderen Pfade → transparent 1:1 an Rapid-MLX weitergereicht,
  inklusive SSE-Streaming für `/v1/chat/completions`

jebi zeigt mit `provider: "ollama"` auf den Proxy (Standard: Port 11434,
jebis Default), der Proxy leitet an Rapid-MLX (Standard: Port 8000) weiter.

```
jebi (ollama-Provider) -> proxy.py :11434 -> Rapid-MLX :8000
```

## Status

Funktionsfähiger Prototyp, manuell gegen einen laufenden Rapid-MLX-Server
(`qwen3.5-4b-4bit`) getestet:

- `GET /api/tags` liefert eine gültige Ollama-Modell-Liste.
- `POST /v1/chat/completions` non-streaming und streaming (SSE) laufen
  transparent durch.

## Nicht im Scope (bisher)

- Kein API-Key-Handling (falls Rapid-MLX mit `RAPID_MLX_API_KEY` läuft).
- Kein Health-Endpoint-Mapping über `/api/tags` hinaus (z. B. `/api/show`,
  `/api/pull` — jebi braucht die aktuell nicht).
- Kein LaunchAgent/Autostart — manuelles Starten oder eigenes Setup.
