from pear_schedule.db_views.views import PatientsOnlyView, GroupActivitiesOnlyView,GroupActivitiesPreferenceView,GroupActivitiesRecommendationView,GroupActivitiesExclusionView
from copy import deepcopy
from config import DAYS, HOURS, GROUP_TIMESLOTS, GROUP_TIMESLOT_MAPPING,MINWEEKLYACTIVITIES

def groupScheduling():
    # Get list of all available group activities (activity ID, title, isFixed, fixedTimeSlots, 
    # minPeopleReq) and create a dictionary of {activity: [patients]/set}
    activityMap = {}
    patientActivityCountMap = {}
    activityMinSizeMap = {}
    activityExclusionMap = {}
    totalPatientSet = set() #set of all patient ids

    patientDF = PatientsOnlyView.get_data()
    for id in patientDF["PatientID"]:
        totalPatientSet.add(id)
        patientActivityCountMap[id] = 0


    groupActivityDF = GroupActivitiesOnlyView.get_data()
    for title in groupActivityDF["ActivityTitle"]:
        activityMap[title] = set()
        activityExclusionMap[title] = set()

    
    groupPreferenceDF = GroupActivitiesPreferenceView.get_data()
    groupRecommendationDF = GroupActivitiesRecommendationView().get_data()
    groupExcludedDF = GroupActivitiesExclusionView().get_data()

    for _, record in groupActivityDF.iterrows():
        patients = totalPatientSet.copy()
        
        activityID = record["ActivityID"]
        activityTitle = record["ActivityTitle"]
        minSizeRequired = record["MinPeopleReq"]

        activityMinSizeMap[activityTitle] = minSizeRequired

        # Find excluded patients from activity
        excludedDF = groupExcludedDF.query(f"CentreActivityID == {activityID}")
        for id in excludedDF["PatientID"]:
            activityExclusionMap[activityTitle].add(id)
            patients.remove(id)

        # Find preferred and recommendation patients of activity
        preferredDF = groupPreferenceDF.query(f"CentreActivityID == {activityID}")
        for id in preferredDF["PatientID"]:
            if id in patients:
                activityMap[activityTitle].add(id)
                patients.remove(id)
                patientActivityCountMap[id] += 1

        recommendedDF = groupRecommendationDF.query(f"CentreActivityID == {activityID}")
        for id in recommendedDF["PatientID"]:
            if id in patients:
                activityMap[activityTitle].add(id)
                patients.remove(id)
                patientActivityCountMap[id] += 1
        
    
    toRemoveList = []
    secondRoundList = []

    for activityTitle, patientList in activityMap.items():
        activityCount = len(patientList)
        patients = totalPatientSet.copy()
        leftOverPatients = patients.difference(patientList).difference(activityExclusionMap[activityTitle])

        if activityCount == 0: # schedule in second round instead
            toRemoveList.append(activityTitle)
            secondRoundList.append(activityTitle)
            continue


        if activityCount < activityMinSizeMap[activityTitle]:
            shortfall = activityMinSizeMap[activityTitle] - activityCount
            if len(leftOverPatients) < shortfall: # not enough to hit minimum requirement
                toRemoveList.append(activityTitle)
                continue

            elif len(leftOverPatients) == shortfall: # just nice enough
                for id in leftOverPatients:
                    activityMap[activityTitle].add(id)
                    patientActivityCountMap[id] += 1

            else: # more leftover patients than shortfall, need to allocate patients with lower group activity count
                minHeap = [(patientActivityCountMap[id], id) for id in leftOverPatients]
                minHeap.sort()

                for i in range(shortfall):
                    _, pid = minHeap[i]
                    activityMap[activityTitle].add(pid)
                    patientActivityCountMap[pid] += 1

        
    # Need to remove because nvr hit min size requirement
    for title in toRemoveList:
        activityMap.pop(title)

    # First round scheduling
    timetable = {} 
    patientCount = 0
    for id in patientDF["PatientID"]:
        patientCount += 1
        timetable[id] = ["" for _ in range(GROUP_TIMESLOTS)]
    
    print("First Round Scheduling")
    firstTimeTable, firstEmptySlots= bruteForceGroupScheduling(activityMap, timetable, GROUP_TIMESLOTS, patientCount * GROUP_TIMESLOTS, groupActivityDF)
        

    # Allocate for second round using secondRoundList
    patientActivityCountMap = getpatientActivityCountMap(firstTimeTable)
    secondActivityMap = {}
    for activityTitle in secondRoundList:
        secondActivityMap[activityTitle] = set()

        minHeap = [(patientActivityCountMap[id], id) for id in patientDF["PatientID"]]
        minHeap.sort()

        for i in range(activityMinSizeMap[activityTitle]):
            _, pid = minHeap[i]
            secondActivityMap[activityTitle].add(pid)
            patientActivityCountMap[pid] += 1

    print("Second Round Scheduling")
    # Second Round Scheduling
    secondTimeTable, secondEmptySlots = bruteForceGroupScheduling(secondActivityMap, firstTimeTable, GROUP_TIMESLOTS, firstEmptySlots, groupActivityDF)
    

    # allocate more patients to activities
    allScheduledActivitiesSet = getAllScheduledActivities(secondTimeTable)
    activityToTimeSlotMap = getActivityToTimeSlotMap(secondTimeTable)
    patientActivityCountMap = getpatientActivityCountMap(secondTimeTable)
    
    for pid in patientDF["PatientID"]:
        if patientActivityCountMap[pid] >= MINWEEKLYACTIVITIES:
            continue
        
        curPatientActivitiesSet = set()
        for activity in secondTimeTable[pid]:
            curPatientActivitiesSet.add(activity)

        canBeScheduledSet = allScheduledActivitiesSet.difference(curPatientActivitiesSet)
        
        toAdd = min(len(canBeScheduledSet), MINWEEKLYACTIVITIES - patientActivityCountMap[pid])

        while toAdd != 0 and canBeScheduledSet:
            activity = canBeScheduledSet.pop()
            activitySlot = activityToTimeSlotMap[activity]
            if secondTimeTable[pid][activitySlot] == "":
                secondTimeTable[pid][activitySlot] = activity
                toAdd -= 1
        

    # for p, slots in secondTimeTable.items():
    #     print(f"{p} Schedule: {slots}")
    
    return secondTimeTable




