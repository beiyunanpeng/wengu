"""P5-18 audit_kg 纯函数层单测：三形态解析 / label 归类 / evidence 抽取 /
两档候选 / 布局探测 / 仓库内路径拒绝 / 学科逐字映射 / Kahn+Tarjan。

全部吃合成数据，不读真实 K12 副本、不联网、不写盘（tmp_path 除外）。
字面串纪律（§19-L）：断言里的期望值手写字面，不引用被测常量。
"""

from __future__ import annotations

import pytest
from scripts.audit_kg import (
    AuditError,
    appears_in_locations,
    book_prefix_of,
    build_candidate_table,
    classify_gaps,
    detect_layout,
    edge_type_counts,
    evidence_of,
    find_cycles,
    label_counts,
    map_subject,
    normalize_name,
    parse_books_yaml,
    parse_rich_graph,
    parse_thin_graph,
    path_inside_repo,
)

BOOKS = [
    {"book_prefix": "math_7a_rjb", "subject": "数学", "stage": "初中", "grade": "七年级上册"},
    {"book_prefix": "math_8a_rjb", "subject": "数学", "stage": "初中", "grade": "八年级上册"},
]


def _their_nodes() -> list[dict]:
    return [
        {"id": "math_7a_rjb_cpt1", "label": "Concept", "name": "正数",
         "properties": {"definition": "他们的定义文本（绝不进仓库）", "importance": "掌握"}},
        {"id": "math_7a_rjb_cpt2", "label": "Concept", "name": "负数"},
        {"id": "math_7a_rjb_skl1", "label": "Skill", "name": "有理数加法"},
        {"id": "math_7a_rjb_cpt3", "label": "Concept", "name": "数轴"},
        {"id": "math_7a_rjb_cpt4", "label": "Concept", "name": "无证据点"},
        {"id": "math_7a_rjb_sec1", "label": "Section", "name": "第一章 有理数"},
        {"id": "math_7a_rjb_exe1", "label": "Exercise", "name": "练习1"},
    ]


def _their_edges() -> list[dict]:
    return [
        {"type": "prerequisites_for", "source": "math_7a_rjb_cpt1", "target": "math_7a_rjb_cpt2",
         "source_name": "正数", "target_name": "负数",
         "properties": {"evidence": "教材第 3 页：正数与负数……"}},
        {"type": "prerequisites_for", "source": "math_7a_rjb_cpt2", "target": "math_7a_rjb_cpt1",
         "source_name": "负数", "target_name": "正数",
         "properties": {"evidence": "教材第 4 页：负数与正数……"}},
        {"type": "is_a", "source": "math_7a_rjb_cpt3", "target": "math_7a_rjb_cpt1",
         "source_name": "数轴", "target_name": "正数",
         "properties": {"evidence": {"text": "数轴图示段……", "page": "图示页"}}},
        {"type": "appears_in", "source": "math_7a_rjb_cpt1", "target": "math_7a_rjb_sec1",
         "source_name": "正数", "target_name": "第一章 有理数"},
        {"type": "tests_concept", "source": "math_7a_rjb_exe1", "source_stem": "题干文本",
         "target_name_to_ids": [
             {"target": "math_7a_rjb_cpt1", "target_name": "正数"},
             {"target": "math_7a_rjb_cpt2", "target_name": "负数"},
         ]},
    ]


def _our_topics() -> list[dict]:
    return [
        {"id": "cnm_j001", "subject": "数学", "name": "正数", "grade": 7},
        {"id": "cnm_j002", "subject": "数学", "name": "负数", "grade": 7},
        {"id": "cnm_j003", "subject": "数学", "name": "有理数", "grade": 8},
        {"id": "cne_j001", "subject": "英语", "name": "hello", "grade": 7},
    ]


# ---------------------------------------------------------------------------
# 三种形态解析
# ---------------------------------------------------------------------------


def test_parse_thin_flat_arrays() -> None:
    graph = parse_thin_graph(
        [{"id": "math_7a_rjb_cpt1", "label": "Concept", "name": "正数"}],
        [
            {"source": "math_7a_rjb_cpt1", "target": "math_7a_rjb_cpt2", "type": "is_a"},
            # 瘦图 tests_* 也是扁平 source/target（盘上实测形态）
            {"source": "math_7a_rjb_exe1", "target": "math_7a_rjb_cpt1", "type": "tests_concept"},
        ],
    )
    assert graph["nodes"][0]["name"] == "正数"
    assert graph["edges"][1]["target"] == "math_7a_rjb_cpt1"
    assert graph["edges"][1]["extra_targets"] == []
    assert evidence_of(graph["edges"][0]) is None


