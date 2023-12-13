import json
import re
import shlex
from typing import Optional, Union
from unittest.mock import MagicMock

import pytest
from anyio import run_process

from prefect._internal.pydantic import HAS_PYDANTIC_V2
from prefect.blocks.core import Block
from prefect.blocks.fields import SecretDict
from prefect.client.orchestration import PrefectClient
from prefect.infrastructure.provisioners.cloud_run import CloudRunPushProvisioner
from prefect.testing.utilities import AsyncMock

if HAS_PYDANTIC_V2:
    from pydantic.v1 import Field
else:
    from pydantic import Field


default_cloud_run_push_base_job_template = {
    "job_configuration": {
        "command": "{{ command }}",
        "env": "{{ env }}",
        "labels": "{{ labels }}",
        "name": "{{ name }}",
        "region": "{{ region }}",
        "credentials": "{{ credentials }}",
        "job_body": {
            "apiVersion": "run.googleapis.com/v1",
            "kind": "Job",
            "metadata": {
                "name": "{{ name }}",
                "annotations": {
                    "run.googleapis.com/launch-stage": "BETA",
                    "run.googleapis.com/vpc-access-connector": (
                        "{{ vpc_connector_name }}"
                    ),
                },
            },
            "spec": {
                "template": {
                    "spec": {
                        "template": {
                            "spec": {
                                "containers": [
                                    {
                                        "image": "{{ image }}",
                                        "command": "{{ command }}",
                                        "resources": {
                                            "limits": {
                                                "cpu": "{{ cpu }}",
                                                "memory": "{{ memory }}",
                                            },
                                            "requests": {
                                                "cpu": "{{ cpu }}",
                                                "memory": "{{ memory }}",
                                            },
                                        },
                                    }
                                ],
                                "timeoutSeconds": "{{ timeout }}",
                                "serviceAccountName": "{{ service_account_name }}",
                            }
                        }
                    }
                }
            },
        },
        "timeout": "{{ timeout }}",
        "keep_job": "{{ keep_job }}",
    },
    "variables": {
        "description": (
            "Default variables for the Cloud Run worker.\n\nThe schema for this class"
            " is used to populate the `variables` section of the default\nbase job"
            " template."
        ),
        "type": "object",
        "required": ["credentials"],
        "properties": {
            "name": {
                "title": "Name",
                "description": "Name given to infrastructure created by a worker.",
                "type": "string",
            },
            "env": {
                "title": "Environment Variables",
                "description": "Environment variables to set when starting a flow run.",
                "type": "object",
                "additionalProperties": {"type": "string"},
            },
            "labels": {
                "title": "Labels",
                "description": "Labels applied to infrastructure created by a worker.",
                "type": "object",
                "additionalProperties": {"type": "string"},
            },
            "command": {
                "title": "Command",
                "description": (
                    "The command to use when starting a flow run. In most cases, this"
                    " should be left blank and the command will be automatically"
                    " generated by the worker."
                ),
                "type": "string",
            },
            "region": {
                "title": "Region",
                "description": "The region where the Cloud Run Job resides.",
                "default": "us-central1",
                "example": "us-central1",
                "type": "string",
            },
            "credentials": {
                "title": "GCP Credentials",
                "description": (
                    "The GCP Credentials used to initiate the Cloud Run Job."
                    " `service_account_info` is required."
                ),
                "allOf": [{"$ref": "#/definitions/GcpCredentials"}],
            },
            "image": {
                "title": "Image Name",
                "description": (
                    "The image to use for a new Cloud Run Job. If not set, the latest"
                    " Prefect image will be used. See"
                    " https://cloud.google.com/run/docs/deploying#images."
                ),
                "example": "docker.io/prefecthq/prefect:2-latest",
                "type": "string",
            },
            "cpu": {
                "title": "CPU",
                "description": (
                    "The amount of compute allocated to the Cloud Run Job. (1000m = 1"
                    " CPU). See"
                    " https://cloud.google.com/run/docs/configuring/cpu#setting-jobs."
                ),
                "pattern": "^(\\d*000)m$",
                "example": "1000m",
                "type": "string",
            },
            "memory": {
                "title": "Memory",
                "description": (
                    "The amount of memory allocated to the Cloud Run Job. Must be"
                    " specified in units of 'G', 'Gi', 'M', or 'Mi'. See"
                    " https://cloud.google.com/run/docs/configuring/memory-limits#setting."
                ),
                "pattern": "^\\d+(?:G|Gi|M|Mi)$",
                "example": "512Mi",
                "type": "string",
            },
            "vpc_connector_name": {
                "title": "VPC Connector Name",
                "description": (
                    "The name of the VPC connector to use for the Cloud Run Job."
                ),
                "type": "string",
            },
            "service_account_name": {
                "title": "Service Account Name",
                "description": (
                    "The name of the service account to use for the task execution of"
                    " Cloud Run Job. By default Cloud Run jobs run as the default"
                    " Compute Engine Service Account. "
                ),
                "example": "service-account@example.iam.gserviceaccount.com",
                "type": "string",
            },
            "keep_job": {
                "title": "Keep Job After Completion",
                "description": "Keep the completed Cloud Run Job after it has run.",
                "default": False,
                "type": "boolean",
            },
            "timeout": {
                "title": "Job Timeout",
                "description": (
                    "The length of time that Prefect will wait for Cloud Run Job state"
                    " changes."
                ),
                "default": 600,
                "exclusiveMinimum": 0,
                "maximum": 3600,
                "type": "integer",
            },
        },
        "definitions": {
            "GcpCredentials": {
                "title": "GcpCredentials",
                "description": (
                    "Block used to manage authentication with GCP. Google"
                    " authentication is handled via the `google.oauth2.\nSee Google's"
                    " [Authentication"
                    " documentation](https://cloud.google.com/docs/authentication#service-accounts)\nfor"
                    " details on inference and recommended authentication patterns."
                ),
                "type": "object",
                "properties": {
                    "service_account_file": {
                        "title": "Service Account File",
                        "description": "Path to the service account JSON keyfile.",
                        "type": "string",
                        "format": "path",
                    },
                    "service_account_info": {
                        "title": "Service Account Info",
                        "description": "The contents of the keyfile as a dict.",
                        "type": "object",
                    },
                    "project": {
                        "title": "Project",
                        "description": "The GCP project to use for the client.",
                        "type": "string",
                    },
                },
                "block_type_slug": "gcp-credentials",
                "secret_fields": ["service_account_info.*"],
                "block_schema_references": {},
            }
        },
    },
}


