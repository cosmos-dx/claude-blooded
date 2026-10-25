"""Claude through three doors, one code path: the Claude API, Amazon Bedrock (API key as bearer token)
and Anthropic-compatible gateways such as MegaLLM (custom base_url)."""
from __future__ import annotations

import anthropic

from app.core.errors import ProviderError
from app.llm.base import PROVIDERS, LLMProvider, LLMRequest, LLMResponse, LLMUsage

FALLBACK_BETA = "server-side-fallback-2026-07-01"


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
        return dict(model=self.model_for(req.model_alias), max_tokens=req.max_tokens, system=system,
                    messages=req.messages, thinking={"type": "adaptive"}, output_config={"effort": req.effort})

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
            raise ProviderError(f"{self.name}: HTTP {e.status_code}", retryable=e.status_code >= 500 or e.status_code in (401, 403, 404)) from e
        if msg.stop_reason == "refusal":
            raise ProviderError(f"{self.name}: the model declined this request", retryable=False)
        blocks = list(msg.content)
        if any(b.type == "fallback" for b in blocks):     # after a server-side fallback only later text may be echoed
            last = max(i for i, b in enumerate(blocks) if b.type == "fallback")
            blocks = [b for b in blocks[last + 1:] if b.type == "text"]
        u = msg.usage
        usage = LLMUsage(u.input_tokens or 0, u.output_tokens or 0, getattr(u, "cache_read_input_tokens", 0) or 0,
                         getattr(u, "cache_creation_input_tokens", 0) or 0)
        return LLMResponse(text="".join(b.text for b in blocks if b.type == "text"),
                           assistant_content=[b.model_dump(exclude_none=True) for b in blocks],
                           usage=usage, provider=self.name, model=msg.model, model_alias=req.model_alias,
                           stop_reason=msg.stop_reason or "", raw=msg)


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
    def _make_client(self):
        return anthropic.AnthropicBedrockMantle(api_key=self.settings["api_key"], aws_region=self.settings.get("region"), max_retries=2)
