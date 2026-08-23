"""内置工具模块"""

from .select_system_prompt import handle_select_system_prompt, SELECT_SYSTEM_PROMPT_DEFINITION
from .load_document import handle_load_document, LOAD_DOCUMENT_DEFINITION
from .unload_document import handle_unload_document, UNLOAD_DOCUMENT_DEFINITION
from .discover_textcli import handle_discover_textcli, DISCOVER_TEXTCLI_DEFINITION
from .call_textcli import handle_call_textcli, CALL_TEXTCLI_DEFINITION

__all__ = [
    "handle_select_system_prompt",
    "SELECT_SYSTEM_PROMPT_DEFINITION",
    "handle_load_document",
    "LOAD_DOCUMENT_DEFINITION",
    "handle_unload_document",
    "UNLOAD_DOCUMENT_DEFINITION",
    "handle_discover_textcli",
    "DISCOVER_TEXTCLI_DEFINITION",
    "handle_call_textcli",
    "CALL_TEXTCLI_DEFINITION",
]