@pytest.fixture(autouse=True)
async def gcs_credentials_block_type_and_schema():
    class MockGcpCredentials(Block):
        _block_type_name = "GCP Credentials"
        service_account_info: Optional[SecretDict] = Field(
            default=None, description="The contents of the keyfile as a dict."
        )

    await MockGcpCredentials.register_type_and_schema()


@pytest.fixture
def mock_run_process(monkeypatch):
    def mock_gcloud(*args, **kwargs):
        command = args[0]
        mock = MagicMock(returncode=0, stdout=b"mock stdout")
        if command == shlex.split("gcloud --version"):
            mock.stdout = b"Google Cloud SDK 123.456.789"
        elif command == shlex.split("gcloud config get-value project"):
            mock.stdout = b"test-project"
        elif command == shlex.split("gcloud auth list --format=json"):
            mock.stdout = json.dumps(
                [
                    {
                        "account": "test-account",
                        "status": "ACTIVE",
                    }
                ]
            ).encode()
        elif command == shlex.split("gcloud projects list --format=json"):
            mock.stdout = json.dumps(
                [
                    {
                        "projectId": "test-project",
                        "name": "Test Project",
                    }
                ]
            ).encode()
        elif "gcloud iam service-accounts keys create" in shlex.join(command):
            with open(command[5], "w") as f:
                json.dump({"private_key": "test-key"}, f)
        return mock

    mock = AsyncMock(spec=run_process)
    mock.side_effect = mock_gcloud
    monkeypatch.setattr(
        "prefect.infrastructure.provisioners.cloud_run.run_process", mock
    )
    return mock


def assert_commands(mock: MagicMock, *commands: Union[str, re.Pattern]):
    for i, command in enumerate(commands):
        if isinstance(command, str):
            assert command in shlex.join(mock.mock_calls[i].args[0])
        else:
            assert command.match(shlex.join(mock.mock_calls[i].args[0]))


