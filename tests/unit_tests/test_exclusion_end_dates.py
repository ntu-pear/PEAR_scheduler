"""Exclusions with no end date ("until further notice") must stay in force."""

import datetime

import pandas as pd

from messaging.mappers.mapper_util import NO_END_DATE, map_activity_exclusion_create, map_activity_exclusion_update
from pear_schedule.scheduler.individualScheduling import _get_max_enddate
from pear_schedule.scheduler.utils import checkActivityExcluded

WEEK_START = datetime.datetime(2026, 10, 12)
BASE = {"id": 1, "patient_id": 3, "centre_activity_id": 5, "start_date": "2026-10-01", "is_deleted": False}


class TestMapper:
    def test_null_end_date_means_no_end(self):
        """Used to become now(), so the exclusion ran out the day it arrived."""
        assert map_activity_exclusion_create({**BASE, "end_date": None})["EndDateTime"] == NO_END_DATE

    def test_missing_end_date_means_no_end(self):
        assert map_activity_exclusion_create(dict(BASE))["EndDateTime"] == NO_END_DATE

    def test_update_clearing_end_date_means_no_end(self):
        assert map_activity_exclusion_update({**BASE, "end_date": None})["EndDateTime"] == NO_END_DATE

    def test_real_end_date_is_kept(self):
        assert map_activity_exclusion_create({**BASE, "end_date": "2026-10-20"})["EndDateTime"] == datetime.datetime(2026, 10, 20)


class TestCheckActivityExcluded:
    def test_no_end_date_excludes_every_day(self):
        for end in (None, pd.NaT, NO_END_DATE):
            assert all(checkActivityExcluded(5, {5: end}, d, WEEK_START) for d in range(6)), end

    def test_past_end_date_no_longer_excludes(self):
        assert not checkActivityExcluded(5, {5: datetime.datetime(2026, 10, 1)}, 0, WEEK_START)


class TestMaxEndDate:
    def test_no_end_wins(self):
        later = pd.Timestamp("2026-11-01")
        assert _get_max_enddate(pd.NaT, later) is None
        assert _get_max_enddate(later, pd.NaT) is None
        assert _get_max_enddate(later, pd.Timestamp("2026-10-01")) == later
