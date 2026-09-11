import anthropic
import pandas as pd
from PyQt6.QtCore import QThread, pyqtSignal
from dataclasses import dataclass

from core.vehicle_pack import build_system_prompt
from core.i18n import current_language

GROQ_DEFAULT_MODEL      = "llama-3.3-70b-versatile"
ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-5"
OLLAMA_DEFAULT_MODEL    = "llama3.1"

# Pack name used when the caller does not specify one (PRD R1.4: generic default).
DEFAULT_VEHICLE_PACK = "generic"


@dataclass(frozen=True)
class ProviderSpec:
    """Descriptor of an AI provider; drives dispatch and defaults (PRD R3.1)."""
    name: str
    kind: str                 # "anthropic" | "openai_compatible"
    default_model: str
    base_url: str = ""
    needs_key: bool = True


PROVIDERS: dict[str, ProviderSpec] = {
    "Anthropic": ProviderSpec("Anthropic", "anthropic", ANTHROPIC_DEFAULT_MODEL),
    "Groq": ProviderSpec(
        "Groq", "openai_compatible", GROQ_DEFAULT_MODEL,
        base_url="https://api.groq.com/openai/v1",
    ),
    "Ollama": ProviderSpec(
        "Ollama", "openai_compatible", OLLAMA_DEFAULT_MODEL,
        base_url="http://localhost:11434/v1", needs_key=False,
    ),
    "OpenAI": ProviderSpec(
        "OpenAI", "openai_compatible", "gpt-4o-mini",
        base_url="https://api.openai.com/v1",
    ),
}


def get_provider(name: str) -> ProviderSpec:
    """Resolve a provider by display name; unknown providers fall back to Anthropic."""
    return PROVIDERS.get(name or "", PROVIDERS["Anthropic"])


BYTE_COLS = ["B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7"]


def build_prompt(
    id_hex: str,
    frames_df: pd.DataFrame,
    context: str = "",
    event_correlations: list = None,
    repo_context: dict = None,
    ml_insights: str = "",
) -> str:
    lines = [f"CAN ID: 0x{id_hex}  ({int(id_hex, 16)} decimal)"]
    lines.append(f"Frame count: {len(frames_df)}")

    # Repo context block — gives Claude vehicle/project knowledge
    if repo_context:
        repo_name = repo_context.get("repo", "")
        repo_desc = repo_context.get("description", "")
        readme_snippet = repo_context.get("readme_snippet", "")
        if repo_name:
            lines.append(f"\nSource repository: {repo_context.get('owner','')}/{repo_name}")
        if repo_desc:
            lines.append(f"Repo description: {repo_desc}")
        if readme_snippet:
            lines.append(f"\nRepository notes (README excerpt):\n{readme_snippet}")

    if not frames_df.empty:
        total_time = frames_df["Timestamp"].iloc[-1] - frames_df["Timestamp"].iloc[0]
        freq = len(frames_df) / total_time if total_time > 0 else 0
        lines.append(f"\nFrequency: {freq:.1f} Hz")

        lines.append("\nByte statistics (min/max/mean/entropy):")
        for col in BYTE_COLS:
            if col not in frames_df.columns:
                continue
            s = frames_df[col].dropna()
            if s.empty:
                continue
            import numpy as np
            counts = np.bincount(s.astype(int), minlength=256)
            probs = counts / counts.sum()
            probs = probs[probs > 0]
            ent = float(-np.sum(probs * np.log2(probs)))
            lines.append(
                f"  {col}: min={int(s.min())} max={int(s.max())} "
                f"mean={s.mean():.1f} entropy={ent:.2f}"
            )

        lines.append("\nLast 20 frames (hex):")
        last20 = frames_df.tail(20)
        for _, row in last20.iterrows():
            byte_str = " ".join(
                format(int(row[col]), "02X") if pd.notna(row.get(col)) else "--"
                for col in BYTE_COLS
            )
            ts = row.get("Timestamp", 0)
            lines.append(f"  [{ts:.3f}] {byte_str}")

    if ml_insights.strip():
        lines.append(
            "\n=== ML PRE-ANALYSIS (factual — derived offline, not inferred) ==="
        )
        lines.append(ml_insights.strip())
        lines.append("=== END ML PRE-ANALYSIS ===")

    if event_correlations:
        lines.append("\nCorrelated events (this ID changed near these timestamps):")
        for evt in event_correlations:
            lines.append(f"  - {evt}")

    if context.strip():
        lines.append(f"\nUser context: {context.strip()}")

    return "\n".join(lines)