def test_parse_rich_subject_form() -> None:
    graph = parse_rich_graph({"nodes": _their_nodes(), "edges": _their_edges()}, "math")
    assert len(graph["nodes"]) == 7
    prereq = graph["edges"][0]
    assert prereq["source_name"] == "正数"
    assert prereq["properties"]["evidence"].startswith("教材第 3 页")


def test_parse_demo_tests_edge_form() -> None:
    graph = parse_rich_graph({"nodes": _their_nodes(), "edges": _their_edges()}, "demo")
    tests = next(e for e in graph["edges"] if e["type"] == "tests_concept")
    assert tests["target"] is None
    assert tests["extra_targets"] == [
        {"target": "math_7a_rjb_cpt1", "target_name": "正数"},
        {"target": "math_7a_rjb_cpt2", "target_name": "负数"},
    ]


def test_parse_rejects_bad_shapes() -> None:
    with pytest.raises(AuditError):
        parse_thin_graph([{"id": "x", "label": "Concept"}], [])  # 缺 name
    with pytest.raises(AuditError):
        parse_thin_graph([], [{"source": "a", "type": "is_a"}])  # 缺 target
    with pytest.raises(AuditError):
        parse_rich_graph([], "math")  # 顶层不是对象
    with pytest.raises(AuditError):
        parse_rich_graph({"nodes": [], "edges": [{"type": "is_a", "source": "a", "target": "b",
                                                 "properties": "不是对象"}]}, "math")
    with pytest.raises(AuditError):
        parse_rich_graph({"nodes": [], "edges": [
            {"type": "tests_concept", "source": "e", "target_name_to_ids": [{"target_name": "缺target"}]},
        ]}, "demo")


def test_label_and_edge_type_counts_iterate_measured_set() -> None:
    graph = parse_rich_graph({"nodes": _their_nodes(), "edges": _their_edges()}, "math")
    assert label_counts(graph["nodes"]) == {
        "Concept": 4, "Skill": 1, "Section": 1, "Exercise": 1,
    }
    # 数学富图无 verifies：按实测集合计数不得 KeyError（卡面⑪）
    counts = edge_type_counts(graph["edges"])
    assert "verifies" not in counts
    assert counts["prerequisites_for"] == 2
    assert counts["tests_concept"] == 1


# ---------------------------------------------------------------------------
# evidence 抽取（含 dict 形态与"瘦图无 evidence 不进②③"）
# ---------------------------------------------------------------------------


def test_evidence_str_and_dict_forms() -> None:
    assert evidence_of({"properties": {"evidence": "原文"}}) == "原文"
    assert evidence_of({"properties": {"evidence": {"text": "图示段", "page": "图示页"}}}) == "图示段"
    assert evidence_of({"properties": {"evidence": "   "}}) is None
    assert evidence_of({"properties": {"evidence": {"page": "只有页码"}}}) is None
    assert evidence_of({"properties": {}}) is None
    assert evidence_of({}) is None


def test_thin_no_evidence_never_enters_gap_lists() -> None:
    """定案三硬规矩：无 evidence 的 gap 不得进②③——瘦图 0 evidence 正是因此只作规模对照。"""
    nodes = _their_nodes()
    edges = [{k: v for k, v in e.items() if k != "properties"} for e in _their_edges()]
    graph = parse_thin_graph(nodes, edges)
    gaps = classify_gaps(
        {"math": graph}, _our_topics(), {("cnm_j001", "cnm_j002")}, BOOKS, ["math"],
    )
    assert gaps["type2_prereq"] == []
    assert gaps["type3_point_missing"] == []
    assert gaps["excluded_no_evidence"] > 0
    assert gaps["prereq_both_known"] == 2  # 可比基数仍如实计数


