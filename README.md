# jebi-rapidmlx-bridge

Winziger Reverse-Proxy, der einen lokalen [Rapid-MLX](https://github.com/raullenchai/Rapid-MLX)-Server
für [jebi](https://github.com/jebi-sh/jebi) wie einen Ollama-Server aussehen lässt.

## Warum

jebi hat nur zwei LLM-Provider: `ollama` und `llama-server`. Der
`ollama`-Provider prüft Verfügbarkeit über `GET /api/tags` — ein Ollama-eigenes
Endpoint, das Rapid-MLX nicht kennt (Rapid-MLX ist rein OpenAI-/
Anthropic-kompatibel). Ohne Übersetzung meldet jebi den Provider deshalb als
nicht verfügbar, obwohl der eigentliche Chat-Endpoint kompatibel wäre.

Details und Hintergrund: siehe [IDEA.md](IDEA.md).

## Funktionsweise

```
jebi (provider: ollama) --> proxy.py :11434 --> Rapid-MLX :8000
```

- `GET /api/tags` wird aus Rapid-MLX' `GET /v1/models` synthetisiert.
- Alle anderen Requests (inkl. SSE-Streaming bei `/v1/chat/completions`)
  werden transparent an Rapid-MLX weitergereicht.

Reine Python-Stdlib, keine Abhängigkeiten.

## Voraussetzungen

- Python 3.9+ (macOS-Systempython reicht)
- Ein laufender Rapid-MLX-Server, z. B.:
  ```bash
  rapid-mlx serve qwen3.5-4b-4bit
  ```

## Verwendung

```bash
python3 proxy.py --listen-port 11434 --backend http://127.0.0.1:8000
```

Optionen:

| Flag             | Default                 | Bedeutung                          |
|------------------|--------------------------|-------------------------------------|
| `--listen-host`  | `127.0.0.1`               | Bind-Adresse des Proxys             |
| `--listen-port`  | `11434`                   | jebis Default-`endpointURL`-Port    |
| `--backend`      | `http://127.0.0.1:8000`   | Rapid-MLX-Server-URL                |
| `--timeout`      | `30`                      | Request-Timeout in Sekunden         |
| `-v`/`--verbose` | aus                       | Zugriffslog aktivieren              |

Alle Optionen sind auch als Env-Vars setzbar: `BRIDGE_LISTEN_HOST`,
`BRIDGE_LISTEN_PORT`, `BRIDGE_BACKEND`, `BRIDGE_TIMEOUT`.

## jebi konfigurieren

In `~/.config/jebi/settings.json`:

```json
{
  "llm": {
    "provider": "ollama",
    "model": "qwen3.5-4b-4bit",
    "endpointURL": "http://localhost:11434",
    "enabled": true
  }
}
```

`model` muss zu einer der IDs passen, die `curl http://127.0.0.1:8000/v1/models`
zurückgibt (bzw. wie sie in Rapid-MLX konfiguriert/geserved wird).

## Testen

```bash
curl -s http://127.0.0.1:11434/api/tags
curl -s http://127.0.0.1:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3.5-4b-4bit","messages":[{"role":"user","content":"Sag nur OK"}],"stream":false}'
```

## Scope / Grenzen

- Kein Auth, kein TLS — nur für localhost-zu-localhost gedacht.
- Emuliert nur `/api/tags`, keine weiteren Ollama-Endpunkte (`/api/show`,
  `/api/pull`, ...) — jebi braucht aktuell nur diesen einen.
- Kein Autostart/LaunchAgent enthalten; manuell starten oder selbst
  einrichten.

## Lizenz

MIT
