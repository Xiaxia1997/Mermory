from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

EventType = Literal["button", "text", "image"]
ActionType = Literal["NEXT_STEP", "ASK_CLARIFY", "FOCUS", "REJECT_IMAGE", "VLM_LOCATE"]
SceneType = Literal["locate", "describe"]


@dataclass
class Observation:
    session_id: str
    message_id: str
    step_index: int
    step_title: str
    step_text: str
    user_text: Optional[str] = None
    has_image: bool = False
    image: Optional[bytes] = None
    image_path: Optional[str] = None
    event_type: EventType = "text"


@dataclass
class RouteDecision:
    action_type: ActionType
    step_index_change: int
    error_code: Optional[str] = None
    scene: Optional[SceneType] = None
    response_text: str = ""
    bboxes: Optional[List[Dict[str, Any]]] = None
    annotated_image: Optional[Dict[str, Any]] = None
    message_id: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)