async def test_provision(mock_run_process, prefect_client: PrefectClient):
    provisioner = CloudRunPushProvisioner()
    new_base_job_template = await provisioner.provision(
        work_pool_name="test",
        base_job_template=default_cloud_run_push_base_job_template,
    )
    assert new_base_job_template
    assert_commands(
        mock_run_process,
        "gcloud --version",
        "gcloud auth list --format=json",
        "gcloud config get-value project",
        "gcloud config get-value run/region",
        "gcloud services enable run.googleapis.com",
        (
            "gcloud iam service-accounts create prefect-cloud-run --display-name"
            " 'Prefect Cloud Run Service Account'"
        ),
        (
            "gcloud projects add-iam-policy-binding test-project"
            " --member=serviceAccount:prefect-cloud-run@test-project.iam.gserviceaccount.com"
            " --role=roles/iam.serviceAccountUser"
        ),
        (
            "gcloud projects add-iam-policy-binding test-project"
            " --member=serviceAccount:prefect-cloud-run@test-project.iam.gserviceaccount.com"
            " --role=roles/run.developer"
        ),
        re.compile(
            r"gcloud iam service-accounts keys create .*\/prefect-cloud-run-key\.json"
            r" --iam-account=prefect-cloud-run@test-project\.iam\.gserviceaccount\.com"
        ),
    )

    new_block_doc_id = new_base_job_template["variables"]["properties"]["credentials"][
        "default"
    ]["$ref"]["block_document_id"]

    block_doc = await prefect_client.read_block_document(new_block_doc_id)
    assert block_doc.name == "test-push-pool-credentials"
    assert block_doc.data == {"service_account_info": {"private_key": "test-key"}}


async def test_check_for_gcloud_failure(mock_run_process):
    mock_run_process.side_effect = MagicMock(returncode=1)
    provisioner = CloudRunPushProvisioner()

    with pytest.raises(RuntimeError):
        await provisioner._verify_gcloud_ready()


async def test_no_active_gcloud_account(mock_run_process):
    mock_run_process.side_effect = [
        MagicMock(returncode=0, stdout=b"Google Cloud SDK 123.456.789"),
        MagicMock(returncode=0, stdout=json.dumps([]).encode()),
    ]
    provisioner = CloudRunPushProvisioner()

    with pytest.raises(RuntimeError):
        await provisioner._verify_gcloud_ready()


async def test_provision_interactive_with_default_names(
    mock_run_process, prefect_client: PrefectClient, monkeypatch
):
    mock_prompt_select_from_table = MagicMock(
        side_effect=[
            {"projectId": "test-project"},
            {
                "option": (
                    "Yes, proceed with infrastructure provisioning with default"
                    " resource names"
                )
            },
        ]
    )
    mock_confirm = MagicMock(return_value=True)

    monkeypatch.setattr(
        "prefect.infrastructure.provisioners.cloud_run.prompt_select_from_table",
        mock_prompt_select_from_table,
    )
    monkeypatch.setattr(
        "prefect.infrastructure.provisioners.cloud_run.Confirm.ask", mock_confirm
    )
    provisioner = CloudRunPushProvisioner()
    monkeypatch.setattr(provisioner._console, "is_interactive", True)
    new_base_job_template = await provisioner.provision(
        work_pool_name="test",
        base_job_template=default_cloud_run_push_base_job_template,
    )
    assert new_base_job_template
    assert_commands(
        mock_run_process,
        "gcloud --version",
        "gcloud auth list --format=json",
        "gcloud projects list --format=json",
        "gcloud config get-value run/region",
        "gcloud services enable run.googleapis.com",
        (
            "gcloud iam service-accounts create prefect-cloud-run --display-name"
            " 'Prefect Cloud Run Service Account'"
        ),
        (
            "gcloud projects add-iam-policy-binding test-project"
            " --member=serviceAccount:prefect-cloud-run@test-project.iam.gserviceaccount.com"
            " --role=roles/iam.serviceAccountUser"
        ),
        (
            "gcloud projects add-iam-policy-binding test-project"
            " --member=serviceAccount:prefect-cloud-run@test-project.iam.gserviceaccount.com"
            " --role=roles/run.developer"
        ),
        re.compile(
            r"gcloud iam service-accounts keys create"
            r" .*\/prefect-cloud-run-key\.json"
            r" --iam-account=prefect-cloud-run@test-project\.iam\.gserviceaccount\.com"
        ),
    )

    new_block_doc_id = new_base_job_template["variables"]["properties"]["credentials"][
        "default"
    ]["$ref"]["block_document_id"]

    block_doc = await prefect_client.read_block_document(new_block_doc_id)

    assert block_doc.name == "test-push-pool-credentials"


