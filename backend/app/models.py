"""Pydantic response models for all API endpoints."""

from datetime import datetime

from pydantic import BaseModel

from app.poller.normalizer import ServiceStatus


class ServiceResponse(BaseModel):
    id: str
    display_name: str
    category: str
    current_status: ServiceStatus
    current_status_detail: str | None = None
    poll_type: str
    status_page_url: str | None = None
    last_polled_at: datetime | None = None
    last_status_change_at: datetime | None = None


class DependencyResponse(BaseModel):
    service_id: str
    service_name: str
    impact_description: str
    severity: str
    current_status: ServiceStatus


class StatusEventResponse(BaseModel):
    id: int
    service_id: str
    service_name: str
    previous_status: ServiceStatus
    new_status: ServiceStatus
    vendor_title: str | None = None
    vendor_detail: str | None = None
    impact_statement: str | None = None
    source: str
    created_at: datetime


class ServiceDetailResponse(BaseModel):
    service: ServiceResponse
    downstream_impacts: list[DependencyResponse]
    upstream_dependencies: list[DependencyResponse]
    recent_events: list[StatusEventResponse]


class ServiceListResponse(BaseModel):
    services: list[ServiceResponse]
    total: int
    healthy_count: int
    degraded_count: int
    outage_count: int
    unknown_count: int


class TimelineResponse(BaseModel):
    events: list[StatusEventResponse]
    total: int


class ActiveIncident(BaseModel):
    service: ServiceResponse
    impact_statement: str
    affected_services: list[str]
    started_at: datetime | None = None


class MaintenanceResponse(BaseModel):
    id: int
    service_id: str
    service_name: str
    title: str
    description: str | None = None
    scheduled_for: datetime
    scheduled_until: datetime | None = None
    status: str


class SummaryResponse(BaseModel):
    overall_status: ServiceStatus
    status_text: str
    active_incidents: list[ActiveIncident]
    upcoming_maintenances: list[MaintenanceResponse]
    total_services: int
    healthy_count: int
    degraded_count: int
    outage_count: int
    unknown_count: int
    last_poll_at: datetime | None = None
