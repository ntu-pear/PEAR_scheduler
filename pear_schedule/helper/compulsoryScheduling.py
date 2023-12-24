from pear_schedule.db_views.views import CompulsoryActivitiesOnlyView

def compulsoryScheduling(patientSchedule):
    compulsoryActivitiesDF = CompulsoryActivitiesOnlyView.get_data()
    
    for activityTitle in compulsoryActivitiesDF["ActivityTitle"]:
        fixedSlotString = compulsoryActivitiesDF.query(f"ActivityTitle == '{activityTitle}'").iloc[0]['FixedTimeSlots']

        fixedSlotArr = fixedSlotString.split(",")
        for slot in fixedSlotArr:
            day = int(slot.split("-")[0])
            hour = int(slot.split("-")[1])

            for pid in patientSchedule.keys():
                patientSchedule[pid][day][hour] = activityTitle

    
