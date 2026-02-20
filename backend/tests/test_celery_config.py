from __future__ import annotations

import pytest

from app.workers import celery_app


def test_broker_connection_retry_on_startup_enabled():
    assert celery_app.conf.broker_connection_retry_on_startup is True


# All task modules must be listed in celery_app.conf.include so the worker
# imports them at startup.  This guards against the "unregistered task" error
# that occurs when a module with @celery_app.task is not discovered.
_EXPECTED_INCLUDE_MODULES = [
    "app.workers.tasks",
    "app.workers.tg_auth_unified_tasks",
    "app.workers.tg_auth_password_tasks",
    "app.workers.tg_auth_verify_tasks",
]


@pytest.mark.parametrize("module", _EXPECTED_INCLUDE_MODULES)
def test_task_module_in_include(module: str):
    assert module in celery_app.conf.include, (
        f"{module} is missing from celery_app include list"
    )


# Verify that individual tasks from tg_auth_tasks are actually registered
# after the module is imported (i.e. the @celery_app.task decorators ran).
_EXPECTED_TG_AUTH_TASKS = [
    "app.workers.tg_auth_tasks.confirm_password_task",
]


@pytest.mark.parametrize("task_name", _EXPECTED_TG_AUTH_TASKS)
def test_tg_auth_task_registered(task_name: str):
    # Force import of the include modules (mimics worker startup)
    celery_app.loader.import_default_modules()
    assert task_name in celery_app.tasks, (
        f"{task_name} not found in celery_app.tasks — "
        "check that the module is listed in include= and the task is decorated"
    )


# Verify that tasks from the standard tasks.py module are still registered
_EXPECTED_STANDARD_TASKS = [
    "app.workers.tasks.campaign_dispatch",
    "app.workers.tasks.account_health_check",
    "app.workers.tasks.start_warming",
]


@pytest.mark.parametrize("task_name", _EXPECTED_STANDARD_TASKS)
def test_standard_task_registered(task_name: str):
    celery_app.loader.import_default_modules()
    assert task_name in celery_app.tasks, (
        f"{task_name} not found in celery_app.tasks"
    )