def test_gap_classification_with_evidence() -> None:
    graph = parse_rich_graph({"nodes": _their_nodes(), "edges": _their_edges()}, "math")
    gaps = classify_gaps(
        {"math": graph}, _our_topics(), {("cnm_j001", "cnm_j002")}, BOOKS, ["math"],
    )
    # ① 整学科缺失：英语在我们点表、不在四科映射 → 点名（demo 单书布局同样按对照线整体判）
    assert [r["subject"] for r in gaps["type1_subject_missing"]] == ["英语"]
    # ② cpt1→cpt2 与我们边同向 = aligned 不列；cpt2→cpt1 反向 = 方向相反；
    #    cpt1↔cpt2 互环 = 成环 entry 带两条 evidence 原文
    kinds = [e["kind"] for e in gaps["type2_prereq"]]
    assert "前置边方向相反" in kinds
    loop = next(e for e in gaps["type2_prereq"] if e["kind"] == "前置边成环")
    assert {m["id"] for m in loop["members"]} == {"math_7a_rjb_cpt1", "math_7a_rjb_cpt2"}
    assert len(loop["edges"]) == 2
    assert all(e["evidence"] for e in loop["edges"])
    # ③ 数轴有 dict evidence → 进清单；无证据点无 evidence → 排除
    names = [r["their_name"] for r in gaps["type3_point_missing"]]
    assert "数轴" in names
    assert "无证据点" not in names
    assert gaps["excluded_no_evidence"] >= 1
    # ④ 粒度差异单列：学科全量行 + 学段行（数学初中 3 名 vs 我们 2 点）
    assert {"subject": "数学", "scope": "全学段", "their_concepts": 4, "our_points": 3} in gaps["type4_granularity"]
    assert {"subject": "数学", "scope": "初中", "their_names": 5, "our_points": 3} in gaps["type4_granularity"]
    # 反向 gap 标注不算问题
    assert all("不得据此删点" in r["note"] for r in gaps["reverse_gap"])


# ---------------------------------------------------------------------------
# 两档候选匹配
# ---------------------------------------------------------------------------


def test_candidate_table_two_tiers_and_scope() -> None:
    graph = parse_rich_graph({"nodes": _their_nodes(), "edges": _their_edges()}, "math")
    table = build_candidate_table(
        graph["nodes"], graph["edges"], _our_topics(), BOOKS, "数学", "初中",
    )
    assert table["their_names"] == 5  # Concept+Skill 去重名（Section/Exercise 不算）
    assert table["our_points"] == 3  # grade7-9 档：正数/负数/有理数（grade8 也在初中档）
    assert table["exact_count"] == 2
    # 子串档 = 同学科全学段："有理数加法" 互含 grade8 的 "有理数" → 命中
    assert table["substring_count"] == 3
    row = next(r for r in table["exact_rows"] if r["their_name"] == "正数")
    assert row["our_ids"] == ["cnm_j001"]
    assert row["location"] == [
        {"target": "math_7a_rjb_sec1", "name": "第一章 有理数", "label": "Section"},
    ]
    assert row["evidence_80"].startswith("教材第 3 页")
    sub = next(r for r in table["substring_only_rows"] if r["their_name"] == "有理数加法")
    assert sub["our_name"] == "有理数"


def test_candidate_table_rejects_unmapped_subject() -> None:
    with pytest.raises(AuditError):
        build_candidate_table([], [], [], BOOKS, "生物学导论", "初中")


def test_appears_in_locations_dedup() -> None:
    graph = parse_rich_graph({"nodes": _their_nodes(), "edges": _their_edges()}, "math")
    nodes_by_id = {n["id"]: n for n in graph["nodes"]}
    loc = appears_in_locations(["math_7a_rjb_cpt1"], graph["edges"], nodes_by_id)
    assert loc == [{"target": "math_7a_rjb_sec1", "name": "第一章 有理数", "label": "Section"}]


# ---------------------------------------------------------------------------
# 布局探测 / 仓库内路径拒绝 / 学科映射 / books.yaml / 归一化
# ---------------------------------------------------------------------------


def test_detect_layout_hf_and_demo() -> None:
    hf_files = {
        "global_KG/nodes.json", "global_KG/edges.json",
        "subject_specific_KG/math.json", "subject_specific_KG/physics.json",
        "subject_specific_KG/chemistry.json", "subject_specific_KG/biology.json",
    }
    assert detect_layout(hf_files) == "hf"
    assert detect_layout({"demo/kg/math_7a_rjb.json", "demo/manifest.json",
                          "books.yaml", "LICENSE"}) == "demo"


def test_detect_layout_failure_is_readable_error() -> None:
    with pytest.raises(AuditError, match="无法识别"):
        detect_layout(set())
    with pytest.raises(AuditError, match="global_KG/nodes.json"):
        detect_layout({"global_KG/edges.json"})  # 缺件点名，不出半份报告


