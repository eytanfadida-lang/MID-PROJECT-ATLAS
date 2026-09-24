import datetime

BUSINESS_HOURS = range(9, 18)
DAYS_AHEAD = 7
MAX_DAY_SUGGESTIONS = 6
MAX_HOUR_SUGGESTIONS = 6
WEEKEND_WEEKDAYS = {4, 5}  # Friday, Saturday


class AvailabilityService:
    def __init__(self, repository):
        self.repository = repository

    def get_available_days(self, max_results=MAX_DAY_SUGGESTIONS):
        booked = self.repository.get_booked_slots()
        available_days = []

        for day in self._upcoming_business_days():
            slot_date = day.isoformat()
            has_free_hour = any(
                (slot_date, f"{hour:02d}:00") not in booked for hour in BUSINESS_HOURS
            )
            if has_free_hour:
                available_days.append(slot_date)
                if len(available_days) >= max_results:
                    break

        return available_days

    def get_available_hours(self, slot_date, max_results=MAX_HOUR_SUGGESTIONS):
        booked = self.repository.get_booked_slots()
        available_hours = []

        for hour in BUSINESS_HOURS:
            slot_time = f"{hour:02d}:00"
            if (slot_date, slot_time) not in booked:
                available_hours.append(slot_time)
                if len(available_hours) >= max_results:
                    break

        return available_hours

    def _upcoming_business_days(self):
        today = datetime.date.today()
        return [
            day
            for day_offset in range(DAYS_AHEAD)
            if (day := today + datetime.timedelta(days=day_offset)).weekday() not in WEEKEND_WEEKDAYS
        ]
