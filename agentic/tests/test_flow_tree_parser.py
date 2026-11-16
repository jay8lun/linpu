"""flow_tree_parser 单元测试：覆盖树构建与结构校验逻辑。"""
import json
import unittest

from util.flow_tree_parser import (
    FlowTreeParseError,
    FlowTreeParser,
    TreeNode,
)


def _node(node_id, agent_id, name="agent", **extra):
    data = {"agentId": agent_id, "name": name}
    data.update(extra)
    return {"id": node_id, "shape": "agent-node", "data": data}


def _edge(edge_id, source, target):
    return {
        "id": edge_id,
        "shape": "edge",
        "source": {"cell": source},
        "target": {"cell": target},
    }


def _flow(cells):
    return json.dumps({"cells": cells})


class TestFlowTreeParser(unittest.TestCase):

    def setUp(self):
        self.parser = FlowTreeParser()

    def test_single_node_no_edge(self):
        """单节点无连线：应正常返回该节点为根"""
        flow = _flow([_node("n1", 1)])
        root = self.parser.parse_to_tree(flow)
        self.assertEqual(root.node.node_id, "n1")
        self.assertEqual(root.node.agent_id, 1)
        self.assertEqual(root.children, [])

    def test_chain_three_nodes(self):
        """线性链 n1 -> n2 -> n3：根为 n1，逐层一个子节点"""
        cells = [
            _node("n1", 1),
            _node("n2", 2),
            _node("n3", 3),
            _edge("e1", "n1", "n2"),
            _edge("e2", "n2", "n3"),
        ]
        root = self.parser.parse_to_tree(_flow(cells))
        self.assertEqual(root.node.node_id, "n1")
        self.assertEqual(len(root.children), 1)
        self.assertEqual(root.children[0].node.node_id, "n2")
        self.assertEqual(root.children[0].children[0].node.node_id, "n3")

    def test_tree_with_branch(self):
        """根 n1 分叉到 n2、n3：根有两个子节点"""
        cells = [
            _node("n1", 1),
            _node("n2", 2),
            _node("n3", 3),
            _edge("e1", "n1", "n2"),
            _edge("e2", "n1", "n3"),
        ]
        root = self.parser.parse_to_tree(_flow(cells))
        self.assertEqual(root.node.node_id, "n1")
        self.assertEqual(len(root.children), 2)

    def test_empty_nodes_raises(self):
        """无任何节点：应抛 ValueError"""
        with self.assertRaises(ValueError):
            self.parser.parse_to_tree(_flow([]))

    def test_multiple_roots_raises(self):
        """两个互不相连的节点（两个根）：应抛 ValueError"""
        cells = [_node("n1", 1), _node("n2", 2)]
        with self.assertRaises(ValueError):
            self.parser.parse_to_tree(_flow(cells))

    def test_cycle_no_root_raises(self):
        """n1 <-> n2 成环（无入度为0的节点）：应抛 ValueError"""
        cells = [
            _node("n1", 1),
            _node("n2", 2),
            _edge("e1", "n1", "n2"),
            _edge("e2", "n2", "n1"),
        ]
        with self.assertRaises(ValueError):
            self.parser.parse_to_tree(_flow(cells))

    def test_duplicate_node_id_raises(self):
        """重复节点 ID：应抛 ValueError"""
        cells = [_node("n1", 1), _node("n1", 2)]
        with self.assertRaises(ValueError):
            self.parser.parse_to_tree(_flow(cells))

    def test_missing_agent_id_raises(self):
        """节点缺少 agentId：应抛 ValueError"""
        cells = [{"id": "n1", "shape": "agent-node", "data": {"name": "no_agent"}}]
        with self.assertRaises(ValueError):
            self.parser.parse_to_tree(_flow(cells))

    def test_edge_reference_missing_node_raises(self):
        """连线引用不存在的节点：应抛 ValueError"""
        cells = [
            _node("n1", 1),
            _edge("e1", "n1", "ghost"),
        ]
        with self.assertRaises(ValueError):
            self.parser.parse_to_tree(_flow(cells))

    def test_invalid_json_raises_parse_error(self):
        """非法 JSON：应抛 FlowTreeParseError"""
        with self.assertRaises(FlowTreeParseError):
            self.parser.parse_to_tree("{not valid json")

    def test_node_data_fields_preserved(self):
        """节点 data 字段（name/description/showReasoning/flowMemory）应正确保留"""
        cells = [
            _node(
                "n1",
                7,
                name="检索智能体",
                description="负责检索",
                showReasoning=True,
                flowMemory=False,
            )
        ]
        root = self.parser.parse_to_tree(_flow(cells))
        self.assertEqual(root.node.agent_name, "检索智能体")
        self.assertEqual(root.node.description, "负责检索")
        self.assertTrue(root.node.show_reasoning)
        self.assertFalse(root.node.flow_memory)


if __name__ == "__main__":
    unittest.main()
