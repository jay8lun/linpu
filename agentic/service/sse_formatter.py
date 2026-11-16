"""SSE 数据块格式化工具：把聊天流中的文本/工具调用/错误格式化为 SSE 字符串。"""
import json
from typing import Optional


def format_sse_text(
    content: str, agent_id: Optional[int] = None, agent_name: str = "主 Agent"
) -> str:
    """格式化文本 SSE 数据块。格式: {"msg": "内容", "agentId": 1, "agentName": "Jarvis"}"""
    chunk_obj = {"msg": content}
    if agent_id is not None:
        chunk_obj["agentId"] = agent_id
    chunk_obj["agentName"] = agent_name
    chunk_str = json.dumps(chunk_obj, ensure_ascii=False)
    return f"data: {chunk_str}\n\n"


def format_sse_tool_call(
    tool_name: str, agent_id: Optional[int] = None, agent_name: str = "主 Agent"
) -> str:
    """格式化工具调用开始 SSE 消息。"""
    chunk_obj = {"tool_call": {"toolName": tool_name}}
    if agent_id is not None:
        chunk_obj["agentId"] = agent_id
    chunk_obj["agentName"] = agent_name
    chunk_str = json.dumps(chunk_obj, ensure_ascii=False)
    return f"data: {chunk_str}\n\n"


def format_sse_tool_result(
    tool_name: str,
    result: str,
    agent_id: Optional[int] = None,
    agent_name: str = "主 Agent",
) -> str:
    """格式化工具调用完成 SSE 消息。"""
    chunk_obj = {"tool_called": {"toolName": tool_name, "toolInvokeResult": result}}
    if agent_id is not None:
        chunk_obj["agentId"] = agent_id
    chunk_obj["agentName"] = agent_name
    chunk_str = json.dumps(chunk_obj, ensure_ascii=False)
    return f"data: {chunk_str}\n\n"


def format_sse_error(error_msg: str) -> str:
    """格式化错误 SSE 消息。"""
    chunk_obj = {"error": {"message": error_msg}}
    chunk_str = json.dumps(chunk_obj, ensure_ascii=False)
    return f"data: {chunk_str}\n\n"
