from rest_framework.throttling import UserRateThrottle


class MobileAppointmentRequestBurstThrottle(UserRateThrottle):
    scope = "mobile_appointment_request_burst"


class MobileAppointmentRequestHourlyThrottle(UserRateThrottle):
    scope = "mobile_appointment_request_hourly"
