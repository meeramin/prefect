from uuid import uuid4

import pendulum
import pytest
import sqlalchemy as sa

from prefect.orion import models
from prefect.orion.schemas.actions import DeploymentCreate


class TestCreateDeployment:
    async def test_create_deployment(self, session, client, flow):
        data = DeploymentCreate(name="My Deployment", flow_id=flow.id).dict(
            json_compatible=True
        )
        response = await client.post("/deployments/", json=data)
        assert response.status_code == 201
        assert response.json()["name"] == "My Deployment"
        deployment_id = response.json()["id"]

        deployment = await models.deployments.read_deployment(
            session=session, deployment_id=deployment_id
        )
        assert str(deployment.id) == deployment_id

    async def test_create_deployment_respects_flow_id_name_uniqueness(
        self, session, client, flow
    ):
        data = DeploymentCreate(name="My Deployment", flow_id=flow.id).dict(
            json_compatible=True
        )
        response = await client.post("/deployments/", json=data)
        assert response.status_code == 201
        assert response.json()["name"] == "My Deployment"
        deployment_id = response.json()["id"]

        # post the same data
        data = DeploymentCreate(name="My Deployment", flow_id=flow.id).dict(
            json_compatible=True
        )
        response = await client.post("/deployments/", json=data)
        assert response.status_code == 200
        assert response.json()["name"] == "My Deployment"
        assert response.json()["id"] == deployment_id

    async def test_create_deployment_populates_and_returned_created(self, client, flow):
        now = pendulum.now(tz="UTC")

        data = DeploymentCreate(name="My Deployment", flow_id=flow.id).dict(
            json_compatible=True
        )
        response = await client.post("/deployments/", json=data)
        assert response.status_code == 201
        assert response.json()["name"] == "My Deployment"
        assert pendulum.parse(response.json()["created"]) >= now
        assert pendulum.parse(response.json()["updated"]) >= now


class TestReadDeployment:
    async def test_read_deployment(self, client, flow):
        # first create a deployment to read
        data = DeploymentCreate(name="My Deployment", flow_id=flow.id).dict(
            json_compatible=True
        )
        response = await client.post("/deployments/", json=data)
        deployment_id = response.json()["id"]

        # make sure we we can read the deployment correctly
        response = await client.get(f"/deployments/{deployment_id}")
        assert response.status_code == 200
        assert response.json()["id"] == deployment_id
        assert response.json()["name"] == "My Deployment"
        assert response.json()["flow_id"] == str(flow.id)

    async def test_read_deployment_returns_404_if_does_not_exist(self, client):
        response = await client.get(f"/deployments/{uuid4()}")
        assert response.status_code == 404


class TestReadDeployments:
    @pytest.fixture
    async def deployments(self, client, flow):
        await client.post(
            "/deployments/",
            json=DeploymentCreate(name="My Deployment", flow_id=flow.id).dict(
                json_compatible=True
            ),
        )
        await client.post(
            "/deployments/",
            json=DeploymentCreate(name="My Deployment 2", flow_id=flow.id).dict(
                json_compatible=True
            ),
        )

    async def test_read_deployments(self, deployments, client):
        response = await client.get("/deployments/")
        assert response.status_code == 200
        assert len(response.json()) == 2

    async def test_read_deployments_applies_limit(self, deployments, client):
        response = await client.get("/deployments/", json=dict(limit=1))
        assert response.status_code == 200
        assert len(response.json()) == 1

    async def test_read_deployments_offset(self, deployments, client, session):
        response = await client.get("/deployments/", json=dict(offset=1))
        assert response.status_code == 200
        assert len(response.json()) == 1

        all_ids = await session.execute(
            sa.select(models.orm.Deployment.id).order_by(models.orm.Deployment.id)
        )
        second_id = [str(i) for i in all_ids.scalars().all()][1]
        assert response.json()[0]["id"] == second_id

    async def test_read_deployments_returns_empty_list(self, client):
        response = await client.get("/deployments/")
        assert response.status_code == 200
        assert response.json() == []


class TestDeleteDeployment:
    async def test_delete_deployment(self, client, flow):
        # first create a deployment to delete

        data = DeploymentCreate(name="My Deployment", flow_id=flow.id).dict(
            json_compatible=True
        )
        response = await client.post("/deployments/", json=data)
        deployment_id = response.json()["id"]

        # delete the deployment
        response = await client.delete(f"/deployments/{deployment_id}")
        assert response.status_code == 204

        # make sure it's deleted
        response = await client.get(f"/deployments/{deployment_id}")
        assert response.status_code == 404

    async def test_delete_deployment_returns_404_if_does_not_exist(self, client):
        response = await client.delete(f"/deployments/{uuid4()}")
        assert response.status_code == 404
