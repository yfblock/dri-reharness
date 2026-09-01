"""LangChain synthesis bridge: LLM 调用 + 信封协议 + 反馈修复.

Consumed by the V2 experiment graph (llm_synthesize/repair) and the
backends pipeline (call_llm). Reads model settings from config.toml [llm].
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Mapping

# ── settings ────────────────────────────────────────────────────────────




# ── LLM 转写（多轮修复的可审查输入/输出日志）────────────────────────
_TRANSCRIPT: dict = {"dir": None, "seq": 0, "label": ""}


def set_transcript_dir(path: "str | Path | None", label: str = "") -> None:
    """Direct subsequent synthesize() calls' prompts/responses to ``path``.

    One markdown file per LLM invocation: llm-<seq>-<kind>.md with the full
    prompt and raw response.  ``None`` disables transcription.  The V2 repair
    loop points this at repairs/round-NNN/llm/ so every round is reviewable.
    """
    if path is None:
        _TRANSCRIPT.update(dir=None, seq=0, label="")
        return
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    _TRANSCRIPT.update(dir=directory, seq=0, label=label)


def _transcribe(prompt: str, response_text: str, *, kind: str,
                meta: Mapping | None = None) -> "Path | None":
    if _TRANSCRIPT["dir"] is None:
        return None
    _TRANSCRIPT["seq"] += 1
    seq = _TRANSCRIPT["seq"]
    out = Path(_TRANSCRIPT["dir"]) / f"llm-{seq:02d}-{kind}.md"
    header = [f"# LLM 转写 {_TRANSCRIPT['label']} #{seq} — {kind}",
              f"- 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
              f"- 模型: {load_langchain_settings().model}",
              f"- prompt: {len(prompt):,} 字符"]
    if meta:
        header += [f"- {k}: {v}" for k, v in meta.items()]
    if response_text:
        header.append(f"- 响应: {len(response_text):,} 字符")
    out.write_text(
        "\n".join(header)
        + "\n\n## PROMPT（完整输入）\n\n```\n" + prompt + "\n```\n"
        + ("\n## RESPONSE（原始输出）\n\n```c\n" + response_text + "\n```\n"
           if response_text else "\n## RESPONSE（空/失败）\n"),
        encoding="utf-8")
    return out


class LangChainBridgeError(RuntimeError):
    pass


def _repo_root(repo_root: str | Path | None) -> Path:
    if repo_root:
        return Path(repo_root).resolve()
    return Path(__file__).resolve().parents[1]


def _project_llm_config(repo_root: Path) -> dict[str, Any]:
    import tomllib
    path = repo_root / "config.toml"
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    section = document.get("llm") if isinstance(document, dict) else None
    if not isinstance(section, dict):
        return {}
    return {k: v for k, v in section.items()
            if isinstance(v, (str, int, float)) and not isinstance(v, bool)}


class LangChainSettings:
    def __init__(self, model: str, base_url: str | None, api_key: str | None,
                 timeout: int, temperature: float) -> None:
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout
        self.temperature = temperature


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    if v is None or not v.strip():
        return default
    return int(v)


def _env_float(name: str, default: float) -> float:
    v = os.environ.get(name)
    if v is None or not v.strip():
        return default
    return float(v)


def load_langchain_settings(*, repo_root: str | Path | None = None) -> LangChainSettings:
    root = _repo_root(repo_root)
    cfg = _project_llm_config(root)
    model = (os.environ.get("REHARNESS_LLM_MODEL")
             or cfg.get("model") or "gpt-5.6-luna")
    base_url = (os.environ.get("REHARNESS_LLM_BASE_URL")
                or cfg.get("base_url"))
    api_key = (os.environ.get("REHARNESS_LLM_API_KEY")
               or os.environ.get("OPENAI_API_KEY")
               or cfg.get("api_key"))
    return LangChainSettings(
        model=model, base_url=base_url, api_key=api_key,
        timeout=_env_int("REHARNESS_LLM_TIMEOUT", cfg.get("timeout", 600)),
        temperature=_env_float("REHARNESS_LLM_TEMPERATURE",
                               cfg.get("temperature", 0.0)))


def build_llm_bridge(root: str | Path, *, timeout: int = 600) -> Any:
    return LangChainBridge(repo_root=root)


# ── synthesis tools (structured tool calling) ──────────────────────────

SYNTHESIS_TOOLS = [{
    "type": "function",
    "function": {
        "name": "emit_driver_code",
        "description": "Emit the generated driver implementation as structured files.",
        "parameters": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {"type": "object",
                              "properties": {"path": {"type": "string"},
                                             "code": {"type": "string"}},
                              "required": ["path", "code"]},
                },
                "scenario": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["files"],
        },
    },
}]


def _tool_call_payload(response: Any) -> dict[str, Any] | None:
    calls = getattr(response, "tool_calls", None)
    if not calls:
        return None
    for call in calls:
        name = call.get("name") if isinstance(call, Mapping) else getattr(call, "name", None)
        if name != "emit_driver_code":
            continue
        args = (call.get("args") if isinstance(call, Mapping)
                else getattr(call, "args", None)) or {}
        files = args.get("files")
        if isinstance(files, list) and files:
            payload: dict[str, Any] = {"files": files}
            if isinstance(args.get("scenario"), list):
                payload["scenario"] = args["scenario"]
            return payload
    return None


# ── response parsing ────────────────────────────────────────────────────


def _response_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    if isinstance(response, Mapping):
        if isinstance(response.get("code"), str):
            return response["code"]
        content = response.get("content", response.get("text", response.get("output")))
    else:
        content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces = []
        for item in content:
            if isinstance(item, str):
                pieces.append(item)
            elif isinstance(item, Mapping) and isinstance(item.get("text"), str):
                pieces.append(item["text"])
        return "".join(pieces)
    return str(response) if response else ""


def _normalise_candidate_files(response: Any) -> list[dict[str, str]]:
    files = response.get("files") if isinstance(response, Mapping) else None
    if not isinstance(files, list):
        return []
    out = []
    for entry in files:
        if isinstance(entry, Mapping) and isinstance(entry.get("code"), str):
            out.append({"path": str(entry.get("path", "candidate.c")),
                        "code": entry["code"]})
    return out


def extract_generated_code(text: str) -> str:
    match = re.findall(r"```(?:c|C)\n(.*?)```", text, re.S)
    return match[0].rstrip() if match else text.strip()


def extract_generated_files(text: str) -> list[dict[str, str]]:
    blocks = re.findall(r"```(?:c|C)\n(.*?)```", text, re.S)
    if not blocks:
        return []
    return [{"path": "candidate.c", "code": b.rstrip()} for b in blocks]


def _primary_candidate_code(files: list[dict[str, str]]) -> str:
    if not files:
        return ""
    return files[0].get("code", "")


def parse_model_response(response: Any) -> dict[str, Any]:
    files: list[dict[str, str]] = []
    if isinstance(response, Mapping) and "files" in response:
        files = _normalise_candidate_files(response)
        text = json.dumps(response, sort_keys=True, default=str)
    else:
        text = _response_text(response)
        try:
            files = extract_generated_files(text)
        except LangChainBridgeError:
            files = []
    code = _primary_candidate_code(files) if files else extract_generated_code(text)
    metadata = {}
    structured_scenario = None
    if isinstance(response, Mapping):
        metadata = response.get("response_metadata",
                                response.get("metadata", {}))
        structured_scenario = response.get("scenario")
    else:
        metadata = getattr(response, "response_metadata",
                           getattr(response, "metadata", {}))
        structured_scenario = getattr(response, "scenario", None)
    scenario = _extract_scenario(text)
    if isinstance(structured_scenario, list):
        scenario = structured_scenario
    result = {"code": code, "scenario": scenario,
              "diagnostics": {"raw_output": text,
                              **({"metadata": metadata} if metadata else {})}}
    if files:
        result["files"] = files
    return result


def _extract_scenario(text: str) -> list | None:
    match = re.search(r'```json\s*(\{[\s\S]*?"scenario"[\s\S]*?\})\s*```', text)
    if not match:
        return None
    try:
        doc = json.loads(match.group(1))
        scenario = doc.get("scenario")
        return scenario if isinstance(scenario, list) else None
    except (json.JSONDecodeError, ValueError):
        return None


# ── bridge ──────────────────────────────────────────────────────────────


class LangChainBridge:
    """Implementation of the experiment runner's synthesis/repair protocol."""

    def __init__(self, model: Any = None, *,
                 settings: LangChainSettings | None = None,
                 repo_root: str | Path | None = None):
        self.settings = settings or load_langchain_settings(repo_root=repo_root)
        self._model = model
        self._repo_root = _repo_root(repo_root)

    def _model_instance(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise LangChainBridgeError(
                "langchain-openai is required for LangChain synthesis") from exc
        kwargs = {"model": self.settings.model,
                  "temperature": self.settings.temperature,
                  "timeout": self.settings.timeout,
                  "max_retries": 0,
                  # Streamed chunks keep reverse proxies (openresty) from
                  # cutting long reasoning-model generations with 504s;
                  # langchain accumulates the chunks transparently.
                  "streaming": True}
        if self.settings.base_url:
            kwargs["base_url"] = self.settings.base_url
        if self.settings.api_key:
            kwargs["api_key"] = self.settings.api_key
        self._model = ChatOpenAI(**kwargs)
        return self._model

    def _invoke(self, prompt: str) -> Any:
        attempts = 40
        for attempt in range(attempts):
            try:
                model = self._model_instance()
                bound = getattr(model, "bind_tools", None)
                if callable(bound):
                    response = bound(SYNTHESIS_TOOLS).invoke(prompt)
                    payload = _tool_call_payload(response)
                    if payload is not None:
                        files = payload.get("files") or []
                        code = (files[0].get("code", "")
                                if files and isinstance(files[0], dict) else "")
                        return {"code": code, "files": files,
                                "response_metadata": {"via_tool_call": True}}
                    return response
                return (model.invoke(prompt) if hasattr(model, "invoke")
                        else model(prompt))
            except LangChainBridgeError:
                raise
            except Exception as exc:
                text = str(exc)
                transient = ("429" in text
                             or "cooldown" in text.lower()
                             or "负载已饱和" in text
                             # 网关渠道/凭据池枯竭: 同属可等恢复的容量类
                             or "无可用渠道" in text
                             or "auth_unavailable" in text)
                if not transient or attempt == attempts - 1:
                    raise LangChainBridgeError(
                        f"model invocation failed: {exc}") from exc
                # 网关 429 是凭据池冷却: 8s 短重试即可撞过冷却窗口,
                # 比按 reset_seconds 等满更快恢复 (用户实测要求)
                wait = 8.0
                time.sleep(wait)
        raise LangChainBridgeError("model invocation failed: retries exhausted")

    def invoke_text(self, prompt: str) -> str:
        return _response_text(self._invoke(prompt))

    def synthesize(self, manifest: Any, evidence: Any,
                   feedback: Any = None, candidate: Any = None) -> dict[str, Any]:
        manifest_digest = getattr(manifest, "digest", None)
        if not isinstance(manifest_digest, str):
            manifest_digest = "0" * 64
        evidence_dict = (evidence if isinstance(evidence, dict)
                         else {"evidence": str(evidence)})
        prompt = (f"Generate a Linux kernel driver module from the following "
                  f"evidence package.\nReturn the implementation in a fenced "
                  f"C code block.\n\nEVIDENCE:\n```json\n"
                  + json.dumps(evidence_dict, indent=2, default=str)[:400000]
                  + "\n```\n")
        if feedback:
            prompt += (f"\nREPAIR DIRECTIVE (authoritative):\n```json\n"
                       + json.dumps(feedback, indent=2, default=str)[:2000]
                       + "\n```\n")
        raw = self._invoke(prompt)
        _transcribe(prompt, _response_text(raw),
                    kind="repair" if feedback else "initial",
                    meta={"manifest_digest": manifest_digest[:12]})
        response = parse_model_response(raw)
        response.setdefault("diagnostics", {})
        response["diagnostics"]["backend"] = "langchain"
        response["diagnostics"]["model"] = self.settings.model
        return response

    def repair(self, manifest: Any, evidence: Any, candidate: Any,
               feedback: Any) -> dict[str, Any]:
        return self.synthesize(manifest, evidence, feedback=feedback,
                               candidate=candidate)


# ── CLI entry ──────────────────────────────────────────────────────────


def call_langchain(prompt: str, *, timeout: int = 120, model: Any = None,
                   repo_root: str | Path | None = None) -> str:
    settings = load_langchain_settings(repo_root=repo_root)
    if timeout != settings.timeout:
        settings = LangChainSettings(
            settings.model, settings.base_url, settings.api_key,
            timeout, settings.temperature)
    return LangChainBridge(model=model, settings=settings,
                           repo_root=repo_root).invoke_text(prompt)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args(argv)
    try:
        response = call_langchain(sys.stdin.read(), timeout=args.timeout)
    except Exception as exc:
        print(f"langchain bridge failed: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(response)
    if response and not response.endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