def bruteForceGroupScheduling(activityMap, timeTable, timeslots, emptySlots, groupActivityDF):
    timeSlotsArr = [i for i in range(timeslots)]
    minEmptySlots = float('inf')
    optimalTimeTable = {}
    

    def can_schedule(activity, time_slot, timeTable, activityMap):
        for person in activityMap[activity]:
            if timeTable[person][time_slot] != "":
                return False
        return True

    def schedule_activities(activity_index, activityList, timeTable, timeSlots, activityMap, groupActivityDF):
        nonlocal minEmptySlots
        nonlocal emptySlots # current number of empty slots
        nonlocal optimalTimeTable #final result

        # emptySlots = checkEmptySlots(timeTable)
        if emptySlots < minEmptySlots:
            # print(numEmpty, minEmpty)
            minEmptySlots = emptySlots
            optimalTimeTable = deepcopy(timeTable)

        if activity_index >= len(activityList):
            return
        

        isScheduled = False
        activity = activityList[activity_index]


        isFixed = groupActivityDF.query(f"ActivityTitle == '{activity}'").iloc[0]['IsFixed']
        # for flexible time activity, try all possible timeslots
        if isFixed:
            fixedTimeSlots = groupActivityDF.query(f"ActivityTitle == '{activity}'").iloc[0]['FixedTimeSlots']
            possibleTimeSlots = getFixedTimeArr(fixedTimeSlots)

        # for fixed time activity, try all given fixed timeslots
        else:
            possibleTimeSlots = timeSlots.copy()

        for ts in possibleTimeSlots:
            if can_schedule(activity, ts, timeTable, activityMap):
                isScheduled = True

                # Schedule in each patient timetable
                for person in activityMap[activity]:
                    timeTable[person][ts] = activity
                    emptySlots -= 1
                

                schedule_activities(activity_index + 1, activityList ,timeTable, timeSlots, activityMap,groupActivityDF)
                    
                # Backtrack and reset the scheduling
                for person in activityMap[activity]:
                    timeTable[person][ts] = ""  
                    emptySlots += 1

         

        if not isScheduled: #means this activity cannot be scheduled already, go to next activity
            schedule_activities(activity_index + 1, activityList ,timeTable, timeSlots, activityMap,groupActivityDF)


    def runSchedule(activityMap, timeTable, timeSlotsArr, groupActivityDF):
        nonlocal optimalTimeTable
        activityList = list(activityMap.keys())


        print('start scheduling')
        schedule_activities(0, activityList, timeTable, timeSlotsArr, activityMap, groupActivityDF)

        # # Print the scheduled activities for each individual
        # for p, slots in optimalTimeTable.items():
        #     print(f"{p} Schedule: {slots}")

        # print(minEmptySlots)
        print("end scheduling")

    runSchedule(activityMap, timeTable, timeSlotsArr,groupActivityDF)
    return optimalTimeTable, minEmptySlots

def getFixedTimeArr(fixedTimeSlots):
    fixedTimeArr = fixedTimeSlots.split(",")

    timeSlotMappingReverse = {}
    for i , slot in enumerate(GROUP_TIMESLOT_MAPPING):
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
            activitySet.add(a)

    return activitySet


def getActivityToTimeSlotMap(timeTable):
    mapping = {}
    for _, arr in timeTable.items():
        for i, a in enumerate(arr):
            if a not in mapping:
                mapping[a] = i

    return mapping


def getpatientActivityCountMap(timeTable):
    mapping = {}
    for pid, arr in timeTable.items():
        count = 0
        for a in arr:
            if a != "":
                count += 1
        mapping[pid] = count

    return mapping
