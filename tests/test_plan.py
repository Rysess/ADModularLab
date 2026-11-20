from labctl.runner import PlanSummary


def rc(type_, index, *actions):
    return {"type": type_, "index": index, "address": f"{type_}.x", "change": {"actions": list(actions)}}


def test_plan_summary_classifies_hosts():
    s = PlanSummary({"resource_changes": [
        rc("aws_instance", "a", "create"), rc("aws_instance", "b", "delete", "create"),
        rc("aws_instance", "c", "delete"), rc("aws_instance", "d", "update"),
        rc("aws_instance", "e", "no-op"), rc("local_file", "f", "create"),
    ]})
    assert s.hosts == {"create": ["a"], "update": ["d"], "replace": ["b"], "delete": ["c"]}
    assert s.destructive and not s.empty and s.other["create"] == 1
    assert PlanSummary({"resource_changes": []}).empty
