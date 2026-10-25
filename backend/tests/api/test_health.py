from app.api import errors
from app.core.exceptions import DomainError


async def test_health_reports_database(client) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_every_domain_error_has_an_http_status() -> None:
    def subclasses(cls: type) -> set[type]:
        return {s for c in cls.__subclasses__() for s in {c, *subclasses(c)}}

    assert subclasses(DomainError) <= set(errors.STATUS_BY_ERROR)
