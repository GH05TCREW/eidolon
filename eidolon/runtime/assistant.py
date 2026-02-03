from __future__ import annotations

import json
import platform
import shutil
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from eidolon.config.settings import SandboxPermissions
from eidolon.core.models.chat import ChatMessage
from eidolon.core.reasoning.llm import LiteLLMClient
from eidolon.core.reasoning.memory import ConversationMemory
from eidolon.runtime.sandbox import SandboxRuntime
from eidolon.runtime.tools.base import Tool
from eidolon.runtime.tools.todo import TodoTool

# Infrastructure and network tools to detect
INFRASTRUCTURE_TOOLS = {
    "network_discovery": ["nmap", "arp-scan", "masscan", "rustscan", "zmap"],
    "network_analysis": ["tcpdump", "tshark", "wireshark", "ngrep"],
    "dns_tools": ["dig", "nslookup", "host", "dnsenum", "dnsrecon"],
    "cloud_cli": ["aws", "az", "gcloud", "kubectl", "terraform", "ansible", "pulumi"],
    "container_tools": ["docker", "podman", "kubectl", "helm", "docker-compose"],
    "monitoring": ["top", "htop", "netstat", "ss", "lsof", "iotop", "iftop"],
    "network_utilities": [
        "ping",
        "traceroute",
        "mtr",
        "curl",
        "wget",
        "nc",
        "netcat",
        "telnet",
        "ssh",
    ],
    "system_info": ["ps", "systemctl", "service", "uptime", "df", "free", "uname"],
}


def detect_available_tools() -> dict[str, list[str]]:
    """Detect which infrastructure tools are available on the system."""
    available = {}
    for category, tools in INFRASTRUCTURE_TOOLS.items():
        found = []
        for tool in tools:
            if shutil.which(tool):
                found.append(tool)
        if found:
            available[category] = found
    return available


def get_graph_summary(repository: Any) -> str:
    """Generate a lightweight summary of the graph for system prompt injection."""
    try:
        # Get node counts by label
        count_query = """
        MATCH (n)
        WHERE n.node_id IS NOT NULL
        RETURN labels(n)[0] AS label, count(n) AS count
        ORDER BY count DESC
        """
        counts = list(repository.run_cypher(count_query, {}))

        # Get sample node IDs (first 3)
        sample_query = """
        MATCH (n)
        WHERE n.node_id IS NOT NULL
        RETURN n.node_id AS id
        LIMIT 3
        """
        samples = list(repository.run_cypher(sample_query, {}))

        # Get active networks
        network_query = """
        MATCH (n:NetworkContainer)
        WHERE n.cidr IS NOT NULL
        RETURN n.cidr AS cidr
        LIMIT 5
        """
        networks = list(repository.run_cypher(network_query, {}))

        # Build summary
        total = sum(record.get("count", 0) for record in counts)
        node_breakdown = ", ".join(
            f"{record.get('count', 0)} {record.get('label', 'Unknown')}" for record in counts[:4]
        )
        sample_ids = [str(record.get("id", ""))[:8] + "..." for record in samples[:3]]
        network_list = [record.get("cidr", "") for record in networks[:5]]

        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

        summary = f"""## Infrastructure Graph Summary (as of {timestamp})
- Total nodes: {total} ({node_breakdown})
- Sample node IDs: {', '.join(sample_ids) if sample_ids else 'none'}
- Active networks: {', '.join(network_list) if network_list else 'none'}
"""
        return summary
    except Exception:  # noqa: BLE001
        # If graph query fails, return minimal summary
        return """## Infrastructure Graph Summary
- Graph data available via graph_query tool
- Use queries to explore nodes, relationships, and metadata
"""


@dataclass
class ToolResult:
    tool_call_id: str
    tool_name: str
    result: dict | None = None
    error: str | None = None
    success: bool = True


