from datetime import timedelta

from pear_schedule.db_utils.utils import timeslot_index


class TestTimeslotIndex:
    def test_zero_offset_returns_slot_zero(self):
        assert timeslot_index(timedelta(minutes=0), 30) == 0

    def test_no_drift_across_a_sweep_of_offsets(self):
        expected = {
            0: 0, 5: 0, 15: 0, 29: 0,
            30: 1, 31: 1, 45: 1, 59: 1,  # fixed: no longer drifts into slot 2
            60: 2, 75: 2,
            90: 3, 105: 3,
            120: 4, 150: 5, 180: 6, 210: 7,
        }
        for minutes, expected_slot in expected.items():
            assert timeslot_index(timedelta(minutes=minutes), 30) == expected_slot, f"minutes={minutes}"
