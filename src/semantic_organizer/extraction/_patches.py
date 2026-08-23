# Monkey-patches for external libraries

# 1. Monkey-patch docling_graph's LiteLLM client to drop json_object response format
# because LM Studio rejects it with a 400 Bad Request.
from docling_graph.llm_clients.litellm import LiteLLMClient
original_build_request = LiteLLMClient._build_request
def patched_build_request(self, *args, **kwargs):
    req = original_build_request(self, *args, **kwargs)
    if req.get("response_format") == {"type": "json_object"}:
        del req["response_format"]
    return req
LiteLLMClient._build_request = patched_build_request

# 2. Monkey-patch DocumentConverter to act as a Singleton.
# This prevents docling_graph from reloading 770MB of PyTorch weights for every single document!
from docling.document_converter import DocumentConverter
_global_converter = None
_original_new = DocumentConverter.__new__
_original_init = DocumentConverter.__init__

def patched_new(cls, *args, **kwargs):
    global _global_converter
    if _global_converter is None:
        _global_converter = _original_new(cls)
    return _global_converter

def patched_init(self, *args, **kwargs):
    if hasattr(self, "_already_initialized"):
        return
    _original_init(self, *args, **kwargs)
    self._already_initialized = True

DocumentConverter.__new__ = patched_new
DocumentConverter.__init__ = patched_init
