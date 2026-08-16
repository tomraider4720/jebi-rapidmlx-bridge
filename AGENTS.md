# AGENTS.md

Hinweise für AI-Coding-Agenten (Claude Code, Codex, etc.), die an diesem
Repo arbeiten.

## Projekt in einem Satz

Ein-Datei-Reverse-Proxy (`proxy.py`, reine Python-Stdlib, kein Build-Schritt),
der Rapid-MLX für jebi wie einen Ollama-Server aussehen lässt, indem er
`GET /api/tags` aus Rapid-MLX' `GET /v1/models` synthetisiert und alles
andere transparent durchreicht.

## Kontext, den man kennen muss

- **jebi** (`core/llm/config/config.go`, `core/llm/providers/ollama.go` im
  jebi-Repo): Provider `"ollama"` ruft vor jedem Request
  `GET {endpointURL}/api/tags` auf. Schlägt das fehl, gilt der Provider als
  nicht verfügbar — es wird gar nicht erst `/v1/chat/completions` versucht.
- **Rapid-MLX** (`vllm_mlx/routes/` im Rapid-MLX-Repo): OpenAI-/
  Anthropic-kompatibel, kein `/api/tags`. `GET /v1/models` liefert
  `{"data": [{"id": "...", ...}], "models": [...]}`.
- Dieser Proxy übersetzt nur in eine Richtung (Ollama-Shape für jebi) und
  reicht sonst alles unverändert durch — bewusst minimal, keine
  Feature-Parität mit echtem Ollama.

## Constraints

- **Nur Python-Stdlib.** Kein `requests`, kein `fastapi`, keine
  externen Abhängigkeiten. Ziel: `python3 proxy.py` läuft ohne venv/pip.
- **Streaming muss erhalten bleiben.** `/v1/chat/completions` mit
  `stream: true` liefert SSE — der Proxy darf das nicht buffern, sondern
  muss chunked weiterreichen (siehe `_stream_response`).
- **Nur localhost.** Der Proxy ist für lokalen Gebrauch gedacht (jebi und
  Rapid-MLX laufen auf demselben Mac). Kein Auth, kein TLS — das ist
  Absicht, nicht vergessen.
- **Keine Secrets im Repo.** Falls später `RAPID_MLX_API_KEY`-Support dazu
  kommt: nur als Env-Var durchreichen, niemals hardcoden oder committen.

## Testen

Es gibt (noch) keine automatisierten Tests. Manueller Smoke-Test:

```bash
# Terminal 1: Rapid-MLX Server muss laufen
rapid-mlx serve qwen3.5-4b-4bit

# Terminal 2: Proxy starten
python3 proxy.py --listen-port 11434 --backend http://127.0.0.1:8000 -v

# Terminal 3: verifizieren
curl -s http://127.0.0.1:11434/api/tags
curl -s http://127.0.0.1:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3.5-4b-4bit","messages":[{"role":"user","content":"Sag nur OK"}],"stream":false}'
```

Erwartung: `/api/tags` liefert eine `"models"`-Liste mit den Rapid-MLX-Modellen;
`/v1/chat/completions` liefert eine normale OpenAI-Chat-Antwort durch.

Wenn du Tests hinzufügst: `unittest` aus der Stdlib bevorzugen, damit die
Zero-Dependency-Eigenschaft erhalten bleibt (oder ein `[dev]`-Extra klar
trennen, das nur für Tests gebraucht wird, nicht für den Betrieb).

## Beim Ändern beachten

- Änderungen an `_proxy`/`_stream_response` immer gegen einen echten
  laufenden Rapid-MLX-Server verifizieren (curl, wie oben) — nicht nur
  gegen Mocks, weil das eigentliche Risiko das SSE-Chunking ist.
- Wenn neue Ollama-Endpunkte emuliert werden (z. B. `/api/show`), immer
  zuerst die reale Ollama-API-Shape für den Endpunkt nachschlagen, nicht
  raten — jebi parst nur die Felder, die es kennt, aber andere Ollama-Clients
  könnten strenger sein.
