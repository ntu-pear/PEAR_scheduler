from copy import deepcopy
from typing import List, Mapping
from pear_schedule.db_utils.views import PatientsOnlyView, GroupActivitiesOnlyView,GroupActivitiesPreferenceView,GroupActivitiesRecommendationView,GroupActivitiesExclusionView

import logging

from pear_schedule.scheduler.baseScheduler import BaseScheduler

logger = logging.getLogger(__name__)


class GroupActivityScheduler(BaseScheduler):
    @classmethod
    def fillSchedule(cls, patientSchedules: Mapping[str, List[str]]):
        
        activityMap = {} # mapping of (activity Title, duration): set of patients that can do the activity
        patientActivityCountMap = {} # mapping of patientid: number of activities that patient is scheduled for
        activityMinSizeMap = {} # mapping of activity Tile: min size required for activity
        activityExclusionMap = {} # mapping of activityTitle: set of patients that are excluded, not recommended, not preferred
        totalPatientSet = set() #set of all patient ids

        patientDF = PatientsOnlyView.get_data()
        for id in patientDF["PatientID"]:
            totalPatientSet.add(id)
            patientActivityCountMap[id] = 0


        groupActivityDF = GroupActivitiesOnlyView.get_data()
        for row in groupActivityDF.itertuples():
            activityMap[(row.ActivityTitle, row.MinDuration)] = set()
            activityExclusionMap[row.ActivityTitle] = set()
            # activityMap[title] = set()
            # activityExclusionMap[title] = set()

        
        groupPreferenceDF = GroupActivitiesPreferenceView.get_data()
        groupRecommendationDF = GroupActivitiesRecommendationView().get_data()
        groupExcludedDF = GroupActivitiesExclusionView().get_data()

        for _, record in groupActivityDF.iterrows():
            patients = totalPatientSet.copy()
            
            centreActivityID = record["CentreActivityID"]
            activityTitle = record["ActivityTitle"]
            minSizeRequired = record["MinPeopleReq"]
            duration = record["MinDuration"]

            activityMinSizeMap[activityTitle] = minSizeRequired

            # Find excluded patients from activity
            excludedDF = groupExcludedDF[groupExcludedDF["CentreActivityID"] == centreActivityID]
            for id in excludedDF["PatientID"]:
                activityExclusionMap[activityTitle].add(id)
                if id in patients:
                    patients.remove(id)

            # Find not recommended patients
            notRecommendedDF = groupRecommendationDF[
                (groupRecommendationDF["CentreActivityID"] == centreActivityID) &
                (groupRecommendationDF["DoctorRecommendation"].astype(int) == -1)
            ]
            for id in notRecommendedDF["PatientID"]:
                activityExclusionMap[activityTitle].add(id)
                if id in patients:
                    patients.remove(id)


            # Find recommended patients of activity
            recommendedDF = groupRecommendationDF[
                (groupRecommendationDF["CentreActivityID"] == centreActivityID) &
                (groupRecommendationDF["DoctorRecommendation"].astype(int) == 1)
            ]
            for id in recommendedDF["PatientID"]:
                if id in patients:
                    activityMap[(activityTitle, duration)].add(id)
                    patients.remove(id)
                    patientActivityCountMap[id] += 1
            
        
            # Find preferred patients of activity
            preferredDF = groupPreferenceDF.query(f"CentreActivityID == {centreActivityID} and IsLike == 1")
            for id in preferredDF["PatientID"]:
                if id in patients and id not in activityExclusionMap[activityTitle]:
                    activityMap[(activityTitle, duration)].add(id)
                    patients.remove(id)
                    patientActivityCountMap[id] += 1

        
        toRemoveList = []
        secondRoundList = []
        # Trying to get activities to hit min size requirement for first round scheduling. Iterates only through recommended and preferred activities
        for key, patientList in activityMap.items():
            activityTitle, duration = key
            activityCount = len(patientList)
            patients = totalPatientSet.copy()
            leftOverPatients = patients.difference(patientList).difference(activityExclusionMap[activityTitle]) # patients that have no preference or recommendation and can be scheduled randomly

            if activityCount == 0: # no preferred or recommended patients, schedule in second round instead
                toRemoveList.append(key)
                secondRoundList.append(key)
                continue


            if activityCount < activityMinSizeMap[activityTitle]:
                shortfall = activityMinSizeMap[activityTitle] - activityCount
                if len(leftOverPatients) < shortfall: # not enough to hit minimum requirement
                    toRemoveList.append(key)
                    continue

                elif len(leftOverPatients) == shortfall: # just nice enough to hit min requirement
                    for id in leftOverPatients:
                        activityMap[(activityTitle, duration)].add(id)
                        patientActivityCountMap[id] += 1 

                else: # more leftover patients than shortfall, need to allocate patients with lower group activity count
                    minHeap = [(patientActivityCountMap[id], id) for id in leftOverPatients]
                    minHeap.sort()

                    for i in range(shortfall):
                        _, pid = minHeap[i]
                        activityMap[(activityTitle, duration)].add(pid)
                        patientActivityCountMap[pid] += 1

            
        # Need to remove because nvr hit min size requirement
        for key_tuple in toRemoveList:
            activityMap.pop(key_tuple)

       # Initialize timetable
        timetable = {} 
        patientCount = 0
        slots_in_bin = cls.config["MAX_ACTIVITY_DURATION"] // cls.config["MIN_ACTIVITY_DURATION"]
        for id in patientDF["PatientID"]:
            patientCount += 1
            # each group time slot is treated as a bin, in which 30 or 60-minute activities can be scheduled
            timetable[id] = [["" for _ in range(slots_in_bin)] for _ in range(cls.config["GROUP_TIMESLOTS"])]

        # Check if there are any activities are scheduled at group time slot, then indicate so we dont allocate there
        # additionally, reduce the number of slots to iterate upon
        already_filled_slots: int = 0
        for patientID, scheduleArr in timetable.items():
            for i, activity in enumerate(scheduleArr):
                day,hour = cls.config["GROUP_TIMESLOT_MAPPING"][i]
                for slot in range(slots_in_bin):
                    if patientSchedules[patientID][day][hour+slot]:
                        # fill the starting slots given in group timeslot mapping first
                        if slot == 0: already_filled_slots += 1
                        timetable[patientID][i][slot] = "-"

        # First round scheduling using brute force
        logger.info("First Round Scheduling")
        firstTimeTable, firstEmptySlots = cls.bruteForceGroupScheduling(
            activityMap, 
            timetable, 
            cls.config["GROUP_TIMESLOTS"], 
            (patientCount * cls.config["GROUP_TIMESLOTS"]) - already_filled_slots, 
            groupActivityDF
        )
    

        # Allocate activities for second round scheduling. 
        # Allocate patients with no preference to activities that currently have no participants (that were recommended or prefer the activity)
        logger.info(f"secondRoundList: {secondRoundList}")
        patientActivityCountMap = getpatientActivityCountMap(firstTimeTable)
        secondActivityMap = {}
        for key in secondRoundList:
            activityTitle, duration = key

            patientSet = totalPatientSet.copy()
            availablePatients = patientSet.difference(activityExclusionMap[activityTitle])
            if len(availablePatients) < activityMinSizeMap[activityTitle]: # not enough available patients to hit min size
                continue


            secondActivityMap[key] = set()

            minHeap = [(patientActivityCountMap[id], id) for id in availablePatients]
            minHeap.sort()

            # Allocate patients with least number of group activities first
            for i in range(activityMinSizeMap[activityTitle]):
                _, pid = minHeap[i]
                if pid not in activityExclusionMap[activityTitle]: # not being excluded 
                    secondActivityMap[key].add(pid)
                    patientActivityCountMap[pid] += 1
        
       
        logger.info("Second Round Scheduling")
        # Second Round Scheduling
        secondTimeTable, secondEmptySlots = cls.bruteForceGroupScheduling(
            secondActivityMap, firstTimeTable, cls.config["GROUP_TIMESLOTS"], firstEmptySlots, groupActivityDF
        )
        
        # all activities currently scheduled have hit min size, can continue to add patients to these activities
        allScheduledActivitiesSet = getAllScheduledActivities(secondTimeTable) # returns the set of ALL group activities that have been scheduled across ALL patients
        activityToTimeSlotMap = getActivityToTimeSlotMap(secondTimeTable)
        patientActivityCountMap = getpatientActivityCountMap(secondTimeTable) # returns number of group activities currently scheduled per patient (mapping pid:count)
        
        for pid in patientDF["PatientID"]:

            # if hit target number of group activities, do not need to schedule already
            if patientActivityCountMap[pid] >= cls.config["TARGET_WEEKLY_GROUP_ACTIVITIES"]:
                continue
            
            curPatientActivitiesSet = set()
            
            for bin in secondTimeTable[pid]:
                activity = bin[0]
                curPatientActivitiesSet.add(activity)

            # find activities that can be scheduled for patient
            canBeScheduledSet = allScheduledActivitiesSet.difference(curPatientActivitiesSet)
            
            toAdd = min(len(canBeScheduledSet), cls.config["TARGET_WEEKLY_GROUP_ACTIVITIES"] - patientActivityCountMap[pid])

            # Add patients to activities
            while toAdd != 0 and canBeScheduledSet:
                activity = canBeScheduledSet.pop()
                activitySlot = activityToTimeSlotMap[activity]
                activityDuration = groupActivityDF.query(f"ActivityTitle == '{activity}'").iloc[0]["MinDuration"]
                i = 0
                bin: list = secondTimeTable[pid][activitySlot]
                slots = activityDuration // cls.config["MIN_ACTIVITY_DURATION"]
                while not bin[i] and i < len(bin): 
                    i+=1
                if i==0: 
                    continue
                elif pid not in activityExclusionMap[activity] and i==slots:
                    for j in range(slots):
                        secondTimeTable[pid][activitySlot][j] = activity
                    toAdd -= 1
                # if secondTimeTable[pid][activitySlot][0] == "" and pid not in activityExclusionMap[activity]:
                #     secondTimeTable[pid][activitySlot][0] = activity
                #     toAdd -= 1
            

        # for p, slots in secondTimeTable.items():
        #     logger.info(f"{p} Schedule: {slots}")
        
        return secondTimeTable
 
    """
    For first round scheduling, brute force is used to attempt to schedule group activities
    for the minimum number of patients that have been recommended or preferred for the activity.
    It disregards the possibility that there may be leftover patients for which the activity can be scheduled for
    """
    @classmethod
    def bruteForceGroupScheduling(cls, activityMap, timeTable, timeslots, emptySlots, groupActivityDF):
        timeSlotsArr = [i for i in range(timeslots)]
        minEmptySlots = float('inf')
        optimalTimeTable = {}

        def can_schedule(activity, time_slot, timeTable, activityMap, activityDuration):
            for person in activityMap[(activity, activityDuration)]:
                # check if time slot is already occupied by another activity
                slots_in_bin = len(timeTable[person][time_slot])
                i = 0
                while i < slots_in_bin and not timeTable[person][time_slot][i] : 
                    i+=1
                if i != (activityDuration // cls.config["MIN_ACTIVITY_DURATION"]):
                    return False
            return True

        """
        This function returns the possible group time slots that this activity can be scheduled in.
        If the activity is not fixed, then it is assumed to be schedulable in any group time slot.
        """
        def get_possible_slots(activity):
            row = groupActivityDF.query(f"ActivityTitle == '{activity}'").iloc[0]
            if int(row['IsFixed']) == 1:
                return cls.getFixedTimeArr(row['FixedTimeSlots'])
            else:
                return timeSlotsArr.copy()

        def schedule_activities(activity_index, activityList, timeTable, timeSlots, activityMap, groupActivityDF):
            nonlocal minEmptySlots
            nonlocal emptySlots
            nonlocal optimalTimeTable

            # --- PRUNING: stop if no better than best so far ---
            if emptySlots >= minEmptySlots:
                return

            # Base case: all activities handled
            if activity_index >= len(activityList):
                if emptySlots < minEmptySlots:
                    minEmptySlots = emptySlots
                    optimalTimeTable = deepcopy(timeTable)
                return

            activity_key = activityList[activity_index]
            activity, activityDuration = activity_key
            possibleTimeSlots = get_possible_slots(activity)
            isScheduled = False

            for ts in possibleTimeSlots:
                if can_schedule(activity, ts, timeTable, activityMap, activityDuration):
                    isScheduled = True

                    # Place activity
                    # TODO: adjust here
                    for person in activityMap[activity_key]:
                        for i in range(activityDuration // cls.config["MIN_ACTIVITY_DURATION"]):
                            timeTable[person][ts][i] = activity
                        emptySlots -= 1

                    # Recurse
                    schedule_activities(activity_index + 1, activityList, timeTable, timeSlots, activityMap, groupActivityDF)

                    # Backtrack
                    for person in activityMap[activity_key]:
                        for i in range(activityDuration // cls.config["MIN_ACTIVITY_DURATION"]):
                            timeTable[person][ts][i] = ""
                        emptySlots += 1

            if not isScheduled:
                schedule_activities(activity_index + 1, activityList, timeTable, timeSlots, activityMap, groupActivityDF)

        def runSchedule(activityMap, timeTable, timeSlotsArr, groupActivityDF):
            nonlocal optimalTimeTable

            # --- ACTIVITY ORDERING: fixed first, then by # of possible slots ---
            def slot_count(activity):
                return len(get_possible_slots(activity))
            
            # sort activity titles (keys of activityMap) by key
            # guarantee sorting by slot count first, then additionally by fixed if tied
            activityList = sorted(
                list(activityMap.keys()),
                key=lambda a: (
                    slot_count(a[0]),
                    int(groupActivityDF.query(f"ActivityTitle == '{a[0]}'").iloc[0]['IsFixed']) == 0,  # fixed
                )
            )

            logger.info('start scheduling')
            schedule_activities(0, activityList, timeTable, timeSlotsArr, activityMap, groupActivityDF)
            logger.info("end scheduling")

        runSchedule(activityMap, timeTable, timeSlotsArr, groupActivityDF)
        return optimalTimeTable, minEmptySlots

    """
    This method reverses group time slot mapping: a list of (day, timeslot) tuples to a mapping of (day, timeslot) to list index.
    Subsequently, fixedTimeSlots column of an activity is processed. Each slot in fixedTimeSlots is replaced with the corresponding list index.
    """
    @classmethod
    def getFixedTimeArr(cls, fixedTimeSlots):
        fixedTimeArr = fixedTimeSlots.split(",")

        timeSlotMappingReverse = {}
        for i , slot in enumerate(cls.config["GROUP_TIMESLOT_MAPPING"]):
            timeSlotMappingReverse[slot] = i

        # Reformat data
        for i in range(len(fixedTimeArr)):
            value = fixedTimeArr[i]
            valueArr = value.split("-")
            day = int(valueArr[0])
            slot = int(valueArr[1])
            fixedTimeArr[i] = timeSlotMappingReverse[(day,slot)]

        return fixedTimeArr


def getAllScheduledActivities(timeTable):
    activitySet = set()

    for _, arr in timeTable.items():
        for a in arr:
            if a[0] and a[0] != "-":
                activitySet.add(a[0])

    return activitySet

"""
This function returns a mapping of activity to index in patient's timetable
Keeps track of empty slots, i.e. a[0] == ""
"""
def getActivityToTimeSlotMap(timeTable):
    mapping = {}
    for _, arr in timeTable.items():
        for i, a in enumerate(arr):
            if a[0] == "-":
                continue
            if a[0] not in mapping:
                mapping[a[0]] = i

    return mapping

"""
This function returns the number of group activities that have been scheduled for each patient.
"""
def getpatientActivityCountMap(timeTable):
    mapping = {}
    for pid, arr in timeTable.items():
        count = 0
        for a in arr:
            if a[0] and a[0] != "-": 
                count += 1
        mapping[pid] = count

    return mapping