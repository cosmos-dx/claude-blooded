"""Claude through three doors, one code path: the Claude API, Amazon Bedrock (API key as bearer token)
and Anthropic-compatible gateways such as MegaLLM (custom base_url)."""
from __future__ import annotations

import anthropic

from app.core.errors import ProviderError
from app.llm.base import PROVIDERS, LLMProvider, LLMRequest, LLMResponse, LLMUsage

FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _sources(blocks) -> list[dict]:
    """URLs the model actually retrieved: web search results, fetched pages and citations."""
    found: dict[str, str] = {}
    for b in blocks:
        if b.type == "web_search_tool_result" and isinstance(getattr(b, "content", None), list):
            for r in b.content:
                if getattr(r, "url", None):
                    found.setdefault(r.url, getattr(r, "title", "") or "")
        elif b.type == "web_fetch_tool_result":
            c = getattr(b, "content", None)
            if getattr(c, "url", None):
                found.setdefault(c.url, getattr(getattr(c, "content", None), "title", "") or "")
        elif b.type == "text":
            for cit in getattr(b, "citations", None) or []:
                if getattr(cit, "url", None):
                    found.setdefault(cit.url, getattr(cit, "title", "") or "")
    return [{"url": u, "title": t} for u, t in found.items()]


class _ClaudeBase(LLMProvider):
    _client = None

    def available(self) -> bool:
        return bool(self.settings.get("api_key"))

    def client(self):
        if self._client is None:
            self._client = self._make_client()
        return self._client

    def _make_client(self):
        raise NotImplementedError

    def _params(self, req: LLMRequest) -> dict:
        system = [{"type": "text", "text": req.system, **({"cache_control": {"type": "ephemeral"}} if req.cache_system else {})}]
        params = dict(model=self.model_for(req.model_alias), max_tokens=req.max_tokens, system=system,
                      messages=req.messages, thinking={"type": "adaptive"}, output_config={"effort": req.effort})
        if req.tools:
            eager = bool(self.settings.get("eager_tool_input"))      # client tools only; server tools reject the field
            params["tools"] = [{**t, "eager_input_streaming": True} if eager and "type" not in t else t for t in req.tools]
        return params

    def _call(self, req: LLMRequest):
        with self.client().messages.stream(**self._params(req)) as stream:
            return stream.get_final_message()

    def complete(self, req: LLMRequest) -> LLMResponse:
        try:
            msg = self._call(req)
        except anthropic.RateLimitError as e:
            raise ProviderError(f"{self.name}: rate limited", retryable=True) from e
        except anthropic.APIConnectionError as e:
            raise ProviderError(f"{self.name}: connection failed", retryable=True) from e
        except anthropic.APIStatusError as e:
            # 401/403/404 and Bedrock's account-level "Operation not allowed" are about this provider, not the request
            blocked = e.status_code == 400 and "operation not allowed" in str(e).lower()
            raise ProviderError(f"{self.name}: HTTP {e.status_code}", retryable=blocked or e.status_code >= 500 or e.status_code in (401, 403, 404)) from e
        if msg.stop_reason == "refusal":
            raise ProviderError(f"{self.name}: the model declined this request", retryable=False)
        blocks = list(msg.content)
        if any(b.type == "fallback" for b in blocks):     # after a server-side fallback only later text may be echoed
            last = max(i for i, b in enumerate(blocks) if b.type == "fallback")
            blocks = [b for b in blocks[last + 1:] if b.type == "text"]
        u = msg.usage
        stu = getattr(u, "server_tool_use", None)
        server_tools = {k: n for k, n in (("web_search", getattr(stu, "web_search_requests", 0) or 0),
                                          ("web_fetch", getattr(stu, "web_fetch_requests", 0) or 0)) if n}
        usage = LLMUsage(u.input_tokens or 0, u.output_tokens or 0, getattr(u, "cache_read_input_tokens", 0) or 0,
                         getattr(u, "cache_creation_input_tokens", 0) or 0, server_tools)
        return LLMResponse(text="".join(b.text for b in blocks if b.type == "text"),
                           assistant_content=[b.model_dump(exclude_none=True) for b in blocks],
                           usage=usage, provider=self.name, model=msg.model, model_alias=req.model_alias,
                           stop_reason=msg.stop_reason or "", sources=_sources(blocks), raw=msg)


@PROVIDERS.register("anthropic")
class AnthropicDirect(_ClaudeBase):
    def _make_client(self):
        return anthropic.Anthropic(api_key=self.settings["api_key"], max_retries=2)

    def _call(self, req: LLMRequest):
        if not self.settings.get("supports_fallbacks"):
            return super()._call(req)
        with self.client().beta.messages.stream(**self._params(req), betas=[FALLBACK_BETA], fallbacks="default") as stream:
            return stream.get_final_message()


@PROVIDERS.register("anthropic_compatible")
class AnthropicCompatible(_ClaudeBase):
    def _make_client(self):
        return anthropic.Anthropic(api_key=self.settings["api_key"], base_url=self.settings["base_url"], max_retries=2)


@PROVIDERS.register("bedrock")
class Bedrock(_ClaudeBase):
    """Bedrock API key (bearer token) or an IAM access key pair (SigV4)."""

    def available(self) -> bool:
        s = self.settings
        return bool(s.get("api_key") or (s.get("access_key_id") and s.get("secret_access_key")))

    def _make_client(self):
        s = self.settings
        auth = ({"api_key": s["api_key"]} if s.get("api_key")
                else {"aws_access_key": s["access_key_id"], "aws_secret_key": s["secret_access_key"]})
        return anthropic.AnthropicBedrockMantle(**auth, aws_region=s.get("region"), max_retries=2)
