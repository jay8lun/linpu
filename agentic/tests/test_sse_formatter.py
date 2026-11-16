"""sse_formatter 单元测试：验证 SSE 数据块格式正确。"""
import json
import unittest

from service.sse_formatter import (
    format_sse_text,
    format_sse_tool_call,
    format_sse_tool_result,
    format_sse_error,
)


def _parse_data(sse_str):
    """从 'data: {...}\n\n' 中提取 JSON 对象。"""
    payload = sse_str.strip()
    assert payload.startswith("data: "), f"缺少 data: 前缀: {payload!r}"
    return json.loads(payload[len("data: "):])


class TestSseFormatter(unittest.TestCase):

    def test_text_with_agent(self):
        sse = format_sse_text("你好", agent_id=1, agent_name="Jarvis")
        obj = _parse_data(sse)
        self.assertEqual(obj, {"msg": "你好", "agentId": 1, "agentName": "Jarvis"})

    def test_text_without_agent_id(self):
        sse = format_sse_text("你好", agent_name="主 Agent")
        obj = _parse_data(sse)
        self.assertEqual(obj, {"msg": "你好", "agentName": "主 Agent"})
        self.assertNotIn("agentId", obj)

    def test_tool_call(self):
        sse = format_sse_tool_call("query_kb", agent_id=2, agent_name="检索")
        obj = _parse_data(sse)
        self.assertEqual(obj["tool_call"], {"toolName": "query_kb"})
        self.assertEqual(obj["agentId"], 2)

    def test_tool_result(self):
        sse = format_sse_tool_result("query_kb", "结果文本", agent_id=2)
        obj = _parse_data(sse)
        self.assertEqual(obj["tool_called"]["toolName"], "query_kb")
        self.assertEqual(obj["tool_called"]["toolInvokeResult"], "结果文本")

    def test_error(self):
        sse = format_sse_error("出错了")
        obj = _parse_data(sse)
        self.assertEqual(obj, {"error": {"message": "出错了"}})

    def test_chinese_not_escaped(self):
        sse = format_sse_text("中文内容")
        self.assertIn("中文内容", sse)  # ensure_ascii=False，中文不应转义


if __name__ == "__main__":
    unittest.main()
