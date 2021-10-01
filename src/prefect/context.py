"""
Async and thread safe models for passing runtime context data.

These contexts should never be directly mutated by the user.
"""
from contextvars import ContextVar
from typing import Optional, Type, TypeVar, Union, List, Set
from uuid import UUID

import pendulum
from anyio.abc import BlockingPortal, CancelScope
from pendulum.datetime import DateTime
from pydantic import BaseModel, Field

from prefect.client import OrionClient
from prefect.executors import BaseExecutor
from prefect.flows import Flow
from prefect.futures import PrefectFuture
from prefect.tasks import Task
from prefect.orion.schemas.states import State

T = TypeVar("T")


class ContextModel(BaseModel):
    """
    A base model for context data that forbids mutation and extra data while providing
    a context manager
    """

    # The context variable for storing data must be defined by the child class
    __var__: ContextVar

    class Config:
        allow_mutation = False
        arbitrary_types_allowed = True
        extra = "forbid"

    def __enter__(self):
        # We've frozen the rest of the data on the class but we'd like to still store
        # this token for resetting on context exit
        object.__setattr__(self, "__token", self.__var__.set(self))
        return self

    def __exit__(self, *_):
        self.__var__.reset(getattr(self, "__token"))

    @classmethod
    def get(cls: Type[T]) -> Optional[T]:
        return cls.__var__.get(None)


class RunContext(ContextModel):
    """
    The base context for a flow or task run. Data in this context will always be
    available when `get_run_context` is called.
    """

    start_time: DateTime = Field(default_factory=lambda: pendulum.now("UTC"))


class FlowRunContext(RunContext):
    """
    The context for a flow run. Data in this context is only available from within a
    flow run function.
    """

    flow: Flow
    flow_run_id: UUID
    client: OrionClient
    executor: BaseExecutor
    task_run_futures: List[PrefectFuture] = Field(default_factory=list)
    subflow_states: List[State] = Field(default_factory=list)
    # The synchronous portal is only created for async flows for creating engine calls
    # from synchronous task and subflow calls
    sync_portal: Optional[BlockingPortal] = None
    timeout_scope: Optional[CancelScope] = None

    __var__ = ContextVar("flow_run")


class TaskRunContext(RunContext):
    """
    The context for a task run. Data in this context is only available from within a
    task run function.
    """

    task: Task
    task_run_id: UUID
    flow_run_id: UUID
    client: OrionClient

    __var__ = ContextVar("task_run")


class TagsContext(ContextModel):
    """
    The context for `prefect.tags` management.
    """

    current_tags: Set[str] = Field(default_factory=set)

    @classmethod
    def get(cls) -> "TagsContext":
        # Return an empty `TagsContext` instead of `None` if no context exists
        return cls.__var__.get(TagsContext())

    __var__ = ContextVar("tags")


def get_run_context() -> Union[FlowRunContext, TaskRunContext]:
    """
    Get the current run context from within a task or flow function.

    Returns:
        A `FlowRunContext` or `TaskRunContext` depending on the function type.

    Raises
        RuntimeError: If called outside of a flow or task run.
    """
    task_run_ctx = TaskRunContext.get()
    if task_run_ctx:
        return task_run_ctx

    flow_run_ctx = FlowRunContext.get()
    if flow_run_ctx:
        return flow_run_ctx

    raise RuntimeError(
        "No run context available. You are not in a flow or task run context."
    )