async def test_provision_interactive_with_custom_names(
    mock_run_process, prefect_client: PrefectClient, monkeypatch
):
    def prompt_mocks(*args, **kwargs):
        if args[0] == "Please enter a name for the service account":
            return "custom-service-account"
        elif args[0] == "Please enter a name for the GCP credentials block":
            return "custom-credentials"

    mock_prompt = MagicMock(side_effect=prompt_mocks)
    mock_prompt_select_from_table = MagicMock(
        side_effect=[
            {"projectId": "test-project"},
            {"option": "Customize resource names"},
        ]
    )
    mock_confirm = MagicMock(return_value=True)

    monkeypatch.setattr(
        "prefect.infrastructure.provisioners.cloud_run.prompt", mock_prompt
    )
    monkeypatch.setattr(
        "prefect.infrastructure.provisioners.cloud_run.prompt_select_from_table",
        mock_prompt_select_from_table,
    )
    monkeypatch.setattr(
        "prefect.infrastructure.provisioners.cloud_run.Confirm.ask", mock_confirm
    )
    provisioner = CloudRunPushProvisioner()
    monkeypatch.setattr(provisioner._console, "is_interactive", True)
    new_base_job_template = await provisioner.provision(
        work_pool_name="test",
        base_job_template=default_cloud_run_push_base_job_template,
    )
    assert new_base_job_template
    assert_commands(
        mock_run_process,
        "gcloud --version",
        "gcloud auth list --format=json",
        "gcloud projects list --format=json",
        "gcloud config get-value run/region",
        "gcloud services enable run.googleapis.com",
        (
            "gcloud iam service-accounts create custom-service-account --display-name"
            " 'Prefect Cloud Run Service Account'"
        ),
        (
            "gcloud projects add-iam-policy-binding test-project"
            " --member=serviceAccount:custom-service-account@test-project.iam.gserviceaccount.com"
            " --role=roles/iam.serviceAccountUser"
        ),
        (
            "gcloud projects add-iam-policy-binding test-project"
            " --member=serviceAccount:custom-service-account@test-project.iam.gserviceaccount.com"
            " --role=roles/run.developer"
        ),
        re.compile(
            r"gcloud iam service-accounts keys create"
            r" .*\/custom-service-account-key\.json"
            r" --iam-account=custom-service-account@test-project\.iam\.gserviceaccount\.com"
        ),
    )

    new_block_doc_id = new_base_job_template["variables"]["properties"]["credentials"][
        "default"
    ]["$ref"]["block_document_id"]

    block_doc = await prefect_client.read_block_document(new_block_doc_id)
    assert block_doc.name == "custom-credentials"
    assert block_doc.data == {"service_account_info": {"private_key": "test-key"}}


async def test_provision_interactive_reject_provisioning(
    mock_run_process, prefect_client: PrefectClient, monkeypatch
):
    mock_prompt_select_from_table = MagicMock(
        side_effect=[
            {"projectId": "test-project"},
            {"option": "Do not proceed with infrastructure provisioning"},
        ]
    )
    mock_confirm = MagicMock(return_value=False)

    monkeypatch.setattr(
        "prefect.infrastructure.provisioners.cloud_run.prompt_select_from_table",
        mock_prompt_select_from_table,
    )
    monkeypatch.setattr(
        "prefect.infrastructure.provisioners.cloud_run.Confirm.ask", mock_confirm
    )
    provisioner = CloudRunPushProvisioner()
    monkeypatch.setattr(provisioner._console, "is_interactive", True)

    unchanged_base_job_template = await provisioner.provision(
        work_pool_name="test",
        base_job_template=default_cloud_run_push_base_job_template,
    )
    assert unchanged_base_job_template == default_cloud_run_push_base_job_template
