from typing import List, Mapping
from pear_schedule.utils import ConfigDependant


class BaseScheduler(ConfigDependant):
    @classmethod
    def fillSchedule(cls, schedules: Mapping[str, List[str]]) -> None:
        raise NotImplementedError(f"fillSchedule not defined for {cls.__name__}")