def build_system_prompt(
    tools: Iterable[Tool], permissions: SandboxPermissions, repository: Any | None = None
) -> str:
    tool_lines = "\n".join(f"- {tool.name}: {tool.description}" for tool in tools)
    allowed = ", ".join(permissions.allowed_tools) if permissions.allowed_tools else "all"
    blocked = ", ".join(permissions.blocked_tools) if permissions.blocked_tools else "none"

    # Capture system environment info
    os_type = platform.system()  # Windows, Linux, Darwin (macOS)
    os_release = platform.release()
    arch = platform.machine()  # x86_64, ARM64, etc.
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    hostname = platform.node()

    # Detect available CLI tools
    available_tools = detect_available_tools()
    tools_summary = []
    for category, tools in available_tools.items():
        tools_summary.append(f"  {category}: {', '.join(tools)}")
    tools_str = (
        "\n".join(tools_summary) if tools_summary else "  (no infrastructure tools detected)"
    )

    # Get graph summary if repository is available
    graph_summary = get_graph_summary(repository) if repository else ""

    return f"""You are Eidolon, a network and infrastructure assistant.

## Operating Environment
- OS: {os_type} {os_release}
- Architecture: {arch}
- Python: {python_version}
- Hostname: {hostname}
- Shell: {'PowerShell' if os_type == 'Windows' else 'bash'}

## Available CLI Tools
{tools_str}

{graph_summary}

## IMPORTANT: Always Check the Graph First

**The infrastructure graph contains discovered network data from scans.** Before running manual
network discovery:
1. Query the graph using `graph_query` to see what's already discovered
2. Check for networks, assets, and their metadata
3. Only use manual tools (nmap, etc.) if the graph lacks the specific information needed

The graph is your PRIMARY data source for network infrastructure information.

## Available Tools
{tool_lines}

## Neo4j Graph Reference

The infrastructure graph uses Neo4j 5.x with the following structure:

**Node Types:**
- Asset (hosts, services) - has `node_id`, `kind`, `metadata` (JSON string)
- NetworkContainer (networks) - has `node_id`, `cidr`
- Identity (users, accounts) - has `node_id`, `name`, `kind`
- Policy (rules) - has `node_id`, `name`, `rule_type`

**Relationships:**
- MEMBER_OF (Asset → NetworkContainer)
- CONNECTS_TO (Asset → Asset)
- HAS_IDENTITY (Asset → Identity)
- GOVERNED_BY (Asset/Network → Policy)

**Metadata Handling:**
The `metadata` field is a JSON string, not a map. Parse after retrieval:
```cypher
MATCH (a:Asset)
WHERE a.metadata IS NOT NULL
RETURN a.node_id, a.metadata
```

**Common Metadata Fields** (populated by collectors):
- `ip` - IPv4/IPv6 address
- `hostname` - DNS hostname
- `mac_address` - MAC address (from ARP/nmap)
- `vendor` - Network interface vendor (from MAC OUI lookup via nmap)
- `ports` - Array of port objects:
  `[{{"port": 22, "state": "open", "service": "ssh", "version": "..."}}]`
- `status` - Host status: "online", "offline", "idle"
- `os` - Operating system fingerprint (if available from nmap)
- `cidr` - Network CIDR the host belongs to

**Example - Find hosts by vendor:**
```cypher
MATCH (a:Asset)
WHERE a.metadata CONTAINS '"vendor"'
RETURN a.node_id, a.metadata
```

Note: Metadata is stored as JSON string. To search for specific values, use CONTAINS with flexible
patterns:
- `WHERE a.metadata CONTAINS 'Samsung'` (case-sensitive substring)
- Use CONTAINS with just the value to avoid JSON formatting issues

**Query Examples:**

List assets:
```cypher
MATCH (a:Asset) WHERE a.node_id IS NOT NULL
RETURN a.node_id, a.metadata LIMIT 100
```

Blast radius (nodes within N hops):
```cypher
MATCH path = (start:Asset)-[*1..2]-(affected)
WHERE start.node_id = $target_id AND affected.node_id IS NOT NULL
RETURN DISTINCT affected.node_id, affected.metadata, length(path) AS distance
ORDER BY distance
```

Network membership:
```cypher
MATCH (a:Asset)-[:MEMBER_OF]->(n:NetworkContainer)
WHERE n.cidr = $cidr
RETURN a.node_id, a.metadata
```

**Notes:**
- Use `WHERE n.node_id IS NOT NULL` to filter auxiliary nodes
- Use `IS NOT NULL` instead of deprecated `exists()`
- Parameterize inputs: `WHERE a.node_id = $param`
- Add LIMIT to prevent overwhelming results

## Output Guidelines

When presenting technical data to users:
- Use human-readable identifiers (IPs, hostnames) from metadata, not raw UUIDs
- Format results clearly (tables, lists, summaries)
- Parse JSON metadata strings to extract meaningful fields

## Todo Workflow

When working with todo items:
1. **Create** todos for multi-step tasks by calling the `todo` tool with action "set"
2. **Execute immediately** - once a todo is created, start working on it in the next iteration
3. **Mark progress** - call `todo` with action "complete" when finishing each item, or "skip"
   if blocked
4. **Never ask permission** - do not ask "Want me to run it now?" or similar questions
5. **Stay focused** - work through the todo list without unnecessary intermediate messages

The todo tool is for YOUR planning and tracking, not for soliciting user input.

## Sandbox Permissions
- allow_shell: {{permissions.allow_shell}}
- allow_network: {{permissions.allow_network}}
- allow_file_write: {{permissions.allow_file_write}}
- allowed_tools: {allowed}
- blocked_tools: {blocked}
"""


