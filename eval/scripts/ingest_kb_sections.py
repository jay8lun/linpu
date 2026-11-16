"""按小节切分知识库文档并按应用一致的向量化方式写入 pgvector。

背景：应用内置的按字符递归切分（DocumentSplitters.recursive）会把 Markdown 标题
和正文切开，导致「某章节讲什么」这类查询召回不到目标段落。本脚本改为按 `## ` 小节
切分，每个分段自带标题，语义更完整。

向量计算方式与应用完全一致（ONNX + mean pooling + L2 归一化），已验证与应用产出的
向量余弦相似度为 1.0，因此与线上查询向量同分布。
"""
import json
import sys
import uuid
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

DOC_PATH = Path("eval/kb/linpu-platform-manual.md")
MODEL_DIR = Path("models")
KB_ID = "1"
FILE_NAME = "linpu-manual.md"
ABS_DIR = "/uploadPath/upload/2026/11/16"


def load_sections(text: str):
    """按 `## ` 二级标题切分，返回 [(标题, 整节文本)]。"""
    sections = []
    cur_title, cur_lines = None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if cur_title is not None:
                sections.append((cur_title, "\n".join(cur_lines).strip()))
            cur_title = line[3:].strip()
            cur_lines = [line]
        else:
            cur_lines.append(line)
    if cur_title is not None:
        sections.append((cur_title, "\n".join(cur_lines).strip()))
    return sections


def build_embedder():
    tok = Tokenizer.from_file(str(MODEL_DIR / "onnx" / "tokenizer.json"))
    tok.enable_truncation(max_length=512)
    tok.enable_padding(length=None)
    sess = ort.InferenceSession(
        str(MODEL_DIR / "onnx" / "model.onnx"), providers=["CPUExecutionProvider"]
    )
    input_names = [i.name for i in sess.get_inputs()]

    def embed(text: str):
        enc = tok.encode(text)
        ids = np.array([enc.ids], dtype=np.int64)
        mask = np.array([enc.attention_mask], dtype=np.int64)
        feeds = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in input_names:
            feeds["token_type_ids"] = np.zeros_like(ids)
        out = sess.run(None, feeds)[0]
        m = mask[..., None].astype(np.float32)
        v = (out * m).sum(1) / np.clip(m.sum(1), 1e-9, None)
        v = v[0]
        return v / (np.linalg.norm(v) + 1e-9)

    return embed


def vec_literal(v: np.ndarray) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in v) + "]"


def main():
    text = DOC_PATH.read_text(encoding="utf-8")
    sections = load_sections(text)
    if not sections:
        sys.exit("未解析到任何小节")
    embed = build_embedder()

    lines = ["BEGIN;"]
    for idx, (title, body) in enumerate(sections):
        vec = vec_literal(embed(body))
        meta = json.dumps(
            {
                "absolute_directory_path": ABS_DIR,
                "kb_id": KB_ID,
                "file_name": FILE_NAME,
                "index": str(idx),
                "section": title,
            },
            ensure_ascii=False,
        ).replace("'", "''")
        seg = body.replace("'", "''")
        lines.append(
            "INSERT INTO embedding (embedding_id, embedding, text, metadata) VALUES "
            f"('{uuid.uuid4()}', '{vec}', '{seg}', '{meta}');"
        )
    lines.append("COMMIT;")

    out = Path("eval/results/_kb_sections.sql")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"已生成 {len(sections)} 个小节，SQL 写入 {out}")


if __name__ == "__main__":
    main()
