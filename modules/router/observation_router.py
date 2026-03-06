from typing import Any, Callable, Dict, List, Optional

from modules.basic.data_class import Observation, RouteDecision
from modules.router.image_quality import check_image_quality

AMBIGUOUS_KEYWORDS = ["我不知道", "不清楚", "不会", "看不出来", "差不多", "不确定"]
IRRELEVANT_KEYWORDS = ["午饭", "吃啥", "天气", "报销", "工资", "周末", "旅游"]
LOCATE_KEYWORDS = ["在哪", "哪个", "标出来", "框选", "圈出来", "功率螺钉", "端子"]


class ObservationRouter:
    def __init__(
        self,
        image_quality_checker: Callable[..., Any] = check_image_quality,
        image_relevance_checker: Optional[Callable[[Observation], bool]] = None,
        vlm_locator: Optional[Callable[[Observation], List[Dict[str, Any]]]] = None,
        rag_retriever: Optional[Callable[[Observation], Optional[str]]] = None,
    ) -> None:
        self.image_quality_checker = image_quality_checker
        self.image_relevance_checker = image_relevance_checker or self._default_image_relevance
        self.vlm_locator = vlm_locator or self._default_vlm_locator
        self.rag_retriever = rag_retriever or (lambda _obs: None)

    def route(self, observation: Observation) -> RouteDecision:
        if observation.event_type == "button":
            return self._decision(observation, "NEXT_STEP", 1, "已收到按钮事件，进入下一步。")

        if observation.event_type == "image" and observation.has_image:
            if not observation.message_id:
                return self._decision(observation, "ASK_CLARIFY", 0, "缺少当前步骤上下文，请返回步骤消息后再上传图片。")

            quality_ok, quality_meta = self.image_quality_checker(
                image=observation.image,
                image_path=observation.image_path,
            )
            if not quality_ok:
                return self._decision(
                    observation,
                    "REJECT_IMAGE",
                    0,
                    "图片清晰度不足，无法判断端子或螺钉位置。请重拍：对焦清晰、目标区域占画面≥1/3、避免反光遮挡。",
                    error_code="IMAGE_QUALITY_LOW",
                    meta={"quality": quality_meta},
                )

            is_relevant = self.image_relevance_checker(observation)
            if not is_relevant:
                return self._decision(
                    observation,
                    "REJECT_IMAGE",
                    0,
                    "图片内容与当前步骤无关。请拍摄：功率矩阵/端子/告警详情/仪表读数等当前步骤关键信息。",
                    error_code="IMAGE_IRRELEVANT",
                    meta={"quality": quality_meta, "relevance": is_relevant},
                )

            if self._contains_keyword(observation.user_text, LOCATE_KEYWORDS):
                return self._decision(
                    observation,
                    "VLM_LOCATE",
                    0,
                    "已在图中标注【功率螺钉】位置，请确认后再操作。若看不清请重拍更近距离。",
                    scene="locate",
                    bboxes=self.vlm_locator(observation),
                    meta={"quality": quality_meta, "relevance": is_relevant},
                )

            return self._decision(
                observation,
                "ASK_CLARIFY",
                0,
                "已收到图片。请说明你希望我定位哪个部件，或补充告警/读数信息。",
                meta={"quality": quality_meta, "relevance": is_relevant},
            )

        if observation.event_type == "text" and self._contains_keyword(observation.user_text, IRRELEVANT_KEYWORDS):
            step_hint = observation.step_text or observation.step_title
            return self._decision(
                observation,
                "FOCUS",
                0,
                f"请聚焦当前步骤：{step_hint}。你可以回复：已完成/未完成，或上传当前步骤相关照片。",
            )

        if observation.event_type == "text" and self._contains_keyword(observation.user_text, AMBIGUOUS_KEYWORDS):
            if observation.step_text.strip():
                return self._decision(
                    observation,
                    "ASK_CLARIFY",
                    0,
                    f"当前步骤需要先完成：{observation.step_text}。请补充现场信息，建议拍摄功率矩阵/端子/告警详情/仪表读数。",
                )

            rag_hit = self.rag_retriever(observation)
            if rag_hit:
                return self._decision(observation, "ASK_CLARIFY", 0, f"检索到相关资料：{rag_hit}。请按资料补充执行细节。")
            return self._decision(
                observation,
                "ASK_CLARIFY",
                0,
                "当前步骤缺少可执行资料，知识库也未检索到相关文档，无法进一步定位。建议扩大排查/升级专家支持。",
            )

        return self._decision(
            observation,
            "ASK_CLARIFY",
            0,
            "请补充当前步骤状态（已完成/未完成），或上传指定照片并提供读数信息。",
        )

    @staticmethod
    def _contains_keyword(text: Optional[str], keywords: List[str]) -> bool:
        return bool(text) and any(keyword in text for keyword in keywords)

    @staticmethod
    def _default_image_relevance(observation: Observation) -> bool:
        return not (observation.image_path and "irrelevant" in observation.image_path.lower())

    @staticmethod
    def _default_vlm_locator(_observation: Observation) -> List[Dict[str, Any]]:
        return [{"label": "功率螺钉", "x": 0.42, "y": 0.53, "w": 0.18, "h": 0.12}]

    @staticmethod
    def _decision(
        observation: Observation,
        action_type: str,
        step_index_change: int,
        response_text: str,
        error_code: Optional[str] = None,
        scene: Optional[str] = None,
        bboxes: Optional[List[Dict[str, Any]]] = None,
        annotated_image: Optional[Dict[str, Any]] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> RouteDecision:
        return RouteDecision(
            action_type=action_type,
            step_index_change=step_index_change,
            error_code=error_code,
            scene=scene,
            response_text=response_text,
            bboxes=bboxes,
            annotated_image=annotated_image,
            message_id=observation.message_id,
            meta=meta or {},
        )


def route_observation(observation: Observation, router: Optional[ObservationRouter] = None) -> RouteDecision:
    return (router or ObservationRouter()).route(observation)
