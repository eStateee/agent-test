from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


@dataclass
class SubTask:
    """Подзадача в рамках основной задачи."""

    id: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    dependencies: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskState:
    """Состояние выполнения задачи."""

    main_task: str
    subtasks: List[SubTask] = field(default_factory=list)
    current_subtask_id: Optional[str] = None
    collected_data: Dict[str, Any] = field(default_factory=dict)
    iteration: int = 0

    def get_current_subtask(self) -> Optional[SubTask]:
        """Возвращает текущую подзадачу."""
        if not self.current_subtask_id:
            return None
        return next(
            (st for st in self.subtasks if st.id == self.current_subtask_id), None
        )

    def get_next_pending_subtask(self) -> Optional[SubTask]:
        """Возвращает следующую невыполненную подзадачу."""
        for subtask in self.subtasks:
            if subtask.status == TaskStatus.PENDING:
                deps_completed = all(
                    any(
                        st.id == dep_id and st.status == TaskStatus.COMPLETED
                        for st in self.subtasks
                    )
                    for dep_id in subtask.dependencies
                )
                if not subtask.dependencies or deps_completed:
                    return subtask
        return None

    def mark_completed(self, subtask_id: str, result: Dict[str, Any]):
        """Отмечает подзадачу как выполненную."""
        for subtask in self.subtasks:
            if subtask.id == subtask_id:
                subtask.status = TaskStatus.COMPLETED
                subtask.result = result
                break

    def update_subtask(
        self,
        subtask_id: str,
        status: TaskStatus = None,
        result: Dict[str, Any] = None,
        context: Dict[str, Any] = None,
    ):
        """Единая точка обновления подзадачи."""
        for subtask in self.subtasks:
            if subtask.id == subtask_id:
                if status:
                    subtask.status = status
                if result:
                    subtask.result = result
                if context:
                    subtask.context.update(context)
                return True
        return False

    def snapshot(self) -> Dict[str, Any]:
        """Создаёт сериализуемый снимок состояния (для rollback / логирования)."""
        return {
            "current_subtask_id": self.current_subtask_id,
            "subtasks": [(st.id, st.status.value) for st in self.subtasks],
            "collected_data": dict(self.collected_data),
        }

    def restore(self, snapshot: Dict[str, Any]):
        """Восстанавливает состояние из снимка."""
        self.current_subtask_id = snapshot.get("current_subtask_id")
        for st_id, status_val in snapshot.get("subtasks", []):
            for st in self.subtasks:
                if st.id == st_id:
                    if isinstance(status_val, str):
                        try:
                            st.status = TaskStatus(status_val)
                        except Exception:
                            pass
                    else:
                        st.status = status_val
        self.collected_data = dict(snapshot.get("collected_data", {}))
