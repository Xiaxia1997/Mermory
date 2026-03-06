from modules.basic.data_class import Observation
from modules.router.observation_router import ObservationRouter


def _base_obs(**kwargs):
    data = dict(
        session_id="s1",
        message_id="msg-step-3",
        step_index=3,
        step_title="检查功率螺钉",
        step_text="确认功率矩阵端子紧固并拍照记录",
        user_text="",
        has_image=False,
        image=None,
        image_path=None,
        event_type="text",
    )
    data.update(kwargs)
    return Observation(**data)


def test_tree_08_image_locate_returns_vlm_locate():
    router = ObservationRouter()
    obs = _base_obs(event_type="image", has_image=True, image_path="fixtures/good.jpg", user_text="功率螺钉在哪，帮我框选")
    decision = router.route(obs)
    assert decision.action_type == "VLM_LOCATE"
    assert decision.scene == "locate"
    assert decision.step_index_change == 0
    assert decision.bboxes and len(decision.bboxes) >= 1
    assert decision.message_id == obs.message_id


def test_tree_09_image_quality_low_rejected():
    router = ObservationRouter()
    obs = _base_obs(event_type="image", has_image=True, image_path="fixtures/low_quality.jpg", user_text="帮我看看端子在哪")
    decision = router.route(obs)
    assert decision.action_type == "REJECT_IMAGE"
    assert decision.error_code == "IMAGE_QUALITY_LOW"
    assert decision.step_index_change == 0


def test_tree_10_image_irrelevant_rejected_without_locate_call():
    calls = {"locate": 0}

    def fake_locator(_):
        calls["locate"] += 1
        return [{"label": "x"}]

    router = ObservationRouter(vlm_locator=fake_locator)
    obs = _base_obs(event_type="image", has_image=True, image_path="fixtures/irrelevant.jpg", user_text="帮我框选")
    decision = router.route(obs)
    assert decision.action_type == "REJECT_IMAGE"
    assert decision.error_code == "IMAGE_IRRELEVANT"
    assert decision.step_index_change == 0
    assert calls["locate"] == 0


def test_tree_11_text_ambiguous_with_sop_returns_ask_clarify():
    router = ObservationRouter()
    obs = _base_obs(event_type="text", user_text="我不知道")
    decision = router.route(obs)
    assert decision.action_type == "ASK_CLARIFY"
    assert decision.step_index_change == 0
    assert "当前步骤需要先完成" in decision.response_text


def test_tree_11_text_ambiguous_without_sop_returns_ask_clarify_no_doc():
    router = ObservationRouter(rag_retriever=lambda _: None)
    obs = _base_obs(event_type="text", step_text="", user_text="不清楚")
    decision = router.route(obs)
    assert decision.action_type == "ASK_CLARIFY"
    assert decision.step_index_change == 0
    assert "知识库也未检索到相关文档" in decision.response_text


def test_tree_12_text_irrelevant_returns_focus():
    router = ObservationRouter()
    obs = _base_obs(event_type="text", user_text="今天午饭吃啥")
    decision = router.route(obs)
    assert decision.action_type == "FOCUS"
    assert decision.step_index_change == 0
    assert "请聚焦当前步骤" in decision.response_text