class AssistantAgent:
    """Single-mode assistant loop with tool calling and todo-driven iterations."""

    def __init__(
        self,
        llm_client: LiteLLMClient,
        sandbox: SandboxRuntime,
        system_prompt: str,
        max_iterations: int = 8,
    ) -> None:
        self.llm_client = llm_client
        self.sandbox = sandbox
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.memory = ConversationMemory(max_tokens=self.llm_client.settings.max_context_tokens)

    def run(
        self, history: list[ChatMessage], cancellation_token: Any | None = None
    ) -> list[ChatMessage]:
        """Run the assistant loop and return new messages."""
        return list(self.run_iter(history, cancellation_token=cancellation_token))

    def run_iter(
        self, history: list[ChatMessage], cancellation_token: Any | None = None
    ) -> Iterable[ChatMessage]:
        """Run the assistant loop and yield messages as they are produced."""
        working_history = list(history)
        todo_tool = self._get_todo_tool()
        if todo_tool:
            self._restore_todo_state(todo_tool, working_history)
        todo_engaged = bool(todo_tool and todo_tool.items)
        completed = False
        iterations = 0

        while iterations < self.max_iterations:
            if self._is_cancelled(cancellation_token):
                break
            iterations += 1
            response = self.llm_client.generate(
                system_prompt=self.system_prompt,
                messages=self._format_messages_for_llm(working_history),
                tools=list(self.sandbox.active_tools.values()),
                memory=self.memory,
            )
            if self._is_cancelled(cancellation_token):
                break

            if not response.tool_calls:
                content = response.content or ""
                if not content:
                    error_summary = self._summarize_recent_tool_errors(working_history)
                    if error_summary:
                        if self._is_cancelled(cancellation_token):
                            break
                        error_msg = ChatMessage(
                            role="assistant",
                            content=error_summary,
                            metadata={"kind": "message", "tool_error": True},
                        )
                        working_history.append(error_msg)
                        yield error_msg
                        # Check if there are pending todos before breaking
                        todo_pending = todo_tool.has_pending() if todo_tool else False
                        if not todo_pending:
                            completed = True
                            break
                        # Continue loop to execute pending todos
                        continue
                    if self._is_cancelled(cancellation_token):
                        break
                    # Check if there are pending todos before breaking
                    todo_pending = todo_tool.has_pending() if todo_tool else False
                    if not todo_pending:
                        empty_msg = ChatMessage(
                            role="assistant",
                            content="Agent returned an empty response.",
                            metadata={"kind": "thinking", "empty_response": True},
                        )
                        working_history.append(empty_msg)
                        yield empty_msg
                        break
                    # Continue loop to execute pending todos
                    continue

                todo_pending = todo_tool.has_pending() if todo_tool else False
                kind = "thinking" if todo_pending else "message"
                if self._is_cancelled(cancellation_token):
                    break
                msg = ChatMessage(
                    role="assistant",
                    content=content,
                    metadata={
                        "kind": kind,
                        "intermediate": todo_pending,
                        "usage": response.usage,
                    },
                )
                working_history.append(msg)
                yield msg
                if not todo_pending:
                    completed = True
                    break
                continue

            if response.content:
                if self._is_cancelled(cancellation_token):
                    break
                thinking_msg = ChatMessage(
                    role="assistant",
                    content=response.content,
                    metadata={
                        "kind": "thinking",
                        "intermediate": True,
                        "transient": True,
                        "usage": response.usage,
                    },
                )
                working_history.append(thinking_msg)
                yield thinking_msg

            tool_calls = self._normalize_tool_calls(response.tool_calls)
            if not tool_calls:
                content = response.content or ""
                if not content:
                    if self._is_cancelled(cancellation_token):
                        break
                    empty_msg = ChatMessage(
                        role="assistant",
                        content="Agent returned an empty tool call payload.",
                        metadata={"kind": "warning", "empty_tool_calls": True},
                    )
                    working_history.append(empty_msg)
                    yield empty_msg
                    break
                if self._is_cancelled(cancellation_token):
                    break
                msg = ChatMessage(
                    role="assistant",
                    content=content,
                    metadata={"kind": "message", "usage": response.usage},
                )
                working_history.append(msg)
                yield msg
                completed = True
                break

            if any(call.get("name") == "todo" for call in tool_calls):
                todo_engaged = True

            if self._is_cancelled(cancellation_token):
                break
            tool_call_msg = ChatMessage(
                role="assistant",
                content=response.content or "",
                metadata={"kind": "tool_call", "tool_calls": tool_calls, "usage": response.usage},
            )
            working_history.append(tool_call_msg)
            yield tool_call_msg

            if self._is_cancelled(cancellation_token):
                break
            tool_results = self._execute_tools(tool_calls)
            for result in tool_results:
                if self._is_cancelled(cancellation_token):
                    break
                content = self._serialize_tool_output(result.result, result.error)
                tool_msg = ChatMessage(
                    role="tool",
                    content=content,
                    metadata={
                        "kind": "tool_result",
                        "tool_call_id": result.tool_call_id,
                        "tool_name": result.tool_name,
                        "success": result.success,
                        "result": self._safe_json(result.result),
                        "error": result.error,
                    },
                )
                working_history.append(tool_msg)
                yield tool_msg

            if any(call.get("name") == "finish" for call in tool_calls):
                completed = True
                break

            for call, result in zip(tool_calls, tool_results, strict=False):
                if self._is_cancelled(cancellation_token):
                    break
                if call.get("name") != "todo":
                    continue
                action = call.get("arguments", {}).get("action")
                if action not in {"set", "add"}:
                    continue
                items = []
                if isinstance(result.result, dict):
                    items = result.result.get("items", [])
                steps = [
                    str(item.get("text"))
                    for item in items
                    if isinstance(item, dict) and item.get("text")
                ]
                if not steps:
                    continue
                plan_content = "\n".join(f"{idx + 1}. {step}" for idx, step in enumerate(steps))
                if self._is_cancelled(cancellation_token):
                    break
                plan_msg = ChatMessage(
                    role="assistant",
                    content=plan_content,
                    metadata={"kind": "plan", "steps": steps},
                )
                working_history.append(plan_msg)
                yield plan_msg

            if todo_engaged and todo_tool and not todo_tool.has_pending():
                summary_msg = self._generate_summary(working_history)
                if summary_msg:
                    if self._is_cancelled(cancellation_token):
                        break
                    working_history.append(summary_msg)
                    yield summary_msg
                completed = True
                break

        if not completed and iterations >= self.max_iterations:
            if self._is_cancelled(cancellation_token):
                return
            warning = ChatMessage(
                role="assistant",
                content=f"Reached iteration limit ({self.max_iterations}).",
                metadata={"kind": "warning", "max_iterations": True},
            )
            yield warning

    def _is_cancelled(self, cancellation_token: Any | None) -> bool:
        if not cancellation_token:
            return False
        is_set = getattr(cancellation_token, "is_set", None)
        if callable(is_set):
            try:
                return bool(is_set())
            except Exception:  # noqa: BLE001
                return False
        return False

    def _get_todo_tool(self) -> TodoTool | None:
        tool = self.sandbox.active_tools.get("todo")
        return tool if isinstance(tool, TodoTool) else None

    def _summarize_recent_tool_errors(self, history: list[ChatMessage]) -> str | None:
        errors: list[str] = []
        for msg in reversed(history[-6:]):
            if msg.role != "tool":
                continue
            error = msg.metadata.get("error")
            if error:
                errors.append(str(error))
        if not errors:
            return None
        if len(errors) == 1:
            return f"Tool error: {errors[0]}"
        joined = "\n".join(f"- {err}" for err in errors)
        return f"Multiple tool errors:\n{joined}"

    def _restore_todo_state(self, todo_tool: TodoTool, history: list[ChatMessage]) -> None:
        if todo_tool.items:
            return
        for msg in reversed(history):
            if msg.role != "tool":
                continue
            if msg.metadata.get("tool_name") == "finish":
                return
            if msg.metadata.get("tool_name") != "todo":
                continue
            result = msg.metadata.get("result")
            if not isinstance(result, dict):
                break
            items = result.get("items")
            if not isinstance(items, list):
                break
            restored = []
            for item in items:
                if isinstance(item, dict) and "text" in item:
                    restored.append(item)
                else:
                    restored.append(
                        {"id": len(restored) + 1, "text": str(item), "status": "pending"}
                    )
            todo_tool.items = restored
            max_id = max((item.get("id", 0) for item in restored), default=0)
            todo_tool._next_id = int(max_id) + 1
            break

    def _generate_summary(self, history: list[ChatMessage]) -> ChatMessage | None:
        response = self.llm_client.generate(
            system_prompt="You are a helpful assistant. Provide a concise summary of the results.",
            messages=self._format_messages_for_llm(history),
            tools=None,
            memory=self.memory,
        )
        content = response.content or ""
        if not content.strip():
            content = "Task complete."
        return ChatMessage(
            role="assistant",
            content=content,
            metadata={"kind": "message", "summary": True, "usage": response.usage},
        )

    def _format_messages_for_llm(self, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        formatted: list[dict[str, Any]] = []
        for msg in messages:
            if msg.metadata.get("transient"):
                continue
            if msg.role == "tool":
                tool_call_id = msg.metadata.get("tool_call_id")
                entry = {"role": "tool", "content": msg.content}
                if tool_call_id:
                    entry["tool_call_id"] = tool_call_id
                tool_name = msg.metadata.get("tool_name")
                if tool_name:
                    entry["name"] = tool_name
                formatted.append(entry)
                continue

            entry = {"role": msg.role, "content": msg.content}
            tool_calls = msg.metadata.get("tool_calls")
            if tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call["arguments"], default=str),
                        },
                    }
                    for call in tool_calls
                ]
            formatted.append(entry)
        return formatted

    def _normalize_tool_calls(self, raw_calls: list[Any]) -> list[dict[str, Any]]:
        tool_calls: list[dict[str, Any]] = []
        for index, call in enumerate(raw_calls or []):
            call_id = getattr(call, "id", None)
            if not call_id and isinstance(call, dict):
                call_id = call.get("id")
            if not call_id:
                call_id = f"call_{index}"

            func = getattr(call, "function", None)
            if func is None and isinstance(call, dict):
                func = call.get("function", {})
            if hasattr(func, "name"):
                name = func.name
                args_raw = func.arguments
            else:
                func_dict = func if isinstance(func, dict) else {}
                name = func_dict.get("name") or (
                    call.get("name", "") if isinstance(call, dict) else ""
                )
                args_raw = func_dict.get("arguments")
                if args_raw is None and isinstance(call, dict):
                    args_raw = call.get("arguments", {})

            if not name:
                continue

            arguments = self._parse_arguments(args_raw)
            tool_calls.append({"id": call_id, "name": name, "arguments": arguments})
        return tool_calls

    def _parse_arguments(self, args: Any) -> dict:
        if isinstance(args, dict):
            return args
        if isinstance(args, str):
            try:
                return json.loads(args)
            except json.JSONDecodeError:
                return {"raw": args}
        return {}

    def _execute_tools(self, tool_calls: list[dict[str, Any]]) -> list[ToolResult]:
        results: list[ToolResult] = []
        todo_tool = self._get_todo_tool()
        todo_locked = bool(todo_tool and todo_tool.items)
        for call in tool_calls:
            tool_name = call["name"]
            tool_call_id = call["id"]
            arguments = call.get("arguments", {})
            if tool_name == "todo" and todo_locked:
                action = str(arguments.get("action", "")).lower()
                if action not in {"list", "complete", "skip"}:
                    results.append(
                        ToolResult(
                            tool_call_id=tool_call_id,
                            tool_name=tool_name,
                            error=(
                                "todo list is already initialized; only 'complete', 'skip', or "
                                "'list' allowed until finish"
                            ),
                            success=False,
                        )
                    )
                    continue
            try:
                result = self.sandbox.execute(tool_name, arguments)
            except Exception as exc:  # noqa: BLE001
                results.append(
                    ToolResult(
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        error=str(exc),
                        success=False,
                    )
                )
                continue

            if isinstance(result, dict) and result.get("error"):
                results.append(
                    ToolResult(
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        error=str(result.get("error")),
                        success=False,
                    )
                )
            else:
                results.append(
                    ToolResult(
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        result=result if isinstance(result, dict) else {"result": result},
                        success=True,
                    )
                )
        return results

    def _serialize_tool_output(self, result: dict | None, error: str | None) -> str:
        payload: dict[str, Any] = {"error": error} if error else result or {"result": "ok"}
        try:
            return json.dumps(payload, ensure_ascii=True)
        except TypeError:
            return json.dumps({"result": str(payload)}, ensure_ascii=True)

    def _safe_json(self, value: Any) -> Any:
        if value is None:
            return None
        try:
            return json.loads(json.dumps(value, default=str))
        except TypeError:
            return {"result": str(value)}
