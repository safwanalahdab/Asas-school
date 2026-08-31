from rest_framework.throttling import UserRateThrottle


class MobileSchoolRequestBurstThrottle(UserRateThrottle):
    scope = "mobile_school_request_burst"


class MobileSchoolRequestHourlyThrottle(UserRateThrottle):
    scope = "mobile_school_request_hourly"