def _readme_snippet(readme: str, max_chars: int = 800) -> str:
    """Return the most annotation-rich portion of a README."""
    if not readme:
        return ""
    lines = readme.splitlines()
    # Prefer lines with TS / timestamp markers
    ts_lines = [l for l in lines if "ts" in l.lower() or "timestamp" in l.lower()
                or any(c.isdigit() for c in l[:10])]
    if ts_lines:
        snippet = "\n".join(ts_lines[:40])
    else:
        snippet = "\n".join(lines[:40])
    return snippet[:max_chars]


class AIWorker(QThread):
    chunk_received = pyqtSignal(str)
    finished       = pyqtSignal(str)
    error          = pyqtSignal(str)

    def __init__(
        self,
        api_key:    str,
        id_hex:     str,
        frames_df:  pd.DataFrame,
        context:    str = "",
        event_correlations: list = None,
        repo_context: dict = None,
        provider:   str = "Anthropic",
        model:      str = "",
        groq_key:   str = "",
        ml_insights: str = "",
        vehicle_pack: str = DEFAULT_VEHICLE_PACK,
        base_url:   str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.spec           = get_provider(provider)
        self.api_key        = api_key
        self.id_hex         = id_hex
        self.frames_df      = frames_df
        self.context        = context
        self.event_correlations = event_correlations or []
        self.repo_context   = repo_context
        self.provider       = provider
        self.model          = model or self.spec.default_model
        self.base_url       = base_url
        self.groq_key       = groq_key
        self.ml_insights    = ml_insights
        self.vehicle_pack   = vehicle_pack
        self._system_prompt = build_system_prompt(
            vehicle_pack, language=current_language())
        self._full_response = ""

    def run(self):
        if self.spec.kind == "openai_compatible":
            self._run_openai_compatible(
                base_url=self.base_url or self.spec.base_url,
                api_key=self._resolve_key(),
                model=self.model,
                name=self.spec.name,
            )
        else:
            self._run_anthropic()

    def _resolve_key(self) -> str:
        # Backward compat: Groq historically stored a separate groq_api_key.
        if self.spec.name == "Groq":
            return self.groq_key or self.api_key
        return self.api_key

    def _build_context(self):
        rc = None
        if self.repo_context:
            rc = dict(self.repo_context)
            rc["readme_snippet"] = _readme_snippet(rc.get("readme", ""))
        return build_prompt(
            self.id_hex, self.frames_df,
            self.context, self.event_correlations,
            repo_context=rc,
            ml_insights=self.ml_insights,
        )

    def _run_anthropic(self):
        try:
            client = anthropic.Anthropic(api_key=self.api_key)
            prompt = self._build_context()
            with client.messages.stream(
                model=self.model,
                max_tokens=1500,
                system=self._system_prompt,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for text in stream.text_stream:
                    self._full_response += text
                    self.chunk_received.emit(text)
            self.finished.emit(self._full_response)
        except anthropic.AuthenticationError:
            self.error.emit("Invalid Anthropic API key. Check Settings > API Keys.")
        except anthropic.RateLimitError:
            self.error.emit("Anthropic rate limit exceeded. Wait a moment and retry.")
        except Exception as e:
            self.error.emit(str(e))

    def _run_openai_compatible(self, base_url: str, api_key: str,
                               model: str, name: str):
        """Stream from any OpenAI-compatible chat/completions endpoint.

        A single base_url + api_key + model is enough to reuse any provider
        with an OpenAI-compatible API (Groq, Ollama, OpenAI, and domestic
        providers like Qwen/DeepSeek/Kimi/GLM via their compatible-mode URLs).
        """
        import json
        import requests

        base = (base_url or "").rstrip("/")
        try:
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            resp = requests.post(
                f"{base}/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "max_tokens": 1500,
                    "stream": True,
                    "messages": [
                        {"role": "system", "content": self._system_prompt},
                        {"role": "user",   "content": self._build_context()},
                    ],
                },
                stream=True, timeout=180,
            )
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                raw = line.decode("utf-8", errors="ignore").strip()
                if not raw.startswith("data:"):
                    continue
                data = raw[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = obj.get("choices") or []
                if not choices:
                    continue
                text = (choices[0].get("delta") or {}).get("content") or ""
                if text:
                    self._full_response += text
                    self.chunk_received.emit(text)
            self.finished.emit(self._full_response)
        except requests.HTTPError as e:
            status = getattr(getattr(e, "response", None), "status_code", 0)
            if status in (401, 403):
                self.error.emit(
                    f"Invalid {name} API key. Check Settings > API Keys.")
            elif status == 429:
                self.error.emit(
                    f"{name} rate limit exceeded. Wait a moment and retry.")
            else:
                self.error.emit(f"{name} error: {e}")
        except requests.ConnectionError:
            self.error.emit(
                f"Cannot reach {name} at {base}. Check base URL or network.")
        except Exception as e:
            self.error.emit(f"{name} error: {e}")
