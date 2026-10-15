"""Recording a given dose in patient service. HTTP is mocked."""

import datetime
from types import SimpleNamespace

import pytest
import requests

from pear_schedule.api.utils import PatientServiceUnavailableException
from pear_schedule.services import patientsvc_util


@pytest.fixture
def patient_url(monkeypatch):
    monkeypatch.setenv("PATIENT_SERVICE_URL", "http://patient/")


def _record():
    patientsvc_util.record_administration("tok", 7, datetime.date(2026, 10, 15), "0900")


def test_sends_the_dose_with_callers_token(monkeypatch, patient_url):
    sent = {}

    def fake_put(url, json, headers, timeout):
        sent.update(url=url, json=json, headers=headers, timeout=timeout)
        return SimpleNamespace(status_code=200, text="")

    monkeypatch.setattr(patientsvc_util.requests, "put", fake_put)
    _record()
    assert sent == {
        "url": "http://patient/api/v1/Medication/administration",
        "json": {"MedicationId": 7, "AdministerDate": "2026-10-15", "ScheduledTime": "0900"},
        "headers": {"Authorization": "Bearer tok"},
        "timeout": 5.0,
    }


@pytest.mark.parametrize("status", [400, 403, 500, 503])
def test_non_2xx_raises(monkeypatch, patient_url, status):
    monkeypatch.setattr(patientsvc_util.requests, "put", lambda *a, **k: SimpleNamespace(status_code=status, text="no"))
    with pytest.raises(PatientServiceUnavailableException):
        _record()


def test_timeout_raises(monkeypatch, patient_url):
    def timeout(*a, **k):
        raise requests.Timeout("slow")

    monkeypatch.setattr(patientsvc_util.requests, "put", timeout)
    with pytest.raises(PatientServiceUnavailableException):
        _record()


def test_missing_url_raises(monkeypatch):
    monkeypatch.delenv("PATIENT_SERVICE_URL", raising=False)
    with pytest.raises(PatientServiceUnavailableException):
        _record()


def test_undo_sends_the_slot_with_callers_token(monkeypatch, patient_url):
    sent = {}

    def fake_delete(url, params, headers, timeout):
        sent.update(url=url, params=params, headers=headers, timeout=timeout)
        return SimpleNamespace(status_code=200, text="")

    monkeypatch.setattr(patientsvc_util.requests, "delete", fake_delete)
    patientsvc_util.undo_administration("tok", 7, datetime.date(2026, 10, 15), "0900")
    assert sent == {
        "url": "http://patient/api/v1/Medication/administration",
        "params": {"medication_id": 7, "administer_date": "2026-10-15", "scheduled_time": "0900"},
        "headers": {"Authorization": "Bearer tok"},
        "timeout": 5.0,
    }


@pytest.mark.parametrize("status", [403, 500])
def test_undo_non_2xx_raises(monkeypatch, patient_url, status):
    monkeypatch.setattr(patientsvc_util.requests, "delete", lambda *a, **k: SimpleNamespace(status_code=status, text="no"))
    with pytest.raises(PatientServiceUnavailableException):
        patientsvc_util.undo_administration("tok", 7, datetime.date(2026, 10, 15), "0900")
