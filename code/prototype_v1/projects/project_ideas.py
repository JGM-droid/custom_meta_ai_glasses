from __future__ import annotations

from .activity_store import ProjectActivityStore
from .models import (
    PROJECT_IDEA_LIST_SCHEMA_VERSION,
    ProjectActivityConfirmationStatus,
    ProjectActivityCreateRequest,
    ProjectActivitySourceType,
    ProjectActivityType,
    ProjectIdeaCreateRequest,
    ProjectIdeaList,
    ProjectIdeaPromotionResponse,
)


IDEA_LIST_LIMIT = 100
PROMOTED_FROM_METADATA_KEY = "promoted_from_activity_id"


class ProjectIdeaError(RuntimeError):
    pass


class ProjectIdeaNotFound(ProjectIdeaError):
    pass


class ProjectIdeaService:
    def __init__(self, activity_store: ProjectActivityStore):
        self.activity_store = activity_store

    def create_idea(self, project_id: str, request: ProjectIdeaCreateRequest):
        metadata = dict(request.metadata or {})
        metadata["idea_state"] = "captured"
        return self.activity_store.create_activity(project_id, ProjectActivityCreateRequest(
            activity_type=ProjectActivityType.IDEA,
            source_type=ProjectActivitySourceType.USER,
            confirmation_status=ProjectActivityConfirmationStatus.REPORTED,
            summary=request.summary,
            details=request.details,
            metadata=metadata,
        ))

    def list_ideas(self, project_id: str) -> ProjectIdeaList:
        activities = self.activity_store.list_activities(project_id)
        ideas = [item for item in activities if item.activity_type == ProjectActivityType.IDEA]
        return ProjectIdeaList(
            schema_version=PROJECT_IDEA_LIST_SCHEMA_VERSION,
            project_id=project_id,
            limit=IDEA_LIST_LIMIT,
            ideas=list(reversed(ideas[-IDEA_LIST_LIMIT:])),
        )

    def promote(self, project_id: str, activity_id: str) -> ProjectIdeaPromotionResponse:
        normalized_project_id = self.activity_store.project_store.validate_project_id(project_id)
        project_lock = self.activity_store.project_store._get_project_lock(normalized_project_id)
        with project_lock:
            idea = self.activity_store.load_activity(normalized_project_id, activity_id)
            if idea.activity_type != ProjectActivityType.IDEA:
                raise ProjectIdeaNotFound("Idea does not exist.")
            activities = self.activity_store.list_activities(normalized_project_id)
            existing = next((item for item in activities
                             if (item.metadata or {}).get(PROMOTED_FROM_METADATA_KEY) == idea.activity_id), None)
            if existing is not None:
                return ProjectIdeaPromotionResponse(idea=idea, roadmap_activity=existing, created=False)
            roadmap = self.activity_store.create_activity(normalized_project_id, ProjectActivityCreateRequest(
                activity_type=ProjectActivityType.MILESTONE,
                source_type=ProjectActivitySourceType.USER,
                confirmation_status=ProjectActivityConfirmationStatus.REPORTED,
                summary=idea.summary,
                details=idea.details,
                metadata={"roadmap_status": "upcoming", PROMOTED_FROM_METADATA_KEY: idea.activity_id},
            ))
            return ProjectIdeaPromotionResponse(idea=idea, roadmap_activity=roadmap, created=True)
