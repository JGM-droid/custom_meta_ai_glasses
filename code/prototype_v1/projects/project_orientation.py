from __future__ import annotations

from .activity_store import ProjectActivityStore, ProjectActivityStoreError
from .models import (
    PROJECT_ORIENTATION_SCHEMA_VERSION,
    ProjectActivity,
    ProjectOrientation,
    ProjectRoadmap,
)
from .project_store import ProjectStore, ProjectStoreError


ROADMAP_STATUS_METADATA_KEY = "roadmap_status"
ROADMAP_STATUSES = ("completed", "current", "upcoming", "deferred")


class ProjectOrientationError(RuntimeError):
    pass


class ProjectOrientationReader:
    """Build a deterministic, read-only orientation from canonical Project state."""

    def __init__(self, project_store: ProjectStore, activity_store: ProjectActivityStore):
        self.project_store = project_store
        self.activity_store = activity_store

    def get_orientation(self, project_id: str) -> ProjectOrientation:
        try:
            project = self.project_store.load_project(project_id)
            activities = self.activity_store.list_activities(project.project_id)
        except (ProjectStoreError, ProjectActivityStoreError):
            raise
        except Exception as exc:  # pragma: no cover - defensive service boundary
            raise ProjectOrientationError("Project orientation is unavailable.") from exc

        grouped: dict[str, list[ProjectActivity]] = {status: [] for status in ROADMAP_STATUSES}
        for activity in activities:
            status = (activity.metadata or {}).get(ROADMAP_STATUS_METADATA_KEY)
            if isinstance(status, str) and status in grouped:
                grouped[status].append(activity)

        checkpoint = project.checkpoint
        return ProjectOrientation(
            schema_version=PROJECT_ORIENTATION_SCHEMA_VERSION,
            project_id=project.project_id,
            name=project.name,
            status=project.status,
            objective=project.goal,
            where_we_are=checkpoint.current_objective,
            now=checkpoint.current_work,
            next=checkpoint.next_action,
            blockers=checkpoint.blockers,
            roadmap=ProjectRoadmap(**grouped),
        )
