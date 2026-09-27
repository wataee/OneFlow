from app.schemas.common import BaseSchema


class DashboardMetricsResponse(BaseSchema):
    total_tasks: int
    pending: int
    processing: int
    in_review: int
    completed: int
    failed: int
    automated_without_human: int
