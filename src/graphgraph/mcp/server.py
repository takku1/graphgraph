"""Stable MCP compatibility facade over domain-owned tools and dispatch."""

from .descriptions import (
    DESCRIPTION_TOOL_NAMES as DESCRIPTION_TOOL_NAMES,
)
from .descriptions import (
    DESCRIPTION_TOOLS as DESCRIPTION_TOOLS,
)
from .descriptions import (
    FORMAT_TABLE as FORMAT_TABLE,
)
from .descriptions import (
    handle_description_tool as handle_description_tool,
)
from .dispatch import dispatch as dispatch
from .graph_management import (
    GRAPH_MANAGEMENT_TOOLS as GRAPH_MANAGEMENT_TOOLS,
)
from .graph_management import (
    handle_build_graph as handle_build_graph,
)
from .graph_management import (
    handle_export_graph as handle_export_graph,
)
from .graph_management import (
    handle_remove_graph_files as handle_remove_graph_files,
)
from .graph_management import (
    handle_update_graph_files as handle_update_graph_files,
)
from .platform_tools import (
    PLATFORM_TOOL_NAMES as PLATFORM_TOOL_NAMES,
)
from .platform_tools import (
    PLATFORM_TOOLS as PLATFORM_TOOLS,
)
from .platform_tools import (
    handle_platform_tool as handle_platform_tool,
)
from .retrieval_tools import (
    SERVER_INFO as SERVER_INFO,
)
from .retrieval_tools import (
    TOOLS as TOOLS,
)
from .retrieval_tools import (
    _validate_required_args as _validate_required_args,
)
from .retrieval_tools import (
    build_final_packet as build_final_packet,
)
from .retrieval_tools import (
    build_full_graph as build_full_graph,
)
from .retrieval_tools import (
    build_query_context as build_query_context,
)
from .retrieval_tools import (
    content as content,
)
from .retrieval_tools import (
    handle_initialize as handle_initialize,
)
from .retrieval_tools import (
    handle_project_status as handle_project_status,
)
from .retrieval_tools import (
    handle_query_relations as handle_query_relations,
)
from .retrieval_tools import (
    handle_search_nodes as handle_search_nodes,
)
from .retrieval_tools import (
    handle_select_symbols as handle_select_symbols,
)
from .retrieval_tools import (
    handle_source_snippets as handle_source_snippets,
)
from .retrieval_tools import (
    handle_tools_call as handle_tools_call,
)
from .retrieval_tools import (
    handle_tools_list as handle_tools_list,
)
from .retrieval_tools import (
    main as main,
)