def test_path_inside_repo(tmp_path) -> None:
    repo = tmp_path / "wengu"
    repo.mkdir()
    assert path_inside_repo(repo, repo) is True
    assert path_inside_repo(repo / "seeds" / "data", repo) is True
    assert path_inside_repo(tmp_path / "kg-audit", repo) is False
    # 兄弟目录前缀陷阱：wengu-evil 不是 wengu 内
    assert path_inside_repo(tmp_path / "wengu-evil", repo) is False


def test_subject_map_literal_equality_only() -> None:
    # 必须逐字：他们"生物学" → 我们"生物"；包含式匹配一律拒绝（卡面⑮陷阱本体）
    assert "生物学" != "生物"
    assert map_subject("生物学") == "生物"
    assert map_subject("数学") == "数学"
    assert map_subject("物理") == "物理"
    assert map_subject("化学") == "化学"
    assert map_subject("生物") is None  # 我们写法不是他们写法，不反向猜
    assert map_subject("生物学导论") is None  # 包含式拒绝
    assert map_subject("数学 ") is None  # 不 trim、不模糊
    assert map_subject("英语") is None  # 无对照学科


def test_parse_books_yaml() -> None:
    text = (
        "books:\n"
        "- book_prefix: math_7a_rjb\n"
        '  source_pdf: ""\n'
        '  source_md: ""\n'
        "  subject: 数学\n"
        "  stage: 初中\n"
        "  grade: 七年级上册\n"
        "  publisher: 人教版\n"
        "- book_prefix: biology_7a_rjb\n"
        "  subject: 生物学\n"
        "  stage: 初中\n"
        "  grade: 七年级上册\n"
    )
    books = parse_books_yaml(text)
    assert books[0]["book_prefix"] == "math_7a_rjb"
    assert books[0]["grade"] == "七年级上册"  # 中文册名透传，绝不映射 int
    assert books[1]["subject"] == "生物学"
    with pytest.raises(AuditError, match="未知 stage"):
        parse_books_yaml("- book_prefix: x\n  subject: 数学\n  stage: 大学\n")
    with pytest.raises(AuditError):
        parse_books_yaml("books: []\n")


def test_normalize_name_nfkc() -> None:
    assert normalize_name("ＡＢＣ１２３") == "abc123"
    assert normalize_name(" 有理数（一） ") == "有理数一"
    assert normalize_name(None) == ""


def test_book_prefix_of() -> None:
    assert book_prefix_of("math_7a_rjb_cpt1") == "math_7a_rjb"
    assert book_prefix_of("chemistry_xzxbx2_rjb_cpt108") == "chemistry_xzxbx2_rjb"


# ---------------------------------------------------------------------------
# Kahn + Tarjan 环检测
# ---------------------------------------------------------------------------


def test_find_cycles_dag_is_zero() -> None:
    result = find_cycles({"a", "b", "c"}, [("a", "b"), ("b", "c")])
    assert result["cycle_count"] == 0
    assert result["kahn_unsorted"] == 0
    assert result["self_loops"] == []
    assert result["dangling_edges"] == 0


def test_find_cycles_three_node_cycle() -> None:
    result = find_cycles({"a", "b", "c"}, [("a", "b"), ("b", "c"), ("c", "a")])
    assert result["cycles"] == [["a", "b", "c"]]
    assert result["kahn_unsorted"] == 3


def test_find_cycles_two_node_mutual() -> None:
    result = find_cycles(
        {"x", "y"}, [("x", "y"), ("y", "x")],
    )
    assert result["cycles"] == [["x", "y"]]
    assert result["kahn_unsorted"] == 2


def test_find_cycles_self_loop_and_dangling() -> None:
    result = find_cycles({"a", "b"}, [("a", "a"), ("a", "z")])
    assert result["self_loops"] == [["a"]]
    assert result["cycles"] == []
    assert result["dangling_edges"] == 1


def test_find_cycles_iterative_survives_deep_chain() -> None:
    # 3000 节点长链 + 末端回边：递归 Tarjan 会爆栈，迭代必须活
    ids = {f"n{i}" for i in range(3000)}
    pairs = [(f"n{i}", f"n{i + 1}") for i in range(2999)] + [("n2999", "n0")]
    result = find_cycles(ids, pairs)
    assert result["cycle_count"] == 1
    assert len(result["cycles"][0]) == 3000
    assert result["kahn_unsorted"] == 3000
