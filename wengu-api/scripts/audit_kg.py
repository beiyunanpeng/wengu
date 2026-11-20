"""P5-18 K12-KGraph 只读对照审计（纯开发者侧，手动跑；零新依赖、零联网、对仓库零写入）。

    python wengu-api/scripts/audit_kg.py                 # HF 全量布局（默认六件）
    python wengu-api/scripts/audit_kg.py --kg-dir D:/MyProducts/StudyDesk/K12-KGraph  # GitHub demo 布局
    python wengu-api/scripts/audit_kg.py --json          # stdout 改出机器可读 JSON
    python wengu-api/scripts/audit_kg.py --subject math  # 候选表/gap 只跑一科（可多次传入）

报告（JSON + Markdown 两件套）一律落仓库外 --out-dir（默认 D:/MyProducts/StudyDesk/kg-audit）；
--kg-dir / --out-dir 任一落在仓库内即拒绝运行。布局靠文件探测：HF 全量（global_KG 瘦图 +
subject_specific_KG 四科富图）或 GitHub demo（demo/kg 一本书 + books.yaml）；认不出、缺件、
文件字节与 sha 锚点不符 → 可读错误 + exit 2，绝不静默出半份报告。
exit 0 = 审计完成（上游成环等发现是产品、不是失败）。

纪律（设计文档 §19-G-3 定案二/三，卡面 P5-18）：
- 只出候选表 + 结构体检，禁止输出名字对齐"覆盖率"结论（evidence 携带率是结构指标、不受此限）；
- 他们的 definition/examples/stem/answer 绝不复制进任何进仓库的文件（抄文本即 Adaptation、
  触发 CC BY-NC-SA 的 SA 义务）；本地报告可带 evidence 片段；
- 主层 = 富图：环检测与 evidence 取回都在 subject_specific_KG 一层；瘦图只作规模对照与交叉验证，
  两层不一致时以富图为准并如实报差异；
- 学科映射写死逐字表（他们"生物学" → 我们"生物"），学段只按 books.yaml 的 stage 三档
  （小学→grade 1–6 / 初中→7–9 / 高中→10–16）；禁止用字符串包含或前缀猜学科与年级，
  禁止逐册年级映射（本票无实测依据）；
- 无 evidence 的 gap 不得进 ②③ 清单；④ 粒度差异单列、不计入缺失总数；
  反向 gap（我们有他们没有）不算问题、不得据此删点。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KG_DIR = Path("D:/MyProducts/StudyDesk/K12-KGraph-hf")
DEFAULT_OUT_DIR = Path("D:/MyProducts/StudyDesk/kg-audit")
GITHUB_SIBLING_DIR = "K12-KGraph"  # HF 布局无 books.yaml 时的同级 GitHub 副本目录名

# 他们 subject → 我们 subject（逐字映射表，卡面定案⑤；dict 精确取值 = 天然拒绝包含式匹配）
SUBJECT_MAP = {"数学": "数学", "物理": "物理", "化学": "化学", "生物学": "生物"}
# 富图文件名 → 他们 books.yaml 的 subject 逐字值
FILE_SUBJECT = {"math": "数学", "physics": "物理", "chemistry": "化学", "biology": "生物学"}
STAGE_BANDS = {"小学": range(1, 7), "初中": range(7, 10), "高中": range(10, 17)}

# 卡面「运行期输入」钉死的 sha256 前 16 位锚点：不符 = 副本被换过，拒绝出报告
HF_ANCHORS = {
    "global_KG/nodes.json": "99d7d4b86e7c92f6",
    "global_KG/edges.json": "b7b2bea4a16467b5",
    "subject_specific_KG/math.json": "00ed25179bb4ad09",
    "subject_specific_KG/physics.json": "2108bcb685554ecb",
    "subject_specific_KG/chemistry.json": "6441ec8e247f8535",
    "subject_specific_KG/biology.json": "c775d68709aaca2c",
}
DEMO_ANCHORS = {
    "demo/kg/math_7a_rjb.json": "568582a7d4fc06e3",
    "LICENSE": "6c16319398a96728",
}
DEMO_REQUIRED = set(DEMO_ANCHORS) | {"demo/manifest.json", "books.yaml"}

LICENSE_NOTE = (
    "K12-KGraph 数据 = CC BY-NC-SA 4.0（代码 MIT）：本报告仅限本机私有使用；"
    "他们的 definition/examples/stem/answer 与本报告都不得进仓库、备份包或任何分发面"
    "（设计文档 §19-G-3 定案二）。"
)


class AuditError(RuntimeError):
    """审计无法得出结论（缺件/布局不认识/锚点不符/路径违规）；调用方必须 exit 2，不猜。"""


# ---------------------------------------------------------------------------
# 纯解析/计算层：只吃数据结构，不接受路径、不联网、不写盘。
# ---------------------------------------------------------------------------


def normalize_name(value: Any) -> str:
    """NFKC → 去非文字符号 → lower（与审核方取证脚本同尺）。"""
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"[^\w一-鿿]", "", text).lower()


def book_prefix_of(node_id: str) -> str:
    """id 去掉最后一段即 book_prefix（math_7a_rjb_cpt1 → math_7a_rjb，卡面⑭）。"""
    return "_".join(str(node_id).split("_")[:-1])


def map_subject(their_subject: str) -> str | None:
    """逐字查表；查不到 = None（无对照学科）。绝不退化成包含/前缀匹配。"""
    return SUBJECT_MAP.get(their_subject)


def parse_books_yaml(text: str) -> list[dict]:
    """books.yaml 的扁平书目块 → [{book_prefix, subject, stage, grade?, publisher?}]。

    零依赖手写解析（该文件是固定扁平结构）；stage 必须是三档之一，否则报错不猜。
    grade 是中文册名（七年级上册…），只透传、绝不映射成 int（卡面⑯）。
    """
    books: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        head = re.match(r"^- book_prefix:\s*(\S+)\s*$", line)
        if head:
            current = {"book_prefix": head.group(1)}
            books.append(current)
            continue
        field = re.match(r"^\s+(subject|stage|grade|publisher):\s*(.+?)\s*$", line)
        if field and current is not None:
            current[field.group(1)] = field.group(2)
    if not books:
        raise AuditError("books.yaml 未解析出任何书目（- book_prefix: 块）")
    for book in books:
        if not book.get("subject") or not book.get("stage"):
            raise AuditError(f"books.yaml 书目缺 subject/stage: {book}")
        if book["stage"] not in STAGE_BANDS:
            raise AuditError(f"books.yaml 出现未知 stage（只认 小学/初中/高中，不猜）: {book}")
    return books


def _normalize_edge(edge: Any, where: str) -> dict:
    """三种形态的边统一成 {type, source, target, source_name, target_name, properties,
    extra_targets}；tests_* 的 target_name_to_ids[] 收进 extra_targets。"""
    if not isinstance(edge, dict):
        raise AuditError(f"{where} 边必须是对象: {str(edge)[:120]}")
    etype, source = edge.get("type"), edge.get("source")
    if not isinstance(etype, str) or not isinstance(source, str):
        raise AuditError(f"{where} 边缺 type/source 字符串: {str(edge)[:120]}")
    props = edge.get("properties")
    if props is not None and not isinstance(props, dict):
        raise AuditError(f"{where} 边 properties 必须是对象: {str(edge)[:120]}")
    target = edge.get("target")
    extra: list[dict] = []
    if etype.startswith("tests_") and isinstance(edge.get("target_name_to_ids"), list):
        # 富图/demo 形态：tests_* 用 source_stem + target_name_to_ids[]
        for pair in edge["target_name_to_ids"]:
            if not isinstance(pair, dict) or not isinstance(pair.get("target"), str):
                raise AuditError(f"{where} target_name_to_ids 条目缺 target: {str(pair)[:120]}")
            extra.append({"target": pair["target"], "target_name": pair.get("target_name")})
        target = None
    elif not isinstance(target, str):
        # 瘦图形态：tests_* 也是扁平 source/target（盘上实测，卡面⑨"仅 source/target/type"）
        raise AuditError(f"{where} 边缺 target 字符串: {str(edge)[:120]}")
    return {
        "type": etype,
        "source": source,
        "target": target,
        "source_name": edge.get("source_name"),
        "target_name": edge.get("target_name"),
        "properties": props or {},
        "extra_targets": extra,
    }


def _check_nodes(nodes: Any, where: str) -> list[dict]:
    if not isinstance(nodes, list):
        raise AuditError(f"{where} nodes 必须是数组")
    for node in nodes:
        if not isinstance(node, dict) or not all(
            isinstance(node.get(key), str) for key in ("id", "label", "name")
        ):
            raise AuditError(f"{where} 节点缺 id/label/name 字符串: {str(node)[:120]}")
        props = node.get("properties")
        if props is not None and not isinstance(props, dict):
            raise AuditError(f"{where} 节点 properties 必须是对象: {str(node)[:120]}")
    return nodes


def parse_thin_graph(nodes: Any, edges: Any) -> dict:
    """瘦图（global_KG）：nodes/edges 两个扁平数组，节点仅 id/label/name。"""
    nodes = _check_nodes(nodes, "瘦图")
    if not isinstance(edges, list):
        raise AuditError("瘦图 edges 必须是数组")
    return {"nodes": nodes, "edges": [_normalize_edge(e, "瘦图") for e in edges]}


def parse_rich_graph(data: Any, where: str) -> dict:
    """富图（subject_specific_KG/*.json 与 demo 书级文件同形态）：顶层 {nodes, edges}。"""
    if not isinstance(data, dict):
        raise AuditError(f"{where} 顶层必须是对象（{{nodes, edges}}）")
    nodes = _check_nodes(data.get("nodes"), where)
    edges = data.get("edges")
    if not isinstance(edges, list):
        raise AuditError(f"{where} edges 必须是数组")
    return {"nodes": nodes, "edges": [_normalize_edge(e, where) for e in edges]}


def evidence_of(edge: dict) -> str | None:
    """边的 properties.evidence；瘦图无 properties → None。

    盘上实测两种形态：非空字符串，或 {"text": ..., "page": ...} 对象（数学富图 77 条、
    demo 13 条为对象形态——只认字符串会漏计，与卡面⑩锚点对不上）。对象形态取 text。
    """
    value = edge.get("properties", {}).get("evidence")
    if isinstance(value, str):
        return value if value.strip() else None
    if isinstance(value, dict):
        text = value.get("text")
        return text if isinstance(text, str) and text.strip() else None
    return None


def label_counts(nodes: list[dict]) -> dict:
    return dict(Counter(n["label"] for n in nodes).most_common())


def edge_type_counts(edges: list[dict]) -> dict:
    """按实测集合遍历计数——不硬编码 9 类（数学富图无 verifies，卡面⑪）。"""
    return dict(Counter(e["type"] for e in edges).most_common())


def evidence_stats(edges: list[dict]) -> dict:
    total = len(edges)
    with_ev = sum(1 for e in edges if evidence_of(e) is not None)
    prereq = [e for e in edges if e["type"] == "prerequisites_for"]
    prereq_ev = sum(1 for e in prereq if evidence_of(e) is not None)
    return {
        "edges": total,
        "edges_with_evidence": with_ev,
        "evidence_rate": with_ev / total if total else 0.0,
        "prereq_edges": len(prereq),
        "prereq_with_evidence": prereq_ev,
        "prereq_evidence_rate": prereq_ev / len(prereq) if prereq else 0.0,
    }


def find_cycles(node_ids: set[str], pairs: list[tuple[str, str]]) -> dict:
    """Kahn 判有无环（排不掉的节点数）+ Tarjan 取强连通分量（纯标准库、迭代防递归爆栈）。

    pairs 方向 = (前置, 后继)。自环与端点缺失单独计数，不参与拓扑。
    """
    ids = set(node_ids)
    adj: dict[str, list[str]] = {n: [] for n in ids}
    self_loops: list[list[str]] = []
    dangling = 0
    for a, b in pairs:
        if a not in ids or b not in ids:
            dangling += 1
        elif a == b:
            self_loops.append([a])
        else:
            adj[a].append(b)

    indeg = {n: 0 for n in ids}
    for a in adj:
        for b in adj[a]:
            indeg[b] += 1
    queue = [n for n in ids if indeg[n] == 0]
    seen = 0
    while queue:
        node = queue.pop()
        seen += 1
        for nxt in adj[node]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    kahn_unsorted = len(ids) - seen

    index: dict[str, int] = {}
    low: dict[str, int] = {}
    onstack: set[str] = set()
    stack: list[str] = []
    components: list[list[str]] = []
    counter = 0
    for root in ids:
        if root in index:
            continue
        work = [(root, iter(adj[root]))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        onstack.add(root)
        while work:
            node, it = work[-1]
            advanced = False
            for nxt in it:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    onstack.add(nxt)
                    work.append((nxt, iter(adj[nxt])))
                    advanced = True
                    break
                if nxt in onstack:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    member = stack.pop()
                    onstack.discard(member)
                    comp.append(member)
                    if member == node:
                        break
                components.append(sorted(comp))
    cycles = sorted((c for c in components if len(c) > 1), key=lambda c: c[0])
    return {
        "nodes": len(ids),
        "edges": len(pairs),
        "kahn_unsorted": kahn_unsorted,
        "cycles": cycles,
        "cycle_count": len(cycles),
        "self_loops": sorted(self_loops),
        "dangling_edges": dangling,
    }


def prereq_pairs(edges: list[dict]) -> list[tuple[str, str]]:
    return [(e["source"], e["target"]) for e in edges if e["type"] == "prerequisites_for"]


def appears_in_locations(node_ids: list[str], edges: list[dict], nodes_by_id: dict) -> list[dict]:
    """他们 appears_in → Section/Chapter 定位（卡面任务 5）。"""
    wanted = set(node_ids)
    out: list[dict] = []
    seen: set[str] = set()
    for edge in edges:
        if edge["type"] != "appears_in" or edge["source"] not in wanted:
            continue
        target = edge["target"]
        if target in seen:
            continue
        seen.add(target)
        out.append({
            "target": target,
            "name": edge.get("target_name") or (nodes_by_id.get(target) or {}).get("name"),
            "label": (nodes_by_id.get(target) or {}).get("label"),
        })
    return out


def first_evidence(node_ids: list[str], edges: list[dict]) -> str | None:
    """节点关联边里取第一条 evidence（prerequisites_for 优先，其余按文件序）。"""
    wanted = set(node_ids)
    incident = [
        e for e in edges
        if e["source"] in wanted or e["target"] in wanted
        or any(t["target"] in wanted for t in e["extra_targets"])
    ]
    incident.sort(key=lambda e: e["type"] != "prerequisites_for")
    for edge in incident:
        ev = evidence_of(edge)
        if ev is not None:
            return ev
    return None


def _name_groups(items: list[dict], id_key: str = "id") -> dict[str, dict]:
    groups: dict[str, dict] = {}
    for item in items:
        key = normalize_name(item.get("name"))
        if not key:
            continue
        group = groups.setdefault(key, {"name": item["name"], "ids": []})
        group["ids"].append(item[id_key])
    return groups


def _mutual_substring(name: str, others: set[str]) -> bool:
    return len(name) >= 2 and any(
        len(other) >= 2 and (name in other or other in name) for other in others
    )


def build_candidate_table(
    their_nodes: list[dict],
    their_edges: list[dict],
    our_topics: list[dict],
    books: list[dict],
    their_subject: str,
    stage: str,
) -> dict:
    """两档候选：精确同名 / NFKC 归一化子串互含（卡面任务 5、⑰实测口径）。

    精确档 = 同学段三档收窄（数学初中 555 名 vs 我们 grade7-9 315 点 → 44）；
    子串档 = 同学科**全学段**（555 vs 数学全 870 点 → 287，审核方取证脚本即此口径；
    若按学段收窄则只有 223，与卡面锚点不符——以盘上实测为准）。
    学科只走逐字映射表；我们侧按 topics 的 subject 字段 + grade int 收窄（不用前缀猜）。
    只报计数与候选行，绝不报"覆盖率"。
    """
    our_subject = map_subject(their_subject)
    if our_subject is None:
        raise AuditError(f"学科不在逐字映射表内（不猜）: {their_subject}")
    prefixes = {
        b["book_prefix"] for b in books
        if b["subject"] == their_subject and b["stage"] == stage
    }
    their_cs = [
        n for n in their_nodes
        if n["label"] in ("Concept", "Skill") and book_prefix_of(n["id"]) in prefixes
    ]
    band = STAGE_BANDS[stage]
    our_ts = [
        t for t in our_topics
        if t.get("subject") == our_subject and t.get("grade") in band
    ]
    our_subject_ts = [t for t in our_topics if t.get("subject") == our_subject]
    their_groups = _name_groups(their_cs)
    our_groups = _name_groups(our_ts)
    subject_groups = _name_groups(our_subject_ts)
    their_names = set(their_groups)
    our_names = set(our_groups)
    subject_names = set(subject_groups)
    exact = sorted(their_names & our_names)
    substring_hits = {n for n in their_names if _mutual_substring(n, subject_names)}
    substring_only = sorted(substring_hits - set(exact))
    nodes_by_id = {n["id"]: n for n in their_nodes}

    def row(name: str, tier: str) -> dict:
        theirs = their_groups[name]
        if name in our_groups:
            ours = our_groups[name]
        else:
            hits = sorted(o for o in subject_names if len(o) >= 2 and len(name) >= 2
                          and (name in o or o in name))
            ours = subject_groups[hits[0]] if hits else {"name": None, "ids": []}
        ev = first_evidence(theirs["ids"], their_edges)
        return {
            "tier": tier,
            "their_name": theirs["name"],
            "their_ids": theirs["ids"],
            "our_name": ours["name"],
            "our_ids": ours["ids"],
            "location": appears_in_locations(theirs["ids"], their_edges, nodes_by_id),
            "evidence_80": ev[:80] if ev else None,
        }

    return {
        "their_subject": their_subject,
        "our_subject": our_subject,
        "stage": stage,
        "their_nodes": len(their_cs),
        "their_names": len(their_groups),
        "our_points": len(our_ts),
        "our_points_subject_wide": len(our_subject_ts),
        "exact_count": len(exact),
        "substring_count": len(substring_hits),
        "exact_rows": [row(n, "exact") for n in exact],
        "substring_only_rows": [row(n, "substring") for n in substring_only],
    }


def classify_gaps(
    rich: dict[str, dict],
    our_topics: list[dict],
    our_pairs: set[tuple[str, str]],
    books: list[dict],
    subjects: list[str],
) -> dict:
    """定案三四类 gap。硬规矩：无 evidence 不进 ②③；④ 单列不计缺失；反向 gap 不算问题。"""
    our_subjects = Counter(t.get("subject") for t in our_topics)
    # ① 按对照线整体覆盖（四科）判，不随 --subject 收窄——demo 布局只有一本书也是 6 科无对照
    mapped = set(SUBJECT_MAP.values())
    type1 = [
        {"subject": s, "our_points": c}
        for s, c in sorted(our_subjects.items()) if s not in mapped
    ]

    book_stage = {b["book_prefix"]: b["stage"] for b in books}
    type2: list[dict] = []
    type3: list[dict] = []
    type4: list[dict] = []
    reverse: list[dict] = []
    excluded_no_evidence = 0
    prereq_both_known = 0

    for file_key in subjects:
        their_subject = FILE_SUBJECT[file_key]
        our_subject = SUBJECT_MAP[their_subject]
        graph = rich[file_key]
        nodes, edges = graph["nodes"], graph["edges"]
        our_ts = [t for t in our_topics if t.get("subject") == our_subject]
        our_groups = _name_groups(our_ts)
        our_names = set(our_groups)
        our_ids_by_name = {n: g["ids"] for n, g in our_groups.items()}

        # ② 前置边：两端名字都精确落在我们点表内才可比；方向语义 source=前置、target=后继
        for edge in edges:
            if edge["type"] != "prerequisites_for":
                continue
            ev = evidence_of(edge)
            src = normalize_name(edge.get("source_name"))
            tgt = normalize_name(edge.get("target_name"))
            if not src or not tgt or src not in our_ids_by_name or tgt not in our_ids_by_name:
                continue
            prereq_both_known += 1
            if ev is None:
                excluded_no_evidence += 1
                continue
            statuses = set()
            for a in our_ids_by_name[src]:
                for b in our_ids_by_name[tgt]:
                    if (a, b) in our_pairs:
                        statuses.add("aligned")
                    elif (b, a) in our_pairs:
                        statuses.add("reversed")
            status = (
                "aligned" if "aligned" in statuses
                else "方向相反" if "reversed" in statuses
                else "缺失"
            )
            if status == "aligned":
                continue
            type2.append({
                "kind": f"前置边{status}",
                "subject": our_subject,
                "their_source": edge["source"],
                "their_target": edge["target"],
                "source_name": edge.get("source_name"),
                "target_name": edge.get("target_name"),
                "our_source_ids": our_ids_by_name[src],
                "our_target_ids": our_ids_by_name[tgt],
                "evidence": ev,
            })

        # ② 成环：富图 prereq 子图的 SCC（环成员间四条边的 evidence 原文随 entry 携带）
        cycles = find_cycles({n["id"] for n in nodes}, prereq_pairs(edges))
        name_by_id = {n["id"]: n["name"] for n in nodes}
        for comp in cycles["cycles"]:
            members = set(comp)
            loop_edges = [
                e for e in edges
                if e["type"] == "prerequisites_for"
                and e["source"] in members and e["target"] in members
            ]
            evidences = [evidence_of(e) for e in loop_edges]
            if not evidences or any(ev is None for ev in evidences):
                excluded_no_evidence += 1
                continue  # 无 evidence 的环只留在环检测节，不进 gap 清单（定案三硬规矩）
            type2.append({
                "kind": "前置边成环",
                "subject": our_subject,
                "members": [{"id": i, "name": name_by_id.get(i)} for i in comp],
                "edges": [
                    {"source": e["source"], "target": e["target"], "evidence": evidence_of(e)}
                    for e in loop_edges
                ],
            })

        # ③ 知识点缺失：他们 Concept/Skill 名在两档都无匹配，且有关联 evidence 才进清单
        their_cs = [n for n in nodes if n["label"] in ("Concept", "Skill")]
        their_groups = _name_groups(their_cs)
        for name, group in sorted(their_groups.items()):
            if name in our_names or _mutual_substring(name, our_names):
                continue
            ev = first_evidence(group["ids"], edges)
            if ev is None:
                excluded_no_evidence += 1
                continue
            stages = sorted({
                book_stage.get(book_prefix_of(i), "未知") for i in group["ids"]
            })
            type3.append({
                "subject": our_subject,
                "their_name": group["name"],
                "their_ids": group["ids"],
                "stages": stages,
                "evidence_80": ev[:80],
            })

        # ④ 粒度差异：单列、不计入缺失总数（学科全量行 + 学段行，卡面⑱）
        type4.append({
            "subject": our_subject,
            "scope": "全学段",
            "their_concepts": sum(1 for n in nodes if n["label"] == "Concept"),
            "our_points": len(our_ts),
        })
        for stage, band in STAGE_BANDS.items():
            prefixes = {
                b["book_prefix"] for b in books
                if b["subject"] == their_subject and b["stage"] == stage
            }
            stage_names = {
                normalize_name(n["name"]) for n in their_cs
                if book_prefix_of(n["id"]) in prefixes and n.get("name")
            }
            our_band = [t for t in our_ts if t.get("grade") in band]
            if not stage_names and not our_band:
                continue
            type4.append({
                "subject": our_subject,
                "scope": stage,
                "their_names": len(stage_names),
                "our_points": len(our_band),
            })

        # 反向 gap：我们有他们没有——不算问题、不得据此删点
        their_names = set(their_groups)
        missing_ids = [
            t["id"] for t in our_ts
            if (name := normalize_name(t.get("name")))
            and name not in their_names and not _mutual_substring(name, their_names)
        ]
        reverse.append({
            "subject": our_subject,
            "our_points_not_in_theirs": len(missing_ids),
            "our_ids": missing_ids,
            "note": "反向 gap 不算问题、不得据此删点（定案三）",
        })

    return {
        "type1_subject_missing": type1,
        "type2_prereq": type2,
        "type3_point_missing": type3,
        "type4_granularity": type4,
        "reverse_gap": reverse,
        "excluded_no_evidence": excluded_no_evidence,
        "prereq_both_known": prereq_both_known,
        "disposition": "B 提上游 issue 首选 → C 本地补（严格限定）→ A 只留报告（定案三）",
    }


def detect_layout(rel_files: set[str]) -> str:
    """纯函数布局判定：HF 全量六件齐 → hf；demo 四件齐 → demo；否则报错点名缺件。"""
    if set(HF_ANCHORS) <= rel_files:
        return "hf"
    if rel_files >= DEMO_REQUIRED:
        return "demo"
    raise AuditError(
        "无法识别 K12-KGraph 布局（不猜、不出半份报告）。"
        f"HF 布局缺: {sorted(set(HF_ANCHORS) - rel_files)}；"
        f"demo 布局缺: {sorted(DEMO_REQUIRED - rel_files)}"
    )


def path_inside_repo(path: Path, repo_root: Path) -> bool:
    """路径是否落在仓库内（含等于仓库根）。纯判定，供 CLI 拒绝与单测覆盖。"""
    resolved = path.resolve()
    root = repo_root.resolve()
    return resolved == root or root in resolved.parents


# ---------------------------------------------------------------------------
# 只读输入层：读文件、算 sha、探测布局；不做任何计算决策。
# ---------------------------------------------------------------------------


def read_json(path: Path) -> Any:
    if not path.is_file():
        raise AuditError(f"找不到 {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AuditError(f"{path} 不是合法 JSON: {exc}") from exc


def sha256_prefix(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def verify_anchors(kg_dir: Path, anchors: dict[str, str]) -> dict:
    report = {}
    for rel, expected in anchors.items():
        actual = sha256_prefix(kg_dir / rel)
        report[rel] = {"expected": expected, "actual": actual, "ok": actual == expected}
        if actual != expected:
            raise AuditError(
                f"{kg_dir / rel} 字节与卡面 sha 锚点不符（期望 {expected}… 实际 {actual}…）"
                "——副本被换过或下载不完整，拒绝出报告"
            )
    return report


def collect_rel_files(kg_dir: Path) -> set[str]:
    if not kg_dir.is_dir():
        raise AuditError(f"--kg-dir 不存在或不是目录: {kg_dir}")
    out: set[str] = set()
    for root, dirs, files in os.walk(kg_dir):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in files:
            out.add((Path(root) / name).relative_to(kg_dir).as_posix())
    return out


def resolve_books_yaml(kg_dir: Path, layout: str, explicit: Path | None) -> Path:
    """books.yaml 解析顺序：显式 --books-yaml → kg-dir 内 → HF 布局的同级 GitHub 副本。

    盘上实况：HF 六件不含 books.yaml，审核方取证脚本一律用同级 K12-KGraph/books.yaml。
    """
    candidates = []
    if explicit is not None:
        candidates.append(explicit)
    candidates.append(kg_dir / "books.yaml")
    if layout == "hf":
        candidates.append(kg_dir.parent / GITHUB_SIBLING_DIR / "books.yaml")
    for path in candidates:
        if path.is_file():
            return path
    raise AuditError(
        "找不到 books.yaml（学科/学段映射的唯一来源，不猜）。"
        f"已试: {[str(p) for p in candidates]}；可用 --books-yaml 显式指定"
    )


def load_our_side() -> tuple[list[dict], list[dict]]:
    data_dir = PROJECT_ROOT / "seeds" / "data"
    topics = read_json(data_dir / "topics.json")
    deps = read_json(data_dir / "dependencies.json")
    if not isinstance(topics, list) or not isinstance(deps, list):
        raise AuditError("seeds/data/topics.json / dependencies.json 必须是数组")
    return topics, deps


# ---------------------------------------------------------------------------
# 报告组装（纯计算）与输出层
# ---------------------------------------------------------------------------


def structure_of_graph(graph: dict) -> dict:
    return {
        "nodes": len(graph["nodes"]),
        "labels": label_counts(graph["nodes"]),
        "edge_types": edge_type_counts(graph["edges"]),
        **evidence_stats(graph["edges"]),
    }


def cycles_section(our_topics: list[dict], our_deps: list[dict], rich: dict[str, dict],
                   thin: dict | None) -> dict:
    our_ids = {t["id"] for t in our_topics}
    our_pairs = [(d["prerequisite_id"], d["topic_id"]) for d in our_deps]
    section: dict[str, Any] = {
        "ours": find_cycles(our_ids, our_pairs),
        "their_rich": {},
    }
    for key, graph in rich.items():
        section["their_rich"][key] = find_cycles(
            {n["id"] for n in graph["nodes"]}, prereq_pairs(graph["edges"])
        )
    if thin is not None:
        section["their_thin"] = find_cycles(
            {n["id"] for n in thin["nodes"]}, prereq_pairs(thin["edges"])
        )
        rich_cycle_members = {
            tuple(comp) for g in section["their_rich"].values() for comp in g["cycles"]
        }
        thin_cycle_members = {tuple(comp) for comp in section["their_thin"]["cycles"]}
        section["thin_vs_rich"] = {
            "consistent": rich_cycle_members == thin_cycle_members,
            "rich_only": [list(c) for c in sorted(rich_cycle_members - thin_cycle_members)],
            "thin_only": [list(c) for c in sorted(thin_cycle_members - rich_cycle_members)],
            "note": "两层不一致时以富图为准并如实报差异（卡面定案④）",
        }
    return section


def build_hf_report(kg_dir: Path, books_path: Path, subjects: list[str]) -> dict:
    anchors = verify_anchors(kg_dir, HF_ANCHORS)
    thin = parse_thin_graph(
        read_json(kg_dir / "global_KG" / "nodes.json"),
        read_json(kg_dir / "global_KG" / "edges.json"),
    )
    rich = {
        key: parse_rich_graph(read_json(kg_dir / "subject_specific_KG" / f"{key}.json"), key)
        for key in FILE_SUBJECT
    }
    books = parse_books_yaml(books_path.read_text(encoding="utf-8"))
    our_topics, our_deps = load_our_side()

    candidates = {
        key: {
            stage: build_candidate_table(
                rich[key]["nodes"], rich[key]["edges"], our_topics, books,
                FILE_SUBJECT[key], stage,
            )
            for stage in STAGE_BANDS
        }
        for key in subjects
    }
    gaps = classify_gaps(
        rich, our_topics, {(d["prerequisite_id"], d["topic_id"]) for d in our_deps},
        books, subjects,
    )
    math_types = set(edge_type_counts(rich["math"]["edges"]))
    all_types = set().union(*(set(edge_type_counts(g["edges"])) for g in rich.values()))
    return {
        "schema": "kg_audit_v1",
        "layout": "hf",
        "kg_dir": str(kg_dir),
        "books_yaml": str(books_path),
        "subjects_audited": subjects,
        "license_note": LICENSE_NOTE,
        "anchors": anchors,
        "structure": {
            "books": {
                "total": len(books),
                "by_subject": dict(Counter(b["subject"] for b in books).most_common()),
                "by_stage": dict(Counter(b["stage"] for b in books).most_common()),
            },
            "thin": structure_of_graph(thin),
            "rich": {key: structure_of_graph(g) for key, g in rich.items()},
            "rich_edge_type_union": sorted(all_types),
            "math_missing_verifies": "verifies" not in math_types,
            "ours": {
                "topics": len(our_topics),
                "by_subject": dict(Counter(t.get("subject") for t in our_topics).most_common()),
                "deps": len(our_deps),
            },
        },
        "cycles": cycles_section(our_topics, our_deps, rich, thin),
        "candidates": candidates,
        "gaps": gaps,
    }


def build_demo_report(kg_dir: Path, books_path: Path) -> dict:
    anchors = verify_anchors(kg_dir, DEMO_ANCHORS)
    manifest = read_json(kg_dir / "demo" / "manifest.json")
    book_file = "demo/kg/math_7a_rjb.json"
    graph = parse_rich_graph(read_json(kg_dir / book_file), book_file)
    books = parse_books_yaml(books_path.read_text(encoding="utf-8"))
    our_topics, our_deps = load_our_side()
    book = next((b for b in books if b["book_prefix"] == "math_7a_rjb"), None)
    if book is None:
        raise AuditError("books.yaml 缺 math_7a_rjb 书目（demo 布局学科/学段定位的唯一来源）")

    candidate = build_candidate_table(
        graph["nodes"], graph["edges"], our_topics, books, book["subject"], book["stage"]
    )
    gaps = classify_gaps(
        {"math": graph}, our_topics,
        {(d["prerequisite_id"], d["topic_id"]) for d in our_deps}, books, ["math"],
    )
    gaps["type4_granularity"] = []  # demo 只有一本书，粒度对照以 HF 布局报告为准
    return {
        "schema": "kg_audit_v1",
        "layout": "demo",
        "kg_dir": str(kg_dir),
        "books_yaml": str(books_path),
        "subjects_audited": ["math"],
        "license_note": LICENSE_NOTE,
        "anchors": anchors,
        "structure": {
            "manifest_schema_version": manifest.get("schema_version"),
            "book": {"file": book_file, **book, **structure_of_graph(graph)},
            "ours": {
                "topics": len(our_topics),
                "by_subject": dict(Counter(t.get("subject") for t in our_topics).most_common()),
                "deps": len(our_deps),
            },
            "note": "GitHub 只发 demo 一本书；瘦图/四科富图规模对照见 HF 布局报告",
        },
        "cycles": cycles_section(our_topics, our_deps, {"math": graph}, None),
        "candidates": {"math": {book["stage"]: candidate}},
        "gaps": gaps,
    }


def _fmt_location(location: list[dict]) -> str:
    return "；".join(
        f"{loc.get('label') or '?'}《{loc.get('name') or '?'}》" for loc in location
    ) or "—"


def render_markdown(report: dict) -> str:
    lines: list[str] = []
    w = lines.append
    w(f"# K12-KGraph 只读对照审计（{report['layout']} 布局）")
    w("")
    w(f"- 数据目录：`{report['kg_dir']}`；书目：`{report['books_yaml']}`")
    w(f"- {report['license_note']}")
    w("- 本报告只出候选表 + 结构体检，**不出名字对齐覆盖率结论**；④ 粒度差异单列、不计缺失。")
    w("")
    w("## sha 锚点")
    for rel, row in report["anchors"].items():
        w(f"- `{rel}`：{row['actual']}…（锚点 {row['expected']}…，{'一致' if row['ok'] else '不符'}）")
    w("")
    structure = report["structure"]
    w("## 结构体检")
    if report["layout"] == "hf":
        thin = structure["thin"]
        w(f"- 瘦图：{thin['nodes']} 节点 / {thin['edges']} 边，带 evidence {thin['edges_with_evidence']} 条")
        w(f"  - label 分布：{thin['labels']}")
        w(f"  - 边类型：{thin['edge_types']}")
        for key, stats in structure["rich"].items():
            w(
                f"- 富图 {key}：{stats['nodes']} 节点 / {stats['edges']} 边，"
                f"evidence {stats['edges_with_evidence']}（{stats['evidence_rate']:.1%}），"
                f"prereq {stats['prereq_with_evidence']}/{stats['prereq_edges']}"
                f"（{stats['prereq_evidence_rate']:.1%}）"
            )
        w(f"- 富图边类型并集：{structure['rich_edge_type_union']}")
        w(f"- 数学富图缺 verifies：{structure['math_missing_verifies']}（卡面⑪，边类型按实测集合遍历）")
        w(f"- books.yaml：{structure['books']['total']} 本，学科 {structure['books']['by_subject']}，"
          f"学段 {structure['books']['by_stage']}")
    else:
        book = structure["book"]
        w(f"- demo 书级文件 `{book['file']}`（{book['subject']} / {book['stage']} / {book.get('grade')}）：")
        w(f"  {book['nodes']} 节点 / {book['edges']} 边，带 evidence {book['edges_with_evidence']} 条")
        w(f"  - label 分布：{book['labels']}")
        w(f"  - 边类型：{book['edge_types']}")
        w(f"- manifest schema_version：{structure['manifest_schema_version']}")
    ours = structure["ours"]
    w(f"- 我们侧：{ours['topics']} 点 / {ours['deps']} 先修边；学科分布 {ours['by_subject']}")
    w("")
    w("## 环检测（Kahn 判有无 + Tarjan 取分量；方向 = 前置 → 后继）")
    cycles = report["cycles"]
    ours_c = cycles["ours"]
    w(f"- **我们侧 dependencies.json：cycles={ours_c['cycle_count']}**"
      f"（自环 {len(ours_c['self_loops'])}，端点缺失 {ours_c['dangling_edges']}，"
      f"Kahn 排不掉 {ours_c['kahn_unsorted']}）")
    for key, stats in cycles["their_rich"].items():
        w(f"- 他们富图 {key}：cycles={stats['cycle_count']}（自环 {len(stats['self_loops'])}，"
          f"Kahn 排不掉 {stats['kahn_unsorted']}）")
        for comp in stats["cycles"]:
            w(f"  - 环成员：{comp}")
    if "their_thin" in cycles:
        stats = cycles["their_thin"]
        w(f"- 他们瘦图全局：cycles={stats['cycle_count']}（自环 {len(stats['self_loops'])}）")
        for comp in stats["cycles"]:
            w(f"  - 环成员：{comp}")
        cross = cycles["thin_vs_rich"]
        w(f"- 瘦图 vs 富图交叉验证：{'一致' if cross['consistent'] else '不一致（以富图为准）'}"
          f"{'；富图独有 ' + str(cross['rich_only']) if cross['rich_only'] else ''}"
          f"{'；瘦图独有 ' + str(cross['thin_only']) if cross['thin_only'] else ''}")
    w("")
    w("## 候选表（精确同名 = 同学段档；子串互含 = 同学科全学段；只报计数，不出覆盖率）")
    for key, stages in report["candidates"].items():
        for stage, table in stages.items():
            w(f"### {key} · {stage}（他们 {table['their_subject']} → 我们 {table['our_subject']}）")
            w(f"- 他们 Concept/Skill {table['their_nodes']} 节点 / 去重 {table['their_names']} 名；"
              f"我们本学段 {table['our_points']} 点（全学段 {table['our_points_subject_wide']}）；"
              f"**精确同名 {table['exact_count']}、子串互含 {table['substring_count']}**")
            for row in table["exact_rows"] + table["substring_only_rows"]:
                w(f"  - [{row['tier']}] 他们《{row['their_name']}》({','.join(row['their_ids'])})"
                  f" ↔ 我们《{row['our_name']}》({','.join(row['our_ids']) or '—'})"
                  f"｜{_fmt_location(row['location'])}"
                  f"｜evidence: {row['evidence_80'] or '—'}")
            w("")
    w("## gap 分类（定案三：B 提上游 issue → C 本地补 → A 只留报告）")
    gaps = report["gaps"]
    w(f"- ① 整学科缺失（{len(gaps['type1_subject_missing'])} 科）："
      + "、".join(f"{r['subject']}（我们 {r['our_points']} 点）" for r in gaps["type1_subject_missing"]))
    w(f"- ② 前置边缺失/方向相反/成环（{len(gaps['type2_prereq'])} 条，全部带 evidence）：")
    for entry in gaps["type2_prereq"]:
        if entry["kind"] == "前置边成环":
            names = " ↔ ".join(f"{m['name']}({m['id']})" for m in entry["members"])
            w(f"  - 【成环·{entry['subject']}】{names}")
            for edge in entry["edges"]:
                w(f"    - {edge['source']} → {edge['target']}｜evidence 原文：{edge['evidence']}")
        else:
            w(f"  - 【{entry['kind']}·{entry['subject']}】{entry['source_name']} → {entry['target_name']}"
              f"｜evidence: {entry['evidence'][:80]}")
    w(f"- ③ 知识点缺失（{len(gaps['type3_point_missing'])} 条，全部带 evidence；"
      f"无 evidence 被排除 {gaps['excluded_no_evidence']} 条）：")
    for entry in gaps["type3_point_missing"]:
        w(f"  - 【{entry['subject']}·{'/'.join(entry['stages'])}】《{entry['their_name']}》"
          f"({','.join(entry['their_ids'])})｜evidence: {entry['evidence_80']}")
    w(f"- ④ 粒度差异（单列、**不计入缺失总数**；{len(gaps['type4_granularity'])} 行）：")
    for entry in gaps["type4_granularity"]:
        if "their_concepts" in entry:
            w(f"  - {entry['subject']}·{entry['scope']}：他们 Concept {entry['their_concepts']}"
              f" vs 我们 {entry['our_points']} 点")
        else:
            w(f"  - {entry['subject']}·{entry['scope']}：他们 Concept+Skill 去重 {entry['their_names']}"
              f" 名 vs 我们 {entry['our_points']} 点")
    w(f"- 前置边两端名字都在我们点表内的共 {gaps['prereq_both_known']} 条（② 的可比基数）")
    w("- 反向 gap（我们有他们没有）——**不算问题、不得据此删点**：")
    for entry in gaps["reverse_gap"]:
        w(f"  - {entry['subject']}：{entry['our_points_not_in_theirs']} 点")
    w("")
    w(f"处置优先级：{gaps['disposition']}")
    return "\n".join(lines) + "\n"


def print_human_summary(report: dict) -> None:
    print(f"K12-KGraph 只读对照审计 · {report['layout']} 布局 · {report['kg_dir']}")
    cycles = report["cycles"]
    print(f"我们侧 cycles={cycles['ours']['cycle_count']}（{cycles['ours']['edges']} 先修边）")
    for key, stats in cycles["their_rich"].items():
        print(f"他们富图 {key}: cycles={stats['cycle_count']}")
    if "their_thin" in cycles:
        print(f"他们瘦图全局: cycles={cycles['their_thin']['cycle_count']}")
    for key, stages in report["candidates"].items():
        for stage, table in stages.items():
            print(f"候选 {key}/{stage}: 他们 {table['their_names']} 名 vs 我们 {table['our_points']} 点"
                  f" → 精确 {table['exact_count']} / 子串 {table['substring_count']}")
    gaps = report["gaps"]
    print(f"gap: ①{len(gaps['type1_subject_missing'])} 科 "
          f"②{len(gaps['type2_prereq'])} 条 ③{len(gaps['type3_point_missing'])} 条 "
          f"④{len(gaps['type4_granularity'])} 行（单列）；无 evidence 排除 {gaps['excluded_no_evidence']}")
    print("提醒：只出候选表 + 结构体检，不出覆盖率结论；报告与他们的文本绝不进仓库/备份。")


# ---------------------------------------------------------------------------
# CLI 与输出层（唯一写盘点 = 仓库外 out-dir 的两件套报告）
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="K12-KGraph 只读对照审计（零依赖、零联网、对仓库零写入；报告落仓外）"
    )
    parser.add_argument("--kg-dir", type=Path, default=DEFAULT_KG_DIR,
                        help="K12-KGraph 数据目录（HF 全量或 GitHub demo 布局，文件探测）")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR,
                        help="报告输出目录（必须在仓库外）")
    parser.add_argument("--books-yaml", type=Path, default=None,
                        help="显式指定 books.yaml（默认 kg-dir 内 → HF 布局的同级 GitHub 副本）")
    parser.add_argument("--json", action="store_true", help="stdout 改出机器可读 JSON")
    parser.add_argument("--subject", action="append", choices=sorted(FILE_SUBJECT),
                        help="候选表/gap 只跑指定科（可多次传入；默认四科全跑）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        for label, path in (("--kg-dir", args.kg_dir), ("--out-dir", args.out_dir)):
            if path_inside_repo(path, PROJECT_ROOT):
                raise AuditError(f"{label} 落在仓库内（{path}）——拒绝运行，报告与数据都不进仓库")
        layout = detect_layout(collect_rel_files(args.kg_dir))
        books_path = resolve_books_yaml(args.kg_dir, layout, args.books_yaml)
        if path_inside_repo(books_path, PROJECT_ROOT):
            raise AuditError(f"books.yaml 落在仓库内（{books_path}）——拒绝运行")
        subjects = args.subject or sorted(FILE_SUBJECT)
        if layout == "hf":
            report = build_hf_report(args.kg_dir, books_path, subjects)
        else:
            report = build_demo_report(args.kg_dir, books_path)
    except AuditError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / f"kg_audit_{layout}.json"
    md_path = args.out_dir / f"kg_audit_{layout}.md"
    with json_path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    with md_path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_markdown(report))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        print_human_summary(report)
        print(f"报告已写：{json_path}")
        print(f"报告已写：{md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